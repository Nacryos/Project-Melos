#!/usr/bin/env python3
"""Ingest David Chamberlain's hand-scanned Greek verse (hypotactic.com) via Urdatorn/hypotactic.

Source of the marks: repo dir `hypotactic_htmls_greek/*.html` (Chamberlain's original page HTML: one <span class="syll long|short ...">
per syllable). We do NOT use the repo's `adjust_syllabification/` output (the README says it is unreliable for lyric/epic) and we
do not re-syllabify anything. Text, syllable division and long/short marks are literal spans of the HTML.

Outputs (data/open/hypotactic/): lines.jsonl.gz, word_table.jsonl.gz, files.json, coverage_campbell.json, manifest.json.
Usage: python -I scripts/ingest_open_hypotactic.py [--work DIR]   (DIR gets the shallow clone + fetched site pages)
"""
import argparse, collections, gzip, hashlib, html.parser, json, os, re, subprocess, sys, unicodedata, urllib.request

UA = "Melos/1.0 (+https://greeklyric.com)"
REPO_URL = "https://github.com/Urdatorn/hypotactic.git"
PIN = "9f478ac82db30d6c16f7dfe7fa49056147ed1785"
DATE = "2026-10-09"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "open", "hypotactic")
CAMPBELL = os.path.join(ROOT, "data", "campbell_glp", "campbell_glp.jsonl")
SITE_PAGES = ["https://hypotactic.com/use-the-source/", "https://hypotactic.com/uncategorized/data/",
              "https://hypotactic.com/about/", "https://hypotactic.com/latin/index.html"]
# Editorial fallback ONLY where the HTML carries no data-author; flagged author_source="filename-map".
FILE_AUTHOR = {"theognis": "Theognis", "lycophron": "Lycophron", "cleanthes": "Cleanthes", "aratus": "Aratus",
               "theogony": "Hesiod", "worksanddays": "Hesiod", "prometheus": "Aeschylus", "persians": "Aeschylus",
               "seven": "Aeschylus", "apollonius": "Apollonius Rhodius", "colluthus": "Colluthus", "tryph": "Tryphiodorus"}
# Tags that mean the syllable's quantity is context-dependent / editorial (word-table "clean" counts exclude words with these).
CONTEXT = {"synizesis", "synecphonesis", "deleted", "added", "checkme", "anceps", "exception", "nores", "endcretic",
           "syll1", "split1", "0", "bil", "diastole"}
TARGETS = ["Pindar", "Theognis", "Solon", "Tyrtaeus", "Semonides", "Archilochus", "Sappho", "Alcaeus", "Anacreon",
           "Mimnermus", "Bacchylides", "Simonides", "Alcman", "Hipponax"]
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")


