"""Build the citation index (release P): loci, TLG work numbers, fragment-number equivalences.

    python scripts/build_citation_index.py --corpus /path/corpus.sqlite --out data/citation_index.sqlite \
        --ogc-readme /path/ogc/README.md --cache runtime/cts-cache [--offline]

Sources of a TLG author/work number, in order (each mapping keeps its source and an example):
  record_urn      the record's own CTS URN (Perseus canonical-greekLit / First1KGreek file name in the
                  record id, metadata cts_urn / perseus_edition_urn) or an OGC slug that embeds it
                  ("tlg0199-tlg001");
  ogc_readme      the Open Greek Corpus README names the slug and its TLG number in one sentence;
  cts_catalogue   the open CTS catalogue (PerseusDL/canonical-greekLit, OpenGreekAndLatin/First1KGreek
                  __cts__.xml): one textgroup whose name contains the OGC author slug, one work whose
                  Latin title equals the OGC work slug, and an edition file with the OGC edition name;
  text_match      most sampled verse lines of the group occur (Greek letters only) in Perseus
                  records carrying one CTS URN: the same text in another collection.
Nothing is taken from the TLG website. Works without such a source stay unmapped.

Fragment equivalences are read only from a record that prints two numbers for one fragment
("178 Campbell ( = Voigt, and Lobel & Page 168A)", "fr. 9 F. (= 184 PMGF)", "40a D.  23 W.").
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.author_aliases import canonical, fold  # noqa: E402
from backend.author_catalogue import display_work  # noqa: E402
from backend.citations import parse_range, normalise_depth  # noqa: E402

URN = re.compile(r"\b(tlg\d{4})\.(tlg\d{3}[a-z]?)(?:\.([A-Za-z0-9-]+))?")
SLUG_URN = re.compile(r"\b(tlg\d{4})-(tlg\d{3}[a-z]?)\b")
README_URN = re.compile(r"`([a-z0-9][a-z0-9.-]+)`, (tlg\d{4})\.(tlg\d{3})")
REPOS = {"canonical-greekLit": "PerseusDL/canonical-greekLit", "First1KGreek": "OpenGreekAndLatin/First1KGreek"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(url, cache, name):
    path = Path(cache) / name
    if path.exists():
        return path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "MelosCorpus/0.1 (citation index; research)"})
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(req, timeout=60).read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return data
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "code", None) == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return b""
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("fetch failed: " + url)


def cts_catalogue(cache, offline=False):
    """{repo: {"files": set(paths), "groups": {tlgA: name}}} from the git trees (and textgroup files)."""
    out = {}
    for short, repo in REPOS.items():
        name = f"{short}-tree.json"
        if offline and not (Path(cache) / name).exists():
            continue
        tree = json.loads(fetch(f"https://api.github.com/repos/{repo}/git/trees/master?recursive=1", cache, name))
        files = {item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"}
        out[short] = {"repo": repo, "sha": tree.get("sha"), "files": files, "truncated": tree.get("truncated")}
    return out


def _xml_text(data, tag):
    return [unicodedata.normalize("NFC", m) for m in re.findall(rf"<ti:{tag}[^>]*>([^<]+)</ti:{tag}>", data)]


def _slug_key(text):
    text = unicodedata.normalize("NFD", text).casefold()
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def match_cts(ogc_author, ogc_work, edition, catalogue, cache):
    """Unique (tlgA, tlgW, repo, path) for an OGC slug, or None."""
    author_tokens = [t for t in _slug_key(ogc_author).split() if len(t) >= 4]
    if not author_tokens:
        return None
    stem = author_tokens[0][:5]
    work_key = _slug_key(ogc_work)
    found = []
    for short, info in catalogue.items():
        groups = sorted({p.split("/")[1] for p in info["files"] if p.startswith("data/tlg") and p.endswith("/__cts__.xml")
                         and p.count("/") == 2})
        for group in groups:
            gdata = fetch(f"https://raw.githubusercontent.com/{info['repo']}/master/data/{group}/__cts__.xml",
                          cache, f"{short}/{group}.xml").decode("utf-8", "replace")
            names = [_slug_key(n) for n in _xml_text(gdata, "groupname")]
            if not any(any(tok.startswith(stem) for tok in n.split()) for n in names):
                continue
            works = sorted({p.split("/")[2] for p in info["files"] if p.startswith(f"data/{group}/") and p.count("/") == 3
                            and p.endswith("/__cts__.xml")})
            for work in works:
                wdata = fetch(f"https://raw.githubusercontent.com/{info['repo']}/master/data/{group}/{work}/__cts__.xml",
                              cache, f"{short}/{group}.{work}.xml").decode("utf-8", "replace")
                titles = [_slug_key(t) for t in _xml_text(wdata, "title")]
                path = f"data/{group}/{work}/{group}.{work}.{edition}.xml"
                if path in info["files"]:
                    rule = ("title" if work_key in titles else
                            "title_stem" if any(t[:5] == work_key[:5] for t in titles if len(t) >= 5) else "edition_only")
                    found.append((group, work, info["repo"], path, rule))
    # One work with the exact title, else one with the same title stem, else the textgroup's only
    # work that has an edition file of that name.
    for rule in ("title", "title_stem"):
        picked = [f for f in found if f[4] == rule]
        if len(picked) == 1:
            return picked[0]
        if picked:
            return None
    return found[0] if len(found) == 1 else None


# --------------------------------------------------------------------------------------- equivalences
_EQ_PATTERNS = [
    # 178 Campbell ( = Voigt, and Lobel & Page 168A)
    (re.compile(r"^(?P<a>\d+[a-zA-Z]?)\s+Campbell\s*\(\s*=\s*Voigt,\s*and\s+Lobel\s*&\s*Page\s+(?P<b>\d+[a-zA-Z]?)\s*\)"),
     [("Campbell", "a", "Voigt", "a"), ("Campbell", "a", "Lobel-Page", "b"), ("Voigt", "a", "Lobel-Page", "b")]),
    # F 287 Campbell = F 6 Page
    (re.compile(r"^F\s+(?P<a>\d+[a-zA-Z]?)\s+Campbell\s*=\s*F\s+(?P<b>\d+[a-zA-Z]?)\s+Page\b"), [("Campbell", "a", "Page", "b")]),
    # fr. 9 F. (= 184 PMGF) / fr. 13 F. (= S10)
    (re.compile(r"^fr\.\s+(?P<a>\d+[a-z]?)\s+F\.\s*\(=\s*(?P<b>\d+[a-z]?)\s+PMGF\)"), [("Finglass", "a", "PMGF", "b")]),
    (re.compile(r"^fr\.\s+(?P<a>\d+[a-z]?)\s+F\.\s*\(=\s*S(?P<b>\d+[a-z]?)\)"), [("Finglass", "a", "SLG", "b")]),
    # απ. S7 (=184 Page) / απ. 282a Page (=S151)
    (re.compile(r"^απ\.\s+S(?P<a>\d+[a-z]?)\s*\(=\s*(?P<b>\d+[a-z]?)\s+Page\)"), [("SLG", "a", "Page", "b")]),
    (re.compile(r"^απ\.\s+(?P<a>\d+[a-z]?)\s+Page\s*\(=\s*S(?P<b>\d+[a-z]?)\)"), [("Page", "a", "SLG", "b")]),
    # 40a D.  23 W. (Diehl / West, Greek Wikisource headings)
    (re.compile(r"^(?P<a>\d+[a-z]?)\s+D\.\s+(?P<b>\d+[a-z]?)\s+W\."), [("Diehl", "a", "West", "b")]),
]


def _lines(text):
    """Verse lines reduced to their Greek letters without marks (edition punctuation differs)."""
    out = []
    for line in str(text or "").split("\n"):
        letters = "".join(c for c in unicodedata.normalize("NFD", line.casefold())
                          if "\u03b1" <= c <= "\u03c9")
        if len(letters) >= 18:
            out.append(letters.replace("\u03c2", "\u03c3"))
    return out


def equivalences(author, citation):
    text = unicodedata.normalize("NFC", str(citation or "")).strip()
    out = []
    for pattern, pairs in _EQ_PATTERNS:
        m = pattern.match(text)
        if m:
            for sa, ga, sb, gb in pairs:
                out.append((sa, m[ga].lower(), sb, m[gb].lower()))
    return out


# --------------------------------------------------------------------------------------- build
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--ogc-readme", default="")
    p.add_argument("--cache", default=str(ROOT / "runtime/cts-cache"))
    p.add_argument("--offline", action="store_true")
    p.add_argument("--catalogue-json", default="", help="also write the TLG mapping summary here")
    args = p.parse_args()
    started = time.time()
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    groups = defaultdict(list)          # work_key -> [record tuple]
    group_meta = {}
    urns = defaultdict(Counter)         # work_key -> Counter((tlgA, tlgW)) from records
    urn_example = {}
    ogc_slugs = defaultdict(set)        # work_key -> {(ogc author, ogc work, edition)}
    equiv_rows = []
    author_cache = {}
    line_owner = defaultdict(set)       # normalised verse line -> {(tlgA, tlgW)} from URN-carrying records
    samples = defaultdict(list)         # work_key -> sample lines (for groups without a URN)
    for rowid, pid, source, author, work, edition, citation, kind, quality, language, seq, data, text in con.execute(
            "SELECT rowid,id,source,author,work,edition,citation,kind,quality,language,sequence,data,text FROM passages "
            "WHERE language IN ('grc','mul') ORDER BY rowid"):
        if author not in author_cache:
            author_cache[author] = canonical(author or "") or (author or "")
        name = author_cache[author]
        title = display_work(work, author)
        key = f"{name}|{title}"
        metadata = json.loads(data or "{}").get("metadata") or {}
        group_meta.setdefault(key, {"author": name, "display_work": title, "labels": Counter(), "sources": Counter()})
        group_meta[key]["labels"][f"{author} / {work}"] += 1
        group_meta[key]["sources"][source] += 1
        found_urn = None
        for field in [pid, str(metadata.get("cts_urn") or ""), str(metadata.get("perseus_edition_urn") or "")]:
            m = URN.search(field)
            if m:
                found_urn = (m[1], m[2])
                urns[key][found_urn] += 1
                urn_example.setdefault((key, m[1], m[2]), {"record": pid, "field": "id" if field == pid else "metadata"})
                break
        if found_urn and kind == "text" and pid.startswith(("perseus:", "p2_perseus:")):
            for line in _lines(text):
                line_owner[line].add(found_urn)
        elif not found_urn and kind == "text" and len(samples[key]) < 120:
            samples[key].extend(_lines(text)[:3])
        if not found_urn:
            m = SLUG_URN.search(str(metadata.get("ogc_urn") or work or ""))
            if m:
                urns[key][(m[1], m[2])] += 1
                urn_example.setdefault((key, m[1], m[2]), {"record": pid, "field": "ogc slug"})
        if source == "ogc" and metadata.get("ogc_urn"):
            ogc_slugs[key].add((str(metadata.get("ogc_urn")), edition or "", str(metadata.get("ogc_source") or "")))
        for sa, na, sb, nb in equivalences(author, citation):
            equiv_rows.append((name, sa, na, sb, nb, pid, citation))
        rng = parse_range(citation)
        if rng:
            groups[key].append((pid, source, kind, quality, edition, citation, seq or 0, rng))
    log("records read", sum(len(v) for v in groups.values()), "loci in", len(groups), "work groups")

    readme = {}
    if args.ogc_readme and Path(args.ogc_readme).exists():
        for slug, a, w in README_URN.findall(Path(args.ogc_readme).read_text(encoding="utf-8")):
            readme[slug] = (a, w)
    catalogue = {} if args.offline and not Path(args.cache).exists() else cts_catalogue(args.cache, args.offline)
    mapping = {}
    for key in group_meta:
        counted = urns.get(key)
        if counted and len(counted) == 1:
            (a, w), n = next(iter(counted.items()))
            mapping[key] = {"tlg_author": a, "tlg_work": w, "source": "record_urn", "records_with_urn": n,
                            "example": urn_example[(key, a, w)]}
            continue
        if counted and len(counted) > 1:
            group_meta[key]["tlg_conflict"] = {f"{a}.{w}": n for (a, w), n in counted.items()}
            continue
        for slug, edition, ogc_source in sorted(ogc_slugs.get(key, ())):
            if slug in readme:
                a, w = readme[slug]
                mapping[key] = {"tlg_author": a, "tlg_work": w, "source": "ogc_readme",
                                "example": {"slug": slug, "readme": "open-greek/open-greek-corpus README.md"}}
                break
            if catalogue and ogc_source in ("perseus", "first1k") and "." in slug:
                ogc_author, ogc_work = slug.split(".", 1)
                hit = match_cts(ogc_author, ogc_work, edition, catalogue, args.cache)
                if hit:
                    a, w, repo, path, rule = hit
                    mapping[key] = {"tlg_author": a, "tlg_work": w, "source": "cts_catalogue",
                                    "example": {"slug": slug, "edition": edition, "repo": repo, "path": path, "rule": rule,
                                                "catalogue_tree_sha": next((c["sha"] for c in catalogue.values()
                                                                            if c["repo"] == repo), None)}}
                    break
    # text_match: a group without a stated number whose verse lines are, for the most part, lines of
    # Perseus records carrying one CTS URN (the same text in another collection).
    conflicted = {k for k, v in group_meta.items() if v.get("tlg_conflict")}
    for key in group_meta:
        if key in mapping or key in conflicted:
            continue
        lines = samples.get(key) or []
        if len(lines) < 15:
            continue
        votes = Counter(owner for line in lines for owner in line_owner.get(line, ()))
        if not votes:
            continue
        (a, w), n = votes.most_common(1)[0]
        winners = [o for o, c in votes.items() if c * 10 >= len(lines) * 6]
        if n * 10 >= len(lines) * 6 and len(winners) == 1:
            mapping[key] = {"tlg_author": a, "tlg_work": w, "source": "text_match",
                            "example": {"matched_lines": n, "sampled_lines": len(lines),
                                        "rule": "at least 60% of sampled verse lines (Greek letters only) occur in "
                                                "Perseus records carrying this CTS URN"}}
    log("tlg mapped", len(mapping), "of", len(group_meta), "work groups")

    out = Path(args.out)
    if out.exists():
        out.unlink()
    ix = sqlite3.connect(out)
    ix.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE work(work_key TEXT PRIMARY KEY, author TEXT, display_work TEXT, tlg_author TEXT, tlg_work TEXT,
                        tlg_source TEXT, tlg_evidence TEXT, depth INTEGER, loci INTEGER, first_passage TEXT,
                        labels TEXT, sources TEXT);
      CREATE TABLE locus(work_key TEXT, s0 INTEGER, e0 INTEGER, start TEXT, end TEXT, passage_id TEXT, source TEXT,
                         kind TEXT, quality TEXT, edition TEXT, citation TEXT, seq INTEGER);
      CREATE TABLE equiv(author TEXT, scheme_a TEXT, num_a TEXT, scheme_b TEXT, num_b TEXT, passage_id TEXT, evidence TEXT);
    """)
    total_loci = 0
    for key, meta in group_meta.items():
        rows = groups.get(key, [])
        depth = Counter(len(r[7][0]) for r in rows).most_common(1)[0][0] if rows else None
        loc_rows = []
        for pid, source, kind, quality, edition, citation, seq, (start, end) in rows:
            s, e = normalise_depth(start, depth), normalise_depth(end, depth)
            loc_rows.append((key, s[0][0], e[0][0], json.dumps(s), json.dumps(e), pid, source, kind, quality, edition,
                             citation, seq))
        ix.executemany("INSERT INTO locus VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", loc_rows)
        total_loci += len(loc_rows)
        m = mapping.get(key) or {}
        first = min(rows, key=lambda r: (r[7][0], r[6]))[0] if rows else None
        ix.execute("INSERT INTO work VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (key, meta["author"], meta["display_work"], m.get("tlg_author"), m.get("tlg_work"), m.get("source"),
                    json.dumps(m.get("example"), ensure_ascii=False) if m else None, depth, len(loc_rows), first,
                    json.dumps(dict(meta["labels"].most_common(8)), ensure_ascii=False),
                    json.dumps(dict(meta["sources"]), ensure_ascii=False)))
    ix.executemany("INSERT INTO equiv VALUES (?,?,?,?,?,?,?)", sorted(set(equiv_rows)))
    ix.executescript("CREATE INDEX locus_work ON locus(work_key, s0, e0); CREATE INDEX locus_passage ON locus(passage_id); CREATE INDEX equiv_author ON equiv(author);")
    by_source = Counter(m["source"] for m in mapping.values())
    manifest = {"version": "melos-citation-index-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "corpus": args.corpus, "works": len(group_meta), "loci": total_loci, "tlg_mapped_works": len(mapping),
                "tlg_sources": dict(by_source), "equivalences": len(set(equiv_rows)),
                "cts_catalogue": {k: {"repo": v["repo"], "tree_sha": v["sha"]} for k, v in catalogue.items()},
                "seconds": round(time.time() - started)}
    ix.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest),))
    ix.commit()
    ix.close()
    if args.catalogue_json:
        authors = defaultdict(set)
        for key, m in mapping.items():
            authors[group_meta[key]["author"]].add(m["tlg_author"])
        Path(args.catalogue_json).write_text(json.dumps({
            "manifest": manifest,
            "authors": {a: sorted(v) for a, v in sorted(authors.items())},
            "works": {key: dict(m, author=group_meta[key]["author"], display_work=group_meta[key]["display_work"],
                                labels=dict(group_meta[key]["labels"].most_common(5)))
                      for key, m in sorted(mapping.items())},
            "conflicts": {k: v["tlg_conflict"] for k, v in group_meta.items() if v.get("tlg_conflict")},
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log("wrote", out, os.path.getsize(out), "bytes;", manifest)


if __name__ == "__main__":
    main()
