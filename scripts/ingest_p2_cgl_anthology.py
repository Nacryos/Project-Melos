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
    gap_markup: list[dict] = []

    def flush() -> None:
        nonlocal current, pending_label, gap_markup
        text = clean("".join(current))
        if text:
            line = {"label": pending_label, "text": text}
            if gap_markup:
                line["source_gap_markup"] = gap_markup
                line["plain_text_limitation"] = "Source CSS gap spacing is not represented in plain text; no missing-letter count inferred."
            lines.append(line)
            pending_label = ""
        current = []
        gap_markup = []

    container = block.select_one("td") or block
    for node in container.descendants:
        if isinstance(node, NavigableString):
            parent = node.parent
            if isinstance(parent, Tag) and "numbering" in parent.get("class", []):
                continue
            current.append(str(node))
        elif isinstance(node, Tag):
            if "gap" in node.get("class", []):
                gap_markup.append({"tag": node.name, "classes": node.get("class", []),
                                   "source_html": str(node)})
            if node.name == "br":
                flush()
            elif node.name == "p" and current:
                flush()
            elif "numbering" in node.get("class", []):
                # Greek verse often starts with this marker; translations can
                # end their paragraph with it. The source p/br boundaries,
                # not the marker's position, delimit the numbered line.
                label = clean(node.get_text(" "))
                if pending_label and pending_label != label:
                    raise ValueError("Conflicting numbering spans inside one source line")
                pending_label = label
    flush()
    # Paragraph-per-line layouts (translations) leave text in <p> elements; the
    # loop above flushes at each <p> boundary, so nothing is joined across lines.
    return lines


def inline_translations(container: Tag) -> list[dict]:
    """Observed CGL layout: each direct text block immediately precedes its credit.

    Empty clearfix elements are layout only. Other unpaired content is an
    error, never a reason to borrow a credit from a later translation.
    """
    children = []
    for node in container.children:
        if isinstance(node, NavigableString):
            if clean(str(node)):
                raise ValueError("Unscoped text in inline translation container")
            continue
        if not isinstance(node, Tag):
            continue
        if "clearfix" in node.get("class", []) and not clean(node.get_text(" ")):
            continue
        children.append(node)
    if len(children) % 2:
        raise ValueError("Inline translation is missing its adjacent credit")
    translations = []
    for offset in range(0, len(children), 2):
        block, credit = children[offset:offset + 2]
        if block.name != "div" or "anth_text" not in block.get("class", []):
            raise ValueError("Unexpected inline translation block")
        if credit.name != "div" or "pull-right" not in credit.get("class", []):
            raise ValueError("Inline translation is not followed by its credit")
        names = credit.find_all("i", recursive=False)
        if len(names) != 1 or not clean(names[0].get_text(" ")):
            raise ValueError("Inline translation has missing or ambiguous credit")
        translator = clean(names[0].get_text(" "))
        if clean(credit.get_text(" ")) != translator:
            raise ValueError("Additional unscoped content in inline translation credit")
        lines = block_lines(block)
        text = "\n".join(line["text"] for line in lines)
        if not text:
            raise ValueError("Inline translation text block is empty")
        translations.append({"translator": translator, "lines": lines, "text": text,
                             "pane_id": "", "source_translation_locator": {
                                 "layout": "inline_adjacent_credit",
                                 "block_ordinal": offset // 2 + 1,
                                 "credit_selector": "adjacent div.pull-right > i"}})
    return translations


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
    inline_blocks = soup.select("div.right-part div.tab-content > div.anth_text")
    if inline_blocks:
        containers = soup.select("div.right-part div.tab-content")
        if panes or len(containers) != 1 or len(tabs) > 1 or any(tab.get("href") for tab in tabs):
            raise ValueError("Ambiguous mixed inline/tabbed translation layout")
        translations = inline_translations(containers[0])
        # The single unlinked tab is a section heading, not a translator credit.
        tabs = []
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


