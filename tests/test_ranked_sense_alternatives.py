"""Uncertain scores do not certify meanings or select grammatical analyses."""
from copy import deepcopy
import pytest

from backend.sense_ranker import apply_sense_ranking
from test_sense_ranker import fixture, run, word, Provider


def uncertain():
    passage, result = fixture()
    provider = Provider({'choice': 'sense-1', 'model': 'fixture',
                         'model_probabilities': {'sense-0': .1, 'sense-1': .57, 'abstain': .33}})
    decision = run(passage, result, provider)
    assert decision['items'][0]['status'] == 'uncertain'
    return result, decision


def test_complete_uncertain_ranking_exposes_literal_alternatives_not_selection():
    result, decision = uncertain()
    before = deepcopy(word(result))
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    token = word(result)
    rows = token['ranked_sense_alternatives']
    assert [r['id'] for r in rows] == ['sense-1', 'sense-0']
    assert [r['score_uncalibrated'] for r in rows] == [.57, .1]
    assert rows[0]['supporting_candidate_ids'] == ['candidate-0']
    assert rows[0]['text'] == 'second meaning'
    assert token['sense_ranking_status'] == 'uncertain'
    assert token['sense_ranking_inventory_sha256'] == decision['items'][0]['inventory_sha256']
    for key in before:
        assert token[key] == before[key]
    assert decision['items'][0]['selected_sense_id'] is None


@pytest.mark.parametrize('mutation', ['digest', 'missing', 'foreign', 'nan', 'bool', 'source', 'offset', 'sense'])
def test_invalid_or_stale_rankings_expose_nothing(mutation):
    result, decision = uncertain()
    item = decision['items'][0]
    if mutation == 'digest': item['inventory_sha256'] = '0' * 64
    elif mutation == 'missing': del item['model_probabilities_uncalibrated']['abstain']
    elif mutation == 'foreign': item['model_probabilities_uncalibrated']['foreign'] = .1
    elif mutation == 'nan': item['model_probabilities_uncalibrated']['sense-1'] = float('nan')
    elif mutation == 'bool': item['model_probabilities_uncalibrated']['sense-1'] = True
    elif mutation == 'source': result['tokens'][0]['source_candidates'][0]['features'] = {'Case': 'Acc'}
    elif mutation == 'offset': word(result)['start'] += 1
    elif mutation == 'sense': word(result)['candidate_meanings'][0]['gloss']['alternatives'][0]['text'] = 'forged'
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert 'ranked_sense_alternatives' not in word(result)


def test_model_supplied_text_ignored_and_abstention_keeps_original_parse():
    result, decision = uncertain()
    item = decision['items'][0]
    item['status'] = 'abstained'
    item['ranked_senses'] = [{'sense_id': 'sense-1', 'text': 'invented'}]
    before = deepcopy(word(result)['features'])
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['ranked_sense_alternatives'][0]['text'] == 'second meaning'
    assert word(result)['features'] == before


def test_invalid_proposed_label_cannot_certify_uncertain_scores():
    result, decision = uncertain()
    item = decision['items'][0]
    item.update(status='proposed', selected_sense_id='sense-1', supporting_candidate_ids=['candidate-0'])
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['sense_ranking_status'] == 'uncertain'
    assert word(result)['gloss']['selection_basis'] != 'jev_contextual_sense_proposal'


def test_revalidation_revokes_previously_projected_stale_alternatives():
    result, decision = uncertain()
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['ranked_sense_alternatives']
    decision['items'][0]['inventory_sha256'] = '0' * 64
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert 'ranked_sense_alternatives' not in word(result)
