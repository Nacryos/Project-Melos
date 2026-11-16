#!/usr/bin/env python3
"""Ingest Robinson Ellis, A Commentary on Catullus (2nd ed., Oxford 1889; public domain) from the archive.org OCR
text of item `commentaryoncatu00elliuoft`. OCR, UNAUDITED: every row says so, and the poem a note belongs to is
worked out, not read off a clean heading.

How a note gets its poem: the OCR keeps the running page head of the odd pages ("ON CATULLUS. LXIV. 301") and some of
the poem headings (a Roman numeral alone on a line); both are read leniently and kept only where they do not run
backwards. Between two such anchors, a note whose line number falls below the one before it opens the next poem.
A second pass then places each run of notes on the poem whose lines (Merrill's text in
data/open/latin/perseus-catullus/poems.jsonl) hold the words its notes open with. `poem_from` says where the poem
came from (`page-head`, `heading`, `reset`, or `text-match` when the second pass moved it) and `poem_check` how far
it is confirmed (`text-match`, `segment-match`, `unverified`). A note is a paragraph that opens with
a line number ("7. Martial xii. 59 ..."); its following paragraphs up to the next note belong to it. Ellis prints the
words commented on in heavy type, which the OCR does not keep, so there is no lemma phrase.

Outputs (data/open/latin/ellis-commentary/): notes.jsonl, manifest.json. Not loaded into data/reference_la.sqlite.
Usage: python -I scripts/ingest_open_ellis_commentary.py        (downloads the raw files when they are missing)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_text import normalize_la, tokenize_la  # noqa: E402
RAW = ROOT / "data" / "raw" / "latin" / "ellis-commentary"
OUT = ROOT / "data" / "open" / "latin" / "ellis-commentary"
ITEM = "commentaryoncatu00elliuoft"
URL = f"https://archive.org/download/{ITEM}/{ITEM}_djvu.txt"
META_URL = f"https://archive.org/metadata/{ITEM}"
UA = "Melos/1.0 (+https://greeklyric.com)"
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
NOISE = "OCR text, unaudited: poem assignment partly inferred; no lemma phrase; Greek and numerals often garbled"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_raw(url: str, path: Path, licence_note: str) -> dict:
    log = path.parent / "fetch-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    status = None
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
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


def roman(s: str) -> int | None:
    """A Roman numeral read leniently (l, 1, | for I); None when it is not one or is out of range."""
    t = s.strip().strip(".,:;'‘’ ").replace("l", "I").replace("1", "I").replace("|", "I").upper()
    if not t or not re.fullmatch(r"[IVXLC]+", t):
        return None
    total = 0
    for i, ch in enumerate(t):
        v = ROMAN[ch]
        total += -v if i + 1 < len(t) and ROMAN[t[i + 1]] > v else v
    return total if 1 <= total <= 116 else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = ensure_raw(URL, RAW / f"{ITEM}_djvu.txt", "archive.org OCR text; rights fields quoted in the manifest")
    ensure_raw(META_URL, RAW / "metadata.json", "archive.org item metadata")
    meta = json.loads((RAW / "metadata.json").read_text(encoding="utf-8")).get("metadata", {})
    lines = (RAW / f"{ITEM}_djvu.txt").read_text(encoding="utf-8", errors="replace").split("\n")
    start = next((i for i, l in enumerate(lines) if "ON CATULLUS. 1, 3" in l), 4000) - 130
    end = next((i for i, l in enumerate(lines) if i > start and re.fullmatch(r"\s*INDEX\.\s*", l)), len(lines))
    # anchors: (line index, poem, kind), kept only where they do not run backwards or leap
    anchors, last = [], 1
    for i in range(start, end):
        l = lines[i]
        m = re.search(r"ON CATULLUS[.,]\s*[-‘'’]?\s*([A-Za-z1|]+)[.,]?", l)
        v, kind = (roman(m.group(1)), "page-head") if m else (None, "")
        if v is None and l.strip() and len(l.strip()) <= 10 and not lines[i - 1].strip():
            v, kind = roman(l), "heading"
        if v is not None and last <= v <= last + 6:
            anchors.append((i, v, kind))
            last = v
    notes, cur, src, prev_n, a, seg = [], 1, "heading", 0, 0, 0
    open_note = None
    para: list[str] = []

    def flush():
        nonlocal para
        text = re.sub(r"\s+", " ", " ".join(para)).replace("- ", "-").strip() if para else ""
        para = []
        return text

    for i in range(start, end + 1):
        l = lines[i] if i < end else ""
        while a < len(anchors) and anchors[a][0] <= i:
            if anchors[a][1] > cur:
                cur, src, prev_n, seg = anchors[a][1], anchors[a][2], 0, seg + 1
            a += 1
        if re.search(r"ON CATULLUS[.,]|^\s*\d+\s+A COMMENTARY\s*$|^\s*A COMMENTARY\s+\d+\s*$", l):
            continue                                                  # running heads
        if l.strip():
            para.append(l.strip())
            continue
        text = flush()
        if not text:
            continue
        m = re.match(r"^(\d{1,3})(?:[-–](\d{1,3}))?[.,] (?=\S)", text)
        if m and int(m.group(1)) <= 408:
            n = int(m.group(1))
            if n < prev_n:                                            # numbering starts again: the next poem
                seg += 1
                nxt = anchors[a][1] if a < len(anchors) else 116
                if cur < nxt or a >= len(anchors):
                    cur, src = min(cur + 1, 116), "reset"
            prev_n = n
            open_note = {"id": "", "poem": str(cur), "line": m.group(0).strip(" .,"),
                         "line_start": n, "line_end": int(m.group(2)) if m.group(2) else n, "kind": "note", "lemma": "",
                         "text": text[m.end():], "poem_from": src, "poem_check": "", "segment": seg, "quality": NOISE,
                         "source_url": f"https://archive.org/details/{ITEM}"}
            notes.append(open_note)
        elif open_note is not None and open_note["segment"] == seg:
            open_note["text"] += "\n" + text
    # Second pass: place each run of notes (a segment) on the poem whose lines hold the words the notes open with.
    # Ellis opens most notes with the words commented on, so a note on line n of the right poem usually shares one
    # of its first words with that line of Merrill's text (u/v folded). Poems never run backwards.
    poem_lines: dict[int, dict[int, set]] = {}
    for x in (ROOT / "data" / "open" / "latin" / "perseus-catullus" / "poems.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(x)
        pm = re.match(r"\d+", r.get("poem", ""))
        if r.get("language") != "la" or not pm:
            continue
        for ln in r["lines"]:
            if str(ln["n"]).isdigit():
                poem_lines.setdefault(int(pm.group(0)), {}).setdefault(int(ln["n"]), set()).update(normalize_la(t) for t in tokenize_la(ln["text"]))

    def hit(note: dict, poem: int) -> bool:
        words = [normalize_la(t) for t in tokenize_la(note["text"][:60])][:3]
        have = poem_lines.get(poem, {}).get(note["line_start"], set())
        return any(len(w) >= 4 and w in have for w in words)

    prev = 1
    for sg in sorted({r["segment"] for r in notes}):
        group = [r for r in notes if r["segment"] == sg]
        guess = max(int(group[0]["poem"]), prev)
        scores = {p: sum(hit(r, p) for r in group) for p in range(prev, min(prev + 8, 116) + 1)}
        best = max(scores, key=lambda p: (scores[p], -abs(p - guess)))
        if scores[best] >= 2 or (scores[best] == 1 and len(group) <= 3):
            poem, how = best, "segment-match"
        else:
            poem, how = guess, "unverified"
        prev = poem
        for r in group:
            if poem != int(r["poem"]):
                r["poem_from"] = "text-match"
            r["poem"] = str(poem)
            r["poem_check"] = "text-match" if hit(r, poem) else how
    for k, r in enumerate(notes):
        r["id"] = f"ellis:{r['poem']}:{r['line_start']}:{k}"
        del r["segment"]
    with open(OUT / "notes.jsonl", "w", encoding="utf-8") as f:
        for r in notes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    per = Counter(r["poem"] for r in notes)
    manifest = {
        "name": "Robinson Ellis, A Commentary on Catullus (2nd ed. 1889): archive.org OCR text, UNAUDITED",
        "date": time.strftime("%Y-%m-%d"), "user_agent": UA, "item": ITEM, "quality": NOISE,
        "licence": {"possible-copyright-status": meta.get("possible-copyright-status", ""), "licenseurl": meta.get("licenseurl", ""),
                    "rights": meta.get("rights", ""), "note": "fields of the archive.org item metadata, verbatim; empty = the item has no such field"},
        "source": {k: meta.get(k, "") for k in ("title", "creator", "publisher", "date", "contributor", "sponsor")},
        "files": {f"{ITEM}_djvu.txt": {"url": fetched.get("url", URL), "sha256": sha(RAW / f"{ITEM}_djvu.txt"),
                                      "bytes": (RAW / f"{ITEM}_djvu.txt").stat().st_size, "fetched_at": fetched.get("fetched_at", "")},
                  "notes.jsonl": {"sha256": sha(OUT / "notes.jsonl"), "bytes": (OUT / "notes.jsonl").stat().st_size}},
        "counts": {"notes": len(notes), "anchors": Counter(k for _, _, k in anchors), "poems_with_notes": len(per),
                   "poems_without_notes": [str(p) for p in range(1, 117) if str(p) not in per],
                   "notes_by_poem_source": Counter(r["poem_from"] for r in notes),
                   "notes_by_poem_check": Counter(r["poem_check"] for r in notes), "notes_per_poem": dict(per)},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest["counts"].items() if k != "notes_per_poem"}, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
