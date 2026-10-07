"""Frozen real packets: source cues change relevance, never dictionary facts."""
from copy import deepcopy
import json

import pytest

from backend.edition_commentary import for_passage, compact_model_context
from backend.sense_ranker import add_context_relevance, sense_packet
from test_commentary_retrieval import ROOT, occurrence
from test_linked_sense_integration import real_result

PACKETS = ROOT / 'runtime/lexical-release-g/commentary-ablation-02'


@pytest.mark.parametrize('case,fragment,form', [(0, '350', 'παχέων'), (1, '129', 'δᾶμον'),
                                              (2, '326', 'ἀνέμων'), (3, '350', 'ἦλθες')])
def test_saved_packets_only_receive_source_cues_and_heuristic_preview(case, fragment, form):
    passage, target = occurrence(fragment, form)
    packet = json.loads((PACKETS / f'{case}-baseline.packet.json').read_bytes())
    original = deepcopy(packet)
    add_context_relevance(packet, passage, target, commentary=for_passage(passage, for_model=True))
    assert packet['commentary_retrieval_cues']['status'] == 'available'
    assert packet['commentary_retrieval_cues']['target_occurrence'] == target
    assert len(packet['constraints']) == len(original['constraints']) + 2
    if packet['selected_morphology']:
        assert packet['selected_morphology']['presentation_role'] == 'current_heuristic_preview'
        assert packet['selected_morphology']['selection_is_source_adjudication'] is False
        assert packet['selected_morphology']['constrains_sense_candidates'] is False
    restored = deepcopy(packet)
    del restored['commentary_retrieval_cues']
    restored['constraints'] = restored['constraints'][:-2]
    if restored['selected_morphology']:
        for key in ('presentation_role', 'selection_is_source_adjudication', 'constrains_sense_candidates'):
            del restored['selected_morphology'][key]
    assert restored == original


@pytest.mark.parametrize('change', ['heading', 'context', 'offset', 'passage', 'coordinated_forgery'])
def test_wrong_packet_source_or_target_is_rejected_before_mutation(change):
    passage, target = occurrence('350', 'παχέων')
    packet = json.loads((PACKETS / '0-baseline.packet.json').read_bytes())
    commentary = for_passage(passage, for_model=True)
    if change == 'heading': commentary['paragraphs'][7]['lemma'] = 'invented'
    elif change == 'context': packet['published_commentary_context']['paragraphs'][0][-1] = 'invented'
    elif change == 'offset': target['start'] += 1
    elif change == 'coordinated_forgery':
        commentary['paragraphs'][7]['lemma'] = 'παχέων'
        packet['published_commentary_context'] = compact_model_context(commentary)
    else: passage['text'] += 'changed'
    before = deepcopy(packet)
    with pytest.raises(ValueError): add_context_relevance(packet, passage, target, commentary=commentary)
    assert packet == before


def test_production_packet_integrates_cues_without_changing_source_inventory():
    passage, result = real_result('350', '350-c381678e548a.response.json')
    token = result['interlinear']['readings'][0]['tokens'][0]
    before = deepcopy(result)
    packet = sense_packet(passage, result, token)
    assert packet['selected_morphology']['presentation_role'] == 'current_heuristic_preview'
    assert [r['paragraph_ordinal'] for r in packet['commentary_retrieval_cues']['matches']] == [8, 9]
    assert result == before
