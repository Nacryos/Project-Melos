"""Extract Pitotto's licensed Stesichorus edition from the publisher PDF.

The source is Elisabetta Pitotto, *Stesicoro Ὁμηρικώτατος e i frammenti
della Gerioneide* (Edizioni Ca' Foscari, 2024), DOI
10.30687/978-88-6969-801-9, CC BY 4.0. The saved PDF is the sole content
input. Greek reading text, ancient quotation, apparatus and Italian
commentary must remain distinct; the extractor never supplies Greek text.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

import fitz


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_stesichorus"
PDF = RAW / "pitotto_2024_geryoneis.pdf"
OUT = ROOT / "data/processed/p2_stesichorus.jsonl"
REPORT = ROOT / "data/reports/p2_stesichorus.json"
SOURCE_URL = "https://edizionicafoscari.unive.it/media/pdf/books/978-88-6969-801-9/978-88-6969-801-9_LOQnbF3.pdf"
LANDING_URL = "https://edizionicafoscari.unive.it/it/edizioni4/libri/978-88-6969-801-9/"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
EXPECTED_SHA256 = "6a0635d13b69217128b98d13d73521790374cc4b4d5b368261945348b8ccc899"

# PDF page/block coordinates are layout selectors, not transcribed passages.
# They were checked against the publisher's Greek-facing pages 24-44. Each
# tuple is (PDF page, block index); the heading itself supplies all citations.
FRAGMENTS = [
    {"heading": (40, 3), "testimony": [(40, 4)]},
    {"heading": (40, 5), "testimony": [(40, 6)], "text": [(40, 7)], "apparatus": [(40, 8)]},
    {"heading": (42, 3), "text": [(42, 4), (42, 5), (42, 6)], "apparatus": [(42, 7)]},
    {"heading": (42, 8), "testimony": [(42, 9)]},
    {"heading": (44, 3), "text": [(44, 4), (44, 5)], "apparatus": [(44, 6)]},
    {"heading": (44, 7), "text": [(44, 8), (44, 9), (44, 10)], "apparatus": [(44, 11)]},
    {"heading": (46, 3), "text": [(46, 4), (48, 3), (48, 4)], "apparatus": [(46, 5), (48, 5)]},
    {"heading": (48, 6), "text": [(48, 7)], "apparatus": [(48, 8)]},
    {"heading": (50, 3), "text": [(50, 4), (50, 5), (52, 3)], "apparatus": [(50, 6), (52, 4)]},
    {"heading": (54, 3), "testimony": [(54, 4)], "text": [(54, 5)], "apparatus": [(54, 6)]},
    {"heading": (58, 3), "testimony": [(58, 4)], "apparatus": [(58, 5)]},
    {"heading": (58, 6), "testimony": [(58, 7)]},
    {"heading": (58, 8), "testimony": [(58, 9)]},
    {"heading": (60, 3), "testimony": [(60, 4)], "text": [(60, 5)], "apparatus": [(60, 6)]},
    {"heading": (60, 7), "testimony": [(60, 8), (60, 9)], "text": [(60, 8)]},
]
LINE_SLICES = {
    # Athenaeus introduces the quote in the first line, and resumes prose
    # after the two quoted lines. The source page 44 makes this typographic
    # split explicit; both slices still come from PDF page 60 block 8.
    ("22b", "testimony", 60, 8): slice(0, 1),
    ("22b", "text", 60, 8): slice(1, 3),
}
SPACE = re.compile(r"[\t\u00a0\u2002\u2003 ]+")
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


def fetch() -> bytes:
    RAW.mkdir(parents=True, exist_ok=True)
    if PDF.exists():
        data = PDF.read_bytes()
    else:
        request = Request(SOURCE_URL, headers={"User-Agent": "Melos scholarly corpus (source attribution in records)"})
        with urlopen(request, timeout=120) as response:
            data = response.read()
        if not data.startswith(b"%PDF"):
            raise ValueError("Publisher response is not a PDF")
        PDF.write_bytes(data)
    return data


def inspect(doc: fitz.Document) -> None:
    for number, page in enumerate(doc, 1):
        text = page.get_text()
        if "ΓΗΡΥΟΝΗΙΣ" in text or "fr. 19 F." in text or "Fragmenta incertae sedis" in text:
            print(f"PDF page {number}, size {page.rect.width:g}x{page.rect.height:g}")
            print(text[:750].replace("\n", " | "))


def block(doc: fitz.Document, page_number: int, block_index: int) -> dict:
    blocks = doc[page_number - 1].get_text("dict")["blocks"]
    value = blocks[block_index]
    if "lines" not in value:
        raise ValueError(f"Expected text block at PDF page {page_number}, block {block_index}")
    return value


def block_lines(value: dict, *, remove_pdf_notes: bool) -> list[str]:
    """Keep reading order while omitting typographic footnote/line counters.

    MuPDF emits the edition's metrical font as private-use characters. Those
    remain in the staging text and make the passage review-needed.
    """
    output: list[str] = []
    current_y: float | None = None
    current: list[str] = []
    for line in value["lines"]:
        spans = []
        for span in line["spans"]:
            if span["size"] < 7 or (remove_pdf_notes and span["font"].startswith("SourceSansPro")):
                continue
            spans.append(span["text"])
        chunk = "".join(spans).replace("\x08", "").replace("\ufeff", "")
        chunk = SPACE.sub(" ", chunk).strip()
        if not chunk:
            continue
        y = line["bbox"][1]
        if current_y is not None and abs(y - current_y) > 3:
            merged = SPACE.sub(" ", " ".join(current)).strip()
            if merged:
                output.append(merged)
            current = []
        current.append(chunk)
        current_y = y
    if current:
        merged = SPACE.sub(" ", " ".join(current)).strip()
        if merged:
            output.append(merged)
    return output


def heading_text(doc: fitz.Document, location: tuple[int, int]) -> str:
    label = " ".join(block_lines(block(doc, *location), remove_pdf_notes=False))
    if not re.match(r"^fr\.\s*\d", label):
        raise ValueError(f"Invalid fragment heading at {location}: {label!r}")
    return label


def records(doc: fitz.Document, digest: str) -> list[dict]:
    output: list[dict] = []
    for item in FRAGMENTS:
        heading = heading_text(doc, item["heading"])
        fragment = re.match(r"fr\.\s*(\d+[ab]?)\s*F\.", heading)
        if fragment is None:
            raise ValueError(f"No numbered F. fragment in heading: {heading}")
        part_number = fragment.group(1)
        for part, kind, author, language in (
            ("text", "text", "Stesichorus", "grc"),
            ("testimony", "reference", "Ancient testimony quoted by Pitotto", "grc"),
            ("apparatus", "apparatus", "Elisabetta Pitotto", "mul"),
        ):
            locations = item.get(part, [])
            if not locations:
                continue
            lines: list[dict] = []
            for page_number, block_index in locations:
                parsed = block_lines(block(doc, page_number, block_index),
                                     remove_pdf_notes=part != "apparatus")
                indexed_lines = list(enumerate(parsed, 1))
                selected = LINE_SLICES.get((part_number, part, page_number, block_index))
                if selected is not None:
                    indexed_lines = indexed_lines[selected]
                for position, line in indexed_lines:
                    lines.append({"label": f"PDF p. {page_number}, block {block_index}, line {position}",
                                  "text": line})
            text = "\n".join(line["text"] for line in lines)
            if not text or (part != "apparatus" and not GREEK.search(text)):
                raise ValueError(f"Empty or non-Greek {part} for {heading}")
            private_glyphs = sorted(set(ch for ch in text if "\ue000" <= ch <= "\uf8ff"))
            output.append({
                "id": f"p2_stesichorus:pitotto2024:fr{part_number}:{part}",
                "source": "p2_stesichorus",
                "source_url": SOURCE_URL,
                "raw_path": PDF.relative_to(ROOT).as_posix(),
                "raw_sha256": digest,
                "author": author,
                "work": "Geryoneis" if part == "text" else "Geryoneis: " + part,
                "edition": "Elisabetta Pitotto, Stesicoro Ὁμηρικώτατος e i frammenti della Gerioneide (2024)",
                "citation": heading,
                "language": language,
                "text": text,
                "kind": kind,
                "quality": ("source_text" if part == "text" and part_number in {"22a", "22b"}
                            else "needs_review" if part == "text"
                            else "mixed_content" if part == "apparatus" else "source_text"),
                "license": "CC BY 4.0",
                "lines": lines,
                "metadata": {
                    "part": part,
                    "fragment_number_finglass": part_number,
                    "pdf_pages": sorted({page for page, _ in locations}),
                    "printed_pages": sorted({page - 16 for page, _ in locations}),
                    "pdf_block_indices": [index for _, index in locations],
                    "edition_doi": "10.30687/978-88-6969-801-9",
                    "publisher": "Edizioni Ca’ Foscari - Venice University Press",
                    "landing_url": LANDING_URL,
                    "license_url": LICENSE_URL,
                    "source_family": "pitotto-2024-geryoneis",
                    "pdf_private_glyphs": private_glyphs,
                    "extraction_caveat": "PDF layout extraction; metrical private glyphs and editorial signs require scan comparison" if part == "text" else None,
                },
            })
    # The edition's discussion occupies printed pp. 47-118. Page units keep
    # Pitotto's prose and her quotations of other ancient authors together,
    # without assigning those quotations to Stesichorus as authored verse.
    for pdf_page in range(63, 135):
        paragraphs = []
        for block_index, value in enumerate(doc[pdf_page - 1].get_text("dict")["blocks"]):
            if "lines" not in value or not (60 < value["bbox"][1] < 590):
                continue
            if pdf_page == 63 and block_index not in {5, 6}:
                continue
            paragraph = "\n".join(block_lines(value, remove_pdf_notes=False)).strip()
            if paragraph and paragraph.strip("\ufeff \n"):
                paragraphs.append(paragraph)
        content = "\n\n".join(paragraphs)
        if len(content) < 50:
            raise ValueError(f"Unexpectedly short commentary page {pdf_page}: {content!r}")
        printed_page = pdf_page - 16
        output.append({
            "id": f"p2_stesichorus:pitotto2024:commentary:p{printed_page}",
            "source": "p2_stesichorus",
            "source_url": SOURCE_URL,
            "raw_path": PDF.relative_to(ROOT).as_posix(),
            "raw_sha256": digest,
            "author": "Elisabetta Pitotto",
            "work": "Geryoneis: notes of commentary",
            "edition": "Elisabetta Pitotto, Stesicoro Ὁμηρικώτατος e i frammenti della Gerioneide (2024)",
            "citation": f"Note di commento, p. {printed_page}",
            "language": "mul",
            "text": content,
            "kind": "commentary",
            "quality": "mixed_content",
            "license": "CC BY 4.0",
            "metadata": {
                "pdf_pages": [pdf_page],
                "printed_pages": [printed_page],
                "edition_doi": "10.30687/978-88-6969-801-9",
                "publisher": "Edizioni Ca’ Foscari - Venice University Press",
                "landing_url": LANDING_URL,
                "license_url": LICENSE_URL,
                "source_family": "pitotto-2024-geryoneis",
                "may_quote_other_ancient_authors": True,
                "extraction_unit": "printed page",
            },
        })
    return output


def write_outputs(rows: list[dict], digest: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    counts = Counter(row["kind"] for row in rows)
    report = {
        "source": "Pitotto 2024 publisher PDF",
        "source_url": SOURCE_URL,
        "landing_url": LANDING_URL,
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "raw_path": PDF.relative_to(ROOT).as_posix(),
        "raw_sha256": digest,
        "processed_path": OUT.relative_to(ROOT).as_posix(),
        "processed_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "record_count": len(rows),
        "kinds": dict(counts),
        "fragment_numbers_finglass": [item["metadata"]["fragment_number_finglass"] for item in rows if item["kind"] == "text"],
        "distinct_fragment_count": len(FRAGMENTS),
        "review_needed": sum(row["quality"] == "needs_review" for row in rows),
        "failed_extractions": [],
        "source_gate": "p2_edition_audit PASS for CC BY 4.0 staging, 2026-09-30",
        "limitations": [
            "Pitotto's reconstructed reading is one modern edition, not an independent papyrus witness.",
            "Ancient prose testimonia are reference records, not assigned as Stesichorus' own verse.",
            "PDF metrical private glyphs and text extraction of editorial punctuation require visual review before source_text promotion.",
            "Apparatus retains competing readings; none is merged into the poet reading.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true", help="download and locate edition sections")
    args = parser.parse_args()
    data = fetch()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Publisher PDF changed: expected {EXPECTED_SHA256}, got {digest}")
    doc = fitz.open(stream=data, filetype="pdf")
    print(json.dumps({"pdf": str(PDF.relative_to(ROOT)), "sha256": digest,
                      "pages": len(doc), "source_url": SOURCE_URL}, ensure_ascii=False))
    if args.inspect:
        inspect(doc)
        return
    rows = records(doc, digest)
    write_outputs(rows, digest)
    print(json.dumps({"records": len(rows), "kinds": dict(Counter(row["kind"] for row in rows)),
                      "processed_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
