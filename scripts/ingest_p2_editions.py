"""Stage Greek OCR from page images of public-domain lyric editions.

Input page/edition metadata is the independently audited Lyra IA index.  This
collector downloads the actual IIIF page images, saves them, and runs the
open-source Tesseract ``grc`` model.  Its output is mixed, uncorrected page
OCR: it is never asserted to be an author's verified Greek text.

The selected ranges follow the printed headings in the scanned volumes:
Edmonds I Alcaeus 308-428; Edmonds II Stesichorus/Ibycus 28-118; Bergk III
Alcaeus 147-197, Stesichorus 205-233, Ibycus 235-252.  Edmonds II leaves
98/100 are excluded because the separate Ibycus collector owns their checked
fragment records.  Change ranges only after comparing the source scans.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "processed" / "lyra.jsonl"
RAW = ROOT / "data" / "raw" / "p2_editions"
OUTPUT = ROOT / "data" / "processed" / "p2_editions.jsonl"
REPORT = ROOT / "data" / "reports" / "p2_editions.json"
US_RIGHTS_URL = "https://www.copyright.gov/circs/circ38b.pdf"

SELECTIONS = {
    "lyragraecabeingr01edmouoft": ((308, 428, "even"),),
    "lyragraecavol20002jmed": ((28, 118, "even"),),
    "poetaelyricigrae03berguoft": (
        (147, 197, "all"),
        (205, 233, "all"),
        (235, 252, "all"),
    ),
}
PUBLICATION_YEARS = {
    "lyragraecabeingr01edmouoft": 1922,
    "lyragraecavol20002jmed": 1924,
    "poetaelyricigrae03berguoft": 1882,
}
EXCLUDED_LEAVES = {("lyragraecavol20002jmed", 98), ("lyragraecavol20002jmed", 100)}
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch(url: str, path: Path) -> bytes:
    """Retain the exact remote image bytes, with explicit retry/failure."""
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    error = None
    for attempt in range(4):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Melos historical Greek OCR research/1.0"},
                timeout=90,
            )
            response.raise_for_status()
            payload = response.content
            if len(payload) < 1_000:
                raise ValueError(f"implausibly short image response: {len(payload)} bytes")
            path.write_bytes(payload)
            return payload
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed for {url}: {error}")


def select_index_rows() -> list[dict]:
    rows = [json.loads(line) for line in INDEX.read_text(encoding="utf-8").splitlines()]
    selected = []
    seen = set()
    for row in rows:
        meta = row["metadata"]
        item = meta["archive_item"]
        if item not in SELECTIONS or not meta.get("printed_page"):
            continue
        try:
            page = int(meta["printed_page"])
        except ValueError:
            continue
        if (item, int(meta["scan_leaf"])) in EXCLUDED_LEAVES:
            continue
        if not any(
            start <= page <= end and (parity == "all" or page % 2 == 0)
            for start, end, parity in SELECTIONS[item]
        ):
            continue
        key = item, int(meta["scan_leaf"])
        if key in seen:
            raise ValueError(f"duplicate indexed scan leaf: {key}")
        seen.add(key)
        selected.append(row)
    if not selected:
        raise ValueError("selected zero indexed pages")
    return selected


def find_tesseract() -> tuple[Path, Path]:
    explicit = os.environ.get("MELOS_TESSERACT")
    default = (
        Path.home()
        / "AppData/Local/melos-ocr-tools/tess-env/Library/bin/tesseract.exe"
    )
    found = explicit or shutil.which("tesseract") or str(default)
    exe = Path(found)
    if not exe.exists():
        raise FileNotFoundError(f"Tesseract executable unavailable: {exe}")
    tessdata = Path(os.environ.get("TESSDATA_PREFIX", "")) if os.environ.get("TESSDATA_PREFIX") else (
        exe.parents[2] / "share/tessdata"
    )
    if not (tessdata / "grc.traineddata").exists():
        raise FileNotFoundError(f"Greek model unavailable: {tessdata / 'grc.traineddata'}")
    return exe, tessdata


def ocr_one(index_row: dict, exe: Path, tessdata: Path) -> dict:
    meta = index_row["metadata"]
    item, leaf = meta["archive_item"], int(meta["scan_leaf"])
    source_image_url = meta["page_image_url"]
    if "/full/max/" not in source_image_url:
        raise ValueError(f"unexpected IIIF image URL for {item} leaf {leaf}")
    # IA's served maximum for these scans is already modest (~1357 px wide).
    image_url = source_image_url
    image_path = RAW / item / f"leaf-{leaf:04d}.jpg"
    text_path = RAW / item / f"leaf-{leaf:04d}.grc.txt"
    image_bytes = fetch(image_url, image_path)
    with Image.open(image_path) as image:
        image.verify()
    env = os.environ.copy()
    env["PATH"] = str(exe.parent) + os.pathsep + env.get("PATH", "")
    env["TESSDATA_PREFIX"] = str(tessdata)
    env["OMP_THREAD_LIMIT"] = "1"
    command = [str(exe), str(image_path), "stdout", "-l", "grc", "--psm", "3"]
    if text_path.exists() and text_path.stat().st_size:
        ocr_bytes = text_path.read_bytes()
    else:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
        if result.returncode:
            raise RuntimeError(
                f"Tesseract failed for {item} leaf {leaf}: {result.stderr.decode('utf-8', errors='replace')}"
            )
        ocr_bytes = result.stdout
        text_path.write_bytes(ocr_bytes)
    text = ocr_bytes.decode("utf-8").strip()
    if not text:
        raise ValueError(f"empty Greek OCR for {item} leaf {leaf}")
    publication_year = PUBLICATION_YEARS[item]
    record = {
        "id": f"p2_editions:{item}:leaf:{leaf}:grc-ocr",
        "source": "p2_editions",
        "source_url": image_url,
        "raw_path": image_path.relative_to(ROOT).as_posix(),
        "raw_sha256": sha256(image_bytes),
        "author": index_row["author"],
        "work": index_row["work"],
        "edition": index_row["edition"],
        "citation": index_row["citation"],
        "language": "mul",
        "text": text,
        "kind": "reference",
        "quality": "machine_ocr",
        "license": "public_domain_us",
        "metadata": {
            "archive_item": item,
            "publication_year_on_scanned_title_page": publication_year,
            "us_rights_basis_url": US_RIGHTS_URL,
            "scan_leaf": leaf,
            "printed_page": meta["printed_page"],
            "page_url": meta["page_url"],
            "iiif_manifest_url": meta["iiif_manifest_url"],
            "full_resolution_image_url": source_image_url,
            "ocr_path": text_path.relative_to(ROOT).as_posix(),
            "ocr_sha256": sha256(ocr_bytes),
            "ocr_engine": "Tesseract 5.5.1 grc, psm 3, IIIF max page",
            "ocr_scope": "full page; ancient Greek, apparatus, Latin, and headings may mix",
            "needs_review": True,
            "greek_unicode_characters": len(GREEK.findall(text)),
            "legacy_ocr_parent_id": index_row["id"],
        },
    }
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="run one Ibycus page before the complete set")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    exe, tessdata = find_tesseract()
    version = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True,
        env={**os.environ, "PATH": str(exe.parent) + os.pathsep + os.environ.get("PATH", "")},
    )
    if version.returncode:
        raise RuntimeError(f"Tesseract version check failed: {version.stderr}")
    index_rows = select_index_rows()
    if args.sample:
        index_rows = [
            row for row in index_rows
            if row["metadata"]["archive_item"] == "lyragraecavol20002jmed"
            and row["metadata"]["printed_page"] == "82"
        ]
        if len(index_rows) != 1:
            raise ValueError(f"expected exactly one sample page, got {len(index_rows)}")
    records = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(ocr_one, row, exe, tessdata): row for row in index_rows}
        for future in concurrent.futures.as_completed(tasks):
            row = tasks[future]
            try:
                record = future.result()
                records.append(record)
                print(
                    f"OCR {record['metadata']['archive_item']} p.{record['metadata']['printed_page']} "
                    f"Greek chars={record['metadata']['greek_unicode_characters']}",
                    file=sys.stderr,
                )
            except Exception as exc:
                failures.append({
                    "archive_item": row["metadata"]["archive_item"],
                    "scan_leaf": row["metadata"]["scan_leaf"],
                    "error": repr(exc),
                })
                print(f"FAILED: {failures[-1]}", file=sys.stderr)
    order = {row["id"]: i for i, row in enumerate(index_rows)}
    records.sort(key=lambda row: order[row["metadata"]["legacy_ocr_parent_id"]])
    output_path = RAW / "sample.jsonl" if args.sample else OUTPUT
    report_path = RAW / "sample-report.json" if args.sample else REPORT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8"
    )
    report = {
        "dataset": "p2_editions",
        "stage": "sample" if args.sample else "full",
        "source": "Internet Archive IIIF images linked by accepted Lyra index",
        "index_path": INDEX.relative_to(ROOT).as_posix(),
        "index_sha256": sha256(INDEX.read_bytes()),
        "ocr_version": version.stdout.splitlines()[0],
        "ocr_model_sha256": sha256((tessdata / "grc.traineddata").read_bytes()),
        "selected_pages": len(index_rows),
        "records": len(records),
        "greek_unicode_pages": sum(row["metadata"]["greek_unicode_characters"] > 0 for row in records),
        "by_archive_item": dict(Counter(row["metadata"]["archive_item"] for row in records)),
        "kind": "reference",
        "quality": "machine_ocr",
        "license": "US public domain basis applies to historical printed editions; jurisdiction-specific reuse may differ",
        "output_path": output_path.relative_to(ROOT).as_posix(),
        "output_sha256": sha256(output_path.read_bytes()),
        "failures": failures,
        "limitations": [
            "Full-page Greek OCR includes unrelated Latin and apparatus and is not a verified fragment transcription.",
            "Only selected Greek-facing pages of Edmonds and target author sections of Bergk are included.",
            "Individual images and raw OCR text are retained with hashes for scan comparison.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(f"{len(failures)} page(s) failed; see {report_path}")


if __name__ == "__main__":
    main()
