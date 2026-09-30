"""Stage source-bound Ibycus bibliography and fragment locators.

These are references, not Greek poem transcriptions. The modern source pages
are copyrighted, and the Greek text on Graecia Antiqua follows Page (1967).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_ibycus"
OUT = ROOT / "data/processed/p2_ibycus.jsonl"
REPORT = ROOT / "data/reports/p2_ibycus.json"
CATALOG = "https://catalog.perseus.org/catalog/urn:cts:greekLit:tlg0293.tlg001.opp-grc2"
INDEX = "https://www.greek-language.gr/digitalResources/ancient_greek/anthology/poetry/browse.html?text_id=348"
PORTAL = "https://greciantiga.org/arquivo.asp?num=0555"
ARTICLE = "https://journals.uoregon.edu/konturen/article/view/2971"
SOURCES = (("perseus-catalog", CATALOG), ("cgl-index", INDEX), ("greciantiga-0555", PORTAL), ("konturen-2971", ARTICLE))
OCR_ROOT = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'melos-ocr-tools/tess-env'
TESSERACT = Path(os.environ.get('MELOS_TESSERACT', OCR_ROOT / 'Library/bin/tesseract.exe'))
TESSDATA = Path(os.environ.get('MELOS_TESSDATA', OCR_ROOT / 'share/tessdata'))

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-ibycus-reference/1.0 (source-bound scholarly metadata)"


def fetch(name: str, url: str, suffix: str = ".html") -> tuple[bytes, Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    target = RAW / f"{name}{suffix}"
    if target.exists() and target.stat().st_size:
        return target.read_bytes(), target
    error = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=45)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty response")
            target.write_bytes(response.content)
            time.sleep(0.3)
            return response.content, target
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Download failed for {url}: {error}")


def base(name: str, url: str, raw: bytes, path: Path) -> dict:
    return {
        "source": "p2_ibycus",
        "source_url": url,
        "raw_path": path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "author": "Ibycus",
        "language": "mul",
        "kind": "reference",
        "quality": "source_text",
        "metadata": {"source_page_type": name, "greek_text_extracted": False},
    }


def catalog_record(raw: bytes, path: Path) -> dict:
    page = BeautifulSoup(raw, "html.parser")
    fields = {}
    for dt in page.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(" ", strip=True).rstrip(":")] = dd.get_text(" ", strip=True)
    required = {"URN", "Work", "Editor", "Host title", "Date publ", "Pages", "Table of cont"}
    if not required.issubset(fields) or fields["URN"] != "urn:cts:greekLit:tlg0293.tlg001.opp-grc2":
        raise ValueError(f"Perseus catalog structure/identity changed: {required - fields.keys()}")
    if fields["Pages"] != "78-119":
        raise ValueError(f"Unexpected catalog page range: {fields['Pages']}")
    return {
        **base("perseus-catalog", CATALOG, raw, path),
        "id": "p2_ibycus:perseus-catalog:opp-grc2",
        "work": fields["Work"],
        "edition": f"{fields['Host title']} ({fields['Date publ']}); {fields['Editor']}",
        "citation": fields["Pages"],
        "text": fields["Table of cont"],
        "license": "CC BY-SA 3.0 US (Perseus catalog metadata)",
        "metadata": {
            **base("perseus-catalog", CATALOG, raw, path)["metadata"],
            "catalog_fields": fields,
            "catalog_license_url": "https://github.com/PerseusDL/catalog_data#readme",
            "edition_text_rights": "not granted by catalog metadata",
        },
    }


def index_records(raw: bytes, path: Path) -> list[dict]:
    page = BeautifulSoup(raw, "html.parser")
    heading = page.find(string=lambda s: s and "Κατάλογος κειμένων: ΙΒΥΚΟΣ" in s)
    if not heading:
        raise ValueError("CGL Ibycus heading missing")
    title = next((tag for tag in page.find_all("h1") if "Λυρικής Ποίησης" in tag.get_text(" ", strip=True)), None)
    if title is None or "Λυρικής Ποίησης" not in title.get_text(" ", strip=True):
        raise ValueError("CGL anthology title missing")
    title_text = title.get_text(" ", strip=True)
    records = []
    for anchor in page.select('a[href*="browse.html?text_id="]'):
        label = anchor.get_text(" ", strip=True)
        if not re.search(r"\b(?:282a|285|286|287|288|303a\+b|310|313|314|315|317a\+b)\s+Page\b", label):
            continue
        link = urljoin(INDEX, anchor["href"])
        text_id = parse_qs(urlparse(link).query).get("text_id", [None])[0]
        if not text_id:
            raise ValueError(f"Missing text_id for {label}")
        records.append({
            **base("cgl-index", INDEX, raw, path),
            "id": f"p2_ibycus:cgl-index:{text_id}",
            "work": title_text,
            "edition": title_text,
            "citation": label,
            "text": label,
            "license": "all rights reserved (index labels only)",
            "metadata": {
                **base("cgl-index", INDEX, raw, path)["metadata"],
                "detail_url": link,
                "underlying_edition_rights": "not granted by anthology index",
            },
        })
    if len(records) != 11 or len({record["id"] for record in records}) != 11:
        raise ValueError(f"Expected 11 distinct CGL Ibycus links, found {len(records)}")
    return records


def portal_record(raw: bytes, path: Path) -> dict:
    # The publisher declares iso-8859-1. Preserve its original response bytes
    # above and materialize a strict, reversible Unicode decoding for generic
    # UTF-8 provenance checks; never replace the publisher's source artifact.
    declared = b'<meta charset="iso-8859-1"'
    if declared not in raw[:1000]:
        raise ValueError("Graecia Antiqua source charset declaration changed")
    decoded = raw.decode("iso-8859-1").encode("utf-8")
    decoded_path = path.with_name(path.stem + ".utf8.html")
    decoded_path.write_bytes(decoded)
    page = BeautifulSoup(raw, "html.parser")
    texticulo = page.find("texticulo", attrs={"name": "0555"})
    if texticulo is None:
        raise ValueError("Graecia Antiqua item 0555 missing")
    source_note = texticulo.find("p").get_text(" ", strip=True)
    title = page.find("h1")
    if title is None:
        raise ValueError("Graecia Antiqua item title missing")
    if "Page (1967)" not in source_note or "F 287 Campbell = F 6 Page" not in source_note:
        raise ValueError("Edition/crosswalk note changed")
    return {
        **base("greciantiga-0555", PORTAL, decoded, decoded_path),
        "id": "p2_ibycus:greciantiga:0555",
        "work": title.get_text(" ", strip=True),
        "edition": source_note,
        "citation": "F 287 Campbell = F 6 Page",
        "text": source_note,
        "license": "CC BY-NC-ND 4.0 (portal); underlying Page edition rights unresolved",
        "metadata": {
            **base("greciantiga-0555", PORTAL, decoded, decoded_path)["metadata"],
            "original_raw_path": path.relative_to(ROOT).as_posix(),
            "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "source_charset": "iso-8859-1 (publisher meta tag)",
            "decoding": "strict iso-8859-1 to UTF-8; no content edits",
            "rights_url": "https://greciantiga.org/arquivo.asp?num=0320",
            "scope": "bibliographic reference and source's numbering crosswalk only",
        },
    }


def article_record(raw: bytes, path: Path) -> dict:
    page = BeautifulSoup(raw, "html.parser")
    meta = {tag.get("name"): tag.get("content", "") for tag in page.select('meta[name^="citation_"]')}
    required = {"citation_title", "citation_author", "citation_journal_title", "citation_date", "citation_volume", "citation_firstpage", "citation_lastpage", "citation_doi", "citation_abstract"}
    if not required.issubset(meta):
        raise ValueError(f"Konturen citation metadata incomplete: {required - meta.keys()}")
    if "Ibykos Fragment 286" not in meta["citation_abstract"]:
        raise ValueError("Konturen Ibycus fragment link not found in abstract")
    return {
        **base("konturen-2971", ARTICLE, raw, path),
        "id": "p2_ibycus:konturen:2971",
        "work": meta["citation_title"],
        "edition": f"{meta['citation_journal_title']} {meta['citation_volume']} ({meta['citation_date'][:4]})",
        "citation": f"{meta['citation_firstpage']}-{meta['citation_lastpage']}",
        "language": "eng",
        "text": meta["citation_title"],
        "license": "open access; author retains copyright; reuse terms unspecified",
        "metadata": {
            **base("konturen-2971", ARTICLE, raw, path)["metadata"],
            "article_author": meta["citation_author"],
            "doi": meta["citation_doi"],
            "subject_locus": "Ibykos Fragment 286",
            "journal_policy_url": "https://journals.uoregon.edu/konturen/about",
            "scope": "bibliographic reference only; article Greek and commentary excluded",
        },
    }


def prepare_ocr_preview() -> None:
    """Download Edmonds's relevant page images and save unedited Greek OCR.

    The selected printed pages are configurable locators, not fragment-number
    claims: they are verified against the saved Lyra page-level scan index.
    """
    if not TESSERACT.exists() or not (TESSDATA / "grc.traineddata").exists():
        raise RuntimeError("Greek Tesseract runtime unavailable")
    source_index = ROOT / "data/processed/lyra.jsonl"
    pages = {}
    for line in source_index.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        meta = record.get("metadata", {})
        if meta.get("archive_item") == "lyragraecavol20002jmed" and meta.get("printed_page") in ("84", "86"):
            pages[meta["printed_page"]] = record
    if set(pages) != {"84", "86"}:
        raise ValueError(f"Expected Edmonds II printed pp. 84/86, found {sorted(pages)}")
    for printed_page, record in sorted(pages.items()):
        image_url = record["metadata"]["page_image_url"]
        image, jpg_path = fetch(f"edmonds-page-{printed_page}", image_url, ".jpg")
        import os
        env = os.environ.copy()
        env["TESSDATA_PREFIX"] = str(TESSDATA)
        result = subprocess.run(
            [str(TESSERACT), str(jpg_path), "stdout", "-l", "grc", "--psm", "3"],
            check=True, capture_output=True, env=env,
        )
        ocr_path = jpg_path.with_suffix(".grc-psm3.txt")
        ocr_path.write_bytes(result.stdout)
        print(f"p.{printed_page}: leaf {record['metadata']['scan_leaf']} image {hashlib.sha256(image).hexdigest()} OCR {hashlib.sha256(result.stdout).hexdigest()} -> {ocr_path}")


def prepare_crop_preview() -> None:
    from PIL import Image, ImageEnhance
    import os

    # Bounding boxes locate the two poem blocks visually in the saved images.
    # These are extraction parameters, not transcribed text.
    boxes = {"84": (225, 1160, 1280, 1870), "86": (235, 500, 1280, 910)}
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(TESSDATA)
    for page_number, box in boxes.items():
        original = RAW / f"edmonds-page-{page_number}.jpg"
        if not original.exists():
            raise FileNotFoundError(original)
        with Image.open(original) as source:
            crop = source.crop(box)
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
            crop = ImageEnhance.Contrast(crop.convert("L")).enhance(1.5)
            crop_path = RAW / f"edmonds-page-{page_number}-poem-crop.png"
            crop.save(crop_path)
        result = subprocess.run(
            [str(TESSERACT), str(crop_path), "stdout", "-l", "grc", "--psm", "6"],
            check=True, capture_output=True, env=env,
        )
        ocr_path = crop_path.with_suffix(".grc-psm6.txt")
        ocr_path.write_bytes(result.stdout)
        print(f"p.{page_number} crop {box}: {hashlib.sha256(crop_path.read_bytes()).hexdigest()} OCR {hashlib.sha256(result.stdout).hexdigest()}")


def prepare_line_preview() -> None:
    from PIL import Image
    import os

    # Row locations in the saved, doubled image; used only to split printed
    # lines before OCR. No Greek glyphs are supplied by this configuration.
    rows_by_page = {
        "84": tuple((number, 45 + (number - 1) * 105, 166 + (number - 1) * 105) for number in range(1, 14)),
        "86": ((1, 48, 169), (2, 160, 280), (3, 270, 389),
               (4, 379, 495), (5, 475, 596), (6, 575, 699), (7, 690, 810)),
    }
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(TESSDATA)
    for page_number, rows in rows_by_page.items():
        crop_path = RAW / f"edmonds-page-{page_number}-poem-crop.png"
        if not crop_path.exists():
            raise FileNotFoundError(crop_path)
        with Image.open(crop_path) as source:
            for number, top, bottom in rows:
                line_image = source.crop((0, top, source.width, bottom))
                line_path = RAW / f"edmonds-page-{page_number}-line-{number}.png"
                line_image.save(line_path)
                result = subprocess.run(
                    [str(TESSERACT), str(line_path), "stdout", "-l", "grc", "--psm", "7"],
                    check=True, capture_output=True, env=env,
                )
                ocr_path = line_path.with_suffix(".grc-psm7.txt")
                ocr_path.write_bytes(result.stdout)
                print(page_number, number, result.stdout.decode("utf-8").strip(), hashlib.sha256(result.stdout).hexdigest())
                if page_number == "86" and number == 6:
                    alternative = subprocess.run(
                        [str(TESSERACT), str(line_path), "stdout", "-l", "grc", "--psm", "13"],
                        check=True, capture_output=True, env=env,
                    )
                    line_path.with_suffix(".grc-psm13.txt").write_bytes(alternative.stdout)


def reviewed_greek_records() -> list[dict]:
    """Select only OCR lines visually checked against Edmonds II scans.

    All words come from the generated Tesseract files, never from this code.
    The selected line numbers were checked at the original image scale.
    """
    reviewed = {"84": (2,), "86": (2, 3, 6, 7)}
    edition_fragments = {"84": "1", "86": "2"}
    lyra_index = {}
    for line in (ROOT / "data/processed/lyra.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        meta = item.get("metadata", {})
        if meta.get("archive_item") == "lyragraecavol20002jmed" and meta.get("printed_page") in reviewed:
            lyra_index[meta["printed_page"]] = item
    if set(lyra_index) != set(reviewed):
        raise ValueError("Missing Lyra scan-page provenance")
    rows = []
    for printed_page, line_numbers in reviewed.items():
        scan = lyra_index[printed_page]
        image_url = scan["metadata"]["page_image_url"]
        image_path = RAW / f"edmonds-page-{printed_page}.jpg"
        image_digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        for line_number in line_numbers:
            line_path = RAW / f"edmonds-page-{printed_page}-line-{line_number}.png"
            page_segmentation_mode = 13 if printed_page == "86" and line_number == 6 else 7
            ocr_path = line_path.with_suffix(f".grc-psm{page_segmentation_mode}.txt")
            line_image_digest = hashlib.sha256(line_path.read_bytes()).hexdigest()
            ocr_bytes = ocr_path.read_bytes()
            content = ocr_bytes.decode("utf-8").strip()
            if not content or "\n" in content:
                raise ValueError(f"Unusable selected OCR line: {ocr_path}")
            rows.append({
                "id": f"p2_ibycus:edmonds-1924:p{printed_page}:fr{edition_fragments[printed_page]}:l{line_number}",
                "source": "p2_ibycus",
                "source_url": image_url,
                "raw_path": image_path.relative_to(ROOT).as_posix(),
                "raw_sha256": image_digest,
                "author": "Ibycus",
                "work": "Fragmenta",
                "edition": "J. M. Edmonds, Lyra Graeca, vol. II (1924)",
                "citation": f"Edmonds fr. {edition_fragments[printed_page]}, line {line_number}, p. {printed_page}",
                "language": "grc",
                "text": content,
                "kind": "text",
                "quality": "source_text",
                "license": "United States public domain, 1924 print edition; other jurisdictions unassessed",
                "lines": [{"label": str(line_number), "text": content}],
                "metadata": {
                    "partial_fragment_line": True,
                    "review_status": "collector_visual_match; independent audit pending",
                    "printed_page": printed_page,
                    "scan_leaf": scan["metadata"]["scan_leaf"],
                    "page_url": scan["metadata"]["page_url"],
                    "ocr_method": f"Tesseract 5.5.1 grc --psm {page_segmentation_mode} on 2x Lanczos grayscale contrast-1.5 crop",
                    "ocr_path": ocr_path.relative_to(ROOT).as_posix(),
                    "ocr_sha256": hashlib.sha256(ocr_bytes).hexdigest(),
                    "line_image_path": line_path.relative_to(ROOT).as_posix(),
                    "line_image_sha256": line_image_digest,
                    "source_family": "Edmonds Lyra Graeca II 1924",
                },
            })
    return rows


def main() -> None:
    prepare_ocr_preview()
    prepare_crop_preview()
    prepare_line_preview()
    downloaded = {name: fetch(name, url) for name, url in SOURCES}
    cat_raw, cat_path = downloaded["perseus-catalog"]
    idx_raw, idx_path = downloaded["cgl-index"]
    port_raw, port_path = downloaded["greciantiga-0555"]
    article_raw, article_path = downloaded["konturen-2971"]
    rows = [catalog_record(cat_raw, cat_path), *index_records(idx_raw, idx_path), portal_record(port_raw, port_path), article_record(article_raw, article_path), *reviewed_greek_records()]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate row IDs")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    OUT.write_bytes(payload.encode("utf-8"))
    REPORT.write_text(json.dumps({
        "dataset": "p2_ibycus",
        "purpose": "edition bibliography and fragment-locator references",
        "records": len(rows),
        "clean_greek_text_records": sum(row["kind"] == "text" and row["language"] == "grc" and row["quality"] == "source_text" for row in rows),
        "source_urls": {name: url for name, url in SOURCES},
        "raw_sha256": {name: hashlib.sha256(raw).hexdigest() for name, (raw, _) in downloaded.items()},
        "output_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "limitations": [
            "Greek coverage is five individually checked lines from Edmonds fragments 1 and 2, not complete poems.",
            "CGL anthology is all rights reserved; Graecia Antiqua Greek derives from Page (1967).",
            "Perseus catalog licenses metadata, not Edmonds's printed edition text.",
            "Konturen is open access, but the author retains copyright; this stages a citation only.",
        ],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {len(rows)} Ibycus records: {len(reviewed_greek_records())} reviewed Greek lines and 14 references")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--ocr-preview":
        prepare_ocr_preview()
    elif len(sys.argv) == 2 and sys.argv[1] == "--crop-preview":
        prepare_crop_preview()
    elif len(sys.argv) == 2 and sys.argv[1] == "--line-preview":
        prepare_line_preview()
    else:
        main()
