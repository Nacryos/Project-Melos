"""Synthetic mechanics plus an optional replay of the existing source artifact."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.editorial_readings import editorial_readings
from backend.passage_analysis import tokenize_span


def record(text):
    return {'id':'synthetic:editorial','text':text,'metadata':{}}


def test_projection_retains_exact_characters_maps_offsets_and_never_asserts_attestation():
    passage = record('😀 β[ό]λλας, α[β]γ')
    before = deepcopy(passage)
    result = editorial_readings(passage)
    assert passage==before
    row = result['rows'][0]
    assert row['original_text']=='β[ό]λλας' and row['projected_text']=='βόλλας'
    assert row['start']==2 and row['start_utf16']==3
    assert [m['source_start'] for m in row['character_source_map']]==[2,4,6,7,8,9]
    assert [m['printed_inside_square_brackets'] for m in row['character_source_map']]==[False,True,False,False,False,False]
    assert row['lookup_eligible'] and row['status']=='conditional_editorial_reading'
    assert not row['word_attestation'] and not row['line_attestation'] and not row['occurrence_verified'] and not row['raw_surface_match']
    for mapping in row['character_source_map']:
        assert passage['text'][mapping['source_start']:mapping['source_end']]==row['projected_text'][mapping['projected_start']:mapping['projected_end']]


@pytest.mark.parametrize('apostrophe',["'",'\u2019','\u02bc','\u1fbd'])
def test_terminal_apostrophes_and_combining_accents_are_not_normalized(apostrophe):
    row = editorial_readings(record('α[β\u0301]γ'+apostrophe))['rows'][0]
    assert row['projected_text']=='αβ\u0301γ'+apostrophe
    assert len(row['character_source_map'])==5
    assert row['lookup_eligible']


@pytest.mark.parametrize('text',[
    'α[β γ]δ', 'α[β\nγ]δ', 'α[.]β', 'α[…]β', 'α[β', 'α]β',
    'α[[β]]γ', 'α[]β', 'α[\u0301]β', 'α[β]γ\u0323', '†α[β]γ†',
    'α[β]<γ>', 'α[β]⟦γ⟧', 'α[a]β', 'α[\u02bc]β', '\u02bcα[β]',
])
def test_unsafe_or_unrecognized_source_structure_cannot_produce_lookup(text):
    rows = editorial_readings(record(text))['rows']
    assert rows
    assert all(not row['lookup_eligible'] and row['projected_text'] is None for row in rows)


def test_only_closed_square_brackets_are_supported_and_repeated_words_stay_distinct():
    assert editorial_readings(record('α<β>γ α⟨β⟩γ α⟦β⟧γ'))['rows']==[]
    rows = editorial_readings(record('[α] [α]'))['rows']
    assert len(rows)==2 and rows[0]['id']!=rows[1]['id']
    assert rows[0]['projected_text']==rows[1]['projected_text']=='α'


def test_unknown_source_uncertainty_is_fail_closed_but_projection_remains_visible():
    passage = record('α[β]γ')
    passage['metadata']['transcription_uncertainty']=['Synthetic unscoped source uncertainty.']
    row = editorial_readings(passage)['rows'][0]
    assert row['projected_text']=='αβγ'
    assert row['status']=='uncertain_editorial_reading' and not row['lookup_eligible']
    assert row['uncertainty_reasons']==['unscoped_or_changed_source_metadata_uncertainty']


def test_bounded_word_and_invalid_inputs_fail_explicitly():
    row = editorial_readings(record('α[β]γ'),max_word_characters=4)['rows'][0]
    assert 'source_word_character_limit' in row['structural_errors']
    with pytest.raises(ValueError):
        editorial_readings({'text':None})
    with pytest.raises(ValueError):
        editorial_readings({'text':'α[β]γ'})
    with pytest.raises(ValueError):
        editorial_readings(record('α[β]'),max_word_characters=True)
    with pytest.raises(ValueError):
        editorial_readings({**record('α[β]'),'metadata':[]})
    with pytest.raises(ValueError):
        editorial_readings({**record('α[β]'),'metadata':{'transcription_uncertainty':False}})
    giant = editorial_readings(record('α['+'β'*5000+']γ'))['rows'][0]
    assert giant['projected_text'] is None and giant['character_source_map']==[]


SOURCE = Path(__file__).resolve().parents[1]/'runtime/campbell-assignment/campbell_assignment.jsonl'


@pytest.mark.skipif(not SOURCE.exists(),reason='Approved source artifact is not installed in this checkout')
def test_approved_source_replay_counts_and_complete_character_provenance():
    passages = [json.loads(line) for line in SOURCE.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    actual = []
    for passage in passages:
        before = deepcopy(passage)
        result = editorial_readings(passage)
        assert passage==before
        words = [t for t in tokenize_span(passage['text'],0,len(passage['text'])) if t['kind']=='word']
        # Bracket-interrupted words are now single reader tokens carrying the
        # editor's reading; count those covered by a projected row.
        covered = sum(sum(r['start'] <= w['start'] and w['end'] <= r['end'] and bool(w.get('editorial_reconstruction')) for w in words)
                      for r in result['rows'] if r['projected_text'] is not None)
        actual.append((passage['id'].split(':')[-1],result['structurally_projectable'],result['lookup_eligible'],covered))
        for row in result['rows']:
            assert passage['text'][row['start']:row['end']]==row['original_text']
            if row['projected_text'] is None:
                continue
            assert ''.join(passage['text'][m['source_start']:m['source_end']] for m in row['character_source_map'])==row['projected_text']
            assert len(row['original_text'])-len(row['projected_text'])==2*len(row['square_bracket_pairs'])
    assert [row[:3] for row in actual]==[('34a',10,8),('129',8,8),('130b',10,10),('326',0,0),('350',0,0)]
    assert [row[3] > 0 for row in actual]==[True,True,True,False,False]


@pytest.mark.skipif(not SOURCE.exists(),reason='Approved source artifact is not installed in this checkout')
def test_reviewed_uncertainty_offsets_require_both_exact_source_and_note_hashes():
    passage = json.loads(SOURCE.read_text(encoding='utf-8').splitlines()[0])
    uncertain = [r for r in editorial_readings(passage)['rows'] if r['status']=='uncertain_editorial_reading']
    assert [(r['start'],r['end']) for r in uncertain]==[(78,84),(85,96)]
    changed_text = deepcopy(passage)
    changed_text['text']=' '+changed_text['text']
    assert editorial_readings(changed_text)['lookup_eligible']==0
    changed_note = deepcopy(passage)
    changed_note['metadata']['transcription_uncertainty'].append('Additional synthetic uncertainty.')
    assert editorial_readings(changed_note)['lookup_eligible']==0
    missing_note = deepcopy(passage)
    missing_note['metadata'].pop('transcription_uncertainty')
    assert editorial_readings(missing_note)['lookup_eligible']==0
