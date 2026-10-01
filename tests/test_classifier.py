"""Synthetic evaluation fixtures: no rows here are corpus evidence."""

import io
import json
import unicodedata
from copy import deepcopy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.classifier import (JevProvider, build_evidence_packet, classify_context,
                                configured_provider, provider_status,
                                MAX_CANDIDATES, MAX_STATE_CHARS)
from backend.jev_gateway import CachedJevProvider, GatewayUnavailable


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


def test_lexical_metadata_cannot_be_a_jev_parse_choice_even_if_stale_projection_arrives():
    canonical = {"id": "wiktionary:kaikki:line:1:morphology:entry#form:0",
                 "lemma": "inflected", "analysis": ["canonical"],
                 "source_family": "enwiktionary-kaikki-synthetic-fixture",
                 "matched_object_form": {"form": "inflected", "tags": ["canonical"]},
                 "claim_ids": ["fixture:canonical"]}
    headword = {"id": "wiktionary:kaikki:line:1:lemma:entry",
                "lemma": "inflected", "analysis": None,
                "source_family": "enwiktionary-kaikki-synthetic-fixture",
                "claim_ids": ["wiktionary:kaikki:line:1:lemma:entry"]}
    typed_metadata = {**CANDIDATES[0], "id": "typed:metadata",
                      "candidate_kind": "lexical_metadata"}
    spoofed_grammar = {**canonical, "id": "typed:canonical",
                       "candidate_kind": "grammatical_analysis"}
    provider = StubProvider(canonical["id"])
    result = classify_context("α", PASSAGE, [canonical, headword, typed_metadata, spoofed_grammar],
                              [claim("fixture:canonical", "source metadata")], provider=provider)
    assert not provider.called
    assert result["status"] == "abstained"
    assert result["packet"]["candidates"] == []
    assert "No existing candidate" in result["reason"]
    assert len([warning for warning in result["warnings"] if "lexical entry metadata" in warning]) == 4


def test_grammar_choice_survives_metadata_filter_and_legacy_candidates_remain_eligible():
    metadata = {"id": "wiktionary:kaikki:line:1:morphology:entry#form:0",
                "lemma": "inflected", "analysis": ["canonical"],
                "source_family": "enwiktionary-kaikki-synthetic-fixture",
                "matched_object_form": {"form": "inflected", "tags": ["canonical"]},
                "claim_ids": ["fixture:canonical"]}
    grammar = {"id": "fixture:form-of", "candidate_kind": "explicit_form_of",
               "lemma": "source-root", "entry_headword": "inflected",
               "analysis": ["dative", "plural"], "relation_raw": "form_of",
               "claim_ids": ["fixture:grammar"]}
    rows = [claim("fixture:canonical", "metadata"), claim("fixture:grammar", "parse")]
    packet = build_evidence_packet("α", PASSAGE, [metadata, grammar, CANDIDATES[0]], rows)
    assert [candidate["id"] for candidate in packet["candidates"]] == ["fixture:form-of", "parse_a"]
    assert packet["candidates"][0]["entry_headword"] == "inflected"
    assert packet["candidates"][0]["candidate_kind"] == "explicit_form_of"
    provider = StubProvider(metadata["id"])
    result = classify_context("α", PASSAGE, [metadata, grammar], rows, provider=provider)
    assert provider.called  # It saw one valid choice, but cannot choose the excluded ID.
    assert result["status"] == "abstained"
    assert result["candidate_id"] is None
    assert "outside the supplied candidate IDs" in result["reason"]


