"""Synthetic transport checks; these are not lexical source records."""
from copy import deepcopy

import pytest

from scripts.check_linked_dictionary_live import check_inventory, packet_source_ids


def fixture():
    expected = {'candidates': [{'candidate_id': 'one'}, {'candidate_id': 'two'}]}
    word = {'linked_dictionary_status': 'available', 'linked_dictionary': deepcopy(expected)}
    analysis = {'tokens': [{'kind': 'word', 'linked_dictionary': deepcopy(expected)}],
                'interlinear': {'readings': [{'tokens': [{'kind': 'word', 'candidate_meanings':
                    [{'candidate_id': 'one'}, {'candidate_id': 'two'}]}]}]}}
    return word, analysis, expected


def test_source_inventory_reaches_both_api_surfaces_and_meaning_alternatives():
    assert check_inventory(*fixture())['kind'] == 'word'


def test_short_wire_ids_expand_to_distinct_source_ids():
    assert packet_source_ids({'candidates': [{'id': 's0'}, {'id': 's1'}],
                              'source_choice_ids': {'s0': 'source-a', 's1': 'source-b'}}) == {'source-a', 'source-b'}


@pytest.mark.parametrize('mapping', [{'s0': 'source-a'}, {'s0': 'source-a', 's1': 'source-a'}])
def test_missing_or_merged_source_ids_fail(mapping):
    with pytest.raises(AssertionError):
        packet_source_ids({'candidates': [{'id': 's0'}, {'id': 's1'}], 'source_choice_ids': mapping})


@pytest.mark.parametrize('location', ['word', 'token', 'meanings'])
def test_dropped_or_changed_candidate_fails_probe(location):
    word, analysis, expected = fixture()
    if location == 'word':
        word['linked_dictionary']['candidates'].pop()
    elif location == 'token':
        analysis['tokens'][0]['linked_dictionary']['candidates'][0]['candidate_id'] = 'changed'
    else:
        analysis['interlinear']['readings'][0]['tokens'][0]['candidate_meanings'].pop()
    with pytest.raises(AssertionError):
        check_inventory(word, analysis, expected)
