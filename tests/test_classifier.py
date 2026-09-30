"""Synthetic evaluation fixtures: no rows here are corpus evidence."""

import io
import json
from copy import deepcopy
from unittest.mock import patch

from backend.classifier import (JevProvider, build_evidence_packet, classify_context,
                                configured_provider, provider_status,
                                MAX_CANDIDATES, MAX_STATE_CHARS)


PASSAGE = {"id": "fixture:1", "text": "α β", "language": "grc", "kind": "text",
           "author": "Fixture poet", "source_url": "https://example.test/passage"}
CANDIDATES = [
    {"id": "parse_a", "lemma": "α", "analysis": "parse A", "matched_form": "α",
     "source_url": "https://example.test/lexicon/a", "claim_ids": ["claim:a"]},
    {"id": "parse_b", "lemma": "β", "analysis": "parse B", "matched_form": "β",
     "source_url": "https://example.test/lexicon/b", "claim_ids": ["claim:b"]},
]


def claim(identifier, object_value):
    return {"id": identifier, "subject": {"type": "form", "form": "α"},
            "predicate": "morphology", "object": object_value,
            "evidence": [{"source_url": f"https://example.test/{identifier}",
                          "quote": f"source quote for {identifier}",
                          "record_id": identifier}],
            "assertion_type": "quoted_source", "status": "source_claim",
            "source_family": "fixture source"}


class StubProvider:
    def __init__(self, choice):
        self.choice = choice
        self.called = False

    def decide(self, packet):
        self.called = True
        return {"choice": self.choice, "model": "fixture-provider-v1"}


def test_packet_retains_conflicting_claims_and_does_not_promote_model_inference():
    rows = [claim("claim:a", {"parse": "A"}), claim("claim:b", {"parse": "B"})]
    inference = claim("model:guess", {"parse": "C"})
    inference["assertion_type"] = "model_inference"
    inference["status"] = "machine_proposed"
    packet = build_evidence_packet("α", PASSAGE, CANDIDATES, rows + [inference],
                                   author_profile=[claim("author:profile", {"dialects": ["mixed"]})])
    assert {r["id"] for r in packet["claims"]} == {"claim:a", "claim:b"}
    assert packet["claims"][0]["object"] == {"parse": "A"}
    assert packet["claims"][1]["object"] == {"parse": "B"}
    assert packet["author_profile"][0]["id"] == "author:profile"
    assert "model:guess" not in json.dumps(packet)
    assert packet["passage"]["text"] == "α β"


def test_packet_preserves_feature_fields_without_author_dialect_shortcut():
    candidate = {**CANDIDATES[0], "features": {"mood": "indicative"},
                 "analysis_text": "verb, indicative", "dialect": ["unresolved"],
                 "matched_form_variants": ["α"]}
    packet = build_evidence_packet("α", PASSAGE, [candidate])
    assert packet["candidates"][0]["features"] == {"mood": "indicative"}
    assert packet["candidates"][0]["dialect"] == ["unresolved"]
    assert packet["author_profile"] == []
    assert "nearby spelling" in " ".join(packet["constraints"])


def test_model_can_only_propose_existing_sourced_candidate():
    provider = StubProvider("parse_b")
    result = classify_context("α", PASSAGE, CANDIDATES,
                              [claim("claim:a", "A"), claim("claim:b", "B")],
                              provider=provider)
    assert provider.called
    assert result["status"] == "proposed"
    assert result["candidate_id"] == "parse_b"
    assert result["model"] == "fixture-provider-v1"
    assert "claim:b" in result["evidence_ids"]
    assert "claim:a" not in result["evidence_ids"]
    assert result["packet"]["claims"][0]["id"] == "claim:a"


def test_accepted_claim_candidate_keeps_its_source_scope():
    candidate = {"id": "claim_candidate", "lemma": "α", "analysis": {"raw": "fixture"},
                 "matched_form": "α", "strength": "general_form_claim",
                 "match_reason": "form-level, not passage attestation",
                 "source_family": "fixture edition", "claim_ids": ["claim:a"],
                 "evidence_refs": ["record:a"]}
    result = classify_context("α", PASSAGE, [candidate], [claim("claim:a", "A")],
                              provider=StubProvider("claim_candidate"))
    assert result["status"] == "proposed"
    assert result["evidence_ids"] == ["claim:a", "record:a"]
    assert result["packet"]["candidates"][0]["strength"] == "general_form_claim"