def bridged_kaikki_fixture():
    """Synthetic records shaped like a Kaikki source bridge; not corpus data."""
    family = 'enwiktionary-kaikki-synthetic-fixture'
    query, source_root, entry_root, source_form = 'αβασι', 'αβᾰ', 'ἄλφα', 'αβᾰσι'
    form_of_id = 'wiktionary:kaikki:line:1:form_of:0'
    morphology_id = 'wiktionary:kaikki:line:2:morphology:entry'
    listed_id = f'{morphology_id}#form:1'
    source_row = {'form': source_form, 'tags': ['dative', 'plural'],
                  'source': 'declension', 'links': [[source_form, f'{query}#Ancient_Greek']]}
    relation = {'id': form_of_id, 'candidate_kind': 'explicit_form_of',
                'lemma': source_root, 'matched_form': query, 'analysis': ['dative', 'plural'],
                'relation_raw': 'form_of', 'source_family': family,
                'claim_ids': [form_of_id], 'evidence_refs': ['wiktionary:kaikki:line:1']}
    listed = {'id': listed_id, 'candidate_kind': 'grammatical_analysis',
              'lemma': entry_root, 'entry_headword': entry_root,
              'matched_form': source_form, 'matched_object_form': source_row,
              'analysis': ['dative', 'plural'], 'source_family': family,
              'claim_ids': [morphology_id], 'evidence_refs': ['wiktionary:kaikki:line:2']}
    def source_claim(identifier, subject, predicate, obj, record_id, quote, locator):
        return {'id': identifier, 'subject': {'type': 'form', 'form': subject},
                'predicate': predicate, 'object': obj, 'source_family': family,
                'status': 'source_claim', 'assertion_type': 'extracted_annotation',
                'evidence': [{'record_id': record_id, 'source_url': 'https://example.test/kaikki',
                              'quote': quote, 'locator': locator}]}
    form_of = source_claim(form_of_id, query, 'lemma',
                           {'relation': 'form_of', 'targets': [{'word': source_root}],
                            'source_tags': ['dative', 'form-of', 'plural']},
                           'wiktionary:kaikki:line:1', '[{"word":"αβᾰ"}]',
                           '/entry/senses/0/form_of')
    inflected_entry = source_claim('wiktionary:kaikki:line:1:lemma:entry', query,
                                   'lemma', {'lemma': query, 'pos': 'noun',
                                             'head_templates': [{'name': 'grc-noun form'}]},
                                   'wiktionary:kaikki:line:1', '"αβασι"', '/entry/word')
    morphology = source_claim(morphology_id, entry_root, 'morphology',
                              {'lemma': entry_root, 'pos': 'noun', 'listed_form_count': 2,
                               'inflection_templates': [{'name': 'grc-decl',
                                                         'args': {'1': source_root}}]},
                              'wiktionary:kaikki:line:2',
                              json.dumps({'form': source_root, 'tags': ['canonical', 'neuter']},
                                         ensure_ascii=False), '/entry/forms')
    morphology['matched_object_forms'] = [deepcopy(source_row)]
    morphology['matched_object_form_ordinals'] = [1]
    passage = {'id': 'fixture:source-bridge', 'text': query, 'language': 'grc',
               'kind': 'text', 'author': 'Fixture only'}
    return query, passage, [relation, listed], [form_of, inflected_entry, morphology]


def test_explicit_source_bridge_groups_one_decision_option_but_preserves_raw_proofs():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    original_candidates, original_claims = deepcopy(candidates), deepcopy(claims)
    packet = build_evidence_packet(form, passage, candidates, claims)
    assert candidates == original_candidates and claims == original_claims
    assert len(candidates) == 2 and len(packet['claims']) == 3
    assert [option['id'] for option in packet['candidates']] == [candidates[1]['id']]
    option = packet['candidates'][0]
    assert option['decision_group']['member_candidate_ids'] == [row['id'] for row in candidates]
    assert option['decision_group']['source_lemma_spellings'] == [row['lemma'] for row in candidates]
    assert option['claim_ids'] == [candidates[0]['id'], candidates[1]['claim_ids'][0]]
    assert 'no passage attestation' in option['decision_group']['scope']
    provider = StubProvider(candidates[1]['id'])
    result = classify_context(form, passage, candidates, claims, provider=provider)
    assert provider.called and result['status'] == 'proposed'
    assert result['candidate_id'] == candidates[1]['id']  # Never a fabricated group ID.
    assert set(result['evidence_ids']) >= set(option['claim_ids'])


