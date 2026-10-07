"""Local source-only editorial UI replay; never requests models or deployment."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.editorial_readings import editorial_readings
from backend.editorial_analysis import analyze_editorial_readings
from backend.server import word


def main():
    source = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    output = ROOT / 'runtime/lexical-release-g/editorial-ui-replay.json'
    rows = []
    for line in source.read_text(encoding='utf-8').splitlines():
        passage = json.loads(line)
        passage['editorial_readings'] = editorial_readings(passage)
        text = passage['text']
        # Same default budget as the live API. Every selected original row
        # remains represented, including ineligible and budget-skipped rows.
        analysis = analyze_editorial_readings(passage, 0, len(text), word, max_lookups=16)
        rows.append({'passage': passage, 'response': {
            'passage': {'id': passage['id'], 'text_sha256': analysis['source_text_sha256']},
            'selection': {'text': text, 'start_utf16': 0, 'end_utf16': len(text.encode('utf-16-le'))//2},
            'editorial_analysis': analysis}})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'evaluation_scope': 'Source-only UI replay; no model calls or new source claims',
                                  'records': rows}, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'path': str(output), 'records': len(rows), 'eligible': sum(r['response']['editorial_analysis']['counts']['eligible'] for r in rows),
                      'available': sum(row.get('analysis', {}).get('status') == 'available' for r in rows for row in r['response']['editorial_analysis']['rows'])}))


if __name__ == '__main__':
    main()
