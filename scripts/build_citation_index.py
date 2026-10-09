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
("178 Campbell ( = Voigt, and Lobel & Page 168A)", "fr. 9 F. (= 184 PMGF)", "40a D.  23 W.",
"105B Voigt = 105C Campbell, LP" in a note's text) or from a cited source sentence in
data/fragment_concordance.json (release Q). The fragment_ref table (release Q) lists, per record,
the numbering schemes it can be cited by: the scheme its own citation names, and an edition's stated
numbering (Campbell, Greek Lyric Poetry p. xxxii: Sappho and Alcaeus by Lobel-Page's marginal numbers).
"""
from __future__ import annotations

import argparse
import hashlib
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
from backend.citations import parse_range, normalise_depth, scheme_name  # noqa: E402
from backend.reference_lookup import _references  # noqa: E402

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


# Equivalences printed inside a record's text (Digital Sappho notes): "105B Voigt = 105C Campbell, LP",
# "103C Voigt = 214 Lobel and Page, and Campbell". A sentence that does not have exactly this shape is
# not read (e.g. "168A Voigt = 178 Campbell, and Lobel & Page 168B ...", which conflicts with the
# site's own heading for that fragment).
_LP = r"(?:LP|L-P|Lobel\s*(?:&|and)\s*Page)"
_TEXT_EQ_PATTERNS = [
    (re.compile(r"(?<![\w.])(?P<a>\d{1,4}[A-Za-z]?)\s+Voigt\s*=\s*(?P<b>\d{1,4}[A-Za-z]?)\s+Campbell,\s*" + _LP + r"(?![\w&])"),
     [("Voigt", "a", "Campbell", "b"), ("Voigt", "a", "Lobel-Page", "b")]),
    (re.compile(r"(?<![\w.])(?P<a>\d{1,4}[A-Za-z]?)\s+Voigt\s*=\s*(?P<b>\d{1,4}[A-Za-z]?)\s+" + _LP + r",\s*and\s+Campbell(?![\w])"),
     [("Voigt", "a", "Lobel-Page", "b"), ("Voigt", "a", "Campbell", "b")]),
]


def text_equivalences(text):
    """(scheme_a, num_a, scheme_b, num_b, evidence snippet) printed in a record's text."""
    text = unicodedata.normalize("NFC", str(text or ""))
    if "Voigt" not in text:
        return []
    out = []
    for pattern, pairs in _TEXT_EQ_PATTERNS:
        for m in pattern.finditer(text):
            snippet = " ".join(text[max(0, m.start() - 20): m.end() + 20].split())
            for sa, ga, sb, gb in pairs:
                out.append((sa, m[ga].lower(), sb, m[gb].lower(), snippet))
    return out


def edition_fragment_refs(pid, author, metadata, concordance):
    """Numbers of a record of an edition whose own numbering statement is in the concordance file:
    (scheme, number, basis, evidence). The printed heading is the edition's own number; the
    statement maps it to the named poets' standard edition; explicit printed suffixes ('96D.',
    'Fr. Adesp. 976 (P.M.G.)') name their edition themselves."""
    out = []
    for ed in concordance.get("edition_numbering", []):
        if not pid.startswith(ed["record_id_prefix"]):
            continue
        printed = unicodedata.normalize("NFC", str(metadata.get("edition_fragment") or "")).strip()
        pages = metadata.get("pdf_pages") or []
        where = f"PDF p. {', '.join(str(p) for p in pages)}" if pages else "the record's printed heading"
        heading = f"{ed['edition']}: heading printed ({printed}), {where}"
        if re.fullmatch(r"\d{1,4}[a-zA-Z]?", printed):
            number = printed.lower()
            out.append((ed["scheme"], number, "edition_heading", heading))
            target = ed.get("authors", {}).get(author)
            if target:
                out.append((target, number, "edition_numbering_statement",
                            f"{heading}; the edition's statement (printed p. {ed['printed_page']}, PDF p. {ed['pdf_page']}): "
                            f"\"{ed['statement']}\""))
        else:
            for rule in ed.get("explicit_headings", []):
                m = re.fullmatch(rule["pattern"], printed)
                if m:
                    out.append((rule["scheme"], m[1].lower(), "edition_heading_explicit", f"{heading}; {rule['rule']}"))
    return out


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
    p.add_argument("--concordance", default=str(ROOT / "data/fragment_concordance.json"),
                   help="fragment-number statements with evidence (release Q)")
    args = p.parse_args()
    started = time.time()
    concordance_path = Path(args.concordance)
    concordance = json.loads(concordance_path.read_text(encoding="utf-8")) if concordance_path.exists() else {}
    frag_rows = []                      # (author, scheme, number, passage_id, basis, evidence)
    source_poets = defaultdict(Counter)  # source -> canonical authors of its Greek text records
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
        if kind == "text" and language == "grc" and name:
            source_poets[source][name] += 1
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
        for sa, na, sb, nb, snippet in text_equivalences(text):
            equiv_rows.append((name, sa, na, sb, nb, pid, snippet))
        # Fragment numbers by numbering scheme (release Q): the scheme a record's own citation names
        # (release-O reference reading), and an edition's stated numbering.
        for number, scheme_key, evidence in _references({"citation": citation, "work": work, "metadata": metadata}):
            scheme = scheme_name(scheme_key) if scheme_key else None
            if scheme:
                frag_rows.append((name, scheme, number.lower(), pid, "record_citation", evidence))
        for scheme, number, basis, evidence in edition_fragment_refs(pid, name, metadata, concordance):
            frag_rows.append((name, scheme, number, pid, basis, evidence))
        rng = parse_range(citation)
        if rng:
            groups[key].append((pid, source, kind, quality, edition, citation, seq or 0, rng))
    log("records read", sum(len(v) for v in groups.values()), "loci in", len(groups), "work groups")
    # Every record's explicit fragment numbers (release-O reading, any scheme, every language): lets
    # /api/cite read the few records citing a number instead of every record of the poet.
    ref_rows = set()
    for pid, citation, work, data in con.execute("SELECT id, citation, work, data FROM passages"):
        if not citation and '"edmonds_fragment_number"' not in (data or "") and "source_citation_aliases" not in (data or ""):
            continue
        record = json.loads(data or "{}")
        for number, _, _ in _references({"citation": citation, "work": work, "metadata": record.get("metadata") or {},
                                         "source_url": record.get("source_url")}):
            ref_rows.add((number, pid))
    log("records with an explicit fragment number", len({r[1] for r in ref_rows}))
    # Notes in other languages (English commentary) can print equivalences too. Such a note's author is
    # its commentator, so the poet is the author of at least 95 % of its source collection's Greek texts.
    poets = {s: v.most_common(1)[0][0] for s, v in source_poets.items()
             if v and v.most_common(1)[0][1] >= 0.95 * sum(v.values())}
    for pid, source, text in con.execute("SELECT id, source, text FROM passages WHERE language NOT IN ('grc','mul') "
                                         "AND text LIKE '%Voigt%=%'"):
        if source not in poets:
            continue
        for sa, na, sb, nb, snippet in text_equivalences(text):
            equiv_rows.append((poets[source], sa, na, sb, nb, pid, snippet))

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
      CREATE TABLE fragment_ref(author TEXT, scheme TEXT, number TEXT, passage_id TEXT, basis TEXT, evidence TEXT);
      CREATE TABLE ref_number(number TEXT, passage_id TEXT, PRIMARY KEY(number, passage_id)) WITHOUT ROWID;
    """)
    ix.executemany("INSERT INTO ref_number VALUES (?,?)", sorted(ref_rows))
    # Equivalences stated by a cited source in the concordance file (passage_id NULL; evidence = JSON
    # {kind, title, revid, url, quote}).
    for eq in concordance.get("equivalences", []):
        (sa, na), (sb, nb) = eq["a"], eq["b"]
        equiv_rows.append((eq["author"], sa, str(na).lower(), sb, str(nb).lower(), None,
                           json.dumps(eq["source"], ensure_ascii=False)))
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
    ix.executemany("INSERT INTO equiv VALUES (?,?,?,?,?,?,?)", sorted(set(equiv_rows), key=lambda r: tuple(str(x) for x in r)))
    frag_rows = sorted(set(frag_rows))
    ix.executemany("INSERT INTO fragment_ref VALUES (?,?,?,?,?,?)", frag_rows)
    ix.executescript("CREATE INDEX locus_work ON locus(work_key, s0, e0); CREATE INDEX locus_passage ON locus(passage_id); "
                     "CREATE INDEX equiv_author ON equiv(author); CREATE INDEX fragment_ref_key ON fragment_ref(scheme, number, author);")
    by_source = Counter(m["source"] for m in mapping.values())
    manifest = {"version": "melos-citation-index-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "corpus": args.corpus, "works": len(group_meta), "loci": total_loci, "tlg_mapped_works": len(mapping),
                "tlg_sources": dict(by_source), "equivalences": len(set(equiv_rows)),
                "corpus_size": os.path.getsize(args.corpus), "corpus_mtime_ns": os.stat(args.corpus).st_mtime_ns,
                "ref_numbers": len(ref_rows),
                "fragment_refs": len(frag_rows), "fragment_ref_bases": dict(Counter(r[4] for r in frag_rows)),
                "fragment_ref_schemes": dict(Counter(r[1] for r in frag_rows)),
                "concordance": {"file": concordance_path.name if concordance else None,
                                "sha256": hashlib.sha256(concordance_path.read_bytes()).hexdigest() if concordance else None,
                                "edition_numbering": [{k: ed.get(k) for k in ("id", "scheme", "edition", "statement",
                                                                             "printed_page", "pdf_page", "authors")}
                                                      for ed in concordance.get("edition_numbering", [])],
                                "conventions": concordance.get("conventions", [])},
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