def test_source_bridge_changes_jev_choice_and_cache_key_without_a_paid_call():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    packet = build_evidence_packet(form, passage, candidates, claims)
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        captured['body'] = json.loads(request.data)
        return Response(json.dumps({'model': 'fixture-jev', 'answers': {
            'contextual_parse': {'type': 'choice', 'choice': candidates[1]['id']}}}).encode())

    with patch('backend.classifier.urlopen', fake_urlopen):
        answer = JevProvider(api_key='fixture-secret').decide(packet)
    criteria = captured['body']['questions']['contextual_parse']['criteria']
    assert set(criteria) == {candidates[1]['id'], 'abstain'}
    assert criteria[candidates[1]['id']]['decision_group']['member_candidate_ids'] == [
        row['id'] for row in candidates]
    assert {row['id'] for row in captured['body']['state']['claims']} == {
        row['id'] for row in claims}
    assert answer['choice'] == candidates[1]['id']
    class CacheProvider:
        model = 'fixture-jev'
        timeout = 8
    cache = CachedJevProvider(CacheProvider(), 'a' * 64)
    assert cache._key(packet) == cache._key(build_evidence_packet(form, passage, candidates, claims))
    assert cache._answer({'choice': candidates[1]['id'], 'model': 'fixture-jev'}, packet)['choice'] == candidates[1]['id']
    with pytest.raises(GatewayUnavailable):
        cache._answer({'choice': candidates[0]['id'], 'model': 'fixture-jev'}, packet)
    ungrouped = deepcopy(candidates)
    ungrouped[1]['matched_object_form']['links'] = []
    assert cache._key(packet) != cache._key(build_evidence_packet(form, passage, ungrouped, claims))


def test_source_bridge_never_merges_on_diacritic_folding_or_weak_proof():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    def ungrouped(mutate):
        options, proofs = deepcopy(candidates), deepcopy(claims)
        mutate(options, proofs)
        packet = build_evidence_packet(form, passage, options, proofs)
        assert [row['id'] for row in packet['candidates']] == [row['id'] for row in options]
        assert all('decision_group' not in row for row in packet['candidates'])
    cases = [
        lambda o, p: o[1]['matched_object_form'].update(links=[]),
        lambda o, p: p[0]['object']['targets'][0].update(word='αβα'),
        lambda o, p: p[0]['object']['targets'].append({'word': 'αβᾰ'}),
        lambda o, p: p[2]['object'].update(pos='verb'),
        lambda o, p: p[1]['object'].update(pos='verb'),
        lambda o, p: o[1].update(analysis=['genitive', 'plural']),
        lambda o, p: p[2].update(assertion_type='model_inference'),
        lambda o, p: p[1].update(status='needs_review'),
        lambda o, p: o[1].update(source_family='different-family'),
        lambda o, p: o[1].update(evidence_refs=[]),
        lambda o, p: p[2].update(matched_object_form_ordinals=[0]),
        lambda o, p: p[2].update(matched_object_forms=[]),
        lambda o, p: o[1]['matched_object_form'].update(links=[]),
        lambda o, p: p[2]['object']['inflection_templates'][0]['args'].update({'1': 'αβα'}),
        lambda o, p: p[2]['evidence'][0].update(quote='{"form":"αβα","tags":["canonical"]}'),
        lambda o, p: p[0]['object'].update(source_raw_tags=['fixture restricted sense']),
        lambda o, p: p[2]['matched_object_forms'][0].update(raw_tags=['fixture row qualifier']),
        lambda o, p: p[1]['subject'].update(passage_id='fixture:other'),
        lambda o, p: p[0]['object']['targets'][0].update(extra='distinct homograph'),
        lambda o, p: p[0]['object']['targets'][0].update(sense='fixture:other'),
    ]
    for mutate in cases:
        ungrouped(mutate)


