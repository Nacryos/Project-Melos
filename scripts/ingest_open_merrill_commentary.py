#!/usr/bin/env python3
"""Ingest E. T. Merrill's commentary on Catullus and his Introduction (Catullus, Ginn / Harvard 1893) from the
Perseus Digital Library TEI, `Perseus:text:1999.02.0004` (one file from the hopper's `dltext` endpoint: one request,
kinder than 116 `xmlchunk` calls). The book is in the public domain; the Perseus markup carries its own statement,
which is copied verbatim into the manifest.

The TEI: <text n="intro"> with 13 headed sections (div2) of numbered paragraphs (div3 n = Merrill's own section
numbers 1-86, sub-lettered div4), and <text n="comm"> with one div1 per poem: a headnote (<p> children) and one
<div2 type="commline" n="LINE or RANGE"> per note, opening with the <lemma> the note hangs on.
Nothing is written from memory: every row is the TEI's text, whitespace normalised. Greek is beta code in the file
and is converted with the `betacode` package (the beta code is kept in `greek_betacode` when any was converted).
`latin` lists the Latin phrases Merrill prints inside the note (<foreign lang="la">, not the parallels quoted in
<quote>), which is what `notes_for_words` matches besides the lemma phrase.

Outputs (data/open/latin/merrill-commentary/): notes.jsonl, intro.jsonl, manifest.json.
Usage: python -I scripts/ingest_open_merrill_commentary.py        (downloads the raw file when it is missing)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "latin" / "merrill-commentary"
OUT = ROOT / "data" / "open" / "latin" / "merrill-commentary"
DOC = "Perseus:text:1999.02.0004"
URL = f"https://www.perseus.tufts.edu/hopper/dltext?doc={DOC}"
NAME = "Perseus_text_1999.02.0004.xml"
PAGE_URL = f"https://www.perseus.tufts.edu/hopper/text?doc={DOC}"
UA = "Melos/1.0 (+https://greeklyric.com)"

BETA = re.compile(r"[a-z*][)(]?[/\\=][a-z|]|\*[)(]?[a-z]+[/\\=]")

try:
    from betacode.conv import beta_to_uni
except Exception:                                   # the package is optional: the beta code is kept as it stands
    beta_to_uni = None


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def ensure_raw(url: str, path: Path, licence_note: str) -> dict:
    """The raw file, downloaded once (one request) and recorded in <source>/fetch-log.jsonl."""
    log = path.parent / "fetch-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    status = None
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            status = r.status
            path.write_bytes(r.read())
        time.sleep(0.6)
    recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()] if log.exists() else []
    rec = next((r for r in recs if r.get("path", "").endswith(path.name) and r.get("sha256") == sha(path)), None)
    if rec is None:
        rec = {"url": url, "path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha(path),
               "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
               "http_status": status or 200, "user_agent": UA, "licence_note": licence_note}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def clean(s: str) -> str:
    s = unicodedata.normalize("NFC", re.sub(r"\s+", " ", s)).strip()
    return re.sub(r"\s+([,;:.!?)])", r"\1", s)


def render(el, skip=None) -> tuple[str, list[str], list[str]]:
    """(text, Latin phrases in <foreign lang="la">, Greek beta code converted) of an element, `skip` left out."""
    latin, greek = [], []

    def walk(e) -> str:
        if e is skip:
            return e.tail or ""
        if not isinstance(e.tag, str):
            return e.tail or ""
        inner = (e.text or "") + "".join(walk(c) for c in e)
        lang = e.get("lang")
        if lang == "la" and BETA.search(inner):     # a few Greek phrases are tagged as Latin in the file
            lang = "greek"
        if e.tag in ("foreign", "quote", "lemma") and lang == "greek" and inner.strip():
            greek.append(clean(inner))
            if beta_to_uni:
                inner = beta_to_uni(inner)
        elif e.tag == "foreign" and lang == "la" and inner.strip():
            latin.append(clean(inner))
        if e.tag in ("p", "l", "item", "head"):
            inner = " " + inner + " "
        elif e.tag == "note" and inner.strip():     # the Perseus editors' remarks on Merrill, not his own words
            inner = " [Note in the Perseus file: " + inner.strip() + "] "
        return inner + (e.tail or "")

    text = (el.text or "") + "".join(walk(c) for c in el)
    return clean(text), latin, greek


def line_span(n: str) -> tuple[int | None, int | None]:
    """'7' -> (7, 7); '1-3' -> (1, 3); '92-6' -> (92, 96); '23b' -> (23, 23)."""
    m = re.fullmatch(r"(\d+)[a-z]?(?:-(\d+)[a-z]?)?", n or "")
    if not m:
        return None, None
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if b < a:                                       # abbreviated end of a range, as the book prints it
        b = int(str(a)[: len(str(a)) - len(str(b))] + str(b))
    return a, b


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = ensure_raw(URL, RAW / NAME, "Perseus hopper dltext; the file's own availability statement is quoted in the manifest")
    root = etree.parse(str(RAW / NAME), etree.XMLParser(recover=True, resolve_entities=False, no_network=True)).getroot()
    avail = root.find(".//teiHeader//availability")
    licence = clean("".join(avail.itertext())) if avail is not None else ""
    src = root.find(".//teiHeader//sourceDesc")
    page_quote = ""                                 # the rights sentence on the Perseus page of the text, when it could be fetched
    try:
        ensure_raw(PAGE_URL, RAW / "hopper_text_page.html", "Perseus hopper page of the text: its rights sentence is quoted in the manifest")
        page = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (RAW / "hopper_text_page.html").read_text(encoding="utf-8", errors="replace")))
        m = re.search(r"This work is licensed under a .*?License\s*\.", page)
        page_quote = clean(m.group(0)) if m else ""
    except Exception as e:  # noqa: BLE001 - the page is only a second witness of the licence
        page_quote = f"not fetched: {e}"
    notes, per_poem, poems = [], Counter(), []
    for d in root.iter("div1"):
        if (d.get("type") or "").lower() != "poem":
            continue
        poem = d.get("n", "")
        poems.append(poem)
        url = f"https://www.perseus.tufts.edu/hopper/text?doc={DOC}:poem={poem}"
        head = [c for c in d if c.tag == "p"]
        if head:
            parts = [render(p) for p in head]
            text = clean(" ".join(t for t, _, _ in parts))
            if text:
                g = [x for _, _, gg in parts for x in gg]
                notes.append({"id": f"merrill:{poem}:0:0", "poem": poem, "line": "", "line_start": None, "line_end": None,
                              "kind": "headnote", "lemma": "", "text": text, "latin": [x for _, ll, _ in parts for x in ll],
                              **({"greek_betacode": g} if g else {}), "source_url": url})
        seq = Counter()
        for c in d.iter("div2"):
            if c.get("type") != "commline":
                continue
            n = c.get("n", "")
            lem = c.find(".//lemma")
            lemma = render(lem)[0] if lem is not None else ""
            text, latin, greek = render(c, skip=lem)
            text = re.sub(r"^[:.,;\s]+", "", text)
            if not text and not lemma:
                continue
            a, b = line_span(n)
            seq[n] += 1
            notes.append({"id": f"merrill:{poem}:{n}:{seq[n]}", "poem": poem, "line": n, "line_start": a, "line_end": b,
                          "kind": "note", "lemma": lemma, "text": text, "latin": latin,
                          **({"greek_betacode": greek} if greek else {}), "source_url": url})
            per_poem[poem] += 1
    intro = []
    for d in root.iter("div1"):
        if d.get("type") != "intro":
            continue
        for hn, sec in enumerate((c for c in d if c.tag == "div2"), 1):
            heading = clean("".join(sec.find("head").itertext())) if sec.find("head") is not None else ""
            for para in sec.iter("div3"):
                n = para.get("n", "")
                text, latin, greek = render(para)
                intro.append({"id": f"merrill-intro:{n}", "section": n, "heading_n": sec.get("n") or str(hn), "heading": heading,
                              "subsections": [chr(97 + k) for k, _ in enumerate(para.iter("div4"))],
                              "text": re.sub(rf"^{re.escape(n)}\.\s*", "", text), "latin": latin,
                              **({"greek_betacode": greek} if greek else {}),
                              "source_url": f"https://www.perseus.tufts.edu/hopper/text?doc={DOC}:text=intro:section={n}"})
    with open(OUT / "notes.jsonl", "w", encoding="utf-8") as f:
        for r in notes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "intro.jsonl", "w", encoding="utf-8") as f:
        for r in intro:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    line_notes = [r for r in notes if r["kind"] == "note"]
    manifest = {
        "name": "E. T. Merrill, Catullus (1893): commentary and introduction, Perseus Digital Library TEI",
        "date": time.strftime("%Y-%m-%d"), "user_agent": UA, "document": DOC,
        "source": {"author": "Elmer Truesdell Merrill", "title": "Catullus", "year": "1893",
                   "tei_sourceDesc": clean("".join(src.itertext())) if src is not None else "",
                   "status": "public domain (published 1893 in the United States)"},
        "licence": {"name": "Perseus availability statement (TEI header of the file)", "quote": licence,
                    "perseus_page_url": PAGE_URL, "perseus_page_quote": page_quote,
                    "note": "The 1893 text is public domain; the statement above is Perseus's condition on its markup "
                            "(credit, non-commercial, statement kept intact). Checked against the header on the date above.",
                    "plain": "The underlying book (1893) is in the public domain; the encoding used here carries the two statements "
                             "quoted above (`quote` from the TEI header, `perseus_page_quote` from the Perseus page of the text)."},
        "greek": "converted from beta code with the betacode package" if beta_to_uni else "left in beta code (betacode package missing)",
        "files": {NAME: {"url": fetched.get("url", URL), "sha256": sha(RAW / NAME), "bytes": (RAW / NAME).stat().st_size,
                         "fetched_at": fetched.get("fetched_at", "")}},
        "counts": {"poems": len(poems), "notes": len(line_notes), "headnotes": sum(r["kind"] == "headnote" for r in notes),
                   "notes_without_lemma": sum(not r["lemma"] for r in line_notes),
                   "notes_with_unparsed_line": sum(r["line_start"] is None for r in line_notes),
                   "poems_without_line_notes": [p for p in poems if not per_poem[p]],
                   "notes_per_poem": {p: per_poem[p] for p in poems},
                   "intro_sections": len(intro), "intro_headings": len({r["heading_n"] for r in intro})},
    }
    for name in ("notes.jsonl", "intro.jsonl"):
        manifest["files"][name] = {"sha256": sha(OUT / name), "bytes": (OUT / name).stat().st_size}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest["counts"].items() if k != "notes_per_poem"}, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
