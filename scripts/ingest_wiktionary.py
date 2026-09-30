"""Stage Kaikki's Ancient Greek enwiktionary extraction without linguistic edits.

Run: python scripts/ingest_wiktionary.py

The raw JSONL is a Kaikki postprocessed Wiktextract export, not a critical
edition or an attestation in the lyric corpus. Each original JSON object is
preserved under ``entry``. The surrounding fields identify its raw line.
Re-running uses the saved raw snapshot; pass --refresh only to fetch a new one.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
INDEX_URL = "https://kaikki.org/dictionary/Ancient%20Greek/index.html"
DOWNLOAD_NAME = "kaikki.org-dictionary-AncientGreek.jsonl"
RAW_DIR = ROOT / "data" / "raw" / "wiktionary"
RAW_INDEX = RAW_DIR / "index.html"
RAW_DATA = RAW_DIR / DOWNLOAD_NAME
OUT = ROOT / "data" / "lexica" / "wiktionary-entries.jsonl"
REPORT = ROOT / "data" / "reports" / "wiktionary.json"
USER_AGENT = "melos-source-ingestion/1.0 (research corpus)"
MAX_DOWNLOAD_BYTES = 800_000_000


class DownloadLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.endswith(DOWNLOAD_NAME):
                self.links.append(urljoin(INDEX_URL, href))


def request(url: str):
    return Request(url, headers={"User-Agent": USER_AGENT})


def download(url: str, path: Path) -> dict:
    """Save full response bytes atomically; never accept a partial download."""
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(4):
        part = path.with_name(path.name + ".part")
        try:
            digest = hashlib.sha256()
            size = 0
            with urlopen(request(url), timeout=120) as response, part.open("wb") as target:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status} for {url}")
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError(f"Source exceeds size limit: {declared} bytes")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("Source exceeded size limit while downloading")
                    digest.update(chunk)
                    target.write(chunk)
                if declared and size != int(declared):
                    raise RuntimeError(f"Incomplete download: {size} of {declared} bytes")
                final_url = response.geturl()
                modified = response.headers.get("Last-Modified")
            if size == 0:
                raise RuntimeError(f"Empty source: {url}")
            os.replace(part, path)
            return {"url": final_url, "bytes": size, "sha256": digest.hexdigest(),
                    "last_modified": modified}
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
            last_error = error
            part.unlink(missing_ok=True)
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed for {url}: {last_error}")


def saved_file(path: Path, url: str) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        raise RuntimeError(f"Empty saved source: {path}")
    return {"url": url, "bytes": size, "sha256": digest.hexdigest(),
            "last_modified": None}


def source_snapshot(refresh: bool) -> tuple[dict, dict, str]:
    if refresh or not RAW_INDEX.exists():
        index = download(INDEX_URL, RAW_INDEX)
    else:
        index = saved_file(RAW_INDEX, INDEX_URL)
    page = RAW_INDEX.read_text(encoding="utf-8")
    parser = DownloadLinkParser()
    parser.feed(page)
    if len(set(parser.links)) != 1:
        raise RuntimeError(f"Expected one Ancient Greek JSONL link; found {parser.links}")
    source_url = parser.links[0]
    if refresh or not RAW_DATA.exists():
        raw = download(source_url, RAW_DATA)
    else:
        raw = saved_file(RAW_DATA, source_url)
    return index, raw, source_url


def source_dates(page: str) -> dict:
    # Source metadata only; no linguistic information is inferred here.
    text = re.sub(r"<[^>]+>", " ", page)
    match = re.search(
        r"structured data extracted on\s+(\d{4}-\d{2}-\d{2})\s+from the "
        r"enwiktionary dump dated\s+(\d{4}-\d{2}-\d{2})", text)
    return ({"kaikki_extracted_on": match.group(1),
             "enwiktionary_dump_date": match.group(2)} if match else {})


def ingest(raw: dict, source_url: str) -> dict:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    part = OUT.with_name(OUT.name + ".part")
    fields: Counter[str] = Counter()
    language_codes: Counter[str] = Counter()
    tag_locations: Counter[str] = Counter()
    line_count = 0
    missing_words = 0
    with RAW_DATA.open("rb") as source, part.open("w", encoding="utf-8", newline="\n") as target:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                raise RuntimeError(f"Blank source line {line_number}")
            try:
                entry = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError(f"Invalid source JSON at line {line_number}: {error}") from error
            if not isinstance(entry, dict):
                raise RuntimeError(f"Source line {line_number} is not an object")
            code = entry.get("lang_code")
            language_codes[str(code)] += 1
            if code != "grc":
                raise RuntimeError(f"Non-Ancient-Greek record on line {line_number}: {code!r}")
            if not isinstance(entry.get("word"), str) or not entry["word"]:
                missing_words += 1
            fields.update(entry.keys())
            for key in ("tags", "raw_tags", "senses", "forms", "alt_of", "form_of"):
                if key in entry:
                    tag_locations[key] += 1
            for sense in entry.get("senses", []):
                if isinstance(sense, dict):
                    for key in ("tags", "raw_tags", "alt_of", "form_of"):
                        if key in sense:
                            tag_locations[f"senses.{key}"] += 1
            for form in entry.get("forms", []):
                if isinstance(form, dict):
                    for key in ("tags", "raw_tags", "alt_of", "form_of"):
                        if key in form:
                            tag_locations[f"forms.{key}"] += 1
            record = {
                "id": f"wiktionary:kaikki:line:{line_number}",
                "source": "Kaikki Ancient Greek postprocessed enwiktionary extraction",
                "source_url": source_url,
                "raw_path": RAW_DATA.relative_to(ROOT).as_posix(),
                "raw_sha256": raw["sha256"],
                "raw_line": line_number,
                "raw_line_sha256": hashlib.sha256(line).hexdigest(),
                "license": "Wiktionary text CC-BY-SA-4.0/GFDL; merged fields may differ",
                "quality": "machine_extracted_unreviewed",
                "entry": entry,
            }
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
            line_count += 1
    if not line_count:
        part.unlink(missing_ok=True)
        raise RuntimeError("Source contained no JSONL records")
    if missing_words:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Source has {missing_words} records without a word")
    os.replace(part, OUT)
    return {"entries": line_count, "language_codes": dict(language_codes),
            "source_field_counts": dict(fields.most_common()),
            "tag_and_relation_locations": dict(tag_locations.most_common())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Download a new snapshot")
    args = parser.parse_args()
    index, raw, source_url = source_snapshot(args.refresh)
    counts = ingest(raw, source_url)
    report = {
        "dataset": "Ancient Greek Kaikki/Wiktextract, postprocessed enwiktionary",
        "status": "staged_pending_independent_audit",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "index_url": INDEX_URL,
        "index_raw_path": RAW_INDEX.relative_to(ROOT).as_posix(),
        "index_sha256": index["sha256"],
        "source_url": source_url,
        "raw_path": RAW_DATA.relative_to(ROOT).as_posix(),
        "raw_sha256": raw["sha256"],
        "raw_bytes": raw["bytes"],
        "raw_last_modified": raw["last_modified"],
        "output_path": OUT.relative_to(ROOT).as_posix(),
        "output_sha256": saved_file(OUT, "")["sha256"],
        "license": {
            "wiktionary_text": "CC-BY-SA-4.0 and GFDL",
            "notice_url": "https://en.wiktionary.org/wiki/Wiktionary:Copyrights",
            "caveat": "Wiktionary's notice allows separate terms for external material; Kaikki says its postprocessing merges additional sources. Per-field licenses are not established.",
        },
        "source_notes": "Kaikki's language-specific export is machine extracted and postprocessed. It is not validated scholarship, a Greek text edition, or evidence of Sappho attestation. Source objects are copied without linguistic transformation or inferred dialect labels.",
        "source_dates": source_dates(RAW_INDEX.read_text(encoding="utf-8")),
        **counts,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": counts["entries"], "raw_bytes": raw["bytes"],
                      "raw_sha256": raw["sha256"], "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
