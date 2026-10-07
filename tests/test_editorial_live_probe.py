"""Synthetic transport-contract tests; these fixtures are not corpus entries."""
from copy import deepcopy
import pytest
from scripts import check_editorial_live as probe


@pytest.fixture
def sample(monkeypatch):
    record = {'id': 'synthetic', 'text': 'a[b]'}
    source = {'id': 'synthetic@0:4', 'start': 0, 'end': 4, 'original_text': 'a[b]',
              'projected_text': 'ab', 'lookup_eligible': True, 'word_attestation': False}
    monkeypatch.setattr(probe, 'editorial_readings', lambda _: {'rows': [deepcopy(source)]})
    candidate = {'basis': 'conditional_editorial_lookup', 'word_attestation': False,
                 'occurrence_verified': False, 'raw_surface_match': False}
    analysis = {'status': 'available', 'lookup_form': 'ab', 'lookup_scope': 'general_form_no_passage',
                'ranking_status': 'not_requested', 'syntax_status': 'not_requested',
                'word_attestation': False, 'occurrence_verified': False, 'raw_surface_match': False,
                'candidate_meanings': [candidate]}
    request = {'start': 0, 'end': 4, 'rerank': False, 'fetch_machine': False}
    result = {'selection': {'text': 'a[b]'}, 'editorial_analysis': {
        'passage_id': 'synthetic', 'source_text_sha256': probe.sha('a[b]'),
        'selection': {'start': 0, 'end': 4, 'offset_unit': 'codepoint', 'text_sha256': probe.sha('a[b]')},
        'limits': {'machine_fetches': 0}, 'ranking_status': 'not_requested',
        'rows': [{**source, 'analysis': analysis}]}}
    return record, request, result


def test_verified_conditional_transport(sample):
    assert probe.verify_projection(*sample)['available'] == 1


@pytest.mark.parametrize('field,value', [('original_text', 'changed'), ('projected_text', 'changed'),
                                      ('word_attestation', True), ('lookup_eligible', False)])
def test_source_mutation_rejected(sample, field, value):
    sample[2]['editorial_analysis']['rows'][0][field] = value
    with pytest.raises(AssertionError):
        probe.verify_projection(*sample)


def test_attestation_promotion_rejected(sample):
    sample[2]['editorial_analysis']['rows'][0]['analysis']['candidate_meanings'][0]['word_attestation'] = True
    with pytest.raises(AssertionError):
        probe.verify_projection(*sample)


def test_machine_fetch_rejected(sample):
    sample[2]['editorial_analysis']['limits']['machine_fetches'] = 1
    with pytest.raises(AssertionError):
        probe.verify_projection(*sample)
