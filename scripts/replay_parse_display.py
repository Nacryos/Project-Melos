"""Copy an existing real API replay into a bounded UI fixture; no model calls."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'runtime/lyric-context-eval/elthes-baseline/0.response.json'
TARGET = ROOT / 'tests/fixtures/elthes-parse-display.json'
data = json.loads(SOURCE.read_text(encoding='utf-8'))
token = data['tokens'][0]
fields = ('id', 'lemma', 'lemma_raw', 'matched_form', 'analysis', 'analysis_text',
          'features', 'match_kind', 'edit_distance', 'source', 'source_url',
          'homograph_id', 'lemma_identity', 'source_tags', 'source_raw_tags')
projection = {
    'source_replay': str(SOURCE.relative_to(ROOT)),
    'form': token['text'],
    'source_candidates': [{k: row[k] for k in fields if k in row}
                          for row in token['source_candidates']],
    'contextual_candidates': token['contextual_candidates'],
}
TARGET.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(TARGET)