def test_full_source_form_array_can_verify_same_bridge_without_compacted_quote():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    canonical = {'form': candidates[0]['lemma'], 'tags': ['canonical', 'neuter']}
    claims[2]['object']['forms'] = [canonical, deepcopy(candidates[1]['matched_object_form'])]
    claims[2]['object'].pop('listed_form_count')
    claims[2]['evidence'][0]['quote'] = 'Full object test does not depend on preview quote'
    packet = build_evidence_packet(form, passage, candidates, claims)
    assert len(packet['candidates']) == 1


def test_latin_target_annotation_requires_an_accepted_same_record_sense_link():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    claims[0]['object']['targets'][0]['extra'] = 'abă'
    listed_row = deepcopy(candidates[1]['matched_object_form'])
    claims[2]['object']['forms'] = [
        {'form': candidates[0]['lemma'], 'tags': ['canonical', 'neuter']},
        {'form': 'abă', 'tags': ['romanization']}, listed_row,
    ]
    claims[2]['object'].pop('listed_form_count')
    claims[2]['matched_object_form_ordinals'] = [2]
    candidates[1]['id'] = candidates[1]['id'].replace('#form:1', '#form:2')
    target = deepcopy(claims[0]['object']['targets'])
    sense = deepcopy(claims[1])
    sense['id'] = 'wiktionary:kaikki:line:1:sense:0'
    sense['predicate'] = 'sense_gloss'
    sense['object'] = {'source_sense': {
        'form_of': target, 'links': [[target[0]['word'],
                                     f"{candidates[1]['lemma']}#Ancient_Greek"]],
        'glosses': ['synthetic form relation (abă)'], 'tags': ['dative', 'form-of', 'plural'],
        'raw_tags': [],
    }}
    assert len(build_evidence_packet(form, passage, candidates, [*claims, sense])['candidates']) == 1
    unlabelled = deepcopy(claims)
    unlabelled[2]['object']['forms'][1]['tags'] = ['fixture unknown annotation']
    assert len(build_evidence_packet(form, passage, candidates, [*unlabelled, sense])['candidates']) == 2
    english_qualifier = deepcopy(claims)
    english_qualifier[0]['object']['targets'][0]['extra'] = 'eye'
    english_sense = deepcopy(sense)
    english_sense['object']['source_sense']['form_of'] = deepcopy(english_qualifier[0]['object']['targets'])
    english_sense['object']['source_sense']['glosses'] = ['synthetic form relation (eye)']
    assert len(build_evidence_packet(form, passage, candidates,
                                     [*english_qualifier, english_sense])['candidates']) == 2
    for mutation in (
        lambda row: row.update(assertion_type='model_inference'),
        lambda row: row['object']['source_sense'].update(links=[]),
        lambda row: row['object']['source_sense'].update(raw_tags=['fixture qualifier']),
        lambda row: row['subject'].update(passage_id='fixture:other'),
    ):
        invalid = deepcopy(sense)
        mutation(invalid)
        assert len(build_evidence_packet(form, passage, candidates, [*claims, invalid])['candidates']) == 2


def test_compact_source_claim_reopens_full_accepted_form_array_for_romanization(monkeypatch):
    form, passage, candidates, claims = bridged_kaikki_fixture()
    claims[0]['object']['targets'][0]['extra'] = 'abă'
    target = deepcopy(claims[0]['object']['targets'])
    sense = deepcopy(claims[1])
    sense['id'] = 'wiktionary:kaikki:line:1:sense:0'
    sense['predicate'] = 'sense_gloss'
    sense['object'] = {'source_sense': {'form_of': target,
        'links': [[target[0]['word'], f"{candidates[1]['lemma']}#Ancient_Greek"]],
        'glosses': ['synthetic form relation (abă)'], 'raw_tags': []}}
    full = deepcopy(claims[2])
    full['object']['forms'] = [
        {'form': candidates[0]['lemma'], 'tags': ['canonical', 'neuter']},
        {'form': 'abă', 'tags': ['romanization']},
        deepcopy(candidates[1]['matched_object_form']),
    ]
    full['object'].pop('listed_form_count')
    compact = deepcopy(full)
    compact['object'].pop('forms')
    compact['object']['listed_form_count'] = 3
    compact['matched_object_form_ordinals'] = [2]
    candidates[1]['id'] = candidates[1]['id'].replace('#form:1', '#form:2')
    rows = [*claims[:2], compact, sense]
    with patch('backend.evidence.EvidenceIndex.get_claim', return_value=full):
        packet = build_evidence_packet(form, passage, candidates, rows)
    assert len(packet['candidates']) == 1
    tampered = deepcopy(full)
    tampered['object']['forms'][1]['tags'] = ['unverified']
    with patch('backend.evidence.EvidenceIndex.get_claim', return_value=tampered):
        packet = build_evidence_packet(form, passage, candidates, rows)
    assert len(packet['candidates']) == 2


