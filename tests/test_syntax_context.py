"""Synthetic source-boundary mechanics; no linguistic judgments or remote calls."""
from copy import deepcopy

import pytest

from backend.passage_analysis import tokenize_span
from backend.syntax_context import project_syntax_tokens, syntax_context_window


def assert_window(text, start, end, result, words=80, chars=2000):
    a, b = result['context_start'], result['context_end']
    assert 0 <= a <= start < end <= b <= len(text)
    assert result['text'] == text[a:b]
    assert len(result['text']) <= chars
    assert sum(t['kind']=='word' for t in tokenize_span(text,a,b)) <= words
    assert result['context_start_utf16'] == len(text[:a].encode('utf-16-le'))//2
    assert result['context_end_utf16'] == len(text[:b].encode('utf-16-le'))//2
    assert result['text'][result['selection_start_in_context']:result['selection_end_in_context']] == text[start:end]


def test_small_passage_including_editorial_text_is_whole_source():
    text = '😀 α[β]γ …\u0323\n\n δ  '
    result = syntax_context_window(text, text.index('δ'), text.index('δ')+1)
    assert result['scope']=='whole_passage'
    assert result['text']==text and not result['warnings']


@pytest.mark.parametrize('index',[0,1,39,99,198,199])
def test_long_poem_center_and_edges_include_nearby_words(index):
    text = 'α '*199+'α'
    start = 2*index
    result = syntax_context_window(text,start,start+1)
    assert_window(text,start,start+1,result)
    assert result['scope']=='bounded_context_window'
    assert result['word_count']==80
    assert result['warnings'] and not result['partial_start_word'] and not result['partial_end_word']
    if index==99:
        assert result['context_start'] < start < result['context_end']-1
        assert result['context_start']==2*59 # nearest words, left wins tie


def test_partial_selection_expands_to_complete_boundary_word():
    text = 'α '*85+'βγδε'+' ζ'*85
    start = 171
    result = syntax_context_window(text,start,start+1)
    assert_window(text,start,start+1,result)
    assert 'βγδε' in result['text']
    assert not result['partial_start_word'] and not result['partial_end_word']


def test_giant_word_preserves_selection_with_explicit_partial_warning():
    text = 'α'*2500
    result = syntax_context_window(text,1200,1201)
    assert_window(text,1200,1201,result)
    assert result['partial_end_word']
    assert any('partial' in warning for warning in result['warnings'])


def test_character_limit_and_nearby_giant_word_never_overflow():
    text = ('α'*100+' ')*40
    result = syntax_context_window(text,2000,2001)
    assert_window(text,2000,2001,result)
    assert len(result['text']) <= 2000
    other = 'α'*3000+' β γ δ'
    result = syntax_context_window(other,3001,3002,max_characters=20)
    assert_window(other,3001,3002,result,chars=20)
    assert result['text']=='β γ δ'


def test_prefer_enclosing_stanza_without_altering_newlines_or_editorial_text():
    prefix = 'α '*81+'\r\n\r\n'
    stanza = '[β] … γ\r\nδ\u0323 ε'
    text = prefix+stanza+'\r\n \r\n'+'ζ '*81
    start = len(prefix)+1
    result = syntax_context_window(text,start,start+1)
    assert_window(text,start,start+1,result)
    assert result['strategy']=='enclosing_stanza'
    assert result['text']==stanza


def test_cross_stanza_selection_preserves_blank_lines():
    text = 'α '*81+'\n\nβ\n\nγ\n\n'+'δ '*81
    start, end = text.index('β'), text.index('γ')+1
    result = syntax_context_window(text,start,end)
    assert_window(text,start,end,result)
    assert 'β\n\nγ' in result['text']


def test_repeated_text_projects_selected_occurrence_by_offset_with_utf16():
    text = '😀 '+'α '*100
    start = 2+2*70
    window = syntax_context_window(text,start,start+1,max_words=3)
    relative = start-window['context_start']
    source = [{'id':1,'start':relative,'end':relative+1,'text':'α','features':{'Case':'Nom'}},
              {'id':0,'start':0,'end':1,'text':'α'}]
    original = deepcopy(source)
    projected = project_syntax_tokens(source,window,text)
    assert projected[0]['absolute_start']==start and projected[0]['start_utf16']==start+1
    assert projected[0]['selected'] and not projected[1]['selected']
    assert source==original


@pytest.mark.parametrize('token',[
    {'start':False,'end':1,'text':'α'}, {'start':-1,'end':1,'text':'α'},
    {'start':0,'end':2,'text':'α'}, {'start':0,'end':1,'text':'β'},
    {'start':0,'end':500,'text':'α'},
])
def test_invalid_provider_offsets_are_rejected_without_fuzzy_search(token):
    with pytest.raises(ValueError,match='offsets'):
        project_syntax_tokens([token],syntax_context_window('α α',2,3),'α α')


@pytest.mark.parametrize('start,end',[(False,1),(-1,1),(1,1),(0,4)])
def test_invalid_selection_offsets_fail(start,end):
    with pytest.raises(ValueError,match='offsets'):
        syntax_context_window('α β',start,end)


def test_oversized_selection_and_invalid_config_fail():
    with pytest.raises(ValueError,match='exceeds'):
        syntax_context_window('α'*2001,0,2001)
    with pytest.raises(ValueError,match='exceeds'):
        syntax_context_window('α '*81,0,162)
    with pytest.raises(ValueError,match='limits'):
        syntax_context_window('α',0,1,max_words=81)


def test_stale_window_is_rejected():
    window = syntax_context_window('α β',0,1)
    window['text']='α γ'
    with pytest.raises(ValueError,match='source selection'):
        project_syntax_tokens([],window,'α β')
