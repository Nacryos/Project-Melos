"""Synthetic span fixtures, never corpus additions."""

import pytest

from backend.discovery_units import (
    MAX_SOURCE_LENGTH, MAX_UNITS_PER_RECORD, OFFSET_BASIS, SUPPORTED_UNITS,
    segment_record,
)


def source(text, **extra):
    return {"id": "synthetic-span-fixture", "text": text, **extra}


@pytest.mark.parametrize("unit", SUPPORTED_UNITS)
def test_every_quote_is_a_literal_original_codepoint_slice(unit):
    record = source("  \U0001f3b5 \u03b1\u0313\u0301\u03b2,  \u03b3;\r\n\u03b4\u2019\u03b5.\r\n \t\r\n\u03b6!  ")
    before = dict(record)
    segments = segment_record(record, unit)
    assert segments
    for segment in segments:
        assert segment["text"] == segment["quote"] == record["text"][segment["start"]:segment["end"]]
        assert segment["parent_id"] == segment["passage_id"] == record["id"]
        assert segment["offset_basis"] == OFFSET_BASIS
        assert segment["unit"] == unit
        assert segment["segmentation_method"]
    assert record == before


def test_passage_keeps_boundary_whitespace():
    record = source(" \t\u03b1  \u03b2\n ")
    assert segment_record(record, "passage")[0]["text"] == record["text"]


def test_lines_preserve_internal_spaces_and_source_offsets():
    record = source(" \u03b1  \u03b2 \r\n\t\u03b3\n\n\u03b4\r\u03b5  ")
    segments = segment_record(record, "line")
    assert [s["text"] for s in segments] == ["\u03b1  \u03b2", "\u03b3", "\u03b4", "\u03b5"]
    assert segments[0]["start"] == 1
    assert len(segment_record(source(" \u03b1 "), "line")) == 1


@pytest.mark.parametrize("text", ["\u03b1", "\u03b1\n\u03b2", "\u03b1\r\n\u03b2", "\n\n\u03b1\n\n"])
def test_stanzas_are_not_invented_from_lines_or_metadata(text):
    assert segment_record(source(text, genre="poetry", stanza="1", work="poem"), "stanza") == []


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_stanzas_require_actual_blank_line_separators(newline):
    record = source(" \u03b1" + newline + "\u03b2" + newline + " \t" + newline + "\u03b3 ")
    assert [s["text"] for s in segment_record(record, "stanza")] == ["\u03b1" + newline + "\u03b2", "\u03b3"]


def test_sentence_and_phrase_heuristics_are_labeled_and_preserve_punctuation():
    record = source("\u03b1,  \u03b2\u00b7 \u03b3; \u201c\u03b4!\u201d \u03b5\u037e \u03b6")
    sentences = segment_record(record, "sentence")
    phrases = segment_record(record, "phrase")
    assert [s["text"] for s in sentences] == ["\u03b1,  \u03b2\u00b7 \u03b3;", "\u201c\u03b4!\u201d", "\u03b5\u037e", "\u03b6"]
    assert [s["text"] for s in phrases] == ["\u03b1,", "\u03b2\u00b7", "\u03b3;", "\u201c\u03b4!\u201d", "\u03b5\u037e", "\u03b6"]
    assert all("heuristic" in s["segmentation_method"] for s in sentences + phrases)


def test_words_keep_combining_marks_and_attached_apostrophes_without_normalizing():
    record = source("\u0323 \u03b1\u0313\u0301\u03b2 \u03b3\u0323' \u03b4\u2019\u03b5 \u03b6\u1fbd \u03b7\u02bc \u03b8\u1fbf \u03b9''\u03ba 31.2")
    assert [s["text"] for s in segment_record(record, "word")] == [
        "\u03b1\u0313\u0301\u03b2", "\u03b3\u0323'", "\u03b4\u2019\u03b5", "\u03b6\u1fbd", "\u03b7\u02bc", "\u03b8\u1fbf", "\u03b9'", "\u03ba",
    ]


def test_word_offsets_count_codepoints_and_never_join_source_line_divisions():
    record = source("\U0001f3b5 \u03b1\u0313-\n\u03b2")
    words = segment_record(record, "word")
    assert [(s["text"], s["start"], s["end"]) for s in words] == [
        ("\u03b1\u0313", 2, 4), ("\u03b2", 6, 7),
    ]


def test_ids_are_stable_unique_and_distinguish_record_revision_and_id_type():
    record = source("\u03b1 \u03b1")
    first = segment_record(record, "word")
    assert first == segment_record(record, "word")
    assert first[0]["id"] != first[1]["id"]
    for changed in [source(record["text"], id="other"), source("\u03b1 \u03b2")]:
        assert first[0]["id"] != segment_record(changed, "word")[0]["id"]
    assert segment_record(source("\u03b1", id=1), "word")[0]["id"] != segment_record(source("\u03b1", id="1"), "word")[0]["id"]


def test_limits_reject_overlong_sources_and_keep_only_complete_units():
    assert segment_record(source("\u03b1" * (MAX_SOURCE_LENGTH + 1)), "passage") == []
    assert segment_record(source("\u03b1" * MAX_SOURCE_LENGTH), "passage")[0]["end"] == MAX_SOURCE_LENGTH
    segments = segment_record(source("\u03b1 " * (MAX_UNITS_PER_RECORD + 10)), "word")
    assert len(segments) == MAX_UNITS_PER_RECORD
    assert segments[-1]["end"] == 2 * MAX_UNITS_PER_RECORD - 1


@pytest.mark.parametrize("record", [None, {}, {"id": "x"}, source(None), source(""), source(" \n\t"), source("\u03b1", id=None)])
def test_invalid_or_empty_records_have_no_units(record):
    assert segment_record(record, "word") == []


def test_unsupported_unit_is_explicit_error():
    with pytest.raises(ValueError, match="Unsupported discovery unit"):
        segment_record(source("\u03b1"), "poem")
