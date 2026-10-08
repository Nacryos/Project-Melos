"""Offline replay of saved public API responses, with no model/network calls."""
import json
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.interlinear import interlinear_reading
from backend.sense_ranker import sense_packet

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--responses', type=Path, default=ROOT / 'runtime/lyric-context-eval/baseline')
args = parser.parse_args()
rows = [json.loads(line) for line in (ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl').read_text(encoding='utf-8').splitlines()]
paths = sorted([*args.responses.glob('*.response.json'), *args.responses.glob('*.body')])
if not paths:
    raise SystemExit('No saved API responses found; no network call was made.')
for path in paths:
    result = json.loads(path.read_text(encoding='utf-8'))
    passage = next(row for row in rows if row['id'] == result['passage']['id'])
    result['interlinear'] = interlinear_reading(result)
    token = next(row for row in result['interlinear']['readings'][0]['tokens'] if row['kind'] == 'word')
    report = {'file': path.name, 'form': token['text'], 'candidate_meanings': len(token.get('candidate_meanings', [])),
              'selection_basis': token.get('selection_basis'),
              'gloss_alternative_counts': [len(row.get('gloss', {}).get('alternatives', [])) for row in token.get('candidate_meanings', [])],
              'morphology_decisions': [(row.get('status'), row.get('decision', {}).get('decision_stage'), row.get('decision', {}).get('warnings')) for row in result.get('ranking', {}).get('items', [])]}
    try:
        packet = sense_packet(passage, result, token)
        report.update(ready=True, choices=len(packet['candidates']), chars=len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))))
    except Exception as exc:
        report.update(ready=False, error=str(exc))
    print(json.dumps(report, ensure_ascii=True))
