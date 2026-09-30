"""Download and index page-level OCR of Lyra Graeca and Bergk vol. III.

This is a reference index of uncorrected scan OCR, not an edition of poems.
All bibliographic strings in records are either from downloaded IA metadata or
from the scanned volume's own series/volume title.  No Greek is supplied here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import io
import zipfile
from collections import Counter
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "lyra"
OUTPUT = ROOT / "data" / "processed" / "lyra.jsonl"
REPORT = ROOT / "data" / "reports" / "lyra.json"

# Internet Archive item identifiers select the three source scans.  The
# bibliographic identity is checked against the scanned title pages separately.
ITEMS = (
    ("I", "lyragraecabeingr01edmouoft", "J. M. Edmonds (editor and translator)", "Lyra Graeca, vol. I"),
    ("II", "lyragraecavol20002jmed", "J. M. Edmonds (editor and translator)", "Lyra Graeca, vol. II"),
    ("III", "lyragraecabeingr03edmouoft", "J. M. Edmonds (editor and translator)", "Lyra Graeca, vol. III"),
    ("Bergk III", "poetaelyricigrae03berguoft", "Bergk, Theodor, 1812-1881", "Poetae lyrici Graeci, vol. III"),
)

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-lyra-reference-index/1.0 (research OCR download)"


def fetch(url: str, target: Path) -> bytes:
    """Fetch an external artifact, save its original bytes, and fail loudly."""
    if target.exists() and target.stat().st_size:
        return target.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    error = None
    for attempt in range(5):
        try:
            response = SESSION.get(url, timeout=90)
            response.raise_for_status()
            content = response.content
            if not content:
                raise ValueError(f"empty response from {url}")
            target.write_bytes(content)
            time.sleep(0.3)
            return content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 4:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}: {error}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_url(item: str, name: str) -> str:
    return f"https://archive.org/download/{item}/{name}"


def selected_file(files: list[dict], suffix: str) -> str:
    matches = [entry["name"] for entry in files if entry["name"].endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected one {suffix} in IA file list, found {matches}")
    return matches[0]


def page_text(obj: ET.Element) -> str:
    paragraphs = []
    for paragraph in obj.findall(".//HIDDENTEXT//PARAGRAPH"):
        lines = []
        for line in paragraph.findall(".//LINE"):
            words = [(word.text or "").strip() for word in line.findall("WORD")]
            words = [word for word in words if word]
            if words:
                lines.append(" ".join(words))
        if lines:
            paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def page_lookup(scan_root: ET.Element) -> dict[int, dict]:
    pages = {}
    for page in scan_root.findall("./pageData/page"):
        leaf = int(page.attrib["leafNum"])
        pages[leaf] = {
            "page_number": page.findtext("pageNumber"),
            "page_type": page.findtext("pageType"),
            "include_in_access_formats": page.findtext("addToAccessFormats"),
        }
    return pages


def index_item(volume: str, item: str, editor: str, edition: str) -> tuple[list[dict], dict]:
    item_dir = RAW / item
    meta_url = f"https://archive.org/metadata/{item}"
    meta_bytes = fetch(meta_url, item_dir / "metadata.json")
    metadata = json.loads(meta_bytes)["metadata"]
    if metadata.get("identifier") != item:
        raise ValueError(f"IA metadata identifier mismatch for {item}")
    files = json.loads(meta_bytes)["files"]
    ocr_name = selected_file(files, "_djvu.xml")
    scan_names = [entry["name"] for entry in files if entry["name"].endswith("_scandata.xml")]
    scan_name = scan_names[0] if len(scan_names) == 1 else selected_file(files, "scandata.zip")
    ocr_bytes = fetch(file_url(item, ocr_name), item_dir / ocr_name)
    scan_bytes = fetch(file_url(item, scan_name), item_dir / scan_name)
    scan_xml_bytes = scan_bytes
    if scan_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(scan_bytes)) as archive:
            scan_xml_bytes = archive.read("scandata.xml")
        (item_dir / "scandata.xml").write_bytes(scan_xml_bytes)
    ocr_root = ET.fromstring(ocr_bytes)
    scan_root = ET.fromstring(scan_xml_bytes)
    for element in scan_root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    manifest_url = f"https://iiif.archive.org/iiif/3/{item}/manifest.json"
    manifest_bytes = fetch(manifest_url, item_dir / "iiif-manifest.json")
    canvases = json.loads(manifest_bytes)["items"]
    scan_pages = page_lookup(scan_root)
    objects = ocr_root.findall(".//BODY/OBJECT")
    access_leaves = [
        leaf for leaf, page in sorted(scan_pages.items())
        if page["include_in_access_formats"] == "true"
    ]
    if not objects or len(objects) != len(access_leaves) or len(objects) != len(canvases):
        raise ValueError(
            f"OCR/access/IIIF count mismatch for {item}: "
            f"{len(objects)} vs {len(access_leaves)} vs {len(canvases)}"
        )
    pdf_files = [f["name"] for f in files if f["name"].lower().endswith(".pdf")]
    pdf_url = file_url(item, pdf_files[0]) if pdf_files else None
    rows = []
    empty = 0
    page_numbered = 0
    ocr_sha = digest(ocr_bytes)
    scan_sha = digest(scan_bytes)
    manifest_sha = digest(manifest_bytes)
    for access_page, (leaf, obj) in enumerate(zip(access_leaves, objects)):
        if leaf not in scan_pages:
            raise ValueError(f"OCR leaf {leaf} has no scan metadata in {item}")
        content = page_text(obj)
        if not content:
            empty += 1
            continue
        scan = scan_pages[leaf]
        number = scan["page_number"]
        if number:
            page_numbered += 1
        citation = f"{edition}, " + (f"p. {number}, " if number else "") + f"scan leaf {leaf}"
        canvas = canvases[access_page]
        image_url = canvas["items"][0]["items"][0]["body"]["id"]
        rows.append(
            {
                "id": f"lyra:{item}:leaf:{leaf}",
                "source": "lyra",
                "source_url": file_url(item, ocr_name),
                "raw_path": (item_dir / ocr_name).relative_to(ROOT).as_posix(),
                "raw_sha256": ocr_sha,
                "author": editor,
                "work": metadata.get("title", ""),
                "edition": f"{edition}; Internet Archive scan {item}",
                "citation": citation,
                "language": "mul",
                "text": content,
                "kind": "reference",
                "quality": "machine_ocr",
                "license": "unknown",
                "metadata": {
                    "volume": volume,
                    "archive_item": item,
                    "scan_leaf": leaf,
                    "printed_page": number,
                    "scan_page_type": scan["page_type"],
                    "archive_access_page": access_page,
                    "page_url": f"https://archive.org/details/{item}/page/n{access_page}/mode/1up",
                    "page_image_url": image_url,
                    "iiif_canvas_url": canvas["id"],
                    "iiif_manifest_url": manifest_url,
                    "iiif_manifest_sha256": manifest_sha,
                    "scan_metadata_url": file_url(item, scan_name),
                    "scan_metadata_sha256": scan_sha,
                    "scan_metadata_member": "scandata.xml" if scan_name.endswith(".zip") else None,
                    "scan_metadata_xml_sha256": digest(scan_xml_bytes),
                    "pdf_url": pdf_url,
                    "ocr_scope": "uncorrected full page, possibly Greek/English/Latin and apparatus",
                },
            }
        )
    report = {
        "archive_item": item,
        "volume": volume,
        "metadata_url": meta_url,
        "metadata_sha256": digest(meta_bytes),
        "ocr_url": file_url(item, ocr_name),
        "ocr_sha256": ocr_sha,
        "scan_metadata_url": file_url(item, scan_name),
        "scan_metadata_sha256": scan_sha,
        "scan_metadata_member": "scandata.xml" if scan_name.endswith(".zip") else None,
        "scan_metadata_xml_sha256": digest(scan_xml_bytes),
        "iiif_manifest_url": manifest_url,
        "iiif_manifest_sha256": manifest_sha,
        "pdf_url": pdf_url,
        "scan_leaves": len(scan_pages),
        "indexed_pages": len(rows),
        "pages_without_ocr": empty,
        "indexed_pages_with_source_page_number": page_numbered,
        "metadata_title": metadata.get("title"),
        "metadata_date": metadata.get("date"),
        "greek_unicode_pages": sum(
            bool(re.search(r"[\u0370-\u03ff\u1f00-\u1fff]", row["text"])) for row in rows
        ),
        "title_page_roman_year_ocr": [
            {"scan_leaf": row["metadata"]["scan_leaf"], "ocr_token": token}
            for row in rows if row["metadata"]["scan_leaf"] < 15
            for token in re.findall(r"\bMCM[XLCDVI]+\b", row["text"])
        ],
    }
    return rows, report


def main() -> None:
    all_rows = []
    reports = []
    for volume, item, editor, edition in ITEMS:
        rows, report = index_item(volume, item, editor, edition)
        all_rows.extend(rows)
        reports.append(report)
        print(f"{volume}: {len(rows)} indexed OCR pages from {item}", file=sys.stderr)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in all_rows),
        encoding="utf-8",
    )
    report = {
        "dataset": "lyra",
        "purpose": "searchable scan OCR reference, not curated poems",
        "source": "Internet Archive downloadable DjVuXML and scandata XML",
        "records": len(all_rows),
        "by_volume": dict(Counter(row["metadata"]["volume"] for row in all_rows)),
        "kind": "reference",
        "quality": "machine_ocr",
        "license": "unknown (edition-level rights require jurisdictional review)",
        "limitations": [
            "OCR text is uncorrected, mixes languages and apparatus, and is not a Greek transcription.",
            "Archive metadata dates are reported verbatim; volume identity should be checked against title-page scans.",
            "PDFs and IIIF page images are linked but not copied into this corpus.",
        ],
        "items": reports,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
