#!/usr/bin/env python3
"""Ingest David Chamberlain's hand-scanned Latin verse (hypotactic.com/latin) as gold data for the Latin scanner.

Source: per-work pages https://hypotactic.com/latin/<id>.html (ids from authors.html: catullus, odes1-odes4, epodes,
...). Licence: the Latin about page (https://hypotactic.com/latin/about.html) states "All the data on this site is/are
licensed as CC-BY 4.0"; attribution "David Chamberlain, hypotactic.com". Each page: div.poem[data-author, data-metre,
data-number, data-work, data-book?] > div.line > span.word > span.syll.{long|short|elided} with modifier classes
(hiatus, synizesis, lengthening, diastole, systole, resolved res1/res2, hypermetric, semihiatus, halffoot). The text
carries macrons; we keep them in `text` and strip them in `text_plain` (the scanner is evaluated on the plain text).

Outputs (data/open/latin/hypotactic/): lines.jsonl.gz, manifest.json. Raw pages are kept under data/raw/latin/hypotactic/
(gitignored) with their sha256 in the manifest; a page is fetched only when the raw copy is absent (one request at a
time, project User-Agent).
Usage: python -I scripts/ingest_open_hypotactic_latin.py [--work catullus odes1 ...]
"""
import argparse, gzip, hashlib, html.parser, json, os, re, sys, time, unicodedata, urllib.request

UA = "Melos/1.0 (+https://greeklyric.com)"
BASE = "https://hypotactic.com/latin/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "latin", "hypotactic")
OUT = os.path.join(ROOT, "data", "open", "latin", "hypotactic")
DEFAULT_WORKS = ["catullus", "odes1"]
MARKS = ("̄", "̆")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fetch(name):
    path = os.path.join(RAW, name + ".html")
    if os.path.exists(path):
        return path, False
    req = urllib.request.Request(BASE + name + ".html", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    os.makedirs(RAW, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    time.sleep(1.5)
    return path, True


class P(html.parser.HTMLParser):
    def __init__(self, work):
        super().__init__(convert_charrefs=True)
        self.work = work
        self.poem = None
        self.lines = []
        self.line = None
        self.word = None
        self.syll = None
        self.depth = 0
        self.pdepth = None
        self.in_title = False
        self.cap = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cl = (a.get("class") or "").split()
        if tag == "div":
            self.depth += 1
            if "poem" in cl and self.pdepth is None:
                self.poem = {"author": a.get("data-author", ""), "work": a.get("data-work", ""), "book": a.get("data-book", ""),
                             "number": a.get("data-number", ""), "metre": a.get("data-metre", ""), "title": "", "n": 0}
                self.pdepth = self.depth
            elif "line" in cl and self.poem is not None:
                self.line = {"words": [], "classes": [c for c in cl if c != "line"]}
            elif "poem_title" in cl:
                self.in_title = True
        elif tag == "span" and self.line is not None:
            if "word" in cl:
                self.word = {"syl": [], "classes": [c for c in cl if c != "word"]}
            elif "syll" in cl and self.word is not None:
                q = "L" if "long" in cl else "S" if "short" in cl else "E" if "elided" in cl else "?"
                self.syll = {"t": "", "q": q, "f": [c for c in cl if c not in ("syll", "long", "short", "elided")]}

    def handle_endtag(self, tag):
        if tag == "span":
            if self.syll is not None and self.word is not None:
                self.word["syl"].append(self.syll)
                self.syll = None
            elif self.word is not None:
                if self.word["syl"]:
                    self.line["words"].append(self.word)
                self.word = None
        elif tag == "div":
            if self.line is not None:
                if self.line["words"]:
                    self.poem["n"] += 1
                    self.lines.append(self._finish(self.line))
                self.line = None
            if self.in_title:
                self.in_title = False
            if self.pdepth is not None and self.depth == self.pdepth:
                self.pdepth = None
                self.poem = None
            self.depth -= 1

    def handle_data(self, data):
        if self.syll is not None:
            self.syll["t"] += data
        elif self.in_title and self.poem is not None:
            self.poem["title"] += data

    def _finish(self, line):
        p = self.poem
        words = []
        for w in line["words"]:
            form = "".join(s["t"] for s in w["syl"]).strip()
            words.append({"form": form, "pat": "".join({"L": "-", "S": "u", "E": "e", "?": "?"}[s["q"]] for s in w["syl"]),
                          "syl": [{"t": s["t"].strip(), "q": s["q"], "f": s["f"]} for s in w["syl"]], "classes": w["classes"]})
        text = " ".join(w["form"] for w in words)
        plain = "".join(ch for ch in unicodedata.normalize("NFD", text) if ch not in MARKS)
        plain = unicodedata.normalize("NFC", plain)
        num = p["number"]
        return {"id": f"hypotactic-la:{self.work}:{num}:{p['n']}", "work_file": self.work, "author": p["author"],
                "work": p["work"], "book": p["book"], "poem_number": num, "poem_title": p["title"].strip(),
                "line_no": p["n"], "metre": p["metre"], "line_classes": line["classes"], "text": text,
                "text_plain": plain, "pattern": "".join(w["pat"] for w in words), "words": words}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", nargs="*", default=DEFAULT_WORKS)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    manifest = {"name": "Hypotactic Latin hand scansion (David Chamberlain)", "date": time.strftime("%Y-%m-%d"),
                "user_agent": UA, "origin": BASE,
                "licence": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
                            "stated_on": BASE + "about.html",
                            "quote": "All the data on this site is/are licensed as CC-BY 4.0 ... While I have made minor "
                                     "corrections to most texts, the versions of Plautus and Terence found here have been "
                                     "substantially modified, and can be considered my own editions.  The CC-BY licence "
                                     "therefore applies to the full text."},
                "required_attribution": "David Chamberlain, hypotactic.com",
                "use": "evaluation gold only; never a source for the quantity lexicon (docs/prd/latin-composer.md §4.4)",
                "files": {}, "counts": {}}
    about, _ = fetch("about")
    manifest["files"]["about.html"] = {"url": BASE + "about.html", "sha256": sha(about), "bytes": os.path.getsize(about)}
    total = 0
    with gzip.open(os.path.join(OUT, "lines.jsonl.gz"), "wt", encoding="utf-8") as out:
        for work in args.work:
            path, fetched = fetch(work)
            p = P(work)
            p.feed(open(path, encoding="utf-8").read())
            metres = {}
            poems = set()
            for row in p.lines:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                metres[row["metre"]] = metres.get(row["metre"], 0) + 1
                poems.add(row["poem_number"])
            manifest["files"][work + ".html"] = {"url": BASE + work + ".html", "sha256": sha(path), "bytes": os.path.getsize(path),
                                                 "fetched_now": fetched, "lines": len(p.lines), "poems": len(poems),
                                                 "lines_per_metre": metres}
            total += len(p.lines)
            print(work, len(p.lines), "lines,", len(poems), "poems,", metres, file=sys.stderr)
    manifest["counts"]["lines"] = total
    manifest["files"]["lines.jsonl.gz"] = {"sha256": sha(os.path.join(OUT, "lines.jsonl.gz"))}
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
