"""Synthetic transport checks for the separate source-linked dictionary lane."""

from copy import deepcopy

from fastapi.testclient import TestClient

from backend import linked_dictionary, lexical_variants, server
from backend.passage_analysis import PassageAnalysisService


class _Evidence:
    def candidate_analyses(self, *_args, **_kwargs):
        return {"candidates": [], "supporting_claims": [], "method": "synthetic"}


class _Morphology:
    def analyze(self, form, **_kwargs):
        return {"form": form, "candidates": [{"lemma": "synthetic ordinary alternative"}],
                "warnings": []}


def _word_fixture(monkeypatch, lookup):
    evidence = _Evidence()
    monkeypatch.setattr(server, "morph_service", lambda: _Morphology())
    monkeypatch.setattr(server, "evidence_service", lambda: evidence)
    monkeypatch.setattr(server, "evidence_lookup", lambda *_args, **_kwargs: {"ready": False, "claims": []})
    monkeypatch.setattr(server, "occurrences", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(lexical_variants, "lookup_variants", lambda *_args: {
        "lexical_variants": [], "dictionary_crossreferences": [], "supporting_claims": []})
    monkeypatch.setattr(linked_dictionary, "lookup_linked_dictionary", lookup)
    return evidence


def test_word_keeps_exact_linked_inventory_separate(monkeypatch):
    inventory = {"form": "λόγος", "method": "synthetic-source-link",
                 "scope": "linked_not_exact_attestation", "inventory_sha256": "a" * 64,
                 "candidates": [{"id": "synthetic-linked-path", "lemma": "source-linked lemma"}]}
    seen = []
    evidence = _word_fixture(monkeypatch, lambda form, index: seen.append((form, index)) or deepcopy(inventory))
    result = server.word("λόγος")
    assert seen == [("λόγος", evidence)]
    assert result["linked_dictionary"] == inventory
    assert result["linked_dictionary_status"] == "available"
    assert result["candidates"] == [{"lemma": "synthetic ordinary alternative"}]
    assert result["contextual_candidates"] == []
    assert result["structured_evidence"]["claims"] == []


def test_word_linked_source_failure_is_diagnostic_not_api_failure(monkeypatch):
    def fail(_form, _index):
        raise OSError("synthetic missing source index")

    _word_fixture(monkeypatch, fail)
    result = server.word("λόγος")
    assert result["linked_dictionary"] is None
    assert result["linked_dictionary_status"] == "unavailable"
    assert any("Source-linked dictionary paths are unavailable" in warning for warning in result["warnings"])
    assert result["candidates"] == [{"lemma": "synthetic ordinary alternative"}]
    assert result["contextual_candidates"] == []
    http = TestClient(server.app).get("/api/word", params={"form": "λόγος"})
    assert http.status_code == 200
    assert http.json()["linked_dictionary_status"] == "unavailable"


def test_passage_token_carries_exact_inventory_without_changing_source_alternatives():
    inventory = {"form": "λόγος", "method": "synthetic-source-link", "inventory_sha256": "a" * 64,
                 "candidates": [{"id": "synthetic-linked-path", "lemma": "source-linked lemma"}]}
    source = {"candidates": [{"id": "synthetic-source-candidate", "lemma": "ordinary lemma"}],
              "contextual_candidates": [], "structured_evidence": {"ready": False, "claims": []},
              "linked_dictionary": inventory, "linked_dictionary_status": "available"}
    passage = {"id": "synthetic:poem", "kind": "text", "language": "grc", "text": "λόγος",
               "related": [], "translation_previews": []}
    service = PassageAnalysisService(lambda _id: passage, lambda *_args: source)
    result = service.analyze({"version": 1, "passage_id": passage["id"], "start": 0, "end": 5,
                              "offset_unit": "codepoint", "selected_text": "λόγος"})
    word = next(token for token in result["tokens"] if token["kind"] == "word")
    assert word["linked_dictionary"] == inventory
    assert word["linked_dictionary_status"] == "available"
    assert word["source_candidates"] == source["candidates"]
    assert word["contextual_candidates"] == []
    word["linked_dictionary"]["candidates"].clear()
    assert source["linked_dictionary"] == inventory
