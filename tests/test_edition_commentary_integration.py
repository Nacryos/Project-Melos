"""Synthetic sense choices with exact audited Campbell passage identity."""

from copy import deepcopy
import hashlib
import json
import re

import pytest

from backend.interlinear import interlinear_reading
from backend.edition_commentary import for_passage
from backend.sense_ranker import PassageSenseRanker, sense_packet
from scripts.build_edition_commentary import GREEK


def _fixture(fragment="34a"):
    passage = next(row for row in map(json.loads, GREEK.read_text(encoding="utf-8").splitlines())
                   if row["id"] == f"campbell-glp:alcaeus:{fragment}")
    match = re.search(r"[\u0370-\u03ff\u1f00-\u1fff]+", passage["text"])
    assert match
    form = match.group()
    senses = [{"id": f"synthetic-sense-{i}", "entry_id": "synthetic-entry",
               "text": f"synthetic meaning {i}", "source": "synthetic test dictionary",
               "source_url": "https://example.org/synthetic-test", "language": "en",
               "evidence_type": "dictionary_sense", "source_locator": {"sense": i},
               "raw_sha256": "a" * 64, "scope_text": f"synthetic meaning {i}",
               "qualifiers": []} for i in (1, 2)]
    result = {"passage": {"id": passage["id"], "text_sha256": hashlib.sha256(passage["text"].encode()).hexdigest()},
              "selection": {"text": form, "start": match.start(), "end": match.end()},
              "tokens": [{"id": "synthetic-token", "kind": "word", "text": form,
                          "start": match.start(), "end": match.end(),
                          "source_candidates": [{"id": "synthetic-parse", "lemma": form,
                                                 "matched_form": form, "features": {"case": "nominative"}}],
                          "lexicon_entries": [{"id": "synthetic-entry", "lemma": form,
                                               "source": "synthetic test dictionary",
                                               "dictionary_senses": senses}]}],
              "syntax": {"state": "unavailable"}, "ranking": {"items": []}}
    result["interlinear"] = interlinear_reading(result)
    token = result["interlinear"]["readings"][0]["tokens"][0]
    return passage, result, token


def test_real_campbell_source_binds_private_whole_poem_packet_not_sense_proof():
    passage, result, token = _fixture()
    packet = sense_packet(passage, result, token)
    commentary = packet["published_commentary_context"]
    assert commentary["schema"] == "campbell-whole-poem-compact-v1"
    assert commentary["commentary_id"] == passage["id"] + ":commentary"
    assert commentary["scope"] == "whole_poem_commentary"
    assert commentary["selection_aligned"] is False
    assert commentary["word_attestation"] is False
    assert commentary["line_attestation"] is False
    assert len(commentary["paragraphs"]) == 14
    assert commentary["uncertain_ocr_paragraphs_omitted"] == 1
    rows = [dict(zip(commentary["paragraph_fields"], row)) for row in commentary["paragraphs"]]
    source = for_passage(passage, for_model=True)
    assert [row["text"] for row in rows] == [row["text"] for row in source["paragraphs"]]
    assert [row["printed_page"] for row in rows] == [row["printed_page"] for row in source["paragraphs"]]
    assert [row["lemma"] for row in rows] == [row["lemma"] for row in source["paragraphs"]]
    assert [commentary["anchor_methods"][row["anchor_method_ref"]] for row in rows] == [row["anchor_method"] for row in source["paragraphs"]]
    assert all("\ufffd" not in row["text"] for row in rows)
    assert [row["id"] for row in packet["candidates"]] == ["synthetic-sense-1", "synthetic-sense-2"]
    assert packet["published_translation_context"] == []
    assert "source_claims" not in packet
    assert packet["commentary_context_sha256"] == hashlib.sha256(json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_all_five_passages_have_exact_separate_commentary_contexts():
    for fragment in ("34a", "129", "130b", "326", "350"):
        passage, result, token = _fixture(fragment)
        packet = sense_packet(passage, result, token)
        assert packet["published_commentary_context"]["commentary_id"] == passage["id"] + ":commentary"
        assert len(packet["published_commentary_context"]["paragraphs"]) in (14, 33, 20, 11, 9)
        assert packet["published_commentary_context"]["schema"] == "campbell-whole-poem-compact-v1"


def test_unavailable_commentary_blocks_provider_without_changing_senses(monkeypatch):
    from backend import sense_ranker
    passage, result, token = _fixture()
    before = deepcopy(token["candidate_meanings"])
    monkeypatch.setattr(sense_ranker, "edition_commentary_for_passage",
                        lambda *_args, **_kwargs: {"status": "unavailable", "paragraphs": []})
    calls = []
    ranking = PassageSenseRanker(lambda _: passage,
                                 lambda _: calls.append("provider") or None)(result)
    assert ranking["attempted_occurrences"] == 0
    assert not calls
    assert "commentary" in ranking["items"][0]["reason"]
    assert token["candidate_meanings"] == before


def test_oversized_commentary_rejects_packet_without_trimming(monkeypatch):
    from backend import sense_ranker
    passage, result, token = _fixture()
    commentary = for_passage(passage, for_model=True)
    commentary["paragraphs"][0]["text"] += "x" * (sense_ranker.MAX_SENSE_STATE_CHARS + 1)  # synthetic test-only packet expansion
    monkeypatch.setattr(sense_ranker, "edition_commentary_for_passage",
                        lambda *_args, **_kwargs: commentary)
    with pytest.raises(ValueError, match="exceeds safe bounds"):
        sense_packet(passage, result, token)
    providers = []
    ranking = PassageSenseRanker(lambda _: passage, lambda _: providers.append("called") or None)(result)
    assert ranking["attempted_occurrences"] == 0 and providers == []
    assert "safe packet bound" in ranking["items"][0]["reason"]


def test_saved_alcaeus_stasin_packet_remains_within_bound_without_dropping_notes():
    from backend.sense_ranker import MAX_SENSE_STATE_CHARS
    baselines = [GREEK.parents[1] / "lyric-context-eval" / folder / "0.response.json"
                 for folder in ("baseline", "canary-326", "canary-b-326")]
    if not all(path.exists() for path in baselines):
        pytest.skip("Source-bound offline packet fixture not installed")
    passage, _, _ = _fixture("326")
    for saved, expected_choices in zip(baselines, (21, 23, 23)):
        result = json.loads(saved.read_text(encoding="utf-8"))
        result["interlinear"] = interlinear_reading(result)
        token = next(row for row in result["interlinear"]["readings"][0]["tokens"] if row["kind"] == "word")
        packet = sense_packet(passage, result, token)
        rows = [dict(zip(packet["published_commentary_context"]["paragraph_fields"], row))
                for row in packet["published_commentary_context"]["paragraphs"]]
        assert len(packet["candidates"]) == expected_choices
        assert [row["text"] for row in rows] == [row["text"] for row in for_passage(passage, for_model=True)["paragraphs"]]
        assert len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))) <= MAX_SENSE_STATE_CHARS


