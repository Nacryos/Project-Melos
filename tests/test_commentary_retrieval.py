"""Existing approved source projection; synthetic edge cases never enter data."""
from copy import deepcopy
import json
from pathlib import Path
import unicodedata

import pytest

from backend.commentary_retrieval import retrieval_cues, _exact_spans, _groups
from backend.edition_commentary import for_passage

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'


def occurrence(fragment, form):
    passage = next(row for row in map(json.loads, RECORDS.read_text(encoding='utf-8').splitlines())
                   if row['id'] == 'campbell-glp:alcaeus:' + fragment)
    start = passage['text'].index(form)
    return passage, {'text': form, 'start': start, 'end': start + len(form)}


@pytest.mark.parametrize('fragment,form,ordinals,groups', [
    ('350', 'παχέων', [8, 9], [[6, 7, 8, 9]]),
    ('326', 'ἀνέμων', [4, 5, 6], [[4, 5], [6]]),
    ('129', 'δᾶμον', [27, 28], [[27], [28]]),
    ('350', 'ἦλθες', [4], [[4, 5]]),
])
def test_saved_occurrences_have_literal_neighbor_cues_not_target_alignment(fragment, form, ordinals, groups):
    passage, target = occurrence(fragment, form)
    original = deepcopy((passage, target))
    source = for_passage(passage, for_model=True)
    result = retrieval_cues(passage, target, commentary=source)
    assert result['status'] == 'available'
    assert [r['paragraph_ordinal'] for r in result['matches']] == ordinals
    assert [r['paragraph_ordinals'] for r in result['note_groups']] == groups
    assert all(r['relation_to_target'] == 'neighbor_surface' for r in result['matches'])
    assert result['selection_aligned'] is result['word_attestation'] is result['line_attestation'] is False
    by_ordinal = {p['ordinal']: p for p in source['paragraphs']}
    for match in result['matches']:
        assert passage['text'][match['matched_start']:match['matched_end']] == match['printed_heading']
        assert match['printed_heading'] == by_ordinal[match['paragraph_ordinal']]['lemma']
        assert match['citation'] == by_ordinal[match['paragraph_ordinal']]['citation']
    assert (passage, target) == original


def test_exact_target_heading_and_target_inside_phrase_are_distinct():
    passage, target = occurrence('326', 'στάσιν')
    result = retrieval_cues(passage, target)
    assert next(r for r in result['matches'] if r['paragraph_ordinal'] == 5)['relation_to_target'] == 'exact_target_surface'
    passage, target = occurrence('350', 'περάτων')
    result = retrieval_cues(passage, target)
    assert next(r for r in result['matches'] if r['paragraph_ordinal'] == 4)['relation_to_target'] == 'target_within_heading_phrase'


@pytest.mark.parametrize('change', ['source_id', 'text', 'heading', 'target', 'offset', 'partial', 'editorial'])
def test_forged_or_partial_identity_yields_no_cues(change):
    passage, target = occurrence('350', 'παχέων')
    commentary = for_passage(passage, for_model=True)
    if change == 'source_id': passage['metadata']['source_pdf_sha256'] = '0' * 64
    elif change == 'text': passage['text'] += 'x'
    elif change == 'heading': commentary['paragraphs'][7]['lemma'] = 'παχέων'
    elif change == 'target': target['text'] = 'invented'
    elif change == 'offset': target['start'] += 1
    elif change == 'partial': target['partial_word'] = True
    elif change == 'editorial': target['editorial_fragment'] = True
    result = retrieval_cues(passage, target, commentary=commentary)
    assert result['status'] == 'unavailable'
    assert result['matches'] == result['note_groups'] == []


def test_no_substrings_folding_or_editorial_boundary_crossing():
    assert list(_exact_spans('αβγ', 'β', 0, 3)) == []
    assert list(_exact_spans('αβ\u0301', 'αβ', 0, 3)) == []
    assert list(_exact_spans('[β]', 'β', 0, 3)) == []
    assert list(_exact_spans('β’', 'β', 0, 2)) == []
    assert list(_exact_spans('πάχ', 'παχ', 0, 3)) == []
    assert list(_exact_spans('βασιληίων', 'βασιληΐων', 0, 20)) == []
    decomposed = unicodedata.normalize('NFD', 'ἴαν')
    assert list(_exact_spans(decomposed, 'ἴαν', 0, len(decomposed))) == []
    assert list(_exact_spans(' β β ', 'β', 0, 5)) == [(1, 2), (3, 4)]


def test_note_groups_do_not_bridge_omitted_source_ordinals_or_repeat_labels():
    rows = [{'ordinal': i, 'printed_page': 1, 'anchor_line_label': label}
            for i, label in [(1, '5.'), (2, '5.'), (4, '5.'), (5, '6.'), (6, '5.')]]
    assert [g['paragraph_ordinals'] for g in _groups(rows)] == [[1, 2], [4], [5], [6]]


def test_returned_cues_cannot_mutate_approved_commentary():
    passage, target = occurrence('350', 'παχέων')
    result = retrieval_cues(passage, target)
    result['note_groups'][0]['paragraph_ordinals'].clear()
    assert retrieval_cues(passage, target)['note_groups'][0]['paragraph_ordinals'] == [6, 7, 8, 9]
