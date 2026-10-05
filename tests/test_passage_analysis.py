"""Synthetic fixtures for selection plumbing; these are not corpus evidence."""
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.passage_analysis import (MAX_WORDS, PassageAnalysisError,
    PassageAnalysisService, lint_syntax, tokenize_span, utf16_offset)
from backend.passage_routes import create_router


def setup(text="ἄνδρα μοι ἄνδρα", *, word=None, machine=None, parser=None, ranker=None):
    passage = {"id": "synthetic:test", "language": "grc", "kind": "text", "text": text,
               "author": "Synthetic fixture", "related": [], "translation_previews": []}
    calls = []
    def lookup(form, passage_id):
        calls.append((form, passage_id))
        return deepcopy(word or {"candidates": [{"lemma": form, "source": "synthetic fixture"}], "warnings": []})
    service = PassageAnalysisService(lambda identifier: passage if identifier == passage["id"] else None,
                                     lookup, machine_service=machine, syntax_provider=parser, ranker=ranker)
    return service, passage, calls


def request(passage, start=0, end=None, **kwargs):
    end = len(passage["text"]) if end is None else end
    return {"passage_id": passage["id"], "start": start, "end": end,
            "offset_unit": "codepoint", "selected_text": passage["text"][start:end], **kwargs}


def test_lossless_unicode_editorial_and_repeated_token_offsets():
    text = "😀 [α\u0313]· ἄνδρα … ⟨ἄνδρα⟩\n"
    service, passage, calls = setup(text)
    result = service.analyze(request(passage))
    assert "".join(token["text"] for token in result["tokens"]) == text
    for token in result["tokens"]:
        assert text[token["start"]:token["end"]] == token["text"]
        assert token["start_utf16"] == utf16_offset(text, token["start"])
        assert token["end_utf16"] == utf16_offset(text, token["end"])
    assert len([token for token in result["tokens"] if token["text"] == "ἄνδρα"]) == 2
    assert len(calls) == 2  # Exact repeated forms are looked up once.
    assert {token["text"] for token in result["tokens"] if token["kind"] == "editorial"} >= {"[", "]", "…", "⟨", "⟩"}


def test_utf16_browser_selection_matches_real_corpus_not_normalized_text():
    service, passage, _ = setup("😀 α\u0313 β")
    result = service.analyze({"passage_id": passage["id"], "start": 3, "end": 5,
                              "offset_unit": "utf16", "selected_text": "α\u0313"})
    assert result["selection"]["start"] == 2
    assert result["tokens"][0]["start_utf16"] == 3
    with pytest.raises(PassageAnalysisError, match="UTF-16"):
        service.analyze({"passage_id": passage["id"], "start": 1, "end": 5,
                         "offset_unit": "utf16", "selected_text": "α\u0313"})
    with pytest.raises(PassageAnalysisError) as failure:
        service.analyze({"passage_id": passage["id"], "start": 3, "end": 5,
                         "offset_unit": "utf16", "selected_text": "ἀ"})
    assert failure.value.code == "stale_selection"
    assert failure.value.status_code == 409


@pytest.mark.parametrize("change,code", [
    ({"start": True}, "invalid_offset"), ({"start": -1}, "invalid_offset"),
    ({"end": 9999}, "invalid_offset"), ({"end": 0}, "invalid_span"),
    ({"offset_unit": "bytes"}, "invalid_offset_unit"), ({"version": 2}, "unsupported_version"),
    ({"passage_id": "unknown"}, "passage_not_found"), ({"text": "invented"}, "invalid_request"),
    ({"author": "invented"}, "invalid_request"), ({"rerank": "yes"}, "invalid_flag"),
    ({"selected_text": "x" * 2001}, "invalid_selection"),
])
def test_invalid_request_rejected_before_lookup(change, code):
    service, passage, calls = setup()
    with pytest.raises(PassageAnalysisError) as failure:
        service.analyze({**request(passage), **change})
    assert failure.value.code == code
    assert not calls


def test_token_bounds_and_punctuation_only():
    for text in ("α " * (MAX_WORDS + 1), "[…] ;"):
        service, passage, _ = setup(text)
        with pytest.raises(PassageAnalysisError) as failure:
            service.analyze(request(passage))
        assert failure.value.code == "invalid_word_count"


def test_partial_words_are_not_looked_up_as_real_words():
    service, passage, calls = setup("ἄνδρα")
    result = service.analyze(request(passage, 1, 4))
    assert result["tokens"][0]["partial_word"]
    assert not result["tokens"][0]["source_candidates"]
    assert not calls


