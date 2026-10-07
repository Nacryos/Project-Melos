"""Synthetic Greek-symbol fixtures; none of these records are corpus evidence."""
from copy import deepcopy
import hashlib

import pytest

from backend.classifier import classify_context
from backend.jev_gateway import CachedJevProvider, GatewayLimit
from backend.passage_ranker import PassageRanker, OccurrenceProvider, MAX_TOKEN_OCCURRENCES


PASSAGE = {"id": "synthetic:1", "text": "α α α α", "language": "grc", "kind": "text",
           "source_url": "https://example.test/synthetic"}
CANDIDATES = [
    {"id": "parse-a", "lemma": "α", "analysis": "synthetic reading A", "matched_form": "α",
     "source_url": "https://example.test/parse-a"},
    {"id": "parse-b", "lemma": "α", "analysis": "synthetic reading B", "matched_form": "α",
     "source_url": "https://example.test/parse-b"},
]


def span(passage=None):
    passage = passage or PASSAGE
    text = passage["text"]
    return {"passage": {"id": passage["id"], "text_sha256": hashlib.sha256(text.encode()).hexdigest()},
        "selection": {"text": text, "start": 0, "end": len(text), "start_utf16": 0, "end_utf16": len(text)},
        "tokens": [{"id": f"t{i}", "kind": "word", "text": char, "start": i, "end": i + 1,
                    "source_candidates": deepcopy(CANDIDATES)} for i, char in enumerate(text) if not char.isspace()],
        "syntax": {"state": "unavailable"}, "context": {}}


class FakeJev:
    model = "synthetic-jev-fixture"
    timeout = 1

    def __init__(self):
        self.packets = []

    def decide(self, packet):
        self.packets.append(deepcopy(packet))
        return {"choice": "parse-a", "model": self.model,
                "model_probabilities": {"parse-a": 0.6, "parse-b": 0.3, "abstain": 0.1}}


def callback(passage, *, candidates=None):
    def classify(form, passage_id, *, provider, candidate_basis="source", machine_receipt_id=None):
        assert passage_id == passage["id"]
        return classify_context(form, passage, candidates if candidates is not None else CANDIDATES, provider=provider)
    return classify


def test_occurrences_are_bounded_separate_and_cache_repeat_exactly(tmp_path):
    fake = FakeJev()
    cached = CachedJevProvider(fake, "a" * 64, state_path=tmp_path / "budget.sqlite")
    ranker = PassageRanker(lambda _: PASSAGE, callback(PASSAGE), lambda _: cached)
    result = span()
    original = deepcopy(result)
    ranked = ranker(result, visitor_id="a" * 64)
    assert result == original
    assert ranked["status"] == "partial"
    assert ranked["attempted_occurrences"] == MAX_TOKEN_OCCURRENCES == len(fake.packets)
    assert [packet["target_occurrence"]["start"] for packet in fake.packets] == [0, 2, 4]
    assert ranked["items"][3]["status"] == "request_limit"
    assert all(item["status"] == "proposed" for item in ranked["items"][:3])
    assert ranked["items"][0]["ranked_candidates"] == [
        {"candidate_id": "parse-a", "score_uncalibrated": 0.6},
        {"candidate_id": "parse-b", "score_uncalibrated": 0.3}]
    repeated = ranker(result, visitor_id="a" * 64)
    assert len(fake.packets) == 3
    assert all(item["decision"]["cache_hit"] for item in repeated["items"][:3])


@pytest.mark.parametrize("change", ["hash", "selection", "later-token", "bool-offset"])
def test_stale_or_invalid_occurrences_fail_before_provider_construction(change):
    result = span()
    if change == "hash":
        result["passage"]["text_sha256"] = "wrong"
    elif change == "selection":
        result["selection"]["text"] = "β"
    elif change == "bool-offset":
        result["tokens"][0]["start"] = False
    else:
        result["tokens"][-1]["text"] = "β"
    constructions = []
    ranker = PassageRanker(lambda _: PASSAGE, callback(PASSAGE), lambda _: constructions.append(True))
    ranked = ranker(result)
    assert ranked["status"] == "unavailable"
    assert constructions == []


def test_trusted_translation_and_predicted_syntax_have_distinct_scopes():
    passage = {**PASSAGE, "text": "α", "translation_previews": [
        {"record_id": "synthetic:translation", "parent_id": PASSAGE["id"], "language": "eng", "text": "synthetic translation " * 200,
         "source_url": "https://example.test/translation", "pairing_proof": {"translation_of": PASSAGE["id"]}},
        {"record_id": "synthetic:wrong-parent", "parent_id": "other", "text": "must not be supplied"}]}
    fake = FakeJev()
    result = span(passage)
    result["context"] = {"published_translations": [{"text": "do not trust copied context"}]}
    result["syntax"] = {"state": "ready", "provider": "synthetic syntax", "scope": "selected_span", "context_start": 0, "context_end": 1,
                        "tokens": [{"id": "s0", "text": "α", "head": None, "deprel": "root", "features": {}}]}
    ranked = PassageRanker(lambda _: passage, callback(passage), lambda _: fake)(result)
    packet = fake.packets[0]
    translations = packet["published_translation_context"]
    assert len(translations) == 1 and len(translations[0]["text"]) == 1800
    assert translations[0]["excerpt_truncated"] is True
    assert translations[0]["selection_aligned"] is False
    assert translations[0]["evidence_type"] == "published_translation"
    assert packet["predicted_syntax_context"]["evidence_type"] == "contextual_prediction"
    assert packet["predicted_syntax_context"]["scope"] == "selected_span"
    assert packet["candidates"] == ranked["items"][0]["decision"]["packet"]["candidates"]
    assert "do not trust copied context" not in str(packet)
    assert "target_occurrence" in ranked["items"][0]["decision"]["packet"]