def test_shared_source_with_distinct_senses_still_invokes_contextual_provider():
    alternatives = [
        {"id": "sense_a", "lemma": "α", "gloss": "sense A",
         "features": {"case": "nominative"}, "claim_ids": ["claim:a"]},
        {"id": "sense_b", "lemma": "α", "gloss": "sense B",
         "features": {"case": "accusative"}, "claim_ids": ["claim:a"]},
    ]
    provider = StubProvider("sense_a")
    result = classify_context("α", PASSAGE, alternatives, [claim("claim:a", "two readings")],
                              provider=provider)
    assert provider.called
    assert result["status"] == "proposed"
    assert result["candidate_id"] == "sense_a"
    uncertain = classify_context("α", PASSAGE, alternatives,
                                 [claim("claim:a", "two readings")],
                                 provider=StubProvider("abstain"))
    assert uncertain["status"] == "abstained"


def test_abstention_on_invalid_choice_unproven_candidate_and_non_greek_context():
    invalid = classify_context("α", PASSAGE, CANDIDATES, provider=StubProvider("invented"))
    assert invalid["status"] == "abstained"
    assert invalid["candidate_id"] is None
    weak = StubProvider("parse_a")
    bare = classify_context("α", PASSAGE, [{"id": "parse_a", "lemma": "α"}], provider=weak)
    assert bare["status"] == "abstained"
    assert not weak.called
    english = classify_context("α", {**PASSAGE, "language": "eng"}, CANDIDATES,
                               provider=StubProvider("parse_a"))
    assert english["status"] == "abstained"
    missing = StubProvider("parse_a")
    absent = classify_context("γ", PASSAGE, CANDIDATES, provider=missing)
    assert absent["status"] == "abstained"
    assert "does not occur" in absent["reason"]
    assert not missing.called


def test_model_abstain_and_unconfigured_provider_are_explicit():
    class UncertainProvider:
        def decide(self, packet):
            return {"choice": "abstain", "model": "fixture-provider-v1",
                    "model_probabilities": {"parse_a": 0.2, "parse_b": 0.1,
                                            "abstain": 0.7},
                    "model_confidence": 0.41,
                    "usage": {"input_tokens": 123, "output_tokens": 4}}

    abstained = classify_context("α", PASSAGE, CANDIDATES, provider=UncertainProvider())
    assert abstained["status"] == "abstained"
    assert abstained["model_probabilities_uncalibrated"]["abstain"] == 0.7
    assert abstained["model_confidence_uncalibrated"] == 0.41
    assert abstained["usage"]["input_tokens"] == 123
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "", "JEV_API_KEY": ""}):
        absent = classify_context("α", PASSAGE, CANDIDATES, provider=JevProvider(api_key=""))
    assert absent["status"] == "abstained"
    assert "not configured" in absent["reason"]


def test_jev_adapter_sends_official_systemone_choice_schema():
    packet = build_evidence_packet("α", PASSAGE, CANDIDATES, [claim("claim:a", "A")])
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(json.dumps({"model": "jev-version-fixture", "answers": {
            "contextual_parse": {"type": "choice", "choice": "parse_a",
                                 "confidence": 0.72,
                                 "probabilities": {"parse_a": 0.72, "parse_b": 0.18,
                                                   "abstain": 0.10}}},
            "usage": {"input_tokens": 100, "output_tokens": 3}}).encode())

    with patch("backend.classifier.urlopen", fake_urlopen):
        answer = JevProvider(api_key="fixture-secret", timeout=2).decide(packet)
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["headers"]["Authorization"] == "Bearer fixture-secret"
    assert captured["body"]["state"]["passage"]["text"] == "α β"
    criteria = captured["body"]["questions"]["contextual_parse"]["criteria"]
    assert set(criteria) == {"parse_a", "parse_b", "abstain"}
    assert criteria['parse_a']['candidate_id'] == 'parse_a'
    assert criteria['parse_a']['analysis'] == 'parse A'
    assert criteria['parse_b']['analysis'] == 'parse B'
    assert criteria['parse_a'] != criteria['parse_b']
    assert isinstance(criteria['abstain'], str)
    assert captured['body']['state']['candidates'] == packet['candidates']
    assert answer["choice"] == "parse_a"
    assert answer["model"] == "jev-version-fixture"
    assert "fixture-secret" not in str(answer)
    assert answer["raw_response"]["usage"]["input_tokens"] == 100


