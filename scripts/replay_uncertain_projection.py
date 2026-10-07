"""Source-bound UI fixture with conspicuously synthetic scores; no API call."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.interlinear import interlinear_reading
from backend.linked_dictionary import lookup_linked_dictionary
from backend.sense_ranker import _inventory, _inventory_digest, apply_sense_ranking


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.source.read_text(encoding='utf-8'))
    result.pop('sense_ranking', None)
    for token in result['tokens']:
        if token.get('kind') == 'word':
            token['linked_dictionary'] = lookup_linked_dictionary(token['text'])
    result['interlinear'] = interlinear_reading(result)
    decisions = []
    for token in result['interlinear']['readings'][0]['tokens']:
        if token.get('kind') != 'word':
            continue
        senses = _inventory(token)
        if len(senses) < 2:
            raise ValueError('At least two actual source alternatives required.')
        # Deterministic first source ID, not a philological answer or reuse of
        # a model decision bound to a different source inventory.
        selected = senses[0]['id']
        probabilities = {s['id']: .23 / (len(senses) - 1) for s in senses}
        probabilities.update({selected: .57, 'abstain': .20})
        decisions.append({'token_id': token['token_id'], 'status': 'uncertain',
            'model': 'SYNTHETIC_UI_TEST_NOT_JEV', 'selected_sense_id': None,
            'proposed_sense_id': selected, 'inventory_sha256': _inventory_digest(result, token, senses),
            'model_probabilities_uncalibrated': probabilities,
            'ranked_senses': sorted([{'sense_id': s['id'], 'score_uncalibrated': probabilities[s['id']]} for s in senses],
                                    key=lambda r: -r['score_uncalibrated'])})
    result['sense_ranking'] = {'status': 'complete', 'provider': 'SYNTHETIC_UI_TEST_NOT_JEV', 'items': decisions}
    apply_sense_ranking(result['interlinear'], result['sense_ranking'], source_result=result)
    result['evaluation_fixture'] = {'synthetic_scores': True, 'actual_model_call': False,
        'source': str(args.source.resolve()), 'purpose': 'UI projection only; not semantic accuracy or a source annotation.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False)
    print(json.dumps({'output': str(args.output), 'synthetic_scores': True,
                      'ranked_counts': [len(t.get('ranked_sense_alternatives', [])) for t in result['interlinear']['readings'][0]['tokens']]}))


if __name__ == '__main__':
    main()