def test_contextual_enrichment_does_not_change_candidate_inventory():
    fake = FakeJev()
    passage = {**PASSAGE, "text": "α"}
    raw = {"form": "α", "passage": passage, "candidates": deepcopy(CANDIDATES), "constraints": []}
    original = deepcopy(raw)
    provider = OccurrenceProvider(fake, passage, span(passage)["tokens"][0], span(passage))
    provider.decide(raw)
    assert raw == original
    assert fake.packets[0]["candidates"] == original["candidates"]


def test_enrichment_cannot_replace_classifier_context_or_bypass_size_bound():
    fake = FakeJev()
    passage = {**PASSAGE, "text": "α"}
    provider = OccurrenceProvider(fake, passage, span(passage)["tokens"][0], span(passage))
    packet = {"form": "α", "passage": {**passage, "text": "β"}, "candidates": CANDIDATES}
    with pytest.raises(ValueError, match="exact source occurrence"):
        provider.decide(packet)
    packet["passage"] = passage
    packet["oversized"] = "x" * 32000
    with pytest.raises(ValueError, match="no candidates were dropped"):
        provider.decide(packet)
    assert fake.packets == []


def test_original_classifier_proof_guards_run_before_model():
    passage = {**PASSAGE, "text": "α"}
    invalid = [{"id": "unsupported", "lemma": "α", "analysis": "synthetic"}]
    fake = FakeJev()
    ranked = PassageRanker(lambda _: passage, callback(passage, candidates=invalid), lambda _: fake)(span(passage))
    assert ranked["items"][0]["status"] == "abstained"
    assert "source references" in ranked["items"][0]["decision"]["reason"]
    assert fake.packets == []


def test_budget_limit_stops_further_occurrences():
    calls = []
    def limited(*args, **kwargs):
        calls.append(True)
        raise GatewayLimit("synthetic budget limit", retry_after=77)
    ranked = PassageRanker(lambda _: PASSAGE, limited, lambda _: FakeJev())(span())
    assert calls == [True]
    assert all(item["status"] == "rate_limited" for item in ranked["items"])
    assert ranked["items"][0]["retry_after"] == 77