def sha(b): return hashlib.sha256(b).hexdigest()
def shaf(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()


class P(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.poem = None; self.lines = []; self.line = None; self.word = None; self.syll = None
        self.cap = None; self.capdepth = 0; self.depth = 0; self.pdepth = None; self.ctx = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); cl = (a.get("class") or "").split()
        if tag == "div":
            self.depth += 1
            if "data-author" in a and "poem" not in cl:
                self.ctx = {"author": a.get("data-author", ""), "work": a.get("data-work", ""), "book": a.get("data-book", ""),
                            "number": "", "metre": a.get("data-metre", ""), "title": "", "citation": "", "work_title": "", "poem_meter": "", "date": ""}
            if "poem" in cl:
                c = self.ctx or {}
                self.poem = {"author": a.get("data-author", "") or c.get("author", ""), "work": a.get("data-work", "") or c.get("work", ""), "book": a.get("data-book", "") or c.get("book", ""),
                             "number": a.get("data-number", ""), "metre": a.get("data-metre", ""), "title": "", "citation": "",
                             "work_title": "", "poem_meter": "", "date": ""}
                self.pdepth = self.depth
            elif self.poem is not None:
                for k in ("work_title", "poem_meter", "poem_title", "citation", "date"):
                    if k in cl: self.cap = k.replace("poem_title", "title"); self.capdepth = self.depth; self.buf = ""
            if "line" in cl:
                self.line = {"n": a.get("data-number", ""), "metre": a.get("data-metre", ""),
                             "classes": [c for c in cl if c != "line"], "words": [], "poem": self.poem or self.ctx}
        elif tag == "span" and self.line is not None:
            if "word" in cl:
                self.word = {"sylls": []}
            elif "syll" in cl:
                self.syll = {"flags": [c for c in cl if c not in ("syll", "long", "short")],
                             "q": "L" if "long" in cl else ("S" if "short" in cl else "?"), "t": ""}

    def handle_data(self, d):
        if self.syll is not None: self.syll["t"] += d
        elif self.cap: self.buf += d

    def handle_endtag(self, tag):
        if tag == "span":
            if self.syll is not None:
                self.syll["t"] = self.syll["t"].strip()
                if self.word is not None: self.word["sylls"].append(self.syll)
                self.syll = None
            elif self.word is not None:
                if self.word["sylls"]: self.line["words"].append(self.word)
                self.word = None
        elif tag == "div":
            if self.cap and self.depth == self.capdepth:
                if self.poem is not None: self.poem[self.cap] = re.sub(r"\s+", " ", self.buf).strip()
                self.cap = None
            if self.line is not None and self.word is None and self.syll is None and self.depth and self.line is not None:
                pass
            self.depth -= 1

    def feed_done(self):
        pass


def parse_file(path):
    """Parse one page; a line ends when the next line/poem starts or the file ends."""
    txt = open(path, encoding="utf8").read()
    p = P()
    # split at line starts so a line is flushed deterministically
    out = []
    orig_start = p.handle_starttag

    def start(tag, attrs):
        cl = (dict(attrs).get("class") or "").split()
        if tag == "div" and ("line" in cl or "poem" in cl) and p.line is not None:
            out.append(p.line); p.line = None
        orig_start(tag, attrs)
    p.handle_starttag = start
    p.feed(txt); p.close()
    if p.line is not None: out.append(p.line)
    return out, txt


def strip_edge(w):
    w = unicodedata.normalize("NFC", w).lower()
    return re.sub(r"^[\s\"“”‘()\[\]{}<>«»\-–—·,.;:?!…]+|[\s\"“”()\[\]{}<>«»\-–—·,.;:?!…]+$", "", w)


def fold(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    w = w.replace("ς", "σ")
    w = re.sub("[’ʼ'᾽᾿]", "'", w)
    return unicodedata.normalize("NFC", re.sub(r"[^Ͱ-Ͽἀ-῿']", "", w))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--work", default=os.path.join(ROOT, "data", "open", "_work_hypotactic"))
    a = ap.parse_args(); os.makedirs(a.work, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    repo = os.path.join(a.work, "repo")
    if not os.path.isdir(repo):
        subprocess.check_call(["git", "clone", "--depth", "1", REPO_URL, repo])
    head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"]).decode().strip()
    if head != PIN: sys.exit(f"repo HEAD {head} != pinned {PIN}")
    site = {}
    for u in SITE_PAGES:
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read()
            site[u] = {"sha256": sha(b), "bytes": len(b), "mentions_CC": bool(re.search(rb"(?i)CC.BY|creative ?commons", b))}
        except Exception as e:  # loud, not silent
            site[u] = {"error": repr(e)}
    lic = open(os.path.join(repo, "LICENCE"), "rb").read(); readme = open(os.path.join(repo, "README.md"), encoding="utf8").read()
    hdir = os.path.join(repo, "hypotactic_htmls_greek"); tdir = os.path.join(repo, "tsv")
    files = {}; allwords = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    authors = collections.Counter(); author_files = collections.defaultdict(set); nsyl = collections.Counter(); nlines = collections.Counter()
    in_hashes = {}
    with gzip.open(os.path.join(OUT, "lines.jsonl.gz"), "wt", encoding="utf8", newline="\n") as lo:
        for fn in sorted(os.listdir(hdir)):
            stem = fn[:-5]; path = os.path.join(hdir, fn)
            lines, _ = parse_file(path); in_hashes[fn] = shaf(path)
            tsvp = os.path.join(tdir, stem + ".tsv")
            tsv_n = sum(1 for _ in open(tsvp, encoding="utf8")) if os.path.exists(tsvp) else None
            files[stem] = {"html_sha256": in_hashes[fn], "lines": len(lines), "tsv_lines": tsv_n}
            for i, ln in enumerate(lines, 1):
                pm = ln["poem"] or {}
                au = pm.get("author", ""); asrc = "html" if au else ""
                if not au and stem.rstrip("0123456789") in FILE_AUTHOR: au, asrc = FILE_AUTHOR[stem.rstrip("0123456789")], "filename-map"
                words = []
                for w in ln["words"]:
                    sy = [{"t": s["t"], "q": s["q"], "f": s["flags"]} for s in w["sylls"]]
                    form = unicodedata.normalize("NFC", "".join(s["t"] for s in sy))
                    words.append({"form": form, "pat": "".join("-" if s["q"] == "L" else "u" if s["q"] == "S" else "?" for s in sy), "syl": sy})
                    key = strip_edge(form)
                    if GREEK.search(key) and "..." not in form and "?" not in w["sylls"][0]["q"] + "".join(s["q"] for s in w["sylls"]):
                        pat = words[-1]["pat"]
                        clean = not any(f in CONTEXT for s in sy for f in s["f"])
                        allwords[key][pat][0] += 1; allwords[key][pat][1] += clean
                    nsyl[au or stem] += len(sy)
                rec = {"id": f"hypotactic:{stem}:{pm.get('number','')}:{ln['n'] or i}", "file": stem, "author": au, "author_source": asrc,
                       "work": pm.get("work", ""), "work_title": pm.get("work_title", ""), "poem_number": pm.get("number", ""),
                       "poem_title": pm.get("title", ""), "citation": pm.get("citation", ""), "poem_metre": pm.get("metre", ""),
                       "line_no": ln["n"], "metre": ln["metre"], "line_classes": ln["classes"],
                       "text": " ".join(w["form"] for w in words), "pattern": " ".join(w["pat"] for w in words), "words": words}
                lo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                authors[au or "(none:" + stem + ")"] += 1; author_files[au or "(none)"].add(stem); nlines[stem] += 1
    # word table
    tab = []
    for key, pats in allwords.items():
        pl = sorted(({"pattern": p, "count": c[0], "clean_count": c[1]} for p, c in pats.items()), key=lambda x: -x["count"])
        tab.append({"form": key, "total": sum(x["count"] for x in pl), "n_patterns": len(pl), "conflict": len(pl) > 1, "patterns": pl})
    tab.sort(key=lambda r: (-r["total"], r["form"]))
    with gzip.open(os.path.join(OUT, "word_table.jsonl.gz"), "wt", encoding="utf8", newline="\n") as wo:
        for r in tab: wo.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(files, open(os.path.join(OUT, "files.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1, sort_keys=True)
    # coverage vs Campbell GLP
    present = {k.lower() for k in authors}
    camp = [json.loads(l) for l in open(CAMPBELL, encoding="utf8")]
    c_auth = collections.Counter(r["author"] for r in camp)
    exact = {r["form"]: r for r in tab}; folded = collections.defaultdict(set)
    for r in tab:
        for p in r["patterns"]: folded[fold(r["form"])].add(p["pattern"])
    types = collections.Counter()
    for r in camp:
        for t in re.split(r"\s+", r["text"]):
            k = strip_edge(t)
            if GREEK.search(k): types[k] += 1
    def stat(fn):
        ty = sum(1 for k in types if fn(k)); tk = sum(c for k, c in types.items() if fn(k)); return ty, tk
    e = stat(lambda k: k in exact); f = stat(lambda k: fold(k) in folded)
    eu = stat(lambda k: k in exact and exact[k]["n_patterns"] == 1); fu = stat(lambda k: len(folded.get(fold(k), ())) == 1)
    cov = {"campbell_poems": len(camp), "campbell_authors": dict(c_auth),
           "authors_with_hand_scansion": sorted(a_ for a_ in c_auth if a_.lower() in present),
           "poems_by_authors_with_hand_scansion": sum(n for a_, n in c_auth.items() if a_.lower() in present),
           "word_spelling_types": len(types), "word_tokens": sum(types.values()),
           "exact_nfc_lower": {"types": e[0], "tokens": e[1], "unique_pattern_types": eu[0], "unique_pattern_tokens": eu[1]},
           "accent_folded": {"types": f[0], "tokens": f[1], "unique_pattern_types": fu[0], "unique_pattern_tokens": fu[1]},
           "note": "matching on whole-word spellings; hypotactic words that contain elision/crasis are single table keys"}
    json.dump(cov, open(os.path.join(OUT, "coverage_campbell.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    outs = {n: {"sha256": shaf(os.path.join(OUT, n)), "bytes": os.path.getsize(os.path.join(OUT, n))}
            for n in ("lines.jsonl.gz", "word_table.jsonl.gz", "files.json", "coverage_campbell.json")}
    i = readme.find("> All the data on this site")
    man = {"name": "Hypotactic hand scansion (David Chamberlain), via Urdatorn/hypotactic", "date": DATE, "user_agent": UA,
           "source_url": "https://github.com/Urdatorn/hypotactic", "commit": head, "origin": "https://hypotactic.com/",
           "licence": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
                       "repo_file": "LICENCE (full CC BY 4.0 legal code, first line: 'Attribution 4.0 International')",
                       "licence_file_sha256": sha(lic),
                       "readme_verbatim": readme[readme.find("The corpus is published"):].strip(),
                       "note": "The licence/permission statement is in the repo README (Chamberlain quoted); the hypotactic.com pages fetched "
                               "(see site_pages) do not themselves mention CC BY."},
           "required_attribution": "David Chamberlain, hypotactic.com (per his statement: reference him and the site if making significant or extensive use in published work)",
           "readme_provenance_verbatim": readme[readme.find("An effort to make"):readme.find("## Syllabification")].strip(),
           "site_pages": site, "source": "hypotactic_htmls_greek/*.html (original hand marks); adjust_syllabification/ NOT used (README: buggy for lyric/epic)",
           "tag_notes": "q = L/S from class long/short; f = other CSS classes verbatim (e.g. anceps, bil = 'Brevis in longo' per site option label, synizesis, hiatus, "
                        "correption, link, worddiv, lbn/lbp/mcl/res1/res2: meaning not documented in repo, kept raw).",
           "word_table_note": "form = NFC lower-case with edge punctuation stripped; pat uses '-' long, 'u' short; clean_count excludes words with context/editorial tags "
                              + ",".join(sorted(CONTEXT)),
           "author_source_note": "author from html data-author; for files lacking it a small editorial file->author map is used (author_source='filename-map'): " + json.dumps(FILE_AUTHOR),
           "counts": {"files": len(files), "lines": sum(nlines.values()), "lines_per_author": dict(authors), "syllables_per_author_or_file": dict(nsyl),
                      "word_table_forms": len(tab), "word_table_conflict_forms": sum(r["conflict"] for r in tab)},
           "target_authors_present": {t: (t.lower() in present) for t in TARGETS},
           "input_html_sha256": in_hashes, "outputs": outs}
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(json.dumps({"lines": man["counts"]["lines"], "forms": len(tab), "targets": man["target_authors_present"], "coverage": cov["exact_nfc_lower"]}))


if __name__ == "__main__":
    main()
