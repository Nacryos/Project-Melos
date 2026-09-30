"""Synthetic comparison safety checks; these fixtures are not corpus evidence."""
from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace
import json
import unicodedata

import pytest

from backend import classifier, server
from backend.parallel_context import matching_texts, source_claim_matches


TEXT = 'α β γ δ έ ζ η θ ι'
TARGET = {'id': 'fixture:target', 'text': TEXT, 'author': 'Fixture poet',
          'language': 'grc', 'kind': 'text', 'quality': 'source_text'}
SOURCE = {**TARGET, 'id': 'fixture:source'}


def annotation(**changes):
    start = TEXT.index('έ')
    row = {'id': 'fixture:claim', 'status': 'source_claim',
           'strength': 'explicit_passage_span', 'predicate': 'morphology',
           'assertion_type': 'quoted_source',
           'subject': {'passage_id': SOURCE['id'], 'form': 'έ', 'start': start, 'end': start + 1},
           'object': {'raw_label': 'synthetic parse'},
           'evidence': [{'source_url': 'https://example.test/source', 'quote': 'synthetic parse'}]}
    row.update(changes)
    return row


def test_complete_canonical_sequence_matches_without_mutating_records():
    source = {**SOURCE, 'text': unicodedata.normalize('NFD', TEXT.replace(' β ', ', β; '))}
    original = deepcopy(source)
    result = matching_texts('έ', TARGET, [source], ['Fixture poet'])
    assert len(result) == 1
    assert result[0]['passage']['id'] == SOURCE['id']
    assert result[0]['alignment']['token_index'] == 4
    assert result[0]['alignment']['matched_words'] == 9
    assert source == original


@pytest.mark.parametrize('change', [
    {'id': TARGET['id']}, {'author': 'Other poet'}, {'language': 'eng'},
    {'kind': 'commentary'}, {'quality': 'machine_ocr'}, {'quality': 'needs_review'},
    {'quality': 'mixed_content'}, {'text': TEXT.replace('έ', 'ε')},
    {'text': TEXT.replace('ι', 'κ')}, {'text': TEXT + ' κ'},
])
def test_nonidentical_or_ineligible_source_not_aligned(change):
    assert not matching_texts('έ', TARGET, [{**SOURCE, **change}], ['Fixture poet'])


@pytest.mark.parametrize('text,form', [('α β γ δ έ ζ η', 'έ'), (TEXT, 'κ'),
                                     (TEXT + ' έ', 'έ'), (TEXT + ' ε', 'έ')])
def test_short_absent_and_accent_ambiguous_occurrences_rejected(text, form):
    assert not matching_texts(form, {**TARGET, 'text': text}, [{**SOURCE, 'text': text}], ['Fixture poet'])


def test_unknown_author_does_not_establish_identity():
    assert not matching_texts('έ', TARGET, [SOURCE], ['unknown'])


def test_source_offsets_and_scope_rechecked():
    assert source_claim_matches(annotation(), SOURCE, 'έ')
    assert not source_claim_matches(annotation(status='machine_proposed'), SOURCE, 'έ')
    assert not source_claim_matches(annotation(subject={'passage_id': TARGET['id'], 'form': 'έ'}), SOURCE, 'έ')
    assert not source_claim_matches(annotation(subject={'passage_id': SOURCE['id'], 'form': 'έ', 'start': 0, 'end': 1}), SOURCE, 'έ')
    assert not source_claim_matches(annotation(subject={'passage_id': SOURCE['id'], 'form': 'έ', 'start': 8, 'end': 100}), SOURCE, 'έ')
    assert not source_claim_matches(annotation(), SOURCE, 'ε')


def test_spanless_source_requires_unique_exact_occurrence():
    row = annotation(subject={'passage_id': SOURCE['id'], 'form': 'έ'})
    assert source_claim_matches(row, SOURCE, 'έ')
    assert not source_claim_matches(row, {**SOURCE, 'text': TEXT + ' έ'}, 'έ')