def test_error_text_is_not_reflected_and_no_further_calls_are_made():
    calls = []
    def broken(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("synthetic-secret-value")
    ranked = PassageRanker(lambda _: PASSAGE, broken, lambda _: FakeJev())(span())
    assert len(calls) == 1
    assert "synthetic-secret-value" not in str(ranked)


def test_partial_and_missing_candidates_do_not_consume_comparison_slots():
    result = span()
    result["tokens"][0]["partial_word"] = True
    result["tokens"][1]["source_candidates"] = []
    fake = FakeJev()
    ranked = PassageRanker(lambda _: PASSAGE, callback(PASSAGE), lambda _: fake)(result)
    assert len(fake.packets) == 2
    assert ranked["items"][0]["status"] == "partial_word"
    assert ranked["items"][1]["status"] == "not_available"


def test_machine_receipt_fallback_is_explicit_and_source_alternatives_take_priority():
    result = span()
    for token in result["tokens"]:
        token["machine"] = {"machine_candidates": [{"id": "machine-synthetic"}], "receipt": {"id": "synthetic-receipt"}}
    result["tokens"][0]["source_candidates"] = []
    arguments = []
    def classify(*args, **kwargs):
        arguments.append(kwargs)
        return {"status": "abstained", "reason": "synthetic preflight only"}
    PassageRanker(lambda _: PASSAGE, classify, lambda _: FakeJev())(result)
    assert arguments[0]["candidate_basis"] == "machine"
    assert arguments[0]["machine_receipt_id"] == "synthetic-receipt"
    assert arguments[1]["candidate_basis"] == "source"
    assert arguments[1]["machine_receipt_id"] is None


def test_malformed_probabilities_are_not_displayed_as_rank_confidence():
    def classify(*args, **kwargs):
        return {"status": "abstained", "packet": {"candidates": CANDIDATES},
                "model_probabilities_uncalibrated": {"parse-a": float("nan"), "parse-b": True, "unknown": 1}}
    ranked = PassageRanker(lambda _: PASSAGE, classify, lambda _: FakeJev())(span())
    assert ranked["items"][0]["ranked_candidates"] == [
        {"candidate_id": "parse-a", "score_uncalibrated": None},
        {"candidate_id": "parse-b", "score_uncalibrated": None}]


def test_whole_passage_syntax_preserves_scope_offsets_and_model_provenance():
    from backend.passage_ranker import _syntax_context
    result = span()
    result["syntax"] = {"state": "ready", "scope": "whole_passage", "context_start": 0, "context_end": 7,
        "offset_unit": "unicode_codepoint", "model_version": "synthetic-1", "annotation_scheme": "synthetic UD",
        "provider": "synthetic", "model": "synthetic parser", "provenance": {"revision": "synthetic-revision"},
        "tokens": [{"id": 0, "text": "α", "start": 0, "end": 1, "absolute_start": 0, "absolute_end": 1,
                    "selected": False, "head": None, "deprel": "root", "token_kind": "lexical", "prediction_status": "predicted"}]}
    context = _syntax_context(result)
    assert context["scope"] == "whole_passage"
    assert (context["context_start"], context["context_end"]) == (0, 7)
    assert context["model_version"] == "synthetic-1"
    assert context["annotation_scheme"] == "synthetic UD"
    assert context["tokens"][0]["selected"] is False
    assert context["tokens"][0]["absolute_start"] == 0
    assert "whole bounded source passage" in context["scope_note"]
    result["syntax"]["scope"] = "selected_span"
    result["syntax"]["context_start"], result["syntax"]["context_end"] = 2, 5
    context = _syntax_context(result)
    assert context["scope"] == "selected_span" and context["context_start"] == 2
    assert "outside it cannot be resolved" in context["scope_note"]


def test_nonlexical_and_editorial_syntax_keeps_only_boundaries_and_unresolved_heads():
    from backend.passage_ranker import _syntax_context
    result = span()
    result["syntax"] = {"state": "ready", "scope": "whole_passage", "tokens": [
        {"id": 0, "text": "α", "head": 1, "deprel": "obj", "token_kind": "lexical", "prediction_status": "predicted"},
        {"id": 1, "text": "[", "head": 0, "deprel": "amod", "lemma": "invented", "features": {"Case": "Nom"},
         "token_kind": "editorial", "prediction_status": "not_applicable", "raw_prediction": {"lemma": "must not reach Jev"}},
        {"id": 2, "text": "\n", "head": 0, "deprel": "obj", "features": {"Case": "Acc"}},
        {"id": 3, "text": ",", "head": 0, "deprel": "punct", "token_kind": "punctuation"},
        {"id": 4, "text": "α[β]", "head": 0, "deprel": "nmod", "token_kind": "lexical"},
    ]}
    context = _syntax_context(result)
    assert len(context["tokens"]) == 5
    first = context["tokens"][0]
    assert first["head"] is None and first["deprel"] is None
    assert first["attachment_status"] == "unresolved_nonlexical_head" and first["unresolved_head_id"] == 1
    for token in context["tokens"][1:]:
        assert token["lemma"] is None and token["features"] == {}
        assert token["head"] is None and token["deprel"] is None
        assert token["prediction_status"] == "not_applicable"
    assert "must not reach Jev" not in str(context) and "invented" not in str(context)


def test_editorial_word_fragments_are_never_ranked_even_if_candidates_arrive():
    result = span()
    result["tokens"][0]["editorial_fragment"] = True
    fake = FakeJev()
    ranked = PassageRanker(lambda _: PASSAGE, callback(PASSAGE), lambda _: fake)(result)
    assert ranked["items"][0]["status"] == "editorial_fragment"
    assert [packet["target_occurrence"]["start"] for packet in fake.packets] == [2, 4, 6]


def test_nearby_spelling_suggestions_do_not_block_exact_machine_receipt():
    passage = {**PASSAGE, "text": "α"}
    result = span(passage)
    result["tokens"][0]["source_candidates"] = [{**CANDIDATES[0], "edit_distance": 1}]
    result["tokens"][0]["machine"] = {"machine_candidates": [{"id": "synthetic-machine"}],
                                       "receipt": {"id": "synthetic-receipt"}}
    original = deepcopy(result)
    arguments = []
    def classify(*args, **kwargs):
        arguments.append(kwargs)
        return {"status": "abstained", "reason": "synthetic receipt validation would run here"}
    PassageRanker(lambda _: passage, classify, lambda _: FakeJev())(result)
    assert arguments[0]["candidate_basis"] == "machine"
    assert arguments[0]["machine_receipt_id"] == "synthetic-receipt"
    assert result == original


def test_nearby_spelling_suggestions_without_receipt_make_no_model_call():
    passage = {**PASSAGE, "text": "α"}
    result = span(passage)
    result["tokens"][0]["source_candidates"] = [{**CANDIDATES[0], "edit_distance": 1}]
    fake = FakeJev()
    ranked = PassageRanker(lambda _: passage, callback(passage), lambda _: fake)(result)
    assert fake.packets == [] and ranked["attempted_occurrences"] == 0
    assert "nearby spellings are not parses" in ranked["items"][0]["reason"]
