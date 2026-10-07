"""Local service integration with a deterministic stub, never a model call."""
import pytest

from backend.passage_analysis import PassageAnalysisService, tokenize_span, utf16_offset


class RecordingParser:
    def __init__(self):
        self.inputs = []
        self.output = None

    def analyze(self, text):
        self.inputs.append(text)
        self.output = {'state': 'ready', 'tokens': [
            {'id': index, 'text': token['text'], 'start': token['start'], 'end': token['end'], 'head': None}
            for index, token in enumerate(tokenize_span(text, 0, len(text))) if token['kind']=='word'],
            'warnings': ['stub provider warning']}
        return self.output


def analyze(text, start, end, parser=None):
    parser = parser or RecordingParser()
    passage = {'id':'synthetic:window', 'text':text, 'language':'grc', 'kind':'text'}
    lookups = []
    def lookup(form, passage_id):
        lookups.append((form, passage_id))
        return {'candidates': [], 'contextual_candidates': []}
    service = PassageAnalysisService(lambda _:passage, lookup, syntax_provider=parser)
    result = service.analyze({'passage_id':passage['id'], 'start':start, 'end':end,
                             'offset_unit':'codepoint', 'selected_text':text[start:end],
                             'rerank':False, 'fetch_machine':False})
    return result, parser, lookups


def test_repeated_selection_in_long_poem_has_context_and_exact_local_absolute_offsets():
    text = '😀 '+'α '*160
    start, end = 162, 163
    result, parser, lookups = analyze(text,start,end)
    syntax = result['syntax']
    assert syntax['scope']=='bounded_context_window'
    assert parser.inputs==[text[syntax['context_start']:syntax['context_end']]]
    assert len(syntax['tokens'])==80
    selected = [t for t in syntax['tokens'] if t['selected']]
    assert len(selected)==1
    assert selected[0]['absolute_start']==start and selected[0]['absolute_end']==end
    assert selected[0]['start']==start-syntax['context_start']
    assert selected[0]['end']==end-syntax['context_start']
    assert selected[0]['start_utf16']==utf16_offset(text,start)
    assert syntax['context_start_utf16']==utf16_offset(text,syntax['context_start'])
    assert syntax['evidence_type']=='contextual_prediction'
    assert lookups==[('α','synthetic:window')]
    assert result['tokens'][0]['source_candidates']==[]
    assert result['tokens'][0]['contextual_candidates']==[]
    assert result['limits']['machine_fetches']==0
    assert syntax['warnings'][0]=='stub provider warning'
    assert any('outside' in w for w in syntax['warnings'])
    assert all('absolute_start' not in t for t in parser.output['tokens'])
    assert parser.output['warnings']==['stub provider warning']


def test_editorial_lint_follows_context_including_unselected_nearby_source():
    text = 'α '*90+'[β] γ δ '+'ε '*90
    start = text.index('γ')
    result, parser, _ = analyze(text,start,start+1)
    assert result['selection']['text']=='γ'
    assert '[β]' in parser.inputs[0]
    warnings = [w for w in result['lint']['warnings'] if w['code']=='editorial_uncertainty']
    assert len(warnings)==1 and 'context' in warnings[0]['message']


def test_editorial_outside_window_does_not_warn_on_unrelated_lacuna():
    text = '[β] '+'α '*200
    start = len(text)-2
    result, parser, _ = analyze(text,start,start+1)
    assert '[' not in parser.inputs[0]
    assert not any(w['code']=='editorial_uncertainty' for w in result['lint']['warnings'])


def test_partial_selection_in_long_poem_preserves_original_token_and_context_word():
    text = 'α '*85+'βγδε'+' ζ'*85
    result, parser, lookups = analyze(text,171,172)
    assert result['tokens'][0]['text']=='γ' and result['tokens'][0]['partial_word']
    assert not lookups
    selected = [t for t in result['syntax']['tokens'] if t['selected']]
    assert len(selected)==1 and selected[0]['text']=='βγδε'
    assert selected[0]['absolute_start']==170 and selected[0]['absolute_end']==174


def test_whole_passage_context_and_scope_are_preserved():
    text = 'α β γ'
    result, parser, _ = analyze(text,2,3)
    assert parser.inputs==[text]
    assert result['syntax']['scope']=='whole_passage'
    assert result['syntax']['context_start']==0
    assert result['syntax']['context_end']==len(text)
    assert result['syntax']['warnings']==['stub provider warning']


def test_ranker_receives_bounded_window_scope_and_source_offsets():
    from backend.passage_ranker import _syntax_context
    text = 'α '*160
    result, _, _ = analyze(text,160,161)
    context = _syntax_context(result)
    assert context['scope']=='bounded_context_window'
    assert 'neighboring words' in context['scope_note']
    assert 'outside that window cannot be resolved' in context['scope_note']
    assert 'scope was not supplied' not in context['scope_note']
    assert context['context_start']==result['syntax']['context_start']
    assert context['context_end']==result['syntax']['context_end']
    assert [t['absolute_start'] for t in context['tokens'] if t['selected']]==[160]


def test_invalid_provider_offsets_fail_without_returning_partial_projection():
    class InvalidParser:
        def analyze(self, text):
            return {'state':'ready','tokens':[{'id':0,'text':'β','start':0,'end':1}]}
    result, _, _ = analyze('α '*160,162,163,InvalidParser())
    assert result['syntax']['status']=='unavailable'
    assert result['syntax']['code']=='provider_error'
    assert result['syntax']['tokens']==[]


@pytest.mark.parametrize('selected,text,start,end',[
    ('α'*2001,'α'*2001,0,2001), ('β','α',0,1), ('α','α',True,1)
])
def test_invalid_context_limits_or_source_fail_explicitly_before_parser(selected,text,start,end):
    parser = RecordingParser()
    service = PassageAnalysisService(lambda _:None,lambda *_:{},syntax_provider=parser)
    result = service._syntax(selected,text,start,end)
    assert result['status']=='unavailable' and result['code']=='context_window_invalid'
    assert parser.inputs==[]
