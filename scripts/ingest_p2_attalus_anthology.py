"""Collect W. R. Paton's Greek Anthology translations from attalus.org, linked to the Greek epigrams.

Source: https://www.attalus.org/poetry/anthology.html lists one page per
epigrammatist. Each page gives every epigram's Anthology number as a red
label (``[5.10]``), the Gow-Page number in green, a link to the Greek text on
Perseus, and the English of W. R. Paton's Loeb edition (1916-18, public
domain in the US) lightly modernised by the site's editor. Translator's notes
are printed in green and are kept apart from the translation text.

Each translation is linked (``parent_id``) to the Perseus Greek Anthology row
for the same book and epigram when the index has one (``perseus:tlg7000...``
with citation ``5.10.1–5.10.4``); otherwise the Anthology reference is kept
in metadata as an unlinked reference. English translations are what let
English search reach Greek, so these records feed cross-lingual retrieval.

Usage: python scripts/ingest_p2_attalus_anthology.py --db /path/to/corpus.sqlite [--refresh]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_attalus_anthology"
OUT = ROOT / "data/processed/p2_attalus_anthology.jsonl"
REPORT = ROOT / "data/reports/p2_attalus_anthology.json"
SOURCE = "p2_attalus_anthology"
INDEX = "https://www.attalus.org/poetry/anthology.html"
EDITION = "W. R. Paton, The Greek Anthology (Loeb Classical Library, 1916-18), English translation as modernised on attalus.org"
LICENSE = ("Paton's 1916-18 translation is public domain in the United States; the attalus.org page is the site's own "
           "compilation with light modernisation (admitted per docs/decisions.md 2026-09-30; credit attalus.org)")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-attalus-collector/1.0 (research corpus; attribution retained; polite cached fetches)"
REF = re.compile(r'<A CLASS="ref" NAME="([0-9]+(?:\.[0-9]+)?[a-z]?)">\[[^\]]*\]</A>', re.I)
BOOK_TITLE = re.compile(r"Greek Anthology,\s*(\d+)", re.I)
POET_LINK = re.compile(r'<A HREF="[a-z0-9_]+\.html#[0-9.]+[a-z]?">[^<]+</A>\s*&rarr;', re.I)
BOLD_AUTHOR = re.compile(r"<B>\s*([^<]+?)\s*</B>", re.I)
GREEN = re.compile(r'<FONT CLASS="green">(.*?)</FONT>', re.I | re.S)
TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, path: Path, *, refresh: bool, delay: float) -> bytes:
    if path.exists() and path.stat().st_size and not refresh:
        return path.read_bytes()
    error = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=60)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty response")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            time.sleep(delay)
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed for {url}: {error}")


def decode(raw: bytes) -> str:
    match = re.search(rb'charset=([A-Za-z0-9_-]+)', raw[:2000])
    encoding = match.group(1).decode("ascii", "replace") if match else "utf-8"
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("latin-1")


def text_of(fragment: str) -> str:
    return SPACES.sub(" ", html.unescape(TAG.sub(" ", fragment))).strip()


def poet_pages(index_html: str) -> list[str]:
    pages = []
    for href in re.findall(r'HREF="([a-z0-9_]+\.html)"', index_html, re.I):
        if href.lower() in ("index.html", "anthology.html") or href in pages:
            continue
        pages.append(href)
    return pages


def parse_page(page_html: str) -> dict:
    title = text_of(re.search(r"<TITLE>(.*?)</TITLE>", page_html, re.I | re.S).group(1)) if re.search(r"<TITLE>", page_html, re.I) else ""
    poet = title.split(":", 1)[0].strip() if title else ""
    intro = re.search(r"<P>\s*<I>(.*?)</I>", page_html, re.I | re.S)
    full_name = None
    if intro:
        link = re.search(r'wikipedia\.org/wiki/[^"]+">([^<]+)</A>', intro.group(1))
        if link and poet and poet.lower() in link.group(1).lower():
            full_name = text_of(link.group(1))
    epigrams = []
    book_match = BOOK_TITLE.search(title or "")
    whole_book = book_match.group(1) if book_match else None
    matches = list(REF.finditer(page_html))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        chunk = page_html[start:end]
        chunk = re.split(r"<HR", chunk, 1, flags=re.I)[0]
        reference = match.group(1)
        if "." not in reference:
            if not whole_book:
                continue
            reference = f"{whole_book}.{reference}"
        # Whole-book pages point to a poet's own page for most epigrams; those
        # are collected from the poet page, so only inline translations count.
        if POET_LINK.search(chunk) and not re.search(r"<P>\s*[^<\s]", POET_LINK.sub("", chunk).split("<BR>", 1)[0]):
            continue
        author_here = None
        bold = BOLD_AUTHOR.search(chunk.split("<P>", 2)[0] if chunk.count("<P>") else chunk)
        if bold:
            label = text_of(bold.group(1))
            if label.isupper():
                label = " ".join(word.lower() if word.lower() in ("of", "the", "and") else word.capitalize() for word in label.split())
            author_here = label
        gow_page = None
        notes = []
        for green in GREEN.findall(chunk):
            value = text_of(green)
            gp = re.match(r"\{\s*(?:G-?P|F|HE|GP|Page)\s*([0-9]+[a-z]?)\s*\}", value, re.I)
            if gp:
                gow_page = gp.group(1)
            elif value:
                notes.append(value)
        chunk = GREEN.sub(" ", chunk)
        chunk = BOLD_AUTHOR.sub(" ", chunk, count=1) if author_here else chunk
        perseus = re.search(r'HREF="(http://www\.perseus\.tufts\.edu/hopper/text\?doc=[^"]+)"', chunk)
        # The translation starts at the first paragraph after the label line.
        paragraphs = [text_of(part) for part in re.split(r"<P>", chunk, flags=re.I)[1:]]
        paragraphs = [part for part in paragraphs if part and not part.startswith("G")]
        text = "\n".join(paragraphs).strip()
        if not text:
            continue
        epigrams.append({"reference": reference, "text": text, "gow_page": gow_page, "notes": notes,
                         "author": author_here, "perseus_url": html.unescape(perseus.group(1)) if perseus else None})
    return {"poet": full_name or poet, "poet_short": poet, "title": title, "epigrams": epigrams}


def link_targets(con: sqlite3.Connection) -> dict[str, str]:
    """book.number -> Perseus Greek Anthology passage id (first row of that epigram)."""
    targets: dict[str, str] = {}
    for identifier, citation in con.execute(
            "SELECT id, citation FROM passages WHERE id LIKE 'perseus:tlg7000.tlg001%' AND kind='text' ORDER BY sequence, id"):
        match = re.match(r"(\d+)\.(\d+[a-z]?)(?:\.|$|–)", citation or "")
        if match:
            targets.setdefault(f"{match.group(1)}.{match.group(2)}", identifier)
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=ROOT / "data/corpus.sqlite", help="index used to link translations to Greek rows")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    index_raw = fetch(INDEX, RAW / "anthology.html", refresh=args.refresh, delay=args.delay)
    pages = poet_pages(decode(index_raw))
    targets = {}
    if args.db.is_file():
        con = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
        targets = link_targets(con)
        con.close()
    records: list[dict] = []
    failures: list[dict] = []
    for name in pages:
        url = urljoin(INDEX, name)
        path = RAW / name
        try:
            raw = fetch(url, path, refresh=args.refresh, delay=args.delay)
            page = parse_page(decode(raw))
        except Exception as exc:  # noqa: BLE001 - logged, collection continues
            failures.append({"page": name, "error": str(exc)})
            continue
        digest = sha256(raw)
        raw_rel = path.relative_to(ROOT).as_posix()
        for epigram in page["epigrams"]:
            reference = epigram["reference"]
            book = reference.split(".", 1)[0]
            parent = targets.get(reference)
            record = {
                "id": f"{SOURCE}:{name.removesuffix('.html')}:{reference}", "source": SOURCE,
                "source_url": f"{url}#{reference}", "raw_path": raw_rel, "raw_sha256": digest,
                "author": epigram.get("author") or (page["poet"] if not BOOK_TITLE.search(page["title"] or "") else "unknown"), "work": f"Greek Anthology, book {book}",
                "edition": EDITION, "citation": f"AP {reference}", "language": "eng", "text": epigram["text"],
                "kind": "translation", "quality": "source_text", "license": LICENSE,
                "metadata": {"anthology_reference": reference, "gow_page_number": epigram["gow_page"],
                             "translator_notes": epigram["notes"], "perseus_greek_url": epigram["perseus_url"],
                             "attalus_page": url, "poet_label_short": page["poet_short"],
                             "translator": "W. R. Paton", "modernised_by": "attalus.org"},
            }
            if parent:
                record["parent_id"] = parent
            else:
                record["metadata"]["unlinked_reference"] = reference
            records.append(record)
        print(f"{name}: {len(page['epigrams'])} epigrams ({page['poet']})", flush=True)
    if not records:
        raise RuntimeError("No records collected")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(OUT)
    report = {
        "status": "collected_pending_index_acceptance", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "index_url": INDEX, "index_sha256": sha256(index_raw), "edition": EDITION, "license": LICENSE,
        "policy": "docs/decisions.md 2026-09-30", "pages": len(pages), "failures": failures,
        "record_count": len(records), "linked_to_perseus_greek": sum(1 for r in records if r.get("parent_id")),
        "unlinked": sum(1 for r in records if not r.get("parent_id")),
        "counts_by_poet": dict(Counter(r["author"] for r in records)),
        "link_targets_available": len(targets), "linking_index": str(args.db),
        "output": OUT.relative_to(ROOT).as_posix(), "output_sha256": sha256(OUT.read_bytes()),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pages", "record_count", "linked_to_perseus_greek", "unlinked")}))


if __name__ == "__main__":
    main()
