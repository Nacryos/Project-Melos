#!/usr/bin/env python3
"""Ingest Allen and Greenough's New Latin Grammar for Schools and Colleges (Ginn, 1903; public domain) from the
Perseus Digital Library TEI, `Perseus:text:1999.04.0001` (one file from the hopper's `dltext` endpoint).

The TEI marks every numbered section with <milestone unit="smythp" n="603"/> and every lettered subsection with
<milestone unit="smythsub" n="a"/>, inside three parts (div1) of chapters (div2), subsections (div3) and
sub-subsections (div4), each with a <head>. The file is walked in document order: text belongs to the section and
sub-letter last opened, and each row carries the heading path in force where it opened. So one row is a section's
opening text (`sub` empty) or one lettered subsection, and a whole section is its rows in order.
Rendering: one line per paragraph, list item ("1. ...") and table row (cells joined by " | "); notes in square
brackets where they stand; the metrical schemes, which are images in the edition (<figure/>), become "[scheme]".


The TEI has no index. The book's own Index of Words and Subjects is read from the Internet Archive's OCR text of a scan
of the same 1903 printing (item `allengreenoughsn00alleiala`), and written with the headings of the TEI as a
subject -> section map (subjects.jsonl). The OCR is unaudited: a reference is marked `confirmed` only when a word of
its subject also stands in the section of the clean TEI it points to, and the lookups use confirmed references alone.

Outputs (data/open/latin/allen-greenough/): sections.jsonl, subjects.jsonl, manifest.json.
Usage: python -I scripts/ingest_open_allen_greenough.py        (downloads the raw file when it is missing)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "latin" / "allen-greenough"
OUT = ROOT / "data" / "open" / "latin" / "allen-greenough"
DOC = "Perseus:text:1999.04.0001"
URL = f"https://www.perseus.tufts.edu/hopper/dltext?doc={DOC}"
NAME = "Perseus_text_1999.04.0001.xml"
README_URL = "https://raw.githubusercontent.com/alpheios-project/grammar-allen-greenough/master/README.md"
UA = "Melos/1.0 (+https://greeklyric.com)"
INDEX_ITEM = "allengreenoughsn00alleiala"
INDEX_URL = f"https://archive.org/download/{INDEX_ITEM}/{INDEX_ITEM}_djvu.txt"
INDEX_META_URL = f"https://archive.org/metadata/{INDEX_ITEM}"
RAW_INDEX = ROOT / "data" / "raw" / "latin" / "allen-greenough-index"
RUNNING_HEAD = "INDEX OF WORDS AND SUBJECTS"
STOP = set("a an and the of in on to with for by or as at from is are its see cf".split())
REF = re.compile(r"(?<![\w.])(\d{1,3})(?:\s?-\s?(\d{1,3}))?(?:\.\s?([a-z¢]|\d{1,2})(?!\w))?")
DEPTH = {"div1": 0, "div2": 1, "div3": 2, "div4": 3}
BLOCKS = {"p", "item", "row", "table", "list", "head", "l", "lg"}


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


def clean_line(s: str) -> str:
    s = unicodedata.normalize("NFC", re.sub(r"[ \t\r\f\v]+", " ", s)).strip()
    return re.sub(r" +([,;:.!?)])", r"\1", s)


def clean(s: str) -> str:
    lines = [clean_line(x) for x in s.split("\n")]
    return "\n".join(x for x in lines if x and x != "|")


def fold(s: str) -> str:
    """Lower case, marks stripped, ligatures opened, v -> u, j -> i, everything else a space (as backend.latin_text)."""
    s = unicodedata.normalize("NFD", s.lower().replace("æ", "ae").replace("œ", "oe"))
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("v", "u").replace("j", "i")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def stems(subject: str) -> list[str]:
    """The content words of a subject, cut short enough to meet their plural or adjective in the text."""
    return [w[:max(4, len(w) - 2)] for w in fold(subject).split() if len(w) >= 3 and w not in STOP and not w.isdigit()]


def index_entries(text: str) -> list[str]:
    """The entries of the printed index out of the OCR text: one string each, in the order printed. An OCR paragraph
    is an entry unless the one before it stops at a comma, semicolon or hyphen, or it opens with one."""
    lines = text.split("\n")
    first = next(i for i, l in enumerate(lines) if l.strip() == RUNNING_HEAD)
    end = next(i for i, l in enumerate(lines) if i > first and l.strip().startswith("LATIN AUTHORS AND THEIR WORKS"))
    start = next(i for i in range(first, end) if lines[i].startswith("A, "))
    blocks, cur = [], []
    for l in lines[start:end] + [""]:
        t = l.strip()
        if not t or t == RUNNING_HEAD or re.fullmatch(r"\d{1,3}", t):
            if cur:
                blocks.append(re.sub(r"(?<=[a-z])- (?=[a-z])", "", " ".join(cur)))     # a word broken at the line end
                cur = []
            continue
        cur.append(t)
    entries: list[str] = []
    for b in blocks:
        if entries and (entries[-1].endswith((",", ";", "-")) or b.startswith((";", ","))):
            entries[-1] += " " + b
        else:
            entries.append(b)
    return entries


def split_head(entry: str) -> tuple[str, str]:
    """Subject (up to the first comma outside brackets) and the rest."""
    depth = 0
    for i, c in enumerate(entry):
        depth += (c == "(") - (c == ")")
        if c == "," and depth <= 0:
            return entry[:i].strip(), entry[i + 1:]
    return entry.strip(), ""


def subjects_from_index(entries: list[str], rows: list[dict]) -> tuple[list[dict], dict]:
    """One row per section reference of the index. A number after 'NNN. ' and a bare number smaller than the section
    before it are items of that section, not sections. `row` is the row of sections.jsonl the reference lands on."""
    row_text = {r["id"]: fold(" ".join(r["heading_path"]) + " " + r["text"]) for r in rows}
    sec_text: dict[str, str] = {}
    for r in rows:
        sec_text[r["section"]] = sec_text.get(r["section"], "") + " " + row_text[r["id"]]
    last = max(int(x) for x in sec_text if x.isdigit())
    out, stats = [], {"entries": len(entries), "entries_with_references": 0, "see_only_or_unreadable": 0}
    for n, entry in enumerate(entries):
        subject, rest = split_head(entry)
        want = stems(subject)
        bare = not want                     # a letter or ending as subject: the words of each detail stand in
        found = False
        for seg in rest.split(";"):
            prev, detail = 0, ""
            for k, m in enumerate(REF.finditer(seg)):
                a, b, sub = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace("¢", "c")
                if k == 0:
                    detail = seg[:m.start()].strip(" ,.")
                    want = stems(detail) if bare else want
                if seg[:m.start()].endswith("p. ") or not 1 <= a <= last or a < prev:
                    continue
                prev = a
                span = [str(x) for x in range(a, b + 1)] if a < b <= last else [str(a)]
                if sub.isalpha() and f"ag:{a}{sub}" in row_text and len(span) == 1:
                    land, hay = f"ag:{a}{sub}", row_text[f"ag:{a}{sub}"] + " " + row_text.get(f"ag:{a}", "")
                    ok = any(" " + w in " " + hay for w in want)
                elif len(span) == 1:
                    sub, land = "", f"ag:{a}"
                    ok = any(" " + w in " " + sec_text.get(str(a), "") for w in want)
                else:                               # a range: the first section in it that has every word of the subject
                    sub = ""
                    hit = next((x for x in span if want and all(" " + w in " " + sec_text.get(x, "") for w in want)), None)
                    land, ok = f"ag:{hit or a}", hit is not None
                if land not in row_text:            # a section whose opening text has no row of its own
                    land = next((r["id"] for r in rows if r["section"] == land[3:]), "")
                if not land:
                    continue
                found = True
                out.append({"id": f"ag-index:{n}:{len(out)}", "source": "index-ocr", "subject": subject, "detail": detail,
                            "ref": m.group(0), "section": land[3:].rstrip("abcdefghijklmnopqrstuvwxyz"), "sub": sub,
                            "to": str(b) if len(span) > 1 else "", "row": land, "confirmed": bool(ok)})
        stats["entries_with_references" if found else "see_only_or_unreadable"] += 1
    stats["references"] = len(out)
    stats["references_confirmed"] = sum(r["confirmed"] for r in out)
    return out, stats


def subjects_from_headings(rows: list[dict]) -> list[dict]:
    """One row per heading of the TEI (every level of the heading path): the sections that stand under it."""
    seen: dict[tuple, dict] = {}
    for r in rows:
        for d in range(len(r["heading_path"])):
            key = tuple(r["heading_path"][:d + 1])
            if key not in seen:
                seen[key] = {"id": f"ag-heading:{len(seen)}", "source": "heading", "subject": key[-1],
                             "detail": " > ".join(key[:-1]), "ref": "", "section": r["section"], "sub": r["sub"],
                             "to": r["section"], "row": r["id"], "confirmed": True}
            seen[key]["to"] = r["section"]
    for h in seen.values():
        h["ref"] = h["section"] if h["to"] == h["section"] else f"{h['section']}-{h['to']}"
    return list(seen.values())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = ensure_raw(URL, RAW / NAME, "Perseus hopper dltext; the file's own availability statement is quoted in the manifest")
    root = etree.parse(str(RAW / NAME), etree.XMLParser(recover=True, resolve_entities=False, no_network=True)).getroot()
    avail = root.find(".//teiHeader//availability")
    licence = re.sub(r"\s+", " ", "".join(avail.itertext())).strip() if avail is not None else ""
    readme_quote = ""       # this file's header has no availability statement: the Alpheios copy of the same Perseus TEI states one
    try:
        ensure_raw(README_URL, RAW / "alpheios_README.md", "README of alpheios-project/grammar-allen-greenough: licence sentence quoted in the manifest")
        m = re.search(r"This work is licensed under a .*?License[^\n]*", (RAW / "alpheios_README.md").read_text(encoding="utf-8"))
        readme_quote = m.group(0).strip() if m else ""
    except Exception as e:  # noqa: BLE001 - a second witness only
        readme_quote = f"not fetched: {e}"
    path: list[str] = ["", "", "", ""]
    rows: list[dict] = []
    cur: dict | None = None
    stray: list[str] = []                 # text met before the first numbered section
    figures = 0

    def emit(s: str):
        if not s:
            return
        (cur["buf"] if cur is not None else stray).append(s)

    def open_row(section: str, sub: str):
        nonlocal cur
        cur = {"section": section, "sub": sub, "heading_path": [h for h in path if h], "buf": []}
        rows.append(cur)

    def walk(e):
        nonlocal figures
        if not isinstance(e.tag, str):
            emit(re.sub(r"\s+", " ", e.tail or ""))
            return
        tag = e.tag
        if tag == "milestone":
            unit, n = e.get("unit"), (e.get("n") or "").strip()
            if unit == "smythp" and n:
                open_row(n, "")
            elif unit == "smythsub" and n and cur is not None:
                open_row(cur["section"], n)
            emit(re.sub(r"\s+", " ", e.tail or ""))
            return
        if tag == "head":
            text = clean_line(re.sub(r"\s+", " ", "".join(e.itertext())))
            parent = e.getparent().tag
            if parent in DEPTH:
                d = DEPTH[parent]
                path[d] = text
                for i in range(d + 1, 4):
                    path[i] = ""
            else:                                   # a table's or list's own caption: part of the text
                emit("\n" + text + "\n")
            emit(re.sub(r"\s+", " ", e.tail or ""))
            return
        if tag == "figure":
            figures += 1
            emit(" [scheme] " + re.sub(r"\s+", " ", "".join(e.itertext()) + (e.tail or "")))
            return
        if tag == "pb":
            emit(re.sub(r"\s+", " ", e.tail or ""))
            return
        if tag in BLOCKS:
            emit("\n")
        if tag == "item" and e.get("n"):
            emit(f"{e.get('n')}. ")
        if tag == "note":
            emit(" [Note: " if e.get("place") != "foot" else " [Footnote: ")
        emit(re.sub(r"\s+", " ", e.text or ""))
        for c in e:
            walk(c)
        if tag == "note":
            emit("] ")
        if tag == "cell":
            emit(" | ")
        if tag in BLOCKS:
            emit("\n")
        emit(re.sub(r"\s+", " ", e.tail or ""))

    body = root.find(".//text")
    walk(body)
    out = []
    for r in rows:
        text = clean("".join(r["buf"]))
        out.append({"id": f"ag:{r['section']}{r['sub']}", "section": r["section"], "sub": r["sub"],
                    "heading_path": r["heading_path"], "text": text,
                    "source_url": f"https://www.perseus.tufts.edu/hopper/text?doc={DOC}:smythp={r['section']}"})
    nums = [int(r["section"]) for r in out if r["sub"] == "" and r["section"].isdigit()]
    missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
    ids = [r["id"] for r in out]
    with open(OUT / "sections.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    index_file = RAW_INDEX / f"{INDEX_ITEM}_djvu.txt"
    index_fetched = ensure_raw(INDEX_URL, index_file, "Internet Archive OCR text of the 1903 printing; rights fields of the item quoted in the manifest")
    ensure_raw(INDEX_META_URL, RAW_INDEX / "metadata.json", "Internet Archive item metadata (rights fields)")
    item = json.loads((RAW_INDEX / "metadata.json").read_text(encoding="utf-8")).get("metadata", {})
    indexed, index_stats = subjects_from_index(index_entries(index_file.read_text(encoding="utf-8", errors="replace")), out)
    headings = subjects_from_headings(out)
    with open(OUT / "subjects.jsonl", "w", encoding="utf-8") as f:
        for r in headings + indexed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    parts = {}
    for r in out:
        if r["sub"] == "":
            parts[r["heading_path"][0] if r["heading_path"] else ""] = parts.get(r["heading_path"][0] if r["heading_path"] else "", 0) + 1
    manifest = {
        "name": "Allen and Greenough's New Latin Grammar for Schools and Colleges (1903), Perseus Digital Library TEI",
        "date": time.strftime("%Y-%m-%d"), "user_agent": UA, "document": DOC,
        "source": {"editors": "J. B. Greenough, G. L. Kittredge, A. A. Howard, Benj. L. D'Ooge", "publisher": "Ginn and Company",
                   "year": "1903", "status": "public domain (published 1903 in the United States)"},
        "licence": {"name": "Perseus availability statement (TEI header of the file)",
                    "quote": licence or "(none: the TEI header of this file carries no availability statement)",
                    "alpheios_readme_url": README_URL, "alpheios_readme_quote": readme_quote,
                    "perseus_page": "https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.04.0001 answered HTTP 403 "
                                    "('Please allow cookies') on 2026-11-15, so its rights sentence is not quoted here",
                    "note": "The 1903 text is public domain. The Alpheios README, which describes the same Perseus digitisation, "
                            "is the only licence statement obtained for the markup; treat the markup as non-commercial, share-alike.",
                    "plain": "The underlying book (1903) is in the public domain; the encoding used here carries the terms quoted above."},
        "index": {"what": "Index of Words and Subjects of the same book. It is not in the Perseus TEI (the file has no index), so it is "
                          "read from the Internet Archive's OCR text of a scan of the 1903 printing. OCR, unaudited.",
                  "item": f"https://archive.org/details/{INDEX_ITEM}",
                  "rights_fields": {k: item.get(k) for k in ("date", "publisher", "contributor", "possible-copyright-status", "licenseurl", "rights")},
                  "confirmed": "a reference is confirmed when a word of its subject stands in the section of the TEI it points to "
                               "(for a range, every word in one section of the range); lookups use confirmed references only",
                  "counts": {**index_stats, "headings": len(headings)}},
        "files": {NAME: {"url": fetched.get("url", URL), "sha256": sha(RAW / NAME), "bytes": (RAW / NAME).stat().st_size,
                         "fetched_at": fetched.get("fetched_at", "")},
                  "sections.jsonl": {"sha256": sha(OUT / "sections.jsonl"), "bytes": (OUT / "sections.jsonl").stat().st_size},
                  index_file.name: {"url": index_fetched.get("url", INDEX_URL), "sha256": sha(index_file), "bytes": index_file.stat().st_size,
                                    "fetched_at": index_fetched.get("fetched_at", "")},
                  "subjects.jsonl": {"sha256": sha(OUT / "subjects.jsonl"), "bytes": (OUT / "subjects.jsonl").stat().st_size}},
        "counts": {"rows": len(out), "sections": len(nums), "first_section": min(nums), "last_section": max(nums),
                   "missing_section_numbers": missing, "lettered_subsections": sum(1 for r in out if r["sub"]),
                   "duplicate_ids": sorted({i for i in ids if ids.count(i) > 1}), "empty_rows": sum(not r["text"] for r in out),
                   "sections_per_part": parts, "figures_replaced_by_[scheme]": figures,
                   "characters_before_first_section": len(clean("".join(stray)))},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
