"""Synthetic runtime safety fixtures; these are not philological claims."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from backend.classifier import build_evidence_packet, classify_context


PASSAGE = {'id': 'fixture:passage', 'text': 'α β', 'language': 'grc', 'kind': 'text'}
CLAIM = {'id': 'fixture:claim', 'subject': {'form': 'α', 'passage_id': PASSAGE['id']},
         'predicate': 'morphology', 'object': {'raw_label': 'synthetic branch A'},
         'status': 'source_claim', 'assertion_type': 'quoted_source',
         'source_family': 'fixture', 'evidence': [{'record_id': 'fixture:source',
            'source_url': 'https://example.test/source', 'quote': 'synthetic branch A or branch B'}]}
CANDIDATE = {'id': 'fixture:analysis', 'candidate_kind': 'grammatical_analysis',
             'lemma': 'α', 'analysis': 'synthetic branch A', 'claim_ids': [CLAIM['id']],
             'source_projection_status': 'incomplete_explicit_alternatives',
             'source_projection_note': 'Synthetic incomplete inventory, not source adjudication.',
             'source_grammar_alternatives': [{'record_id': 'fixture:source',
                'quote': 'synthetic branch A or branch B', 'offsets': [[0, 18], [22, 30]]}]}


class Provider:
    def __init__(self):
        self.calls = 0

    def decide(self, packet):
        self.calls += 1
        return {'model': 'fixture-model', 'choice': CANDIDATE['id'], 'cache_hit': True}


def test_incomplete_source_alternatives_stop_before_provider_or_cache_with_claims_preserved():
    provider = Provider()
    candidates, claims = [deepcopy(CANDIDATE)], [deepcopy(CLAIM)]
    original = deepcopy((candidates, claims))
    result = classify_context('α', PASSAGE, candidates, claims, provider=provider)
    assert result['status'] == 'abstained' and result['decision_stage'] == 'preflight'
    assert provider.calls == 0
    assert 'does not preserve all' in result['reason']
    assert result['packet']['claims'][0]['evidence'] == CLAIM['evidence']
    assert result['packet']['candidates'][0]['source_grammar_alternatives'] == CANDIDATE['source_grammar_alternatives']
    assert result['packet']['incomplete_source_projections'][0]['id'] == CANDIDATE['id']
    assert (candidates, claims) == original


@pytest.mark.parametrize('status', [None, 'partial_with_explicit_alternatives', 'explicit_alternatives_represented'])
def test_ordinary_shared_partial_and_fully_represented_ambiguity_are_not_blanket_blocked(status):
    provider = Provider()
    candidate = {**CANDIDATE, 'source_projection_status': status}
    result = classify_context('α', PASSAGE, [candidate], [CLAIM], provider=provider)
    assert provider.calls == 1
    assert result['status'] == 'proposed'
    assert 'incomplete_source_projections' not in result['packet']
    assert result['packet']['claims'][0]['evidence'][0]['quote'] == CLAIM['evidence'][0]['quote']


def test_incomplete_flag_cannot_disappear_with_a_grouped_member_or_valid_other_candidate():
    other = {'id': 'fixture:other', 'candidate_kind': 'grammatical_analysis', 'analysis': 'synthetic alternative',
             'source_url': 'https://example.test/dictionary'}
    # Simulate a grouping implementation consuming the flagged member; the
    # inventory-level condition must still survive and prevent paid fallback.
    def grouped(form, options, claims):
        return [options[1]], 1
    provider = Provider()
    with patch('backend.classifier._group_source_bridged_options', grouped):
        result = classify_context('α', PASSAGE, [CANDIDATE, other], [CLAIM], provider=provider)
    assert result['packet']['candidates'][0]['id'] == other['id']
    assert result['packet']['incomplete_source_projections'][0]['id'] == CANDIDATE['id']
    assert result['decision_stage'] == 'preflight' and provider.calls == 0


def test_old_prompt_and_cache_version_remain_in_force_while_experiment_is_parked():
    from backend.jev_gateway import CACHE_VERSION
    packet = build_evidence_packet('α', PASSAGE, [], [])
    assert CACHE_VERSION == 'jev-contextual-parse-v4'
    assert 'Preserve conflicting interpretations; abstain if evidence does not resolve them.' in packet['constraints']
    assert not any('provisional contextual grammatical hypothesis' in value for value in packet['constraints'])