def test_classifier_api_keeps_idless_generic_alternative_and_original_claim(monkeypatch):
    """Real morphology rows need not have IDs; packet builder assigns them."""
    source_claim = annotation()
    comparison = {'id': 'fixture:claim', 'claim_ids': ['fixture:claim'],
                  'matched_form': 'έ', 'analysis': 'synthetic source parse',
                  'strength': 'parallel_matching_text', 'source_passage_id': SOURCE['id'],
                  'comparison_scope': 'Comparison only; not a target annotation.'}
    generic = {'lemma': 'synthetic lemma', 'analysis': 'generic competing parse',
               'matched_form': 'έ', 'edit_distance': 0,
               'source_url': 'https://example.test/lexicon'}
    analysis = {'context': TARGET, 'candidates': [generic], 'contextual_candidates': [],
                'structured_evidence': {'claims': []},
                'parallel_contexts': [{'claims': [source_claim], 'candidates': [comparison]}]}
    before = deepcopy(analysis)
    monkeypatch.setattr(server, 'word', lambda *args: analysis)
    monkeypatch.setattr('backend.jev_gateway.public_enabled', lambda: False)
    captured = {}
    def fake_classify(form, context, **kwargs):
        captured.update(kwargs)
        return {'status': 'abstained', 'warnings': []}
    monkeypatch.setattr(classifier, 'classify_context', fake_classify)
    result = server.classify_context_request(server.ContextRequest(form='έ', passage_id=TARGET['id']), SimpleNamespace())
    assert 'parallel_text_comparison' in result['candidate_origin']
    assert len(captured['candidates']) == 2
    assert {c['analysis'] for c in captured['candidates']} == {'generic competing parse', 'synthetic source parse'}
    assert captured['claims'][0]['subject']['passage_id'] == SOURCE['id']
    assert analysis == before


def test_word_api_comparison_is_not_direct_target_evidence(monkeypatch):
    claim = annotation()
    original = deepcopy(claim)
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: {'data': json.dumps(TARGET)}))
    class Evidence:
        def lookup(self, form, passage_id=None, limit=20):
            return {'claims': [claim] if passage_id == SOURCE['id'] else [], 'total': 1}
        def candidate_analyses(self, form, passage_id=None, limit=20):
            return {'candidates': [{'id': claim['id'], 'claim_ids': [claim['id']],
                                    'analysis': 'synthetic source parse', 'strength': claim['strength']}]
                    if passage_id == SOURCE['id'] else []}
    monkeypatch.setattr(server, 'connect', connection)
    monkeypatch.setattr(server, 'author_chronology', lambda name: None)
    monkeypatch.setattr(server, 'author_profile', lambda name: None)
    monkeypatch.setattr(server, 'author_labels', lambda name: [name])
    monkeypatch.setattr(server, 'morph_service', lambda: SimpleNamespace(analyze=lambda *args, **kwargs: {'candidates': [], 'warnings': []}))
    monkeypatch.setattr(server, 'occurrences', lambda *args, **kwargs: [SOURCE])
    monkeypatch.setattr(server, 'evidence_lookup', lambda *args, **kwargs: {'claims': []})
    monkeypatch.setattr(server, 'evidence_service', lambda: Evidence())
    result = server.word('έ', TARGET['id'])
    assert result['context_analysis_status'] == 'unresolved'
    assert result['structured_evidence']['claims'] == []
    assert result['contextual_candidates'] == []
    comparison = result['parallel_contexts'][0]
    assert comparison['claims'][0]['subject']['passage_id'] == SOURCE['id']
    assert comparison['candidates'][0]['source_passage_id'] == SOURCE['id']
    assert comparison['candidates'][0]['strength'] == 'parallel_matching_text'
    assert comparison['candidates'][0]['original_source_strength'] == 'explicit_passage_span'
    assert claim == original
