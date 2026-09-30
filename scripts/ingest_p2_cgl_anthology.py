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
EDITION_TOKENS = ("West", "Page", "Voigt", "Maehler", "Davies", "Campbell", "Gentili", "Lobel", "Snell",
                  "Diehl", "Bergk", "Edmonds", "PMG", "PMGF", "L-P", "LP", "Gerber", "Kock", "Adrados")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-cgl-anthology-collector/1.0 (research corpus; attribution retained; polite cached fetches)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, path: Path, *, refresh: bool, delay: float) -> bytes:
    if path.exists() and path.stat().st_size and not refresh:
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
            time.sleep(delay)
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed for {url}: {error}")


def clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text.replace("\r", "")).strip()


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
            headers = [clean(th.get_text(" ")) for th in table.select("tr > th")]
            for row in table.select("tr"):
                cells = row.select("td")
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
    for tab, pane in zip(tabs, panes):
        translator = clean(tab.get("title") or tab.get_text(" "))
        block = pane.select_one("div.anth_text")
        if block is None:
            continue
        lines = block_lines(block)
        text = "\n".join(line["text"] for line in lines)
        if text:
            translations.append({"translator": translator, "lines": lines, "text": text,
                                 "pane_id": pane.get("id", "")})
    edition = next((token for token in EDITION_TOKENS if re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", citation)), "")
    return {"author": title_author, "citation": citation, "crumbs": crumbs, "greek_lines": greek_lines,
            "greek_text": greek_text, "translations": translations, "edition_token": edition}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-download pages that are already cached")
    parser.add_argument("--limit", type=int, default=0, help="stop after N text pages (smoke test)")
    parser.add_argument("--delay", type=float, default=0.4, help="seconds to wait after each download")
    args = parser.parse_args()
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
