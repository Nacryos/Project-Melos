"""Synthetic retrieval mechanics only; no fixture is corpus evidence."""
from backend.retrieval import fuse


def record(identifier, *, quality="source_text", author="Poet", language="grc",
           edition="Synthetic edition", kind="text", **extra):
    return {"id": identifier, "quality": quality, "author": author,
            "language": language, "edition": edition, "kind": kind,
            "text": "Synthetic " + identifier, "citation": identifier,
            "source_url": "https://example.org/synthetic/" + identifier, **extra}


def test_reference_toggle_includes_review_text_without_erasing_quality():
    records = {quality: record(quality, quality=quality) for quality in
               ("source_text", "needs_review", "machine_ocr", "mixed_content")}
    normal = fuse("synthetic", list(records.values()), [], [], records.get)
    assert [r["id"] for r in normal["results"]] == ["source_text"]
    expanded = fuse("synthetic", list(records.values()), [], [], records.get, include_reference=True)
    assert {r["id"] for r in expanded["results"]} == set(records)
    assert {r["quality"] for r in expanded["results"]} == set(records)


def test_reference_toggle_does_not_override_author_language_or_edition_filters():
    records = {
        "wanted": record("wanted", quality="needs_review"),
        "author": record("author", quality="needs_review", author="Other"),
        "language": record("language", quality="needs_review", language="eng"),
        "edition": record("edition", quality="needs_review", edition="Other edition"),
    }
    result = fuse("synthetic", list(records.values()), [], [], records.get,
                  include_reference=True, author="Poet", language="grc", edition="Synthetic edition")
    assert [r["id"] for r in result["results"]] == ["wanted"]


def test_review_commentary_quality_survives_projection_to_clean_parent():
    records = {
        "parent": record("parent"),
        "note": record("note", quality="needs_review", language="eng", kind="commentary",
                       author="Editor", parent_id="parent"),
    }
    normal = fuse("synthetic", [records["note"]], [], [], records.get, author="Poet", language="grc")
    assert normal["total"] == 0
    expanded = fuse("synthetic", [records["note"]], [], [], records.get,
                    author="Poet", language="grc", include_reference=True)
    assert expanded["results"][0]["quality"] == "source_text"
    evidence = expanded["results"][0]["matched_evidence"]
    assert evidence[0]["id"] == "note"
    assert evidence[0]["quality"] == "needs_review"