def discover_catalog(stage_dir: Path, *, delay: float) -> dict:
    """Save the source catalog and exact discovered URL set for independent review."""
    stage_dir = stage_dir.resolve()
    stage_dir.relative_to((ROOT / "data/staging").resolve())
    if stage_dir.exists() and any(stage_dir.iterdir()):
        raise ValueError("Discovery staging directory must be new or empty")
    receipt: dict = {}
    catalog_path = stage_dir / "browse.html"
    content = fetch(CATALOG, catalog_path, refresh=False, delay=delay, receipt=receipt)
    entries = parse_catalog(content)
    ids = [entry["text_id"] for entry in entries]
    duplicate_ids = [text_id for text_id, count in Counter(ids).items() if count > 1]
    discovery = {"status": "discovered_pending_independent_audit", "catalog_receipt": {
        **receipt, "raw_path": catalog_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(content), "bytes": len(content)},
        "page_count": len(entries), "unique_page_count": len(set(ids)), "duplicate_ids": duplicate_ids,
        "pages": [{**entry, "url": f"{CATALOG}?text_id={entry['text_id']}"} for entry in entries]}
    (stage_dir / "catalog-discovery.json").write_text(json.dumps(discovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not entries or duplicate_ids:
        raise ValueError("Catalog discovery empty or contains duplicate page IDs; audit required")
    return discovery


def download_raw_selection(raw_dir: Path, text_ids: list[int], *, delay: float,
                           resume: bool = False, discovery: dict | None = None) -> dict:
    """Fetch only catalog, contributors and requested pages into fresh staging.

    No text-page parser, processed records or production corpus is touched.
    The manifest is checkpointed after each HTTP fetch, including failures.
    """
    raw_dir = raw_dir.resolve()
    raw_dir.relative_to((ROOT / "data/staging").resolve())
    if not text_ids or len(set(text_ids)) != len(text_ids):
        raise ValueError("Download-only selection requires distinct text IDs")
    manifest_path = raw_dir / "fetch-manifest.json"
    if raw_dir.exists() and any(raw_dir.iterdir()) and not (resume and manifest_path.exists()):
        raise ValueError("Download-only raw directory must be new/empty or have a resume manifest")
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_bytes()) if resume and manifest_path.exists() else {
        "status": "raw_download_in_progress", "requested_text_ids": text_ids, "files": [], "failures": []}
    if manifest["requested_text_ids"] != text_ids:
        raise ValueError("Resume selection differs from recorded request")
    completed = {item["requested_url"]: item for item in manifest["files"]}
    if len(completed) != len(manifest["files"]):
        raise ValueError("Duplicate URL receipts in resume manifest")
    manifest["status"] = "raw_download_in_progress"

    def checkpoint() -> None:
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)

    def retrieve(url: str, filename: str, entry: dict | None = None) -> bytes:
        if url in completed:
            saved = completed[url]
            path = (raw_dir / filename).resolve()
            content = path.read_bytes()
            if ((ROOT / saved["raw_path"]).resolve() != path or saved.get("http_status") != 200
                    or len(content) != saved["bytes"] or sha256(content) != saved["sha256"]):
                raise ValueError(f"Resume artifact failed verification: {filename}")
            return content
        receipt: dict = {}
        try:
            # An interrupted fetch may have saved bytes before its receipt; it
            # must be re-fetched, not promoted to a fabricated HTTP receipt.
            content = fetch(url, raw_dir / filename, refresh=True, delay=delay, receipt=receipt)
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
        completed[url] = receipt
        for failure in manifest["failures"]:
            if failure.get("requested_url") == url and not failure.get("resolved_at_utc"):
                failure["resolved_at_utc"] = receipt["fetched_at_utc"]
        checkpoint()
        return content

    checkpoint()
    catalog = retrieve(CATALOG, "browse.html")
    if discovery is not None and sha256(catalog) != discovery["catalog_receipt"]["sha256"]:
        manifest["status"] = "catalog_changed_since_discovery"
        checkpoint()
        raise ValueError("Catalog changed since discovery audit; stop for a new source review")
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
        if len(manifest["files"]) % 25 == 0:
            print(f"Downloaded/verified {len(manifest['files'])}/{len(selected) + 2} raw files", flush=True)
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
    parser.add_argument("--parse-raw-manifest", type=Path, help="parse an independently audited download-only manifest without network access")
    parser.add_argument("--stage-dir", type=Path, help="new/empty directory under data/staging for provisional parsed output")
    parser.add_argument("--discover-only", action="store_true", help="save full catalog URL discovery for independent review")
    parser.add_argument("--download-discovery", type=Path, help="download the complete independently reviewed discovery set")
    parser.add_argument("--resume", action="store_true", help="resume a download-discovery run using verified receipts")
    parser.add_argument("--inspect-only", action="store_true", help="with --parse-raw-manifest, write parser diagnostics but no corpus records")
    args = parser.parse_args()
    if args.discover_only:
        if not args.stage_dir or args.download_only or args.download_discovery or args.parse_raw_manifest or args.raw_dir or args.text_id or args.resume:
            parser.error("--discover-only requires --stage-dir and no other collection mode")
        discovery = discover_catalog(args.stage_dir, delay=args.delay)
        print(f"Discovered {discovery['page_count']} catalog pages; pending independent source audit.")
        return
    if args.download_discovery:
        if not args.raw_dir or args.download_only or args.parse_raw_manifest or args.text_id or args.stage_dir or args.refresh or args.limit:
            parser.error("--download-discovery requires --raw-dir and rejects other collection modes")
        discovery = json.loads(args.download_discovery.read_bytes())
        if discovery.get("duplicate_ids") or discovery.get("page_count") != len(discovery.get("pages", [])):
            raise ValueError("Invalid discovery manifest")
        ids = [page["text_id"] for page in discovery["pages"]]
        if any(page["url"] != f"{CATALOG}?text_id={page['text_id']}" for page in discovery["pages"]):
            raise ValueError("Discovery URL is outside the catalog source contract")
        manifest = download_raw_selection(args.raw_dir, ids, delay=args.delay, resume=args.resume, discovery=discovery)
        print(f"Downloaded/verified {len(manifest['files'])} raw files; pending independent audit.")
        return
    if args.resume:
        parser.error("--resume requires --download-discovery")
    if args.inspect_only and not args.parse_raw_manifest:
        parser.error("--inspect-only requires --parse-raw-manifest")
    if args.download_only:
        if not args.raw_dir or args.refresh or args.limit or args.parse_raw_manifest or args.stage_dir:
            parser.error("--download-only requires --raw-dir and does not accept --refresh or --limit")
        manifest = download_raw_selection(args.raw_dir, args.text_id, delay=args.delay)
        print(f"Downloaded {len(manifest['files'])} raw files; pending independent audit. No final records written.")
        return
    if args.raw_dir or args.text_id:
        parser.error("--raw-dir and --text-id require --download-only")
    raw_directory, output_path, report_path = RAW, OUT, REPORT
    audited_files: dict[str, tuple[Path, bytes]] = {}
    manifest = None
    manifest_raw = b""
    if args.parse_raw_manifest:
        if not args.stage_dir or args.refresh or args.limit:
            parser.error("--parse-raw-manifest requires --stage-dir and rejects --refresh/--limit")
        manifest_path = args.parse_raw_manifest.resolve()
        manifest_path.relative_to((ROOT / "data/staging").resolve())
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        if manifest.get("status") != "raw_download_complete_pending_independent_audit" or any(not f.get("resolved_at_utc") for f in manifest.get("failures", [])):
            raise ValueError("Raw manifest is incomplete or contains failures")
        raw_directory = manifest_path.parent
        for item in manifest["files"]:
            path = (ROOT / item["raw_path"]).resolve()
            path.relative_to(raw_directory)
            content = path.read_bytes()
            if item.get("http_status") != 200 or sha256(content) != item["sha256"] or len(content) != item["bytes"]:
                raise ValueError(f"Raw input failed hash/size/HTTP verification: {path.name}")
            url = item["requested_url"]
            if url in audited_files:
                raise ValueError("Duplicate raw manifest URL")
            audited_files[url] = (path, content)
        expected = {CATALOG, CONTRIBUTORS, *(f"{CATALOG}?text_id={n}" for n in manifest["requested_text_ids"])}
        if set(audited_files) != expected:
            raise ValueError("Raw manifest files do not exactly match requested selection")
        stage_dir = args.stage_dir.resolve()
        stage_dir.relative_to((ROOT / "data/staging").resolve())
        if stage_dir.exists() and any(stage_dir.iterdir()):
            raise ValueError("Parsed staging directory must be new or empty")
        output_path, report_path = stage_dir / "cgl-pilot.jsonl", stage_dir / "parser-report.json"
    elif args.stage_dir:
        parser.error("--stage-dir requires --parse-raw-manifest")

    def acquire(url: str, path: Path) -> bytes:
        if manifest is not None:
            actual_path, content = audited_files[url]
            if actual_path != path.resolve():
                raise ValueError("Raw manifest URL/path mismatch")
            return content
        return fetch(url, path, refresh=args.refresh, delay=args.delay)

    raw_directory.mkdir(parents=True, exist_ok=True)
    catalog_raw = acquire(CATALOG, raw_directory / "browse.html")
    contributors_raw = acquire(CONTRIBUTORS, raw_directory / "contributors.html")
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
    if manifest is not None:
        by_id = {entry["text_id"]: entry for entry in unique}
        unique = [by_id[text_id] for text_id in manifest["requested_text_ids"]]
    records: list[dict] = []
    failures: list[dict] = []
    for number, entry in enumerate(unique, 1):
        url = f"{CATALOG}?text_id={entry['text_id']}"
        path = raw_directory / f"text_{entry['text_id']}.html"
        try:
            html = acquire(url, path)
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
                "metadata": {**metadata, "translator": translation["translator"], "translation_of": base_id,
                             "source_translation_locator": translation.get("source_translation_locator") or {
                                 "layout": "linked_tab", "pane_id": translation["pane_id"]}},
            })
        if number % 25 == 0:
            print(f"{number}/{len(unique)} pages, {len(records)} records", flush=True)
    if not records:
        raise RuntimeError("No records collected; output not written")
    if args.inspect_only:
        diagnostic = {
            "status": "parser_inspection_pending_independent_audit", "failures": failures,
            "input_manifest": args.parse_raw_manifest.resolve().relative_to(ROOT).as_posix(),
            "input_manifest_sha256": sha256(manifest_raw), "requested_pages": len(unique),
            "parser_sha256": sha256(Path(__file__).read_bytes()),
            "counts_by_kind": dict(Counter(record["kind"] for record in records)),
            "records": [{"id": record["id"], "source_url": record["source_url"],
                         "raw_sha256": record["raw_sha256"], "author": record["author"],
                         "citation": record["citation"], "language": record["language"],
                         "kind": record["kind"], "parent_id": record.get("parent_id"),
                         "text_sha256": sha256(record["text"].encode("utf-8")),
                         "text_characters": len(record["text"]), "line_count": len(record["lines"]),
                         "lines_sha256": sha256(json.dumps(record["lines"], ensure_ascii=False, sort_keys=True).encode("utf-8")),
                         "source_numbered_lines": [{"line_index": index, "label": line["label"]}
                                                   for index, line in enumerate(record["lines"]) if line["label"]],
                         "gap_markup_count": sum(len(line.get("source_gap_markup", [])) for line in record["lines"]),
                         "source_translation_locator": record["metadata"].get("source_translation_locator")}
                        for record in records],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Inspected {len(unique)} pages: {len(records)} provisional records, {len(failures)} failures. Diagnostics only; no JSONL written.")
        if failures:
            sys.exit(1)
        return
    if manifest is not None and failures:
        raise RuntimeError(f"Pilot parse failed; no final staging records written: {failures}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(output_path)
    report = {
        "status": "staged_pending_independent_parser_audit" if manifest is not None else "collected_pending_index_acceptance",
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
        "output": output_path.relative_to(ROOT).as_posix(), "output_sha256": sha256(output_path.read_bytes()),
    }
    if manifest is not None:
        report["input_manifest"] = args.parse_raw_manifest.resolve().relative_to(ROOT).as_posix()
        report["input_manifest_sha256"] = sha256(manifest_raw)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records from {report['pages_collected']} pages to {output_path}; {len(failures)} failures", flush=True)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
