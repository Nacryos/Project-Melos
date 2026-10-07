"""Offline real-source regression; no model call or corpus mutation."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from backend.linked_dictionary import lookup_linked_dictionary
from backend.interlinear import interlinear_reading
from backend.sense_ranker import sense_packet, _inventory, _inventory_digest, apply_sense_ranking

ROOT = Path(__file__).resolve().parents[1]


def real_result(fragment, filename):
    result = json.loads((ROOT / 'runtime/lexical-release-c/operational' / filename).read_text(encoding='utf-8'))
    passage = next(json.loads(line) for line in (ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf-8').splitlines()
                   if json.loads(line)['id'] == 'campbell-glp:alcaeus:' + fragment)
    for row in result['tokens']:
        if row['kind'] == 'word':
            row['linked_dictionary'] = lookup_linked_dictionary(row['text'])
    result['interlinear'] = interlinear_reading(result)
    return passage, result


@pytest.mark.parametrize('fragment,filename', [('350', '350-c381678e548a.response.json'), ('129', '129-1e649d40c42b.response.json')])
def test_real_full_packet_ready(fragment, filename):
    passage, result = real_result(fragment, filename)
    token = result['interlinear']['readings'][0]['tokens'][0]
    packet = sense_packet(passage, result, token)
    assert len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) <= 32000
    assert packet['candidates']
    original_senses = {s['id']: s for s in _inventory(token)}
    original_paths = {r['candidate_id']: r for r in token['candidate_meanings']}
    for row in [*packet['candidates'], *packet['morphology_alternatives']]:
        if row.get('linked_path'):
            compact = deepcopy(row['linked_path'])
            full = {**packet['shared_source_evidence'][compact.pop('context_ref')], **compact}
            if 'source_noun_metadata_ref' in full:
                full['source_noun_metadata'] = deepcopy(packet['shared_source_evidence'][full.pop('source_noun_metadata_ref')])
            source_id = (packet.get('source_choice_ids') or {}).get(row.get('id'), row.get('id'))
            original = original_senses[source_id] if 'id' in row else original_paths[row['candidate_id']]
            assert full == original['linked_path']


@pytest.mark.parametrize('standalone', [False, True])
def test_cubit_selection_does_not_inherit_adjective_parse_or_choose_full_noun_parse(standalone):
    _, result = real_result('350', '350-c381678e548a.response.json')
    if standalone:
        for original in result['tokens']:
            original['source_candidates'] = []
            original['contextual_candidates'] = []
            original['machine'] = {}
        result['interlinear'] = interlinear_reading(result)
    token = result['interlinear']['readings'][0]['tokens'][0]
    inventory = _inventory(token)
    chosen = next(s for s in inventory if s['text'].startswith('cubit ('))
    assert token['candidate_id'] not in chosen['supporting_candidate_ids']
    decision = {'items': [{'token_id': token['token_id'], 'status': 'proposed',
        'selected_sense_id': chosen['id'], 'supporting_candidate_ids': chosen['supporting_candidate_ids'],
        'inventory_sha256': _inventory_digest(result, token, inventory),
        'model_probabilities_uncalibrated': {**{s['id']: .001 for s in inventory}, chosen['id']: .9, 'abstain': .01}}]}
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert token['gloss']['text'] == chosen['text']
    assert token['candidate_id'] is None and token['features'] == {}
    assert len(token['candidate_meanings']) > 3
    assert result['syntax']['tokens']  # preserved raw predictions
