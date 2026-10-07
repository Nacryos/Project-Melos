"""Accepted Campbell sidecar stays literal, scoped, and fail-closed."""

import hashlib
import json
from pathlib import Path

from backend import edition_commentary
from scripts import build_edition_commentary


def _greek():
    return [json.loads(line) for line in build_edition_commentary.GREEK.read_text(encoding="utf-8").splitlines()]


def _source_notes():
    return [json.loads(line) for line in build_edition_commentary.COMMENTARY.read_text(encoding="utf-8").splitlines()]


def test_projected_package_is_deterministic_and_approval_bound(tmp_path):
    projected = build_edition_commentary.build()
    staged = build_edition_commentary.OUTPUT.read_bytes()
    assert hashlib.sha256(staged).hexdigest() == edition_commentary.DATA_SHA256
    assert json.loads(staged) == projected
    assert projected["record_count"] == 5
    assert projected["paragraph_count"] == 88
    assert projected["uncertain_ocr_paragraph_count"] == 1
    assert build_edition_commentary.write(tmp_path / "public.json") == edition_commentary.DATA_SHA256
    assert (tmp_path / "public.json").read_bytes() == staged


def test_every_approved_paragraph_is_verbatim_with_printed_page_and_no_private_paths():
    projected = build_edition_commentary.build()
    originals = {row["assignment_fragment"]: row for row in _source_notes()}
    for record in projected["records"]:
        source = originals[record["assignment_fragment"]]
        assert record["commentary_id"] == source["id"]
        assert record["edition_fragment"] == source["edition_fragment"]
        assert len(record["paragraphs"]) == len(source["paragraphs"])
        for new, original in zip(record["paragraphs"], source["paragraphs"]):
            for key in ("kind", "line_label", "lemma", "text", "anchor_line_label", "anchor_method"):
                assert new[key] == original[key]
            assert new["printed_page"] == original["source"]["printed_page"]
            assert new["pdf_page"] == original["source"]["pdf_page"]
            assert str(new["printed_page"]) in new["citation"]
            assert new["scope"] == "whole_poem_commentary"
    assert projected["records"][2]["assignment_fragment"] == "130b"
    assert projected["records"][2]["edition_fragment"] == "130"
    text = build_edition_commentary.OUTPUT.read_text(encoding="utf-8")
    for private in ("image_file", "embedded_text_file", "blocks_file", "ocr_file", "audit_path",
                    "raw_path", "bounds_pdf_points", "C:\\Users", "runtime\\"):
        assert private not in text


def test_exact_accepted_poem_only_and_no_word_or_translation_claims():
    for poem in _greek():
        result = edition_commentary.for_passage(poem, path=build_edition_commentary.OUTPUT)
        assert result["status"] == "available"
        assert result["parent_id"] == poem["id"]
        assert result["scope"] == "whole_poem_commentary"
        assert result["evidence_type"] == "published_commentary"
        assert result["selection_aligned"] is False
        assert result["word_attestation"] is False
        assert result["line_attestation"] is False
        assert "published_translations" not in result
        assert "source_claims" not in result


def test_wrong_edition_or_poem_text_cannot_acquire_notes():
    poem = _greek()[0]
    for changed in ({**poem, "text": poem["text"] + "x"},
                    {**poem, "raw_sha256": "0" * 64},
                    {**poem, "source": "perseus"},
                    {**poem, "metadata": {**poem["metadata"], "edition_fragment": "129"}},
                    {**poem, "metadata": {**poem["metadata"], "source_pdf_sha256": "0" * 64}}):
        result = edition_commentary.for_passage(changed, path=build_edition_commentary.OUTPUT)
        assert result["status"] == "unavailable" and result["paragraphs"] == []
    assert edition_commentary.for_passage({**poem, "id": "p2_alcaeus:34a"},
                                          path=build_edition_commentary.OUTPUT) is None


def test_reader_retains_one_uncertain_ocr_paragraph_model_excludes_it():
    poem = _greek()[0]
    reader = edition_commentary.for_passage(poem, path=build_edition_commentary.OUTPUT)
    model = edition_commentary.for_passage(poem, path=build_edition_commentary.OUTPUT, for_model=True)
    assert reader["paragraph_count"] == 15
    assert model["paragraph_count"] == 14
    assert sum("\ufffd" in row["text"] for row in reader["paragraphs"]) == 1
    assert all("\ufffd" not in row["text"] for row in model["paragraphs"])
    assert model["uncertain_ocr_paragraphs_omitted_for_model"] == 1
    assert reader["uncertain_ocr_paragraphs_omitted_for_model"] == 0


def test_projection_tamper_or_missing_file_fails_closed(tmp_path):
    poem = _greek()[0]
    path = tmp_path / "public.json"
    assert edition_commentary.for_passage(poem, path=path)["status"] == "unavailable"
    path.write_bytes(build_edition_commentary.OUTPUT.read_bytes() + b" ")
    assert edition_commentary.for_passage(poem, path=path)["status"] == "unavailable"


def test_source_approval_and_package_tamper_fail_before_projection(tmp_path):
    changed = tmp_path / "source.jsonl"
    changed.write_bytes(build_edition_commentary.COMMENTARY.read_bytes() + b"\n")
    try:
        build_edition_commentary.build(commentary=changed)
    except ValueError as error:
        assert "receipt mismatch" in str(error)
    else:
        raise AssertionError("Changed source package was admitted")
    changed.write_bytes(build_edition_commentary.GREEK_APPROVAL.read_bytes() + b" ")
    try:
        build_edition_commentary.build(greek_approval=changed)
    except ValueError as error:
        assert "receipt mismatch" in str(error)
    else:
        raise AssertionError("Changed Greek approval was admitted")
