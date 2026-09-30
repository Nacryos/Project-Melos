"""Collect the Centre for the Greek Language's Anthology of Archaic Lyric Poetry.

Source: https://www.greek-language.gr/digitalResources/ancient_greek/anthology/poetry/
(Ψηφίδες για την ελληνική γλώσσα, Ανθολογία Αρχαϊκής Λυρικής Ποίησης, ed.
Sotiris Tselikas). Each text page carries an ancient Greek poem or fragment
cited by a modern edition number (West, Page, Voigt, Maehler, ...) with one
or more Modern Greek translations by named translators.

The site states "© Κέντρο Ελληνικής Γλώσσας, all rights reserved". It is
collected under the owner decision of 2026-09-30 (docs/decisions.md): rights
are recorded on every record and attribution is kept; they are not a gate.
Raw HTML is saved with its SHA-256 before parsing. Nothing is authored here:
Greek text, translations, citations and names come from the saved pages.

Usage: python scripts/ingest_p2_cgl_anthology.py [--refresh] [--limit N] [--delay S]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_cgl_anthology"
OUT = ROOT / "data/processed/p2_cgl_anthology.jsonl"
REPORT = ROOT / "data/reports/p2_cgl_anthology.json"
BASE = "https://www.greek-language.gr/digitalResources/ancient_greek/anthology/poetry/"
CATALOG = urljoin(BASE, "browse.html")
CONTRIBUTORS = urljoin(BASE, "contributors.html")
SOURCE = "p2_cgl_anthology"
RIGHTS = "© Κέντρο Ελληνικής Γλώσσας (Centre for the Greek Language); all rights reserved as stated by the site. Admitted per docs/decisions.md (2026-09-30)."
EDITION_TOKENS = ("Lobel-Page", "West", "Page", "Voigt", "Maehler", "Davies", "Campbell", "Gentili", "Lobel", "Snell",
                  "Diehl", "Bergk", "Edmonds", "PMG", "PMGF", "L-P", "LP", "Gerber", "Kock", "Adrados")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-cgl-anthology-collector/1.0 (research corpus; attribution retained; polite cached fetches)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, path: Path, *, refresh: bool, delay: float, receipt: dict | None = None) -> bytes:
    if path.exists() and path.stat().st_size and not refresh:
        if receipt is not None:
            receipt.update({"requested_url": url, "cached": True, "http_status": None})
        return path.read_bytes()
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=60)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty response")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            if receipt is not None:
                receipt.update({"requested_url": url, "resolved_url": response.url,
                                "cached": False, "http_status": response.status_code,
                                "fetched_at_utc": datetime.now(timezone.utc).isoformat()})
            time.sleep(delay)
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed for {url}: {error}")


def clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text.replace("\r", "")).strip()


def cited_edition_label(citation: str) -> str:
    """Preserve the printed edition label, preferring a complete compound name.

    This extracts labels only: it does not assert numbering equivalences or
    identify an edition from an otherwise unqualified fragment number.
    """
    for token in sorted(EDITION_TOKENS, key=len, reverse=True):
        pattern = re.escape(token).replace(r"\-", r"\s*[-–—]\s*")
        match = re.search(rf"(?<![A-Za-z]){pattern}(?![A-Za-z])", citation)
        if match:
            return match.group(0)
    return ""


def parse_catalog(html: bytes) -> list[dict]:
    """Every text link with its section, author and column heading, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    # The page header also uses the span9 class; the catalog column is the
    # one that actually holds text links.
    column = next((div for div in soup.select("div.span9") if div.select_one("a[href*='text_id=']")), None)
    if column is None:
        raise ValueError("Catalog layout changed: no div.span9 with text links found")
    entries: list[dict] = []
    section = author = ""
    for element in column.children:
        if not isinstance(element, Tag):
            continue
        if element.name == "h3":
            style = element.get("style", "")
            label = clean(element.get_text(" "))
            if "background" in style:
                section = label
            else:
                author = label
            continue
        for table in element.select("table") if element.name != "table" else [element]:
            headers: list[str] = []
            for row in table.select("tr"):
                # A single catalog table contains successive heading/data bands.
                # Never apply the first band's headings to all later rows.
                row_headers = row.find_all("th", recursive=False)
                if row_headers:
                    headers = [clean(th.get_text(" ")) for th in row_headers]
                    continue
                cells = row.find_all("td", recursive=False)
                for index, cell in enumerate(cells):
                    heading = headers[index] if index < len(headers) else ""
                    for link in cell.select("a[href]"):
                        match = re.search(r"text_id=(\d+)", link["href"])
                        if not match:
                            continue
                        entries.append({"text_id": int(match.group(1)), "section": section, "author": author,
                                        "group": heading, "catalog_label": clean(link.get_text(" "))})
    return entries


