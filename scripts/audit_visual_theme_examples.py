"""Validate proposed aesthetic examples against the frozen source packets.

This validates quotations/IDs, not the model's interpretation of a landscape.
Never writes to the corpus or a production annotation table.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / '.benchmarks/visual-themes'


def folded(value):
    return re.sub(r'\s+', ' ', value).strip()


def main():
    accepted, rejected, coverage = [], [], []
    for packet_file in sorted((ROOT / 'packets').glob('packet-*.json')):
        records = json.loads(packet_file.read_text(encoding='utf-8'))
        by_id = {record['id']: record for record in records}
        review_file = ROOT / 'reviews' / packet_file.name
        if not review_file.exists():
            coverage.append({'packet': packet_file.stem, 'records': len(records), 'reviewed_records': None})
            continue
        review = json.loads(review_file.read_text(encoding='utf-8'))
        coverage.append({'packet': packet_file.stem, 'records': len(records),
                         'model_reported_reviewed_records': review.get('reviewed_records'),
                         'notes': review.get('notes')})
        for theme in review.get('themes', []):
            for example in theme.get('examples', []):
                record = by_id.get(example.get('id'))
                quote = example.get('quote', '')
                result = {'category': theme.get('category'), **example, 'packet': packet_file.stem}
                if not record or not quote or folded(quote) not in folded(record['text']):
                    rejected.append({**result, 'reason': 'Quote is not an exact source span after whitespace folding.'})
                    continue
                result.update({key: record.get(key) for key in ('author', 'citation', 'source_url', 'parent_id', 'language')})
                accepted.append(result)
    output = {'status': 'aesthetic suggestions only; not corpus annotations',
              'validation': 'IDs and quotations checked; interpretations remain model proposals',
              'coverage': coverage, 'accepted_examples': accepted, 'rejected_examples': rejected}
    (ROOT / 'validated-examples.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'accepted': len(accepted), 'rejected': len(rejected), 'coverage': [
        {key: value for key, value in item.items() if key != 'notes'} for item in coverage]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
