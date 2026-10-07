"""Synthetic token mechanics only; no authored poem or dictionary evidence."""
from copy import deepcopy

import pytest

from backend.lacuna_boundaries import annotate_lacuna_boundaries, intact_word_eligible
from backend.passage_analysis import tokenize_span


def annotate(text, start=0, end=None, critical=True):
    tokens = tokenize_span(text, start, len(text) if end is None else end)
    return annotate_lacuna_boundaries(text, tokens, source_critical=critical)


def words(tokens):
    return [token for token in tokens if token["kind"] == "word"]


def test_dot_run_changes_uncertainty_not_literal_text_or_word_identity():
    text = "αβ . . γδ εζ"
    original = tokenize_span(text, 0, len(text))
    snapshot = deepcopy(original)
    annotated = annotate_lacuna_boundaries(text, original, source_critical=True)
    assert original == snapshot
    assert "".join(token["text"] for token in annotated) == text
    first, second, third = words(annotated)
    assert first["lacuna_boundary_uncertain"] and second["lacuna_boundary_uncertain"]
    assert not third.get("lacuna_boundary_uncertain")
    assert not first["partial_word"] and not second["partial_word"]
    assert not first.get("editorial_fragment") and not second.get("editorial_fragment")
    assert first["lacuna_boundary_evidence"][0]["side"] == "after"
    assert second["lacuna_boundary_evidence"][0]["side"] == "before"
    for token in (first, second):
        evidence = token["lacuna_boundary_evidence"][0]
        assert text[evidence["start"]:evidence["end"]] == ". ."
        assert not intact_word_eligible(token)
    assert intact_word_eligible(third)


@pytest.mark.parametrize("text", ["αβ .. γδ", "αβ .\t. γδ", "αβ .\u00a0. γδ",
                                 "αβ .\u202f. γδ", "αβ[. .]γδ"])
def test_same_line_printed_runs_with_horizontal_spacing_or_brackets(text):
    assert all(token.get("lacuna_boundary_uncertain") for token in words(annotate(text)))


@pytest.mark.parametrize("text", ["αβ. γδ", "αβ .\n. γδ", "αβ .\r\n. γδ",
                                 "αβ . .\nγδ", "αβ . . · γδ"])
def test_no_single_period_newline_or_punctuation_crossing(text):
    assert not words(annotate(text))[-1].get("lacuna_boundary_uncertain")


def test_selection_does_not_hide_source_gap_before_selected_word():
    text = "αβ . . γδ εζ"
    start = text.index("γδ")
    token = words(annotate(text, start, start + 2))[0]
    assert token["lacuna_boundary_uncertain"]
    assert token["text"] == "γδ" and not token["partial_word"]


def test_source_profile_is_explicit_and_not_coerced_from_truthy_values():
    text = "αβ . . γδ"
    for value in (False, None, "true", 1):
        assert not any(token.get("lacuna_boundary_uncertain") for token in annotate(text, critical=value))


def test_intact_eligibility_keeps_other_editorial_and_selection_guards():
    for flag in ("partial_word", "editorial_fragment", "uncertain_letters", "lacuna_boundary_uncertain"):
        assert not intact_word_eligible({"kind": "word", flag: True})
    assert not intact_word_eligible({"kind": "punctuation"})


def test_stale_offsets_are_rejected_instead_of_attaching_evidence_elsewhere():
    with pytest.raises(ValueError, match="offsets"):
        annotate_lacuna_boundaries("α . . β", [{"kind": "word", "text": "γ", "start": 0, "end": 1}], source_critical=True)


def test_repeat_annotation_is_idempotent():
    text = "α . . β"
    first = annotate(text)
    assert annotate_lacuna_boundaries(text, first, source_critical=True) == first
