"""Audit mechanics use synthetic characters, never new linguistic evidence."""
import json
import pytest
from scripts.audit_alcaeus_occurrences import blocks, catalog, chunks, feature_coverage, Receipts, sha
from backend.passage_analysis import tokenize_span


def test_chunks_preserve_every_source_occurrence_and_editorial_context():
    text = 'α[β]γ δ\nε ζ\n'
    spans = chunks(text, 4)
    assert ''.join(text[a:b] for a,b in spans) == text
    words = lambda ts: [(t['start'],t['end'],t.get('editorial_fragment', False)) for t in ts if t['kind']=='word']
    assert [w for a,b in spans for w in words(tokenize_span(text,a,b))] == words(tokenize_span(text,0,len(text)))


def test_verse_catalog_excludes_prose_gap_and_does_not_claim_accuracy():
    record = {'id':'synthetic', 'text':'α β\nX Y\nγ δ', 'metadata':{'verse_segments':[
        {'start_line_index':0,'end_line_index_exclusive':1}, {'start_line_index':2,'end_line_index_exclusive':3}]}}
    words = [t for t in tokenize_span(record['text'],0,len(record['text'])) if t['kind']=='word']
    spans = list(catalog(record, words, {}))
    assert len(spans) == 6
    assert all('X' not in record['text'][s['start']:s['end']] for s in spans)
    assert all(s['semantic_accuracy']=='not_verified' and not s['api_requested_for_this_exact_span'] for s in spans)


def test_pos_specific_completeness_does_not_merge_alternatives():
    assert feature_coverage({'POS':'VERB','VerbForm':'Inf','Tense':'Pres','Voice':'Act'})['status']=='complete_fields'
    assert 'Person' in feature_coverage({'POS':'VERB','VerbForm':'Inf'})['not_applicable']
    assert feature_coverage({'POS':'VERB','Tense':'Pres'})['status']=='unknown_verb_subtype'
    assert feature_coverage({'Case':'Nom','Number':'Sing','Gender':'Masc'})['status']=='unknown_pos'
    assert feature_coverage({'POS':'PART'})['status']=='complete_fields'
    pronoun = feature_coverage({'POS':'PRON','Case':'Acc','Number':'Sing'})
    assert pronoun['status']=='complete_fields'
    assert pronoun['conditional_applicability_unresolved']==['Gender','Person']
    assert 'Gender' not in pronoun['not_applicable']


def test_cached_429_stops_without_a_retry(tmp_path):
    request = {'base':'https://invalid.example','route':'/api/analyze-passage','params':None,'payload':None}
    key = sha(json.dumps(request,sort_keys=True,ensure_ascii=False))
    (tmp_path/(key+'.json')).write_text(json.dumps({'request':request,'http_status':429}),encoding='utf-8')
    try:
        Receipts(request['base'],tmp_path,offline=True).call(request['route'])
    except RuntimeError as error:
        assert '429' in str(error) and 'no retry' in str(error)
    else:
        raise AssertionError('429 incorrectly treated as a successful receipt')


def test_leading_editorial_material_cannot_exceed_character_bound():
    with pytest.raises(ValueError, match='request bound'):
        chunks('[]\n' * 700 + 'a')


def test_interrupted_request_is_not_retried(tmp_path):
    request = {'base':'https://invalid.example','route':'/test','params':None,'payload':None}
    key = sha(json.dumps(request,sort_keys=True,ensure_ascii=False))
    (tmp_path/(key+'.pending.json')).write_text(json.dumps(request),encoding='utf-8')
    with pytest.raises(RuntimeError, match='no automatic retry'):
        Receipts(request['base'],tmp_path).call(request['route'])
