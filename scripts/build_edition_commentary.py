"""Project independently approved Campbell OCR into a public-safe sidecar.

This is a transformation of two already source-audited packages, not a new
transcription. All paragraph text is copied verbatim; private extraction paths
and coordinates remain in the retained source receipts, not this projection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
COMMENTARY = ROOT / "runtime/campbell-commentary/commentary-candidates.jsonl"
COMMENTARY_APPROVAL = ROOT / "runtime/campbell-commentary/audits/package-approval.json"
GREEK = ROOT / "data/campbell_glp/alcaeus_five_corrected.jsonl"
GREEK_APPROVAL = ROOT / "docs/audits/campbell-assignment-approval.json"
OUTPUT = ROOT / "runtime/campbell-commentary/edition-commentary.public.json"
PINS = {
    "commentary": "3e33ec114f43058f62553d4f6764f65c0e7bc655b204376c7ac82b063c07335a",
    "commentary_approval": "be05382bae2d421e3a164b3f257700cd35c32031ea91568c13dd740d33fe81c2",
    "greek": "ab2e1487885431669ebff57c566419bdceb1d6af69740e6ed05e8b7190d84457",
    "greek_approval": "5d549fca6bc0662ce283f909fbf0b7fa3a819675e3f47fcae7629c8d5e9c47b4",
    "source_pdf": "8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f",
}
FRAGMENTS = ("34a", "129", "130b", "326", "350")
MAX_INPUT_BYTES = 2_000_000


def _read(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if len(data) > MAX_INPUT_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Source receipt mismatch: {path.name}")
    return data


def _rows(data: bytes) -> list[dict]:
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != len(FRAGMENTS) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Expected exactly five source-backed Campbell records")
    return rows


def build(commentary: Path = COMMENTARY, commentary_approval: Path = COMMENTARY_APPROVAL,
          greek: Path = GREEK, greek_approval: Path = GREEK_APPROVAL, *, pins: dict | None = None) -> dict:
    pins = PINS if pins is None else pins
    approved_commentary = json.loads(_read(commentary_approval, pins["commentary_approval"]))
    approved_greek = json.loads(_read(greek_approval, pins["greek_approval"]))
    if (approved_commentary.get("verdict") != "PASS"
            or approved_commentary.get("sha256") != pins["commentary"]
            or approved_commentary.get("source_sha256") != pins["source_pdf"]
            or approved_commentary.get("record_count") != 5
            or approved_commentary.get("paragraph_count") != 88
            or approved_commentary.get("pending_source_count") != 0
            or approved_commentary.get("all_retained_paragraphs_traced") is not True
            or (approved_greek.get("package") or {}).get("verdict") != "PASS"
            or (approved_greek.get("package") or {}).get("sha256") != pins["greek"]
            or approved_greek.get("source_sha256") != pins["source_pdf"]):
        raise ValueError("Campbell approval chain is incomplete or changed")
    notes = _rows(_read(commentary, pins["commentary"]))
    poems = _rows(_read(greek, pins["greek"]))
    by_fragment = {row.get("metadata", {}).get("assignment_fragment"): row for row in poems}
    note_fragments = {row.get("assignment_fragment") for row in notes}
    if set(by_fragment) != set(FRAGMENTS) or note_fragments != set(FRAGMENTS):
        raise ValueError("Campbell fragment identities differ from the approved five")
    approval_records = {row.get("assignment_fragment"): row for row in approved_commentary.get("records", [])}
    if set(approval_records) != set(FRAGMENTS):
        raise ValueError("Commentary approval record inventory differs")
    records = []
    paragraph_count = 0
    uncertain_count = 0
    for fragment in FRAGMENTS:
        poem = by_fragment[fragment]
        source = next(row for row in notes if row["assignment_fragment"] == fragment)
        source_approval = approval_records[fragment]
        parent_id = f"campbell-glp:alcaeus:{fragment}"
        metadata = poem.get("metadata") or {}
        if (poem.get("id") != parent_id or poem.get("source") != "campbell_assignment"
                or poem.get("kind") != "text" or poem.get("language") != "grc"
                or poem.get("quality") != "machine_corrected_ocr" or not isinstance(poem.get("text"), str)
                or not poem["text"] or metadata.get("source_pdf_sha256") != pins["source_pdf"]
                or source.get("id") != parent_id + ":commentary"
                or source.get("source_sha256") != pins["source_pdf"]
                or source.get("status") != "independently_audited_source_transcription"
                or source.get("pending_sources") != []
                or source.get("license") != "user_supplied_edition_excerpt"
                or source.get("edition_fragment") != metadata.get("edition_fragment")
                or source_approval.get("id") != source["id"]
                or source_approval.get("edition_fragment") != source["edition_fragment"]
                or source_approval.get("status") != source["status"]
                or source_approval.get("paragraph_count") != len(source.get("paragraphs", []))):
            raise ValueError(f"Campbell source linkage failed for {fragment}")
        paragraphs = []
        for ordinal, paragraph in enumerate(source["paragraphs"], 1):
            locator = paragraph.get("source") or {}
            page = locator.get("printed_page")
            pdf_page = locator.get("pdf_page")
            if (not isinstance(paragraph.get("text"), str) or not paragraph["text"]
                    or type(page) is not int or page not in source_approval.get("printed_pages", [])
                    or type(pdf_page) is not int or pdf_page not in source_approval.get("pdf_pages", [])
                    or locator.get("source_sha256") != pins["source_pdf"]
                    or locator.get("fragment") != fragment
                    or (page, pdf_page) not in {(p - 32, p) for p in source_approval["pdf_pages"]}
                    or type(locator.get("paragraph_index")) is not int):
                raise ValueError(f"Unbound Campbell paragraph in {fragment}")
            uncertain = "\ufffd" in paragraph["text"]
            uncertain_count += int(uncertain)
            paragraphs.append({
                "ordinal": ordinal,
                "kind": paragraph.get("kind", ""),
                "line_label": paragraph.get("line_label", ""),
                "lemma": paragraph.get("lemma", ""),
                "text": paragraph["text"],
                "anchor_line_label": paragraph.get("anchor_line_label", ""),
                "anchor_method": paragraph.get("anchor_method", ""),
                "printed_page": page,
                "pdf_page": pdf_page,
                "citation": f"Campbell, Greek Lyric Poetry (1967), Alcaeus {source['edition_fragment']}, p. {page}",
                "scope": "whole_poem_commentary",
                "model_eligible": not uncertain,
                "uncertain_ocr": uncertain,
            })
        paragraph_count += len(paragraphs)
        records.append({
            "parent_id": parent_id,
            "commentary_id": source["id"],
            "parent_text_sha256": hashlib.sha256(poem["text"].encode("utf-8")).hexdigest(),
            "parent_raw_sha256": poem["raw_sha256"],
            "parent_source_url": poem["source_url"],
            "parent_quality": poem["quality"],
            "parent_author": poem["author"],
            "parent_work": poem["work"],
            "parent_edition": poem["edition"],
            "assignment_fragment": fragment,
            "edition_fragment": source["edition_fragment"],
            "source_title": "David A. Campbell, Greek Lyric Poetry (1967)",
            "source_pdf_sha256": pins["source_pdf"],
            "license": source["license"],
            "rights_note": "User-supplied edition excerpt; the source states all rights reserved. No open license is asserted.",
            "scope": "whole_poem_commentary",
            "paragraphs": paragraphs,
        })
    if paragraph_count != approved_commentary["paragraph_count"] or uncertain_count != 1:
        raise ValueError("Campbell paragraph inventory or documented OCR uncertainty changed")
    return {
        "schema_version": 1,
        "source_package_sha256": pins["commentary"],
        "source_approval_sha256": pins["commentary_approval"],
        "greek_package_sha256": pins["greek"],
        "greek_approval_sha256": pins["greek_approval"],
        "source_pdf_sha256": pins["source_pdf"],
        "record_count": len(records),
        "paragraph_count": paragraph_count,
        "uncertain_ocr_paragraph_count": uncertain_count,
        "selection_alignment": "none; word and line links require separate audited source mapping",
        "records": records,
    }


def write(output: Path = OUTPUT, **inputs) -> str:
    payload = build(**inputs)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != data:
            raise FileExistsError("Existing staged projection differs; use a fresh output path")
        return digest
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        if output.exists():
            raise FileExistsError("Staged output appeared during build")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(write(args.output))


if __name__ == "__main__":
    main()
