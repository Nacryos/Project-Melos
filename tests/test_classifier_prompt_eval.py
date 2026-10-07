"""Offline preparation mechanics; no corpus facts or paid model calls."""
from copy import deepcopy

from backend import classifier
from scripts.prepare_classifier_prompt_eval import digest, request_body, source_state
from scripts.prepare_classifier_prompt_eval import scope_instruction_pair, SCOPE_ADDITION
import pytest


def baseline_body(packet, model):
    """The ablation preparer intentionally rejects the already-adopted prompt."""
    body = request_body(classifier, packet, model)
    body['questions']['contextual_parse']['instructions'] = body['questions']['contextual_parse']['instructions'].replace(SCOPE_ADDITION + ' ', '')
    return body


def test_source_equality_ignores_only_task_constraints_not_qualifications():
    original = {'constraints': ['old task'], 'candidates': [{'id': 'fixture', 'analysis': ['partial']}],
                'claims': [{'quote': 'uncertain synthetic evidence'}], 'warnings': ['retain this qualification']}
    revised = deepcopy(original)
    revised['constraints'] = ['new task']
    assert source_state(original) == source_state(revised)
    assert digest(source_state(original)) == digest(source_state(revised))
    revised['claims'][0]['quote'] = 'unqualified synthetic evidence'
    assert source_state(original) != source_state(revised)


def test_capture_uses_exact_provider_body_without_network_or_credentials(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network call')

    monkeypatch.setattr(classifier, 'urlopen', forbidden)
    packet = {'candidates': [{'id': 'fixture', 'analysis': ['partial']}], 'claims': [], 'constraints': []}
    before = deepcopy(packet)
    body = request_body(classifier, packet, 'fixture-pinned-model')
    assert body['state'] == before == packet
    assert body['model'] == 'fixture-pinned-model'
    assert set(body['questions']['contextual_parse']['criteria']) == {'fixture', 'abstain'}
    assert body['questions']['contextual_parse']['instructions'].startswith('Which supplied')
    assert 'offline-fixture-not-a-key' not in str(body)
    assert classifier.urlopen is forbidden


def test_scope_ablation_changes_only_one_instruction_field():
    packet = {'candidates': [{'id': 'fixture', 'analysis': ['partial']}],
              'claims': [{'quote': 'SYNTHETIC uncertainty'}], 'constraints': ['Retain source scope']}
    body = baseline_body(packet, 'fixture-pinned-model')
    original = deepcopy(body)
    before, after = scope_instruction_pair(body)
    assert body == before == original
    assert after['state'] == before['state']
    assert after['questions']['contextual_parse']['criteria'] == before['questions']['contextual_parse']['criteria']
    assert SCOPE_ADDITION in after['questions']['contextual_parse']['instructions']
    after['questions']['contextual_parse']['instructions'] = before['questions']['contextual_parse']['instructions']
    assert after == before


def test_scope_ablation_refuses_unknown_or_double_applied_prompt():
    body = baseline_body({'candidates': [], 'claims': [], 'constraints': []}, 'fixture-model')
    _, after = scope_instruction_pair(body)
    with pytest.raises(ValueError):
        scope_instruction_pair(after)
    body['questions']['contextual_parse']['instructions'] = 'Unknown task'
    with pytest.raises(ValueError):
        scope_instruction_pair(body)
