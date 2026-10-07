"""Approved-source replay with synthetic analysis adapters, not philological claims.

Greek is read from the accepted artifact. The fixture dictionary deliberately
uses labelled synthetic meanings: these tests check plumbing, not Greek accuracy.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend import edition_commentary
from backend.interlinear import interlinear_reading
from backend.lacuna_boundaries import intact_word_eligible
from backend.passage_analysis import PassageAnalysisService
from backend.passage_ranker import PassageRanker


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'


def accepted(fragment):
    data = ARTIFACT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == edition_commentary.GREEK_PACKAGE_SHA256
    passage = next(row for row in map(json.loads, data.decode('utf8').splitlines())
                   if row['metadata']['assignment_fragment'] == fragment)
    assert edition_commentary.for_passage(passage)['status'] == 'available'
    return passage


def dictionary(form):
    senses = [{'id': f'synthetic:sense:{i}', 'entry_id': 'synthetic:entry',
               'text': f'Synthetic fixture meaning {i}', 'source': 'synthetic LSJ fixture',
               'source_url': 'https://example.invalid/synthetic', 'language': 'eng',
               'evidence_type': 'dictionary_sense', 'source_locator': {'test_fixture': i},
               'raw_sha256': 'a' * 64} for i in (1, 2)]
    return {'candidates': [{'id': 'synthetic:parse', 'lemma': form, 'matched_form': form,
            'features': {'Case': 'Nom', 'Number': 'Sing', 'POS': 'NOUN'},
            'gloss_entry_id': 'synthetic:entry', 'source': 'synthetic fixture'}],
            'lexicon_entries': [{'id': 'synthetic:entry', 'lemma': form,
                'source': 'synthetic LSJ fixture', 'dictionary_senses': senses}],
            'warnings': []}


def analyze(passage, start, end, *, machine=None, rerank=False, ranker=None, sense_ranker=None):
    calls = []
    def lookup(form, passage_id):
        calls.append((form, passage_id))
        return dictionary(form)
    service = PassageAnalysisService(lambda _: deepcopy(passage), lookup,
        machine_service=machine, ranker=ranker, sense_ranker=sense_ranker)
    result = service.analyze({'passage_id': passage['id'], 'start': start, 'end': end,
        'offset_unit': 'codepoint', 'selected_text': passage['text'][start:end], 'rerank': rerank})
    return result, calls


def test_130b_surviving_letters_stay_conditional_without_losing_dictionary_meanings():
    passage = accepted('130b')
    # Locator/assertion only: never used to author or repair source data.
    first_line = passage['text'].splitlines()[0]
    start = first_line.index(' ις ') + 1
    before = deepcopy(passage)
    result, calls = analyze(passage, start, start + 2)
    token = result['tokens'][0]
    assert token['text'] == 'ις' and (token['start'], token['end']) == (27, 29)
    assert calls == [('ις', passage['id'])]
    assert token['lacuna_boundary_uncertain'] and not intact_word_eligible(token)
    assert not token['partial_word'] and not token.get('editorial_fragment')
    assert token['source_candidates'] == dictionary('ις')['candidates']
    assert token['lexicon_entries'] == dictionary('ις')['lexicon_entries']
    assert token['word_attestation'] is False and token['occurrence_verified'] is False
    evidence = token['lacuna_boundary_evidence'][0]
    assert passage['text'][evidence['start']:evidence['end']] == '. .'
    assert result['lacuna_boundary_policy']['status'] == 'applied'
    shown = result['interlinear']['readings'][0]['tokens'][0]
    assert shown['status'] == 'conditional' and shown['selection_basis'] == 'conditional_lacuna_boundary'
    assert shown['parse_short'] and shown['gloss']['text'] == 'Synthetic fixture meaning 1'
    assert len(shown['gloss']['alternatives']) == 2
    assert shown['candidate_meanings'][0]['status'] == 'conditional_alternative'
    assert shown['candidate_meanings'][0]['gloss']['alternatives'] == dictionary('ις')['lexicon_entries'][0]['dictionary_senses']
    assert passage == before


def test_possible_complete_word_next_to_dots_keeps_full_parse_and_literal_definitions():
    passage = accepted('350')
    # The helper must not infer incompleteness merely because a complete-looking
    # printed unit is followed by dots. Select that unit from the actual source.
    from backend.lacuna_boundaries import annotate_lacuna_boundaries
    from backend.passage_analysis import tokenize_span
    units = annotate_lacuna_boundaries(passage['text'], tokenize_span(passage['text'], 0, len(passage['text'])), source_critical=True)
    target = next(token for token in units if token.get('lacuna_boundary_uncertain'))
    result, calls = analyze(passage, target['start'], target['end'])
    raw = result['tokens'][0]
    shown = result['interlinear']['readings'][0]['tokens'][0]
    assert calls == [(target['text'], passage['id'])]
    assert not raw['partial_word'] and not raw.get('editorial_fragment')
    assert shown['features'] == {'Case': 'Nom', 'Number': 'Sing', 'POS': 'NOUN'}
    assert shown['gloss']['text'] and len(shown['candidate_meanings']) == 1
    assert shown['status'] == 'conditional'


@pytest.mark.parametrize('change', ['text', 'raw_sha256', 'edition', 'source', 'pdf'])
def test_source_optin_requires_actual_approved_identity_not_attached_status(change):
    passage = accepted('130b')
    start = passage['text'].splitlines()[0].index(' ις ') + 1
    passage['published_commentary'] = {'status': 'available'}
    if change == 'pdf':
        passage['metadata']['source_pdf_sha256'] = '0' * 64
    elif change == 'text':
        passage['text'] += ' '
    else:
        passage[change] = 'unapproved'
    result, _ = analyze(passage, start, start + 2)
    assert not result['tokens'][0].get('lacuna_boundary_uncertain')
    assert result['lacuna_boundary_policy']['status'] in {'source_unverified', 'not_applicable'}


def test_generic_prose_or_unrelated_editions_do_not_opt_in():
    passage = {'id': 'synthetic:prose', 'text': 'α . . β', 'kind': 'text', 'language': 'grc',
               'published_commentary': {'status': 'available'}}
    result, _ = analyze(passage, 6, 7)
    assert not result['tokens'][0].get('lacuna_boundary_uncertain')


def test_machine_hypotheses_remain_accessible_but_occurrence_scope_is_conditional():
    passage = accepted('130b')
    start = passage['text'].splitlines()[0].index(' ις ') + 1
    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            return {'status': 'ok', 'receipt': {'id': 'synthetic-receipt'},
                    'machine_candidates': [{'id': 'synthetic:machine', 'lemma': form, 'matched_form': form,
                        'features': {'Case': 'Acc', 'Number': 'Sing', 'POS': 'NOUN'}, 'basis': 'machine_analysis'}]}
    result, _ = analyze(passage, start, start + 2, machine=Machine())
    machine = result['tokens'][0]['machine']
    assert machine['machine_candidates'] and machine['receipt']['id'] == 'synthetic-receipt'
    assert machine['occurrence_scope'] == 'conditional_on_word_boundary'
    assert machine['word_attestation'] is False
    meanings = result['interlinear']['readings'][0]['tokens'][0]['candidate_meanings']
    assert {item['basis'] for item in meanings} == {'machine_analysis', 'source_alternative'}
    assert all(item['status'] == 'conditional_alternative' for item in meanings)


def test_parse_ranker_does_not_resolve_boundary_or_request_paid_decision():
    passage = accepted('130b')
    start = passage['text'].splitlines()[0].index(' ις ') + 1
    calls = []
    ranker = PassageRanker(lambda _: passage, lambda *args, **kwargs: calls.append(args), lambda _: object())
    result, _ = analyze(passage, start, start + 2, rerank=True, ranker=ranker)
    assert not calls
    assert result['ranking']['attempted_occurrences'] == 0
    assert result['ranking']['items'][0]['status'] == 'boundary_uncertain'


def test_stale_parse_ranking_cannot_change_conditional_display_to_resolved():
    passage = accepted('130b')
    start = passage['text'].splitlines()[0].index(' ις ') + 1
    result, _ = analyze(passage, start, start + 2)
    result['ranking'] = {'items': [{'token_id': result['tokens'][0]['id'],
        'decision': {'status': 'proposed', 'candidate_id': 'synthetic:parse',
                     'model_probabilities_uncalibrated': {'synthetic:parse': 1, 'abstain': 0}}}]}
    displayed = interlinear_reading(result)['readings'][0]['tokens'][0]
    assert displayed['status'] == 'conditional'
    assert displayed['selection_basis'] == 'conditional_lacuna_boundary'
    assert displayed['word_attestation'] is False