def test_multiple_form_of_senses_do_not_greedily_group_one_listed_form():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    second_candidate = deepcopy(candidates[0])
    second_candidate['id'] = second_candidate['id'].replace('form_of:0', 'form_of:1')
    second_candidate['claim_ids'] = [second_candidate['id']]
    second_claim = deepcopy(claims[0])
    second_claim['id'] = second_candidate['id']
    for options in ([*candidates, second_candidate],
                    [second_candidate, *candidates],
                    [candidates[1], second_candidate, candidates[0]]):
        packet = build_evidence_packet(form, passage, options, [*claims, second_claim])
        assert [row['id'] for row in packet['candidates']] == [row['id'] for row in options]
        assert all('decision_group' not in row for row in packet['candidates'])


def test_source_bridge_keeps_ambiguous_multiple_listed_options_separate():
    form, passage, candidates, claims = bridged_kaikki_fixture()
    duplicate = deepcopy(candidates[1])
    duplicate['id'] = duplicate['id'].replace('#form:1', '#form:2')
    claims[2]['object']['listed_form_count'] = 3
    claims[2]['matched_object_form_ordinals'].append(2)
    claims[2]['matched_object_forms'].append(deepcopy(duplicate['matched_object_form']))
    options = [*candidates, duplicate]
    packet = build_evidence_packet(form, passage, options, claims)
    assert [row['id'] for row in packet['candidates']] == [row['id'] for row in options]


def test_api_packet_includes_accepted_sibling_form_of_proof_without_passage_promotion(monkeypatch):
    from backend import classifier, server
    from backend import jev_gateway

    listed = claim("fixture:listed", {"forms": [{"form": "αβγ", "tags": ["dative"]}]})
    sibling = claim("fixture:form-of", {"relation": "form_of", "targets": [{"word": "δ"}]})
    sibling["subject"] = {"type": "form", "form": "αβ"}
    sibling["strength"] = "general_entry_relation"
    candidate = {"id": "fixture:listed#form:0", "candidate_kind": "grammatical_analysis",
                 "lemma": "δ", "analysis": ["dative"], "matched_form": "αβγ",
                 "claim_ids": ["fixture:listed", "fixture:form-of"]}
    response = {
        "context": {"id": "fixture:passage", "text": "αβγ", "language": "grc", "kind": "text"},
        "contextual_candidates": [candidate], "contextual_supporting_claims": [sibling],
        "structured_evidence": {"claims": [listed]}, "parallel_contexts": [],
        "author_profile": None,
    }
    provider = StubProvider(candidate["id"])
    monkeypatch.setattr(server, "word", lambda form, passage_id: response)
    monkeypatch.setattr(jev_gateway, "public_enabled", lambda: False)
    monkeypatch.setattr(classifier, "configured_provider", lambda: provider)
    result = TestClient(server.app).post("/api/classify-context", json={
        "form": "αβγ", "passage_id": "fixture:passage",
    }).json()
    assert result["status"] == "proposed"
    assert provider.called
    assert {row["id"] for row in result["packet"]["claims"]} == {"fixture:listed", "fixture:form-of"}
    proof = next(row for row in result["packet"]["claims"] if row["id"] == "fixture:form-of")
    assert proof["subject"] == {"type": "form", "form": "αβ"}
    assert proof["strength"] == "general_entry_relation"
    assert result["packet"]["candidates"][0]["claim_ids"] == ["fixture:listed", "fixture:form-of"]


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


