"""Commentary transport isolation using explicitly synthetic metadata."""
from copy import deepcopy

from backend.passage_analysis import _context


def test_edition_commentary_is_separate_from_translation_and_source_claims():
    passage = {'id':'synthetic:commentary', 'text':'α', 'related':[],
               'structured_evidence':{'ready':False,'claims':[]}}
    commentary = {'status':'available', 'evidence_type':'published_commentary',
                  'scope':'whole_poem_commentary', 'selection_aligned':False,
                  'word_attestation':False, 'line_attestation':False,
                  'paragraphs':[{'text':'Synthetic fixture commentary.'}]}
    passage['published_commentary'] = deepcopy(commentary)
    context = _context(passage)
    assert context['published_commentary']==commentary
    context['published_commentary']['paragraphs'].clear()
    assert passage['published_commentary']['paragraphs']==commentary['paragraphs']
    assert context['commentary']==[] and context['published_translations']==[]
    assert context['structured_evidence']['claims']==[]
    assert context['translation_status']=='unavailable'


def test_unrelated_passage_has_no_campbell_commentary():
    context = _context({'id':'synthetic:unrelated','text':'α','related':[]})
    assert context['published_commentary'] is None


def test_failed_commentary_binding_remains_explicitly_unavailable():
    unavailable = {'status':'unavailable','scope':'whole_poem_commentary','paragraphs':[]}
    context = _context({'id':'synthetic:stale','text':'α','related':[], 'published_commentary':unavailable})
    assert context['published_commentary']==unavailable
    assert context['published_translations']==[] and context['structured_evidence']['claims']==[]