def test_editorial_interruptions_never_create_repaired_words_or_complete_fragments():
    service, passage, calls = setup("α[β]γ α[…]β [γ]")
    result = service.analyze(request(passage))
    assert "".join(token["text"] for token in result["tokens"]) == passage["text"]
    assert calls == [("γ", "synthetic:test")]
    fragments = [token for token in result["tokens"] if token.get("editorial_fragment")]
    assert len(fragments) == 5
    assert all(not token["source_candidates"] for token in fragments)


def test_all_candidate_identities_and_proofs_survive_without_merging():
    alternatives = [{"lemma": "α", "lexicon_entry_ids": ["synthetic:A"], "analysis": "one"},
                    {"lemma": "α", "lexicon_entry_ids": ["synthetic:B"], "analysis": "one"},
                    {"lemma": "β", "analysis": "two", "edit_distance": 1}]
    contextual = [{"id": "synthetic:claim", "claim_ids": ["synthetic:proof"], "lemma": "α"}]
    source = {"candidates": alternatives, "contextual_candidates": contextual,
              "contextual_supporting_claims": [{"id": "synthetic:proof", "evidence": []}],
              "lexicon_entries": [{"id": "synthetic:A"}, {"id": "synthetic:B"}]}
    service, passage, _ = setup("α α", word=source)
    result = service.analyze(request(passage))
    for token in (result["tokens"][0], result["tokens"][2]):
        assert token["source_candidates"] == alternatives
        assert token["contextual_candidates"] == contextual
        assert token["contextual_supporting_claims"] == source["contextual_supporting_claims"]
    result["tokens"][0]["source_candidates"].clear()
    assert result["tokens"][2]["source_candidates"] == alternatives


class Machine:
    def __init__(self):
        self.calls = []

    def analyze(self, form, visitor, fetch=False):
        self.calls.append((form, visitor, fetch))
        return {"status": "ok" if fetch else "cache_miss", "receipt": {"id": form} if fetch else None,
                "machine_candidates": [{"id": form + ":1"}, {"id": form + ":2"}] if fetch else []}


def test_machine_default_is_cache_only_and_explicit_fetch_is_bounded():
    machine = Machine()
    service, passage, _ = setup("α β γ δ α", machine=machine)
    result = service.analyze(request(passage), visitor_id="synthetic")
    assert all(not call[2] for call in machine.calls)
    assert result["limits"]["machine_fetches"] == 0
    machine.calls.clear()
    result = service.analyze(request(passage, fetch_machine=True), visitor_id="synthetic")
    assert len([call for call in machine.calls if call[2]]) == 3
    assert result["tokens"][0]["machine"]["receipt"] == {"id": "α"}
    assert len(result["tokens"][0]["machine"]["machine_candidates"]) == 2
    assert result["tokens"][6]["machine"]["status"] == "request_limit"
    assert result["tokens"][8]["machine"] == result["tokens"][0]["machine"]


def test_provider_failures_leave_source_candidates_available():
    class Broken:
        def analyze(self, *args, **kwargs):
            raise RuntimeError("synthetic failure")
    service, passage, _ = setup("α", machine=Broken(), parser=Broken(), ranker=Broken().analyze)
    result = service.analyze(request(passage, rerank=True))
    assert result["tokens"][0]["source_candidates"]
    assert result["tokens"][0]["machine"]["status"] == "unavailable"
    assert result["syntax"]["status"] == "unavailable"
    assert result["ranking"]["status"] == "unavailable"


def test_parser_offsets_verified_and_absolutized():
    class Parser:
        def analyze(self, text):
            return {"state": "ready", "tokens": [{"id": index, "text": token["text"], "start": token["start"], "end": token["end"], "head": None}
                    for index, token in enumerate(tokenize_span(text, 0, len(text))) if token["kind"] == "word"]}
    service, passage, _ = setup("😀 α β", parser=Parser())
    result = service.analyze(request(passage, 4, 5))
    token = result["syntax"]["tokens"][-1]
    assert (token["start"], token["absolute_start"], token["start_utf16"]) == (4, 4, 5)
    assert token["selected"] is True
    assert result["syntax"]["tokens"][0]["selected"] is False
    assert result["syntax"]["scope"] == "whole_passage"
    class Invalid:
        def analyze(self, text):
            return {"state": "ready", "tokens": [{"id": 0, "text": "changed", "start": 0, "end": 1}]}
    service.syntax_provider = Invalid()
    assert service.analyze(request(passage))["syntax"]["status"] == "unavailable"


