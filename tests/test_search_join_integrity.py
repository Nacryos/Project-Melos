"""Synthetic layout mechanics, not authored philological forms or attestations."""
import unicodedata

import pytest

from backend.textutils import search_text


@pytest.mark.parametrize("division", ["-\n", "‐\n", "\u00ad\n", "- \t\r\n \t"])
def test_intact_division_and_whole_chain(division):
    text = f"αβ{division}γδ{division}εζ"
    assert search_text(text) == "αβγδεζ"
    assert division in text  # Original string is not modified.


@pytest.mark.parametrize("sign", ["'", "’", "᾽", "ʼ", "᾿"])
def test_final_printed_sign_retained_not_reconstructed(sign):
    assert search_text(f"αβ-\nγδ{sign}") == f"αβγδ{sign}"
    # The same printed sign before a further division is not an intact stem.
    text = f"αβ{sign}-\nγδ-\nεζ"
    assert search_text(text) == text


@pytest.mark.parametrize("text", [
    "α[β-\nγ[]δ", "α[β-\nγ̣δ", "[αβ-\nγδ", "αβ-\nγδ]",
    "αβ-\nγ[δ", "α̣β-\nγδ", "αβ-\nγδ̣", "αβ-\nγδ…", "αβ-\nγδ†",
    "αβ-\nγδ. . .", "αβ-\nγδ...", "αβ-\nγδ-", "-αβ-\nγδ",
    "⟨αβ-\nγδ⟩", "‹αβ-\nγδ›", "⸢αβ-\nγδ⸣",
    "αβ-\nγδ-\nεζ]", "[αβ-\nγδ-\nεζ", "αβ-\nγ̣δ-\nεζ",
    "xαβ-\nγδ-\nεζ", "αβ-\nγδx-\nεζ-\nηθ", "1-\nαβ-\nγδ",
    "αβ-\n2. γδ", "αβ-\n\nγδ", "αβ--\nγδ", "αβ- γδ", "αβ -\nγδ",
])
def test_damaged_or_nonexplicit_chain_never_salvages_suffix(text):
    assert search_text(text) == text


def test_local_edges_not_unrelated_editorial_content():
    assert search_text("[α] βγ-\nδε [ζ]") == "[α] βγδε [ζ]"
    assert search_text("(αβ-\nγδ), εζ") == "(αβγδ), εζ"
    assert search_text("αβ-\nγδ. εζ") == "αβγδ. εζ"


def test_rejected_chain_does_not_block_separate_clean_chain():
    assert search_text("[αβ-\nγδ] εζ-\nηθ") == "[αβ-\nγδ] εζηθ"


def test_nfc_contract_no_accent_or_case_folding():
    decomposed = unicodedata.normalize("NFD", "Ἄβ-\nγδ")
    assert search_text(decomposed) == "Ἄβγδ"
    assert search_text("Ἄβ") == "Ἄβ"


def test_large_independent_chains_have_same_guard_behavior():
    # Deterministic coverage of iterative traversal, not a timing threshold.
    text = ("[αβ-\nγδ] εζ-\nηθ ") * 4000
    assert search_text(text) == ("[αβ-\nγδ] εζηθ ") * 4000


@pytest.mark.parametrize("text", ["[αβ-\nγδ]", "α[β-\nγ[]δ", "αβ-\nγ̣δ"])
def test_classifier_occurrence_gate_does_not_call_provider_for_false_join(text):
    from backend.classifier import classify_context
    class NoCallProvider:
        def decide(self, packet):
            pytest.fail("A synthetic damaged concatenation must not reach a model")
    passage = {"id": "synthetic:join", "text": text, "language": "grc", "kind": "text",
               "author": "Synthetic fixture", "source_url": "https://example.test/layout"}
    candidate = {"id": "synthetic:parse", "lemma": "αβγδ", "analysis": "synthetic parse",
                 "matched_form": "αβγδ", "source_url": "https://example.test/fixture"}
    result = classify_context("αβγδ", passage, [candidate], provider=NoCallProvider())
    assert "does not occur as a token" in result["reason"]
    assert passage["text"] == text