def test_oversized_candidate_set_abstains_without_call():
    provider = StubProvider("parse_a")
    result = classify_context("α", PASSAGE,
                              CANDIDATES * (MAX_CANDIDATES // len(CANDIDATES) + 1),
                              provider=provider)
    assert result["status"] == "abstained"
    assert not provider.called
    assert result['decision_stage'] == 'preflight'


def test_expanded_candidate_bound_preserves_all_options_and_refuses_overflow():
    candidates = [{**CANDIDATES[0], 'id': f'parse_{i}'}
                  for i in range(MAX_CANDIDATES + 1)]
    provider = StubProvider('parse_16')
    within = classify_context('α', PASSAGE, candidates[:17], provider=provider)
    assert provider.called
    assert within['status'] == 'proposed'
    assert len(within['packet']['candidates']) == 17
    overflow_provider = StubProvider('parse_0')
    overflow = classify_context('α', PASSAGE, candidates, provider=overflow_provider)
    assert not overflow_provider.called
    assert overflow['status'] == 'abstained'
    assert len(overflow['packet']['candidates']) == MAX_CANDIDATES + 1
    assert 'safe bounds' in overflow['reason']


def test_fuzzy_choice_is_not_a_contextual_parse():
    provider = StubProvider("parse_a")
    result = classify_context("α", PASSAGE, [{**CANDIDATES[0], "edit_distance": 1}],
                              provider=provider)
    assert result["status"] == "abstained"
    assert "spelling suggestion" in result["reason"]
    assert not provider.called
    assert result['decision_stage'] == 'preflight'


def test_shared_provenance_compacts_without_merging_hypotheses_or_evidence_ids():
    sources = [{'source_url': 'https://example.test/source/' + str(i) + '/' + 'x' * 200}
               for i in range(6)]
    candidates = [{**CANDIDATES[0], 'id': f'parse_{i}', 'supporting_sources': sources,
                   'features': {'case': str(i), 'unresolved': None},
                   'gloss': '', 'edit_distance': 0}
                  for i in range(5)]
    original = deepcopy(candidates)
    rows = [claim('claim:a', {'alternatives': ['A', 'B'], 'uncertain': None})]
    packet = build_evidence_packet('α', PASSAGE, candidates, rows)
    assert candidates == original
    assert len(packet['candidates']) == len(candidates)
    assert packet['claims'][0]['object'] == rows[0]['object']
    assert packet['claims'][0]['evidence'] == rows[0]['evidence']
    assert packet['passage']['text'] == PASSAGE['text']
    assert 'source_catalog' in packet
    for index, candidate in enumerate(packet['candidates']):
        assert candidate['id'] == candidates[index]['id']
        assert candidate['features'] == candidates[index]['features']
        assert candidate['gloss'] == ''
        assert candidate['edit_distance'] == 0
        assert 'dialect' not in candidate  # Absent, not supplied with a value.
        expanded = [{**packet['source_catalog'][ref['source_ref']], 'id': ref['id']}
                    for ref in candidate['source_references']]
        assert expanded[0]['id'] == f'parse_{index}:source_url'
        assert expanded[0]['url'] == candidates[index]['source_url']
        assert [ref['url'] for ref in expanded[1:]] == [s['source_url'] for s in sources]
        assert all(ref['scope'] == 'candidate metadata; verify source scope' for ref in expanded)


def test_repeated_provenance_no_longer_blocks_otherwise_small_exact_candidates():
    sources = [{'source_url': 'https://example.test/' + str(i) + '/' + 'x' * 350}
               for i in range(8)]
    candidates = [{**CANDIDATES[0], 'id': f'parse_{i}', 'supporting_sources': sources}
                  for i in range(8)]
    provider = StubProvider('parse_3')
    result = classify_context('α', PASSAGE, candidates, provider=provider)
    assert provider.called
    assert result['status'] == 'proposed'
    assert 'parse_3:source_url' in result['evidence_ids']
    assert len(result['packet']['candidates']) == 8
    assert len(result['packet']['source_catalog']) == 9
    assert len(json.dumps(result['packet'], ensure_ascii=False)) < 16000


def test_fuzzy_only_oversized_packet_reports_missing_parses_without_provider_call():
    candidate = {**CANDIDATES[0], 'edit_distance': 1, 'gloss': 'x' * (MAX_STATE_CHARS + 1)}
    provider = StubProvider('parse_a')
    result = classify_context('α', PASSAGE, [candidate], provider=provider)
    assert not provider.called
    assert 'Only nearby-spelling suggestions' in result['reason']
    assert result['packet']['candidates'][0]['gloss'] == candidate['gloss']


def test_genuine_oversize_is_refused_without_truncating_passage_or_quoted_claims():
    rows = [claim('claim:a', 'A')]
    rows[0]['evidence'][0]['quote'] = 'x' * (MAX_STATE_CHARS + 1)
    provider = StubProvider('parse_a')
    result = classify_context('α', PASSAGE, CANDIDATES, rows, provider=provider)
    assert not provider.called
    assert f'exceeds {MAX_STATE_CHARS}' in result['reason']
    assert result['packet']['claims'][0]['evidence'][0]['quote'] == 'x' * (MAX_STATE_CHARS + 1)
    assert result['packet']['passage']['text'] == PASSAGE['text']


def test_mixed_fuzzy_and_exact_hypotheses_are_not_silently_removed():
    candidates = [{**CANDIDATES[0], 'edit_distance': 1}, CANDIDATES[1]]
    provider = StubProvider('parse_b')
    result = classify_context('α', PASSAGE, candidates, provider=provider)
    assert provider.called
    assert result['status'] == 'proposed'
    assert [c['id'] for c in result['packet']['candidates']] == ['parse_a', 'parse_b']


def test_parallel_context_is_preserved_as_comparison_not_target_attestation():
    comparison = {'target_excerpt': 'α β', 'source_excerpt': 'α β',
                  'method': 'fixture exact context comparison'}
    candidate = {**CANDIDATES[0], 'comparison_scope': 'parallel_context',
                 'source_passage_id': 'fixture:other-edition',
                 'comparison_context': comparison}
    rows = [claim('claim:a', 'A')]
    rows[0]['subject'] = {'passage_id': 'fixture:other-edition', 'form': 'α'}
    packet = build_evidence_packet('α', PASSAGE, [candidate], rows)
    assert packet['candidates'][0]['comparison_context'] == comparison
    assert packet['candidates'][0]['source_passage_id'] == 'fixture:other-edition'
    assert packet['claims'][0]['subject'] == rows[0]['subject']
    assert 'not proof of edition identity' in ' '.join(packet['constraints'])


def test_relation_candidates_keep_semantics_in_packet_and_choice_descriptions():
    morphology = {**CANDIDATES[0], 'features': {'mood': 'infinitive'}}
    equivalent = {**CANDIDATES[1], 'analysis': None, 'lemma': None,
                  'equivalent_form': 'fixture-equivalent', 'relation_raw': '=',
                  'lemma_targets': [{'word': 'fixture-headword', 'extra': 'source note'}],
                  'source_tags': ['alternative-A', 'alternative-B'],
                  'source_raw_tags': ['raw ambiguous source label'],
                  'strength': 'parallel_matching_text',
                  'comparison_scope': 'Comparison only; not direct target attestation',
                  'source_passage_id': 'fixture:other'}
    packet = build_evidence_packet('α', PASSAGE, [morphology, equivalent])
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_): self.close()

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response(json.dumps({'model': 'fixture-model', 'answers': {
            'contextual_parse': {'type': 'choice', 'choice': 'abstain'}}}).encode())

    with patch('backend.classifier.urlopen', fake_urlopen):
        JevProvider(api_key='fixture-only').decide(packet)
    criteria = captured['questions']['contextual_parse']['criteria']
    for key in ('equivalent_form', 'relation_raw', 'lemma_targets', 'source_tags',
                'source_raw_tags', 'strength', 'comparison_scope', 'source_passage_id'):
        assert packet['candidates'][1][key] == equivalent[key]
        assert criteria['parse_b'][key] == equivalent[key]
    assert criteria['parse_a']['features'] == morphology['features']
    assert 'lemma' not in criteria['parse_b']  # No invented completion.
    assert 'analysis' not in criteria['parse_b']
    assert set(criteria) == {'parse_a', 'parse_b', 'abstain'}
    assert 'source_references' not in criteria['parse_b']  # Full provenance stays in state.


def test_provider_status_never_returns_key():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret"}):
        status = provider_status()
    assert status["configured"] is True
    assert "fixture-secret" not in str(status)


def test_installed_local_model_requires_validation_and_explicit_opt_in():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "", "JEV_API_KEY": "",
                                   "MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER": "1"}):
        with patch("backend.local_classifier.local_model_status",
                   return_value={"installed": True, "validated": False,
                                 "model": "fixture-local"}):
            assert configured_provider() is None
            status = provider_status()
    assert status["configured"] is False
    assert status["installed"] is True
    assert "disabled" in status["reason"]
