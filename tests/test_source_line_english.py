"""Finite full-line English must never become a partial-phrase fallback."""
from copy import deepcopy
import hashlib
import json

import pytest

from backend import source_line_english as helper


def _poems():
    path=helper.ROOT/'data/campbell_glp/alcaeus_five_corrected.jsonl'
    return {row['id']:row for row in map(json.loads,path.read_text(encoding='utf8').splitlines())}


def _records():
    return json.loads(helper.DATA_PATH.read_text(encoding='utf8'))['records']


def _selection(row):
    return deepcopy(row['span'])


def test_deterministic_projection_retains_approved_source_english_and_notes(tmp_path):
    raw=helper.DATA_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==helper.DATA_SHA256
    assert json.loads(raw)==helper.project()
    assert helper.build_data(tmp_path/'copy.json')==helper.DATA_SHA256
    accepted=json.loads((helper.STAGED/'line-pairs.accepted.json').read_text(encoding='utf8'))
    originals={row['id']:row for row in accepted['accepted']}
    for row in _records():
        match=row['match']; source=originals[row['id']]
        assert match['text']==source['source_english']['text']
        assert match['source_greek']==source['source_greek']['text']
        assert match['source_context']['whole_source_translation']==source['full_source_translation']
        for key in ('translator','edition','citation','source_url','license','license_url','reuse_status'):
            assert match[key]==source[key]
        assert match['audit_caveats']==source['independent_audit']['caveats']
        assert len(match['source_notes'])==(1 if row['id']=='chs-line-pair:129:21' else 0)
        if match['source_notes']:
            assert match['source_notes'][0]['number']==30
            assert match['source_notes'][0]['text']==next(n['text'] for n in source['source_notes'] if n['number']==30)
    for forbidden in ('raw_path','C:\\Users','runtime/','translation_of','parent_id'):
        assert forbidden not in raw.decode('utf8')


def test_all_and_only_six_exact_full_lines_match():
    poems=_poems(); records=_records()
    expected={row['id'] for row in records}
    found=set()
    for poem in poems.values():
        cursor=0
        for line in poem['text'].splitlines(keepends=True):
            content=line.rstrip('\r\n')
            selection={'text':content,'start':cursor,'end':cursor+len(content),'offset_unit':'codepoint'}
            result=helper.exactmatch(poem,selection)
            if result:
                found.add(result['comparison_id'])
                assert result['status']=='matched'
                assert result['scope']=='one_full_source_line_only'
                assert result['selection_match']=='exact_full_line'
                for key in ('word_aligned','standalone_sentence_claim','whole_poem_translation','exact_edition_alignment','model_eligible','license_unrestricted'):
                    assert result[key] is False
                assert result['outer_whitespace_trimmed'] is False
        # Reset via actual line bytes, preserving empty structural lines.
            cursor+=len(line)
    assert found==expected and len(found)==6


def test_partial_words_partial_lines_and_multiple_lines_never_match():
    poems=_poems()
    for row in _records():
        poem=poems[row['campbell_record_id']]; span=_selection(row)
        for start,end in [(span['start']+1,span['end']),(span['start'],span['end']-1),
                          (span['start'],span['start']+1),(0,len(poem['text']))]:
            selection={'start':start,'end':end,'text':poem['text'][start:end],'offset_unit':'codepoint'}
            assert helper.exactmatch(poem,selection) is None
            assert helper.exactmatch(poem,selection,allow_outer_whitespace=True) is None
    poem=poems['campbell-glp:alcaeus:129']
    a,b=_records()[0],_records()[1]
    selection={'start':a['span']['start'],'end':b['span']['end'],'offset_unit':'codepoint'}
    selection['text']=poem['text'][selection['start']:selection['end']]
    assert helper.exactmatch(poem,selection) is None


def test_actual_selected_outer_whitespace_requires_explicit_opt_in():
    row=_records()[0]; poem=_poems()[row['campbell_record_id']]
    start,end=row['span']['start']-1,row['span']['end']+1
    assert poem['text'][start].isspace() and poem['text'][end-1].isspace()
    selection={'start':start,'end':end,'text':poem['text'][start:end],'offset_unit':'codepoint'}
    assert helper.exactmatch(poem,selection) is None
    result=helper.exactmatch(poem,selection,allow_outer_whitespace=True)
    assert result['comparison_id']==row['id'] and result['outer_whitespace_trimmed'] is True
    assert result['matched_span']['start']==row['span']['start']
    assert result['matched_span']['end']==row['span']['end']
    fabricated=_selection(row); fabricated['text']=' '+fabricated['text']+' '
    assert helper.exactmatch(poem,fabricated,allow_outer_whitespace=True) is None
    assert helper.exactmatch(poem,_selection(row),allow_outer_whitespace='yes') is None


@pytest.mark.parametrize('change',[{'offset_unit':'utf16'},{'offset_unit':'bytes'},{'start':True},
    {'end':True},{'start':-1},{'end':10**9},{'text':'not the selected Greek'},
    {'passage_id':'campbell-glp:alcaeus:130b'}])
def test_wrong_units_stale_text_and_invalid_spans_are_rejected(change):
    row=_records()[0]; poem=_poems()[row['campbell_record_id']]
    selection={**_selection(row),**change}
    assert helper.exactmatch(poem,selection) is None
    del selection['offset_unit']
    assert helper.exactmatch(poem,selection) is None


@pytest.mark.parametrize('field,value',[('id','campbell-glp:alcaeus:130b'),('text','different'),
    ('source','perseus'),('edition','another'),('author','another'),('work','another'),
    ('language','eng'),('kind','translation'),('quality','source_text'),
    ('source_url','https://example.invalid'),('raw_sha256','0'*64)])
def test_wrong_campbell_identity_fails_closed(field,value):
    row=_records()[0]; poem={**_poems()[row['campbell_record_id']],field:value}
    assert helper.exactmatch(poem,_selection(row)) is None


def test_metadata_sidecar_tamper_and_missing_file_return_none(tmp_path):
    row=_records()[0]; poem=_poems()[row['campbell_record_id']]
    for field in ('assignment_fragment','edition_fragment','source_pdf_sha256'):
        modified=deepcopy(poem);modified['metadata'][field]='wrong'
        assert helper.exactmatch(modified,_selection(row)) is None
    path=tmp_path/'data.json'
    assert helper.exactmatch(poem,_selection(row),path=path) is None
    path.write_bytes(helper.DATA_PATH.read_bytes()+b' ')
    assert helper.exactmatch(poem,_selection(row),path=path) is None
    first=helper.exactmatch(poem,_selection(row));first['text']='caller mutated copy'
    assert helper.exactmatch(poem,_selection(row))['text']!=first['text']


@pytest.mark.parametrize('argument,filename',[('accepted_path','line-pairs.accepted.json'),
    ('final_audit_path','line-pair-final-audit.json'),('source_audit_path','line-pair-audit.json')])
def test_changed_source_or_audit_cannot_be_projected(tmp_path,argument,filename):
    path=tmp_path/'changed.json';path.write_bytes((helper.STAGED/filename).read_bytes()+b'\n')
    with pytest.raises(ValueError,match='hash mismatch'):
        helper.project(**{argument:path})