def block_lines(block: Tag) -> list[dict]:
    """Verse lines of one `.anth_text` block, with source line numbers where printed."""
    lines: list[dict] = []
    pending_label = ""
    current: list[str] = []

    def flush() -> None:
        nonlocal current, pending_label
        text = clean("".join(current))
        if text:
            lines.append({"label": pending_label, "text": text})
            pending_label = ""
        current = []

    container = block.select_one("td") or block
    for node in container.descendants:
        if isinstance(node, NavigableString):
            parent = node.parent
            if isinstance(parent, Tag) and "numbering" in parent.get("class", []):
                continue
            current.append(str(node))
        elif isinstance(node, Tag):
            if node.name == "br":
                flush()
            elif node.name == "p" and current:
                flush()
            elif "numbering" in node.get("class", []):
                flush()
                pending_label = clean(node.get_text(" "))
    flush()
    # Paragraph-per-line layouts (translations) leave text in <p> elements; the
    # loop above flushes at each <p> boundary, so nothing is joined across lines.
    return lines


def parse_text_page(html: bytes, entry: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one("div.part-header")
    title_author = clean(header.h2.get_text(" ")) if header and header.h2 else entry["author"]
    citation = clean(header.h3.get_text(" ")) if header and header.h3 else entry["catalog_label"]
    crumbs = [clean(li.get_text(" ")).rstrip("/").strip() for li in soup.select("ul.breadcrumb li")]
    crumbs = [crumb for crumb in crumbs if crumb]
    greek_block = soup.select_one("div.left-part div.anth_text")
    if greek_block is None:
        raise ValueError("no Greek text block")
    greek_lines = block_lines(greek_block)
    greek_text = "\n".join(line["text"] for line in greek_lines)
    if not GREEK.search(greek_text):
        raise ValueError("Greek block contains no Greek letters")
    translations = []
    tabs = soup.select("div.right-part ul.nav-tabs a[data-toggle=tab]")
    panes = soup.select("div.right-part div.tab-content > div.tab-pane")
    pane_by_id: dict[str, Tag] = {}
    for pane in panes:
        pane_id = pane.get("id", "")
        if not pane_id or pane_id in pane_by_id:
            raise ValueError("Translation panes have missing or duplicate IDs")
        pane_by_id[pane_id] = pane
    linked_panes: set[str] = set()
    for tab in tabs:
        href = tab.get("href", "")
        pane_id = href[1:] if href.startswith("#") else ""
        if pane_id not in pane_by_id or pane_id in linked_panes:
            raise ValueError(f"Translation tab has missing or ambiguous pane target: {href!r}")
        pane = pane_by_id[pane_id]
        linked_panes.add(pane_id)
        translator = clean(tab.get("title") or tab.get_text(" "))
        block = pane.select_one("div.anth_text")
        if block is None:
            raise ValueError(f"Translation pane {pane_id!r} has no text block")
        lines = block_lines(block)
        text = "\n".join(line["text"] for line in lines)
        if text:
            translations.append({"translator": translator, "lines": lines, "text": text,
                                 "pane_id": pane.get("id", "")})
    if linked_panes != set(pane_by_id):
        raise ValueError("Translation pane has no corresponding translator tab")
    edition = cited_edition_label(citation)
    return {"author": title_author, "citation": citation, "crumbs": crumbs, "greek_lines": greek_lines,
            "greek_text": greek_text, "translations": translations, "edition_token": edition}


def download_raw_selection(raw_dir: Path, text_ids: list[int], *, delay: float) -> dict:
    """Fetch only catalog, contributors and requested pages into fresh staging.

    No text-page parser, processed records or production corpus is touched.
    The manifest is checkpointed after each HTTP fetch, including failures.
    """
    raw_dir = raw_dir.resolve()
    raw_dir.relative_to((ROOT / "data/staging").resolve())
    if not text_ids or len(set(text_ids)) != len(text_ids):
        raise ValueError("Download-only selection requires distinct text IDs")
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise ValueError("Download-only raw directory must be new or empty")
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"status": "raw_download_in_progress", "requested_text_ids": text_ids,
                "files": [], "failures": []}
    manifest_path = raw_dir / "fetch-manifest.json"

    def checkpoint() -> None:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def retrieve(url: str, filename: str, entry: dict | None = None) -> bytes:
        receipt: dict = {}
        try:
            content = fetch(url, raw_dir / filename, refresh=False, delay=delay, receipt=receipt)
        except Exception as exc:
            manifest["status"] = "raw_download_failed"
            manifest["failures"].append({"requested_url": url, "error": str(exc),
                                         "failed_at_utc": datetime.now(timezone.utc).isoformat()})
            checkpoint()
            raise
        receipt.update({"raw_path": (raw_dir / filename).relative_to(ROOT).as_posix(),
                        "sha256": sha256(content), "bytes": len(content)})
        if entry is not None:
            receipt["catalog_entry"] = entry
        manifest["files"].append(receipt)
        checkpoint()
        return content

    catalog = retrieve(CATALOG, "browse.html")
    entries = parse_catalog(catalog)
    selected = []
    for text_id in text_ids:
        matches = [entry for entry in entries if entry["text_id"] == text_id]
        if len(matches) != 1:
            manifest["status"] = "catalog_selection_failed"
            manifest["failures"].append({"text_id": text_id, "catalog_matches": len(matches)})
            checkpoint()
            raise ValueError(f"Requested page {text_id} is not unique in the fetched catalog")
        selected.append(matches[0])
    retrieve(CONTRIBUTORS, "contributors.html")
    for entry in selected:
        text_id = entry["text_id"]
        retrieve(f"{CATALOG}?text_id={text_id}", f"text_{text_id}.html", entry)
    manifest["status"] = "raw_download_complete_pending_independent_audit"
    checkpoint()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-download pages that are already cached")
    parser.add_argument("--limit", type=int, default=0, help="stop after N text pages (smoke test)")
    parser.add_argument("--delay", type=float, default=0.4, help="seconds to wait after each download")
    parser.add_argument("--download-only", action="store_true", help="fetch selected raw pages only; no final records")
    parser.add_argument("--raw-dir", type=Path, help="new/empty directory under data/staging for download-only mode")
    parser.add_argument("--text-id", type=int, action="append", default=[], help="catalog text ID for download-only mode (repeatable)")
    args = parser.parse_args()
    if args.download_only:
        if not args.raw_dir or args.refresh or args.limit:
            parser.error("--download-only requires --raw-dir and does not accept --refresh or --limit")
        manifest = download_raw_selection(args.raw_dir, args.text_id, delay=args.delay)
        print(f"Downloaded {len(manifest['files'])} raw files; pending independent audit. No final records written.")
        return
    if args.raw_dir or args.text_id:
        parser.error("--raw-dir and --text-id require --download-only")
    RAW.mkdir(parents=True, exist_ok=True)
    catalog_raw = fetch(CATALOG, RAW / "browse.html", refresh=args.refresh, delay=args.delay)
    contributors_raw = fetch(CONTRIBUTORS, RAW / "contributors.html", refresh=args.refresh, delay=args.delay)
    entries = parse_catalog(catalog_raw)
    if not entries:
        raise ValueError("Catalog parse found no text links")
    seen: set[int] = set()
    unique = []
    for entry in entries:
        if entry["text_id"] in seen:
            continue
        seen.add(entry["text_id"])
        unique.append(entry)
    if args.limit:
        unique = unique[:args.limit]
    records: list[dict] = []
    failures: list[dict] = []
    for number, entry in enumerate(unique, 1):
        url = f"{CATALOG}?text_id={entry['text_id']}"
        path = RAW / f"text_{entry['text_id']}.html"
        try:
            html = fetch(url, path, refresh=args.refresh, delay=args.delay)
            page = parse_text_page(html, entry)
        except Exception as exc:  # noqa: BLE001 - logged per page, collection continues
            failures.append({"text_id": entry["text_id"], "url": url, "error": str(exc)})
            print(f"FAILED text_id={entry['text_id']}: {exc}", flush=True)
            continue
        digest = sha256(html)
        raw_rel = path.relative_to(ROOT).as_posix()
        work = " / ".join(part for part in (entry["section"], entry["group"]) if part) or entry["section"] or "Ανθολογία Αρχαϊκής Λυρικής Ποίησης"
        base_id = f"{SOURCE}:{entry['text_id']}"
        metadata = {
            "text_id": entry["text_id"],
            "anthology": "Ανθολογία Αρχαϊκής Λυρικής Ποίησης (Ψηφίδες για την ελληνική γλώσσα)",
            "anthology_editor": "Σωτήρης Τσέλικας",
            "publisher": "Κέντρο Ελληνικής Γλώσσας",
            "catalog_section": entry["section"],
            "catalog_author": entry["author"],
            "catalog_group": entry["group"],
            "breadcrumb": page["crumbs"],
            "cited_edition_token": page["edition_token"] or None,
            "translators": [item["translator"] for item in page["translations"]],
            "rights_note": RIGHTS,
            "contributors_url": CONTRIBUTORS,
        }
        records.append({
            "id": base_id, "source": SOURCE, "source_url": url, "raw_path": raw_rel, "raw_sha256": digest,
            "author": page["author"] or entry["author"], "work": work,
            "edition": f"Modern edition as cited by the anthology: {page['edition_token']}" if page["edition_token"] else "Modern edition as cited by the anthology (unspecified)",
            "citation": page["citation"], "language": "grc", "text": page["greek_text"], "kind": "text",
            "quality": "source_text", "license": "all rights reserved (Centre for the Greek Language); see metadata.rights_note",
            "lines": page["greek_lines"], "metadata": metadata,
        })
        for index, translation in enumerate(page["translations"], 1):
            records.append({
                "id": f"{base_id}:tr{index}", "source": SOURCE, "source_url": url + f"#{translation['pane_id']}" if translation["pane_id"] else url,
                "raw_path": raw_rel, "raw_sha256": digest,
                "author": re.sub(r"^Μετ\.\s*", "", translation["translator"]) or "unknown", "work": work,
                "edition": "Modern Greek translation printed in the anthology", "citation": page["citation"],
                "language": "ell", "text": translation["text"], "kind": "translation", "quality": "source_text",
                "license": "all rights reserved (translator / Centre for the Greek Language); see metadata.rights_note",
                "parent_id": base_id, "lines": translation["lines"],
                "metadata": {**metadata, "translator": translation["translator"], "translation_of": base_id},
            })
        if number % 25 == 0:
            print(f"{number}/{len(unique)} pages, {len(records)} records", flush=True)
    if not records:
        raise RuntimeError("No records collected; output not written")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(OUT)
    report = {
        "status": "collected_pending_index_acceptance",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": BASE, "catalog_url": CATALOG, "catalog_sha256": sha256(catalog_raw),
        "contributors_sha256": sha256(contributors_raw),
        "policy": "docs/decisions.md 2026-09-30: modern editions admitted; rights recorded per record",
        "catalog_text_links": len(entries), "distinct_text_pages": len(unique),
        "pages_collected": len(unique) - len(failures), "failures": failures,
        "record_count": len(records),
        "counts_by_kind": dict(Counter(r["kind"] for r in records)),
        "counts_by_author": dict(Counter(r["author"] for r in records if r["kind"] == "text")),
        "counts_by_section": dict(Counter(r["metadata"]["catalog_section"] for r in records if r["kind"] == "text")),
        "cited_edition_tokens": dict(Counter(r["metadata"].get("cited_edition_token") or "unspecified" for r in records if r["kind"] == "text")),
        "output": OUT.relative_to(ROOT).as_posix(), "output_sha256": sha256(OUT.read_bytes()),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records from {report['pages_collected']} pages to {OUT}; {len(failures)} failures", flush=True)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
