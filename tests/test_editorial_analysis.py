"""Synthetic dictionary plumbing plus approved-source projection replay."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.editorial_analysis import analyze_editorial_readings
from backend.editorial_readings import editorial_readings


def record(text):
    return {'id':'synthetic:editorial-analysis','text':text,'metadata':{}}


def dictionary(form):
    # Explicit synthetic fixture, never linguistic evidence or corpus data.
    return {'form':form,'candidates':[{'id':'synthetic:candidate','lemma':form,'matched_form':form,
            'features':{'POS':'NOUN','Case':'Gen','Number':'Sing','Gender':'Fem'},
            'gloss':'Synthetic literal dictionary definition.','gloss_language':'eng',
            'source':'synthetic fixture dictionary','source_url':'https://example.invalid/fixture'}],
            'occurrences':[{'id':'must-not-leak'}],
            'context':{'id':'must-not-leak'}, 'structured_evidence':{'claims':[]}}


def test_conditional_parses_and_literal_meanings_preserve_raw_source_and_adapter_output():
    passage = record('😀 α[β]γ')
    original = deepcopy(passage)
    source = dictionary('αβγ')
    before_source = deepcopy(source)
    calls = []
    def lookup(form, passage_id):
        calls.append((form,passage_id))
        return source
    result = analyze_editorial_readings(passage,2,len(passage['text']),lookup)
    row = result['rows'][0]
    assert calls==[('αβγ','')]
    assert row['original_text']=='α[β]γ' and row['start']==2 and row['start_utf16']==3
    candidate = row['analysis']['candidate_meanings'][0]
    assert candidate['features']==source['candidates'][0]['features']
    assert candidate['gloss']['text']==source['candidates'][0]['gloss']
    assert candidate['source_provenance']['source_url']=='https://example.invalid/fixture'
    assert candidate['basis']=='conditional_editorial_lookup'
    assert not candidate['word_attestation'] and not candidate['raw_surface_match']
    assert 'must-not-leak' not in json.dumps(result)
    assert not {'start','end','source_candidate','structured_evidence','occurrences','context'} & row['analysis'].keys()
    assert passage==original and source==before_source


def test_partial_selection_returns_expansion_hint_without_lookup():
    calls=[]
    result=analyze_editorial_readings(record('α[β]γ'),0,1,lambda *args:calls.append(args))
    assert calls==[] and result['rows']==[]
    hint=result['selection_expansion_hints'][0]
    assert (hint['start'],hint['end'])==(0,5)
    assert hint['lookup_status']=='not_requested_partial_selection'


def test_ineligible_projections_and_source_uncertainty_never_call_adapter():
    passage=record('α[β γ]δ ε[ζ]η')
    passage['metadata']['transcription_uncertainty']=['Synthetic uncertainty.']
    calls=[]
    result=analyze_editorial_readings(passage,0,len(passage['text']),lambda *args:calls.append(args))
    assert not calls and result['limits']['lookups']==0
    assert all(r['lookup_status']=='ineligible_projection' for r in result['rows'])


def test_budget_exhaustion_and_duplicate_forms_are_explicit():
    passage=record('α[β]γ α[β]γ δ[ε]ζ')
    calls=[]
    def lookup(form,pid):
        calls.append((form,pid)); return dictionary(form)
    result=analyze_editorial_readings(passage,0,len(passage['text']),lookup,max_lookups=1)
    assert len(calls)==1 and result['counts']['eligible']==3
    assert result['counts']['processed']==2
    assert result['counts']['skipped_by_reason']=={'request_limit':1}
    assert len(result['rows'])==3
    result['rows'][0]['analysis']['candidate_meanings'].clear()
    assert result['rows'][1]['analysis']['candidate_meanings']


def test_failed_lookup_is_not_retried_for_repeated_projection():
    passage=record('α[β]γ α[β]γ')
    calls=[]
    def lookup(*args):
        calls.append(args); raise RuntimeError('Synthetic failure')
    result=analyze_editorial_readings(passage,0,len(passage['text']),lookup)
    assert len(calls)==1
    assert result['counts']['skipped_by_reason']=={'lookup_failed':2}


@pytest.mark.parametrize('bad',[
    {'quarantined':True},{'assertion_type':'model_inference'}, {'candidate_kind':'machine_analysis'},
    {'source_consistent':False},{'status':'machine_proposed'}, {'matched_form':'δ'}, {'edit_distance':1},
])
def test_fuzzy_machine_and_rejected_rows_are_not_conditional_source_analyses(bad):
    source=dictionary('αβγ')
    source['candidates'][0].update(bad)
    source['machine']={'machine_candidates':dictionary('αβγ')['candidates']}
    result=analyze_editorial_readings(record('α[β]γ'),0,5,lambda *_:source)
    assert result['rows'][0]['analysis']['candidate_meanings']==[]


def test_invalid_offsets_and_budget_rejected_before_lookup():
    with pytest.raises(ValueError):
        analyze_editorial_readings(record('α[β]γ'),False,5,lambda *_:{})
    with pytest.raises(ValueError):
        analyze_editorial_readings(record('α[β]γ'),0,5,lambda *_:{},max_lookups=27)


def test_candidate_identity_collision_cannot_swap_dictionary_provenance():
    source=dictionary('αβγ')
    other=deepcopy(source['candidates'][0])
    other.update(gloss='Different synthetic literal definition.',source_url='https://example.invalid/other')
    source['contextual_candidates']=[other]
    result=analyze_editorial_readings(record('α[β]γ'),0,5,lambda *_:source)
    analysis=result['rows'][0]['analysis']
    assert analysis['candidate_meanings']==[]
    assert analysis['rejected_candidate_identity_collisions']==['synthetic:candidate']


SOURCE=Path(__file__).resolve().parents[1]/'data/campbell_glp/alcaeus_five_corrected.jsonl'


@pytest.mark.skipif(not SOURCE.exists(),reason='Approved source artifact is not installed')
def test_approved_source_named_examples_lookup_exact_projected_letters_and_skip_uncertain():
    passages=[json.loads(line) for line in SOURCE.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    wanted={'34a':[(109,121)],'129':[(67,77),(157,168)],'130b':[(124,132)]}
    totals={'eligible':0,'lookups':0}
    for passage in passages:
        original=deepcopy(passage)
        calls=[]
        def lookup(form,pid):
            calls.append((form,pid)); return dictionary(form)
        result=analyze_editorial_readings(passage,0,len(passage['text']),lookup)
        totals['eligible']+=result['counts']['eligible']; totals['lookups']+=result['limits']['lookups']
        projections={ (r['start'],r['end']):r for r in editorial_readings(passage)['rows'] }
        for span in wanted.get(passage['id'].split(':')[-1],[]):
            row=next(r for r in result['rows'] if (r['start'],r['end'])==span)
            assert (projections[span]['projected_text'],'') in calls
            assert row['analysis']['candidate_meanings']
            assert row['character_source_map']==projections[span]['character_source_map']
        if passage['id'].endswith(':34a'):
            for span in [(78,84),(85,96)]:
                assert projections[span]['projected_text'] not in [form for form,_ in calls]
        assert passage==original
    assert totals=={'eligible':26,'lookups':26}
