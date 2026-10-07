"""Exact-record Campbell commentary sidecar, not corpus or lexical evidence.

The approved JSON projection is staged separately from the corpus. A release
may copy its exact bytes beside this module; no database or embedding rebuild
is needed. This loader never infers a same-numbered edition relationship.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path


DATA_PATH = Path(__file__).with_name("edition_commentary_data.json")
DATA_SHA256 = "9b551021b8dfceb0fcd9efc28e7aac66783dfef65cd495ae43f22cf5678db099"
SOURCE_PDF_SHA256 = "8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f"
SOURCE_PACKAGE_SHA256 = "3e33ec114f43058f62553d4f6764f65c0e7bc655b204376c7ac82b063c07335a"
GREEK_PACKAGE_SHA256 = "afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b"
MAX_BYTES = 100_000
FRAGMENTS = frozenset(("34a", "129", "130b", "326", "350"))


def _read(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError("Approved commentary projection hash mismatch")
    payload = json.loads(raw)
    if (payload.get("schema_version") != 1 or payload.get("record_count") != 5
            or payload.get("paragraph_count") != 88
            or payload.get("uncertain_ocr_paragraph_count") != 1
            or payload.get("source_pdf_sha256") != SOURCE_PDF_SHA256
            or payload.get("source_package_sha256") != SOURCE_PACKAGE_SHA256
            or payload.get("greek_package_sha256") != GREEK_PACKAGE_SHA256
            or not isinstance(payload.get("records"), list)
            or len(payload["records"]) != 5):
        raise ValueError("Approved commentary projection schema mismatch")
    return payload


def _bound(record: dict, passage: dict) -> bool:
    metadata = passage.get("metadata") or {}
    return (isinstance(metadata, dict)
            and passage.get("id") == record.get("parent_id")
            and passage.get("id") == record.get("commentary_id", "").removesuffix(":commentary")
            and passage.get("source") == "campbell_assignment"
            and passage.get("kind") == "text"
            and passage.get("language") == "grc"
            and passage.get("quality") == record.get("parent_quality") == "machine_corrected_ocr"
            and passage.get("author") == record.get("parent_author")
            and passage.get("work") == record.get("parent_work")
            and passage.get("edition") == record.get("parent_edition")
            and passage.get("source_url") == record.get("parent_source_url")
            and passage.get("raw_sha256") == record.get("parent_raw_sha256")
            and metadata.get("assignment_fragment") == record.get("assignment_fragment")
            and metadata.get("edition_fragment") == record.get("edition_fragment")
            and metadata.get("source_pdf_sha256") == record.get("source_pdf_sha256") == SOURCE_PDF_SHA256
            and isinstance(passage.get("text"), str)
            and hashlib.sha256(passage["text"].encode("utf-8")).hexdigest() == record.get("parent_text_sha256"))


def for_passage(passage: dict, *, path: Path = DATA_PATH, for_model: bool = False) -> dict | None:
    """Return all source paragraphs or an explicit fail-closed unavailability.

    No phrase/word matching is performed. The single OCR-replacement paragraph
    remains available to readers with its uncertainty flag but cannot enter a
    model packet. Callers must not append these paragraphs to source claims,
    translation previews, or grammatical candidate inventories.
    """
    if not isinstance(passage, dict):
        return None
    passage_id = passage.get("id")
    if not isinstance(passage_id, str) or not passage_id.startswith("campbell-glp:alcaeus:"):
        return None
    fragment = passage_id.removeprefix("campbell-glp:alcaeus:")
    if fragment not in FRAGMENTS:
        return None
    try:
        payload = _read(Path(path))
        records = [row for row in payload["records"] if row.get("parent_id") == passage_id]
        if len(records) != 1 or not _bound(records[0], passage):
            raise ValueError("Accepted poem identity differs")
        record = records[0]
        paragraphs = deepcopy(record["paragraphs"])
        omitted = 0
        if for_model:
            omitted = sum(1 for row in paragraphs if not row.get("model_eligible"))
            paragraphs = [row for row in paragraphs if row.get("model_eligible") is True]
        return {
            "status": "available",
            "evidence_type": "published_commentary",
            "scope": "whole_poem_commentary",
            "selection_aligned": False,
            "word_attestation": False,
            "line_attestation": False,
            "commentary_id": record["commentary_id"],
            "parent_id": passage_id,
            "edition_fragment": record["edition_fragment"],
            "source_title": record["source_title"],
            "license": record["license"],
            "rights_note": record["rights_note"],
            "source_pdf_sha256": record["source_pdf_sha256"],
            "paragraph_count": len(paragraphs),
            "uncertain_ocr_paragraphs_omitted_for_model": omitted,
            "scope_note": ("Published whole-poem scholarly commentary, not an exact line, word, "
                           "translation, grammatical parse, or dictionary-sense attestation."),
            "paragraphs": paragraphs,
        }
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"status": "unavailable", "evidence_type": "published_commentary",
                "scope": "whole_poem_commentary",
                "reason": "Approved commentary projection is missing or no longer matches this source passage.",
                "paragraphs": []}


MODEL_PARAGRAPH_FIELDS = ("ordinal", "kind", "line_label", "lemma", "anchor_line_label",
                          "anchor_method_ref", "printed_page", "text")


def compact_model_context(commentary: dict) -> dict:
    """Lossless model view of every eligible paragraph's prose and note scope.

    Repeated citation boilerplate and PDF extraction coordinates are omitted;
    printed page plus the shared source/fragment uniquely cites each row. The
    retained heading/anchor fields are source metadata, never word alignment.
    """
    if commentary.get("status") != "available" or commentary.get("scope") != "whole_poem_commentary":
        raise ValueError("Only bound whole-poem commentary can enter a model packet")
    paragraphs = commentary["paragraphs"]
    if not all(row.get("model_eligible") is True and "\ufffd" not in row.get("text", "")
               for row in paragraphs):
        raise ValueError("Uncertain OCR cannot enter model commentary context")
    methods = list(dict.fromkeys(row["anchor_method"] for row in paragraphs))
    rows = [[row["ordinal"], row["kind"], row["line_label"], row["lemma"],
             row["anchor_line_label"], methods.index(row["anchor_method"]),
             row["printed_page"], row["text"]] for row in paragraphs]
    return {"schema": "campbell-whole-poem-compact-v1",
            "evidence_type": "published_commentary",
            "scope": "whole_poem_commentary",
            "selection_aligned": False, "word_attestation": False, "line_attestation": False,
            "commentary_id": commentary["commentary_id"],
            "source_title": commentary["source_title"],
            "edition_fragment": commentary["edition_fragment"],
            "license": commentary["license"],
            "uncertain_ocr_paragraphs_omitted": commentary["uncertain_ocr_paragraphs_omitted_for_model"],
            "paragraph_fields": MODEL_PARAGRAPH_FIELDS,
            "anchor_methods": methods,
            "paragraphs": rows}
