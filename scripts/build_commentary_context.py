"""Build data/commentary_context.sqlite: commentary notes linked to corpus passages (release S).

  python scripts/build_commentary_context.py --raw <dir with sources.json> --corpus data/corpus.sqlite \
      --inbox data/commentary_inbox --out data/commentary_context.sqlite

Sources (all from open repositories, fetched with the generic User-Agent "Melos/1.0 (+https://greeklyric.com)";
their URLs, sha256 and licence evidence are in the raw directory's sources.json):

- Perseus Hopper commentaries (hand-keyed Greek): Gildersleeve, Pindar O./P. (1885); Allen and Sikes, Homeric
  Hymns (1904); Cholmeley, Theocritus (1901). One note per paragraph group of a poem's commentary page.
- Internet Archive scans (OCR, page-level): Smyth, Greek Melic Poets (1900); Jebb, Bacchylides (1905); Wharton,
  Sappho (1887). One note per scan page (``page`` = scan leaf, plus the printed page number when the running
  head shows one). Pages that are mostly Greek (the poems' own text) are not notes.
- The owner's PDFs in ``--inbox`` (``<name>.pdf`` with an optional ``<name>.json``: title, author, year,
  licence, url, poets). One note per PDF page. Unless the JSON says "public domain", the licence is
  "in copyright (owner-provided PDF)": the note feeds search signals only, and the site may quote at most
  30 words (backend.commentary_context.display_note).

Linking: a note is linked to a passage of the commentary's poets when the passage contains the Greek the note
quotes: at least two of the note's Greek word pairs (adjacent words, accents and case removed), or one pair and
one rare word (seven letters or more, at most 50 corpus occurrences). At most five passages per note, best first.
Notes without such Greek (Wharton's OCR has none) are kept but unlinked.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize  # noqa: E402

GREEK_WORD = re.compile(r"[Ͱ-Ͽἀ-῿]+")
LATIN_WORD = re.compile(r"\b[a-z]{3,}\b")
MELIC = ["Sappho", "Alcaeus", "Anacreon", "Anacreontea", "Alcman", "Stesichorus", "Ibycus", "Simonides", "Pindar",
         "Bacchylides", "Corinna", "Timotheus", "Telesilla", "Praxilla", "Arion", "Terpander", "Lamprocles", "Melanippides"]
SOURCES = {
    "perseus-gildersleeve-pindar": {"parser": "perseus", "poets": ["Pindar"]},
    "perseus-allen-sikes-homeric-hymns": {"parser": "perseus", "poets": ["Homeric Hymns"]},
    "perseus-cholmeley-theocritus": {"parser": "perseus", "poets": ["Theocritus"]},
    "smyth-melic-1900": {"parser": "djvu", "poets": MELIC},
    "jebb-bacchylides-1905": {"parser": "djvu", "poets": ["Bacchylides"]},
    "wharton-sappho": {"parser": "djvu", "poets": ["Sappho"]},
}
NOTE_WORDS = 220


def greek_keys(text):
    return [normalize(w) for w in GREEK_WORD.findall(text)]


def perseus_notes(path, url):
    s = path.read_text(encoding="utf-8")
    start = s.find('class="text_container en"')
    stop = s.find('class="footnotes en"', start)
    body = s[start:stop if stop > 0 else len(s)]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body.split(">", 1)[1] if ">" in body else body))
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\s{3,}\n", text)]
    m = re.search(r"text=comm(?:_book=([^_]+))?_poem=(\w+)", path.name)
    m2 = re.search(r"text=intro_chapter=(\w+)", path.name)
    locator = (f"{m.group(1) + ' ' if m.group(1) else ''}{m.group(2)}, commentary" if m
               else f"introduction, chapter {m2.group(1)}" if m2 else path.stem)
    notes, buf = [], []
    for p in paragraphs:
        if not p:
            continue
        buf.append(p)
        if sum(len(x.split()) for x in buf) >= NOTE_WORDS:
            notes.append(" ".join(buf))
            buf = []
    if buf:
        notes.append(" ".join(buf))
    return [{"locator": f"{locator} ({i + 1})", "page": None, "url": url, "text": t} for i, t in enumerate(notes)]


def djvu_notes(path, url):
    s = path.read_text(encoding="utf-8")
    out = []
    for leaf, obj in enumerate(s.split("<OBJECT")[1:], start=1):
        lines = []
        for line in re.findall(r"<LINE[^>]*>(.*?)</LINE>", obj, flags=re.S):
            words = [html.unescape(w) for w in re.findall(r"<WORD[^>]*>(.*?)</WORD>", line, flags=re.S)]
            if words:
                lines.append(" ".join(words))
        text = re.sub(r"-\s*\n\s*", "", "\n".join(lines))
        text = re.sub(r"\s+", " ", text).strip()
        latin = LATIN_WORD.findall(text.lower())
        if len(latin) < 40:
            continue  # a plate, a blank leaf, or a page of the poems' Greek text: not a note
        head = re.match(r"^\D{0,40}?(\d{1,3})\b|^.{0,60}?\b(\d{1,3})$", " ".join(lines[:1]))
        printed = next((g for g in (head.groups() if head else ()) if g), None)
        out.append({"locator": f"p. {printed}" if printed else f"scan leaf {leaf}",
                    "page": f"leaf {leaf}" + (f" (printed p. {printed})" if printed else ""),
                    "url": url.replace("_djvu.txt", "") + f"/page/n{leaf - 1}" if "archive.org/download" in url else url,
                    "text": text})
    return out


def pdf_notes(path):
    import pypdf
    reader = pypdf.PdfReader(str(path))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        text = re.sub(r"\s+", " ", page.extract_text() or "").strip()
        if len(text.split()) >= 20:
            out.append({"locator": f"p. {i}", "page": f"PDF page {i}", "url": None, "text": text})
    return out


class Linker:
    """Greek word pairs of a note found in the passages of the commentary's poets."""

    def __init__(self, con):
        self.con = con
        self.vocab = {k: c for k, c in con.execute("SELECT normalized, count FROM vocabulary")}
        self.cache = {}

    def scope(self, poets):
        key = tuple(poets)
        if key not in self.cache:
            rows = []
            for poet in poets:
                rows += self.con.execute(
                    "SELECT id, normalized FROM passages WHERE language='grc' AND kind='text' "
                    "AND quality IN ('source_text','machine_corrected_ocr') AND author_canonical=?", (poet,)).fetchall()
            index = defaultdict(set)
            texts = {}
            for pid, norm in rows:
                words = norm.split()
                texts[pid] = " " + " ".join(re.sub(r"[^\w']", "", w) for w in words) + " "
                for w in set(texts[pid].split()):
                    index[w].add(pid)
            self.cache[key] = (index, texts)
        return self.cache[key]

    def link(self, text, poets, top=5):
        index, texts = self.scope(poets)
        keys = [re.sub(r"[^\w']", "", k) for k in greek_keys(text)]
        keys = [k for k in keys if len(k) >= 2]
        pairs = {(a, b) for a, b in zip(keys, keys[1:]) if len(a) + len(b) >= 7}
        rare = {k for k in keys if len(k) >= 7 and 0 < self.vocab.get(k, 0) <= 50}
        score = defaultdict(float)
        for a, b in pairs:
            for pid in index.get(a, set()) & index.get(b, set()):
                if f" {a} {b} " in texts[pid]:
                    score[pid] += 1.0
        for k in rare:
            for pid in index.get(k, set()):
                if pid in score:
                    score[pid] += 0.5
        linked = [(p, s) for p, s in score.items() if s >= 1.5]
        linked.sort(key=lambda x: (-x[1], x[0]))
        return linked[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--inbox", default=str(ROOT / "data/commentary_inbox"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    raw = Path(args.raw)
    entries = json.loads((raw / "sources.json").read_text(encoding="utf-8"))
    by_slug = defaultdict(list)
    for e in entries:
        by_slug[e["slug"]].append(e)
    corpus = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    linker = Linker(corpus)
    out = Path(args.out)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript("""
        CREATE TABLE source(slug TEXT PRIMARY KEY, title TEXT, author TEXT, year TEXT, licence TEXT, repository TEXT,
                            identifier TEXT, url TEXT, files TEXT, poets TEXT);
        CREATE TABLE note(id TEXT PRIMARY KEY, slug TEXT, locator TEXT, page TEXT, url TEXT, text TEXT);
        CREATE TABLE note_link(note_id TEXT, passage_id TEXT, method TEXT, score REAL);
        CREATE INDEX note_link_passage ON note_link(passage_id);
        CREATE INDEX note_link_note ON note_link(note_id);
        CREATE VIRTUAL TABLE note_fts USING fts5(id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
    """)
    report = {}

    def add_source(slug, meta, notes, poets):
        db.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (slug, meta["title"], meta["author"], meta["year"], meta["licence"], meta.get("repository"),
                    meta.get("identifier"), meta.get("url"), json.dumps(meta.get("files", []), ensure_ascii=False),
                    json.dumps(poets, ensure_ascii=False)))
        links = 0
        passages = set()
        for i, n in enumerate(notes):
            nid = f"{slug}:{i + 1}"
            db.execute("INSERT INTO note VALUES (?,?,?,?,?,?)", (nid, slug, n["locator"], n["page"], n["url"], n["text"]))
            db.execute("INSERT INTO note_fts VALUES (?,?)", (nid, n["text"] + " " + " ".join(greek_keys(n["text"]))))
            for pid, score in linker.link(n["text"], poets):
                db.execute("INSERT INTO note_link VALUES (?,?,?,?)", (nid, pid, "greek_quotation", score))
                links += 1
                passages.add(pid)
        report[slug] = {"notes": len(notes), "links": links, "passages": len(passages),
                        "notes_linked": db.execute("SELECT count(DISTINCT note_id) FROM note_link WHERE note_id LIKE ?",
                                                   (slug + ":%",)).fetchone()[0], "licence": meta["licence"]}
        print(slug, report[slug], flush=True)

    for slug, cfg in SOURCES.items():
        files = by_slug.get(slug)
        if not files:
            continue
        first = files[0]
        licence = first["licence"]
        licence = ("Public domain (" + licence.split(":", 1)[1].strip() + ")") if licence.lower().startswith("public domain") \
            else licence
        meta = {"title": first["title"], "author": first["author"], "year": first["year"], "licence": licence,
                "repository": first.get("source_repository"), "identifier": first.get("identifier"),
                "url": first.get("url"), "files": [{"url": f["url"], "sha256": f.get("sha256")} for f in files]}
        notes = []
        if cfg["parser"] == "perseus":
            for f in sorted(files, key=lambda f: f["file"]):
                p = raw / slug / Path(f["file"]).name
                if p.suffix == ".html" and p.exists():
                    notes += perseus_notes(p, f["url"])
        else:
            xml = next((f for f in files if f["file"].endswith("_djvu.xml")), None)
            if xml:
                notes = djvu_notes(raw / slug / Path(xml["file"]).name,
                                   next((f["url"] for f in files if f["url"].endswith("_djvu.txt")), xml["url"]))
        add_source(slug, meta, notes, cfg["poets"])
    inbox = Path(args.inbox)
    for pdf in sorted(inbox.glob("*.pdf")) if inbox.exists() else []:
        side = pdf.with_suffix(".json")
        info = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        licence = info.get("licence") or "in copyright (owner-provided PDF)"
        meta = {"title": info.get("title") or pdf.stem, "author": info.get("author") or "", "year": str(info.get("year") or ""),
                "licence": licence, "repository": "owner-provided PDF", "identifier": pdf.name, "url": info.get("url"),
                "files": [{"file": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}]}
        add_source("pdf-" + re.sub(r"[^a-z0-9]+", "-", pdf.stem.lower()), meta, pdf_notes(pdf), info.get("poets") or MELIC)
    db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('report', ?)", (json.dumps(report, ensure_ascii=False),))
    db.commit()
    db.execute("VACUUM")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