def test_common_candidate_fields_are_lossless_against_unenriched_packet(monkeypatch):
    from backend import sense_ranker
    passage, result, token = _fixture("326")
    enriched = sense_packet(passage, result, token)
    monkeypatch.setattr(sense_ranker, "edition_commentary_for_passage", lambda *_args, **_kwargs: None)
    baseline = sense_packet(passage, result, token)
    common = enriched["candidate_common_fields"]
    assert common
    assert [{**row, **common} for row in enriched["candidates"]] == baseline["candidates"]
    assert enriched["inventory_sha256"] == baseline["inventory_sha256"]
    assert enriched["published_translation_context"] == baseline["published_translation_context"]
    assert enriched["predicted_syntax_context"] == baseline["predicted_syntax_context"]


def test_newest_packet_reaches_real_prompt_builder_with_all_choices_and_distinct_cache_key(monkeypatch, tmp_path):
    from backend import classifier, sense_ranker
    from backend.jev_gateway import CachedJevProvider
    saved = GREEK.parents[1] / "lyric-context-eval/canary-326/0.response.json"
    if not saved.exists():
        pytest.skip("Source-bound offline packet fixture not installed")
    passage, _, _ = _fixture("326")
    result = json.loads(saved.read_text(encoding="utf-8"))
    result["interlinear"] = interlinear_reading(result)
    token = next(row for row in result["interlinear"]["readings"][0]["tokens"] if row["kind"] == "word")
    enriched = sense_packet(passage, result, token)
    monkeypatch.setattr(sense_ranker, "edition_commentary_for_passage", lambda *_args, **_kwargs: None)
    baseline = sense_packet(passage, result, token)
    gateway = CachedJevProvider(classifier.JevProvider(api_key="synthetic-test-key"), "a" * 64,
                                state_path=tmp_path / "cache.sqlite")
    assert gateway._key(enriched) != gateway._key(baseline)
    captured = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self):
            return json.dumps({"model": "synthetic-model", "answers": {
                "contextual_parse": {"type": "choice", "choice": "abstain"}}}).encode()

    def fake_urlopen(request, **_kwargs):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(classifier, "urlopen", fake_urlopen)
    classifier.JevProvider(api_key="synthetic-test-key").decide(enriched)
    assert len(captured) == 1
    body = captured[0]
    assert body["state"]["candidate_common_fields"] == enriched["candidate_common_fields"]
    assert body["state"]["source_contexts"][enriched["candidate_common_fields"]["source_context_ref"]]
    choices = body["questions"]["contextual_parse"]["criteria"]
    assert len(choices) == 24  # Every one of 23 source senses plus abstain.
    assert {row["id"] for row in enriched["candidates"]} == set(choices) - {"abstain"}
    assert all(choices[row["id"]]["text"] == row["text"] for row in enriched["candidates"])
