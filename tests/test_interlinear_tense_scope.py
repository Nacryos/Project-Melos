"""Synthetic scope-consumer fixtures, never lexical source data."""
from copy import deepcopy

import pytest

from backend.interlinear import sense_form_compatible, _gloss


def sense():
    locator = {'node_path': '/entryFree/sense[1]/tr', 'rendered_start': 1,
               'rendered_end': 2, 'offset_basis': 'synthetic rendered text'}
    restriction = {'kind': 'source_tense_only', 'feature': 'Tense', 'allowed_values': ['Pres'],
                   'source_text': 'Synthetic source restriction; not corpus evidence.',
                   'source_url': 'https://example.invalid/synthetic', 'raw_sha256': 'a' * 64,
                   'lexicon_entry_id': 'synthetic:entry',
                   'extraction_rule': 'explicit_terminal_two_foregoing_present_senses_v1',
                   'source_locator': {**locator, 'node_path': '/entryFree/sense[2]',
                                      'rendered_start': 10, 'rendered_end': 30},
                   'tense_source_locator': {**locator, 'node_path': '/entryFree/sense[2]/tns',
                                            'rendered_start': 20, 'rendered_end': 25},
                   'scope': {'kind': 'preceding_meaning_units', 'count': 2,
                             'target_source_sense_ids': ['synthetic:s1', 'synthetic:s2']}}
    return {'id': 'synthetic:sense', 'text': 'synthetic meaning', 'language': 'en',
            'evidence_type': 'dictionary_sense', 'source_url': restriction['source_url'],
            'source_locator': locator, 'raw_sha256': restriction['raw_sha256'],
            'lexicon_entry_id': restriction['lexicon_entry_id'], 'entry_id': 'entry',
            'sense_path': [{'id': 'synthetic:s1'}], 'morphology_restrictions': [restriction]}


@pytest.mark.parametrize('features,compatible', [
    ({'Tense': 'Aor'}, False), ({'tense': 'aorist'}, False),
    ({'Tense': 'Pres'}, True), ({}, True), ({'Tense': 'Unknown'}, True),
    ({'Tense': 'Pres,Aor'}, True),
])
def test_only_known_canonical_tense_contradictions_rejected(features, compatible):
    assert sense_form_compatible(sense(), {'text': 'α'}, candidate={'features': features}) is compatible


@pytest.mark.parametrize('field,value', [
    ('raw_sha256', 'b' * 64), ('source_url', 'wrong'), ('lexicon_entry_id', 'other'),
    ('entry_id', 'other-raw-id'),
    ('source_text', ''), ('extraction_rule', 'guess'), ('feature', 'Mood'),
    ('allowed_values', ['Aor']), ('source_locator', {}), ('tense_source_locator', {}),
    ('scope', {'kind': 'preceding_meaning_units', 'count': 2, 'target_source_sense_ids': ['other', 'second']}),
])
def test_unproven_or_wrongly_bound_restriction_cannot_filter(field, value):
    row = sense()
    row['morphology_restrictions'][0][field] = value
    assert sense_form_compatible(row, {'features': {'Tense': 'Aor'}})


def test_same_english_text_on_unrelated_sense_not_filtered():
    row = sense()
    row['sense_path'] = [{'id': 'unrelated'}]
    assert sense_form_compatible(row, {'features': {'Tense': 'Aor'}})


def test_per_candidate_gloss_does_not_use_other_candidate_or_model_tense():
    row = sense()
    unrestricted = {**deepcopy(row), 'id': 'synthetic:unrestricted', 'morphology_restrictions': [],
                    'text': 'other synthetic meaning'}
    entry = {'id': 'synthetic:entry', 'entry_id': 'entry', 'lemma': 'α',
             'dictionary_senses': [row, unrestricted]}
    token = {'text': 'α', 'features': {'Tense': 'Pres'}, 'lexicon_entries': [entry]}
    candidate = {'lemma': 'α', 'features': {'Tense': 'Aor'}}
    preview = _gloss(candidate, token)
    assert preview['sense_id'] == unrestricted['id']
    assert preview['alternatives'] == [row, unrestricted]
    assert _gloss({**candidate, 'features': {}}, token)['sense_id'] == row['id']


def test_ambiguous_or_unknown_support_preserved_but_all_aorist_excluded():
    row = sense()
    def candidate(identifier, tense):
        return {'candidate_id': identifier, 'features': {'Tense': tense} if tense else {},
                'gloss': {'alternatives': [row]}}
    token = {'candidate_meanings': [candidate('a', 'Aor'), candidate('b', 'Pres')]}
    assert sense_form_compatible(row, token)
    token['candidate_meanings'][1] = candidate('b', None)
    assert sense_form_compatible(row, token)
    token['candidate_meanings'][1] = candidate('b', 'Aor')
    assert not sense_form_compatible(row, token)
    token['candidate_meanings'][1] = candidate('b', 'Pres')
    token['candidate_id'] = 'a'
    assert not sense_form_compatible(row, token)
    token['candidate_id'] = 'unrelated-selected-lemma'
    assert sense_form_compatible(row, token)


def test_standalone_syntax_prediction_cannot_exclude_source_sense():
    assert sense_form_compatible(sense(), {'selection_basis': 'syntax_prediction',
                                         'features': {'Tense': 'Aor'}})


@pytest.mark.parametrize('field,value', [('sense_path', [None]), ('sense_path', ['bad']),
    ('sense_path', 'bad'), ('source_locator', []), ('morphology_restrictions', 'bad')])
def test_malformed_parent_proof_does_not_crash_or_constrain(field, value):
    row = sense()
    row[field] = value
    assert sense_form_compatible(row, {'features': {'Tense': 'Aor'}})


@pytest.mark.parametrize('field,value', [('scope', []), ('source_locator', []),
    ('tense_source_locator', []), ('source_text', ['bad']),
    ('scope', {'kind': 'preceding_meaning_units', 'count': 2, 'target_source_sense_ids': [['bad'], {}]}),
    ('scope', {'kind': 'preceding_meaning_units', 'count': 2, 'target_source_sense_ids': 'bad'})])
def test_malformed_nested_proof_does_not_crash_or_constrain(field, value):
    row = sense()
    row['morphology_restrictions'][0][field] = value
    assert sense_form_compatible(row, {'features': {'Tense': 'Aor'}})