def test_occurrence_guard_accepts_explicit_line_division_without_editing_source():
    original = 'φωνεί-\r\n  σας'
    passage = {**PASSAGE, 'text': original, 'quality': 'source_transcription',
               'edition': {'title': 'Synthetic fixture edition', 'uncertain': True}}
    provider = StubProvider('parse_a')
    result = classify_context('φωνείσας', passage, CANDIDATES, provider=provider)
    assert provider.called
    assert result['packet']['passage']['text'] == original
    assert result['packet']['passage']['quality'] == passage['quality']
    assert result['packet']['passage']['edition'] == passage['edition']
    assert 'not secure letters, restored text' in ' '.join(result['packet']['constraints'])


def test_occurrence_guard_handles_combining_marks_before_tokenization():
    # Purely synthetic spellings to exercise Unicode handling, not attestations.
    for original in ('ἄ\u0323μμι', unicodedata.normalize('NFD', 'ἄ\u0323μμι'),
                     'α\u0323β', 'άβ', 'α\u0301β'):
        query = 'ἄμμι' if 'μ' in original else 'αβ'
        passage = {**PASSAGE, 'text': original}
        provider = StubProvider('parse_a')
        result = classify_context(query, passage, CANDIDATES, provider=provider)
        assert provider.called, (original, result['reason'])
        assert result['packet']['passage']['text'] == original


def test_occurrence_guard_does_not_join_editorial_gaps_or_non_layout_boundaries():
    for original in ('φωνεί- σας', 'φωνεί\nσας', 'φωνεί-\n[σας]',
                     'φωνεί-\n4 σας', 'φωνεί-\n\nσας', 'φωνεί—\nσας',
                     'φωνεί-\n…σας', 'φωνεί[σ]ας', 'φωνεί2σας',
                     'φωνεί[…]σας', 'φωνεί-\n.σας'):
        provider = StubProvider('parse_a')
        result = classify_context('φωνείσας', {**PASSAGE, 'text': original},
                                  CANDIDATES, provider=provider)
        assert not provider.called, original
        assert result['decision_stage'] == 'preflight'
        assert 'does not occur' in result['reason']
        assert result['packet']['passage']['text'] == original


def test_provider_status_never_returns_key():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret"}):
        status = provider_status()
    assert status["configured"] is True
    assert "fixture-secret" not in str(status)


def test_occurrence_guard_keeps_elided_and_unelided_tokens_distinct():
    for mark in "'’᾽ʼ":
        original = 'α\u0323' + mark + ' β'
        provider = StubProvider('parse_a')
        result = classify_context("α'", {**PASSAGE, 'text': original}, CANDIDATES, provider=provider)
        assert provider.called
        assert result['packet']['passage']['text'] == original
        provider = StubProvider('parse_a')
        result = classify_context('α', {**PASSAGE, 'text': original}, CANDIDATES, provider=provider)
        assert not provider.called
        assert 'does not occur' in result['reason']
        provider = StubProvider('parse_a')
        result = classify_context("α'", {**PASSAGE, 'text': 'α β'}, CANDIDATES, provider=provider)
        assert not provider.called
        assert 'does not occur' in result['reason']


def test_occurrence_guard_preserves_spacing_psili_without_equating_it_with_apostrophe():
    for query, found in [('α᾿', True), ('α', False), ("α'", False)]:
        provider = StubProvider('parse_a')
        result = classify_context(query, {**PASSAGE, 'text': 'α᾿ β'}, CANDIDATES, provider=provider)
        assert provider.called == found
        assert result['packet']['passage']['text'] == 'α᾿ β'


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
