"""Synthetic transport-contract tests; no philological fixtures."""
from copy import deepcopy

import pytest

from scripts.evaluate_context_windows import sha, verify, verify_comparisons


def fixture():
    text = "a b c"
    request = {"start": 2, "end": 3, "selected_text": "b"}
    record = {"id": "synthetic", "text": text}
    result = {"selection": {"text": "b"},
              "passage": {"id": "synthetic", "text_sha256": sha(text)},
              "ranking": {"status": "not_requested"},
              "sense_ranking": {"status": "not_requested"},
              "limits": {"machine_fetches": 0},
              "syntax": {"state": "ready", "context_start": 0, "context_end": 5,
                         "scope": "whole_passage", "tokens": [
                             {"text": "b", "start": 2, "end": 3, "absolute_start": 2,
                              "absolute_end": 3, "selected": True}]}}
    return result, request, record


def test_valid_context_contract():
    result, request, record = fixture()
    assert verify(result, request, record)["context_characters"] == 5


@pytest.mark.parametrize("mutation", ["offset", "selection", "text", "missing_context", "paid"])
def test_contract_rejects_bad_response(mutation):
    result, request, record = fixture()
    if mutation == "offset":
        result["syntax"]["tokens"][0]["absolute_start"] = 0
    elif mutation == "selection":
        result["syntax"]["tokens"][0]["selected"] = False
    elif mutation == "text":
        result["passage"]["text_sha256"] = "wrong"
    elif mutation == "missing_context":
        result["syntax"].update(context_start=2, context_end=3, scope="selected_span")
    elif mutation == "paid":
        result["ranking"]["status"] = "proposed"
    with pytest.raises(AssertionError):
        verify(result, request, record)


def test_commentary_requires_whole_poem_scope_without_word_alignment():
    result, request, record = fixture()
    with pytest.raises(AssertionError):
        verify(result, request, record, require_commentary=True)
    result["context"] = {"published_commentary": {
        "status": "available", "parent_id": "synthetic", "scope": "whole_poem_commentary",
        "selection_aligned": False, "word_attestation": False, "paragraph_count": 2}}
    assert verify(result, request, record, require_commentary=True)["commentary_paragraph_count"] == 2
    wrong = deepcopy(result)
    wrong["context"]["published_commentary"]["selection_aligned"] = True
    with pytest.raises(AssertionError):
        verify(wrong, request, record, require_commentary=True)


def test_comparison_verifier_checks_whole_reader_projection_and_no_model_alignment():
    # Synthetic source payload exercises preservation, not a translation.
    expected = {"status": "available", "scope": "whole_poem_other_edition",
                "selection_aligned": False, "exact_edition_alignment": False,
                "word_attestation": False, "line_attestation": False,
                "model_eligible": False, "comparison_count": 1,
                "translation_comparisons": [{"text": "Synthetic text", "credit": "Synthetic credit"}]}
    result = {"context": {"translation_comparisons": deepcopy(expected)}}
    assert verify_comparisons(result, expected) == 1
    for field in ("text", "credit"):
        altered = deepcopy(result)
        altered["context"]["translation_comparisons"]["translation_comparisons"][0][field] = "altered"
        with pytest.raises(AssertionError):
            verify_comparisons(altered, expected)
    bad = deepcopy(expected)
    bad["model_eligible"] = True
    with pytest.raises(AssertionError):
        verify_comparisons({"context": {"translation_comparisons": bad}}, bad)