def test_lint_is_conditional_and_only_checks_predicted_relations():
    syntax = {"state": "ready", "tokens": [
        {"id": 0, "head": 1, "deprel": "amod", "features": {"Case": "Nom", "Number": "Sing"}},
        {"id": 1, "head": None, "deprel": "root", "features": {"Case": "Acc", "Number": "Sing"}}]}
    result = lint_syntax(syntax, editorial=True)
    assert {row["code"] for row in result["warnings"]} == {"predicted_agreement_conflict", "editorial_uncertainty"}
    assert all(row["severity"] == "uncertain" for row in result["warnings"])
    syntax["tokens"][0]["deprel"] = "conj"
    assert not lint_syntax(syntax)["warnings"]


def test_translations_remain_whole_passage_and_commentary_requires_real_link():
    service, passage, _ = setup()
    passage["translation_previews"] = [{"record_id": "synthetic:translation", "scope": "whole_source_passage", "text": "Synthetic fixture"}]
    passage["related"] = [{"id": "synthetic:comment", "kind": "commentary", "parent_id": passage["id"], "text": "Synthetic fixture"},
                          {"id": "synthetic:unlinked", "kind": "commentary", "text": "Unlinked fixture"}]
    result = service.analyze(request(passage, 0, 5))
    context = result["context"]
    assert context["published_translations"][0]["scope"] == "whole_source_passage"
    assert context["published_translations"][0]["selection_aligned"] is False
    assert [row["id"] for row in context["commentary"]] == ["synthetic:comment"]


def test_rerank_receives_corpus_offsets_but_cannot_mutate_raw_candidates():
    seen = []
    def ranker(result, *, visitor_id):
        seen.append((deepcopy(result), visitor_id))
        result["tokens"][0]["source_candidates"].clear()
        return {"status": "ok", "evidence_type": "model_estimate"}
    service, passage, _ = setup("α", ranker=ranker)
    result = service.analyze(request(passage, rerank=True), visitor_id="synthetic-machine", ranker_visitor_id="synthetic-ranker")
    assert seen[0][0]["passage"]["id"] == passage["id"]
    assert seen[0][0]["selection"]["start"] == 0
    assert seen[0][1] == "synthetic-ranker"
    assert result["tokens"][0]["source_candidates"]
    assert result["ranking"]["status"] == "ok"


def test_http_post_status_stale_and_forbidden_override():
    _, passage, _ = setup()
    app = FastAPI()
    app.include_router(create_router(lambda identifier: passage, lambda form, identifier: {}))
    client = TestClient(app)
    payload = request(passage)
    assert client.post("/api/analyze-passage", json=payload).status_code == 200
    assert client.get("/api/analyze-passage", params=payload).status_code == 405
    assert client.get("/api/passage-analysis/status").status_code == 200
    assert client.post("/api/passage-analysis", json=payload).status_code == 200
    assert client.post("/api/analyze-passage", json={**payload, "selected_text": "stale"}).status_code == 409
    assert client.post("/api/analyze-passage", json={**payload, "author": "spoof"}).status_code == 422
    assert client.post("/api/analyze-passage", json={**payload, "start": True}).status_code == 422
    assert client.post("/api/analyze-passage", json={**payload, "rerank": True}).status_code == 403


def test_same_form_source_annotation_is_not_promoted_to_other_occurrence():
    source = {"structured_evidence": {"ready": True, "claims": [
        {"id": "synthetic:span", "subject": {"passage_id": "synthetic:test", "start": 0, "end": 1}},
        {"id": "synthetic:passage", "subject": {"passage_id": "synthetic:test"}}]}}
    service, passage, _ = setup("α α", word=source)
    result = service.analyze(request(passage))
    first, second = result["tokens"][0], result["tokens"][2]
    assert first["claim_applications"]["synthetic:span"]["scope"] == "exact_token_span"
    assert second["claim_applications"]["synthetic:span"]["scope"] == "other_passage_span"
    assert second["claim_applications"]["synthetic:passage"]["scope"] == "whole_passage_not_token_aligned"


def test_large_passage_parses_only_selection_and_warns_about_lost_context():
    class Parser:
        def analyze(self, text):
            assert text == "β"
            return {"state": "ready", "tokens": [{"id": 0, "text": text, "start": 0, "end": 1, "head": None}]}
    text = "α " * 81 + "β"
    service, passage, _ = setup(text, parser=Parser())
    result = service.analyze(request(passage, len(text) - 1, len(text)))
    assert result["syntax"]["scope"] == "selected_span"
    assert result["syntax"]["warnings"]
    assert result["syntax"]["tokens"][0]["absolute_start"] == len(text) - 1
