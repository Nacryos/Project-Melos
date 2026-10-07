#!/usr/bin/env python3
"""Audit every raw proposal without accepting any failed literal evidence.

Useful while independent packet reviews are arriving. Missing packets remain
explicitly unreviewed. This report makes no semantic verification claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_visual_annotations import read_json, validate_decision


def audit(packets, raw_dir):
    sources, expected = {}, {}
    for path in sorted(Path(packets).glob('packet-*.json')):
        greek = [row for row in read_json(path) if row['kind'] == 'text' and row['language'] == 'grc']
        if greek:
            expected[path.stem] = {row['id'] for row in greek}
            sources.update({row['id']: row for row in greek})
    report = {'scope_records': len(sources), 'missing_packets': [], 'packets': {}, 'errors': []}
    if not sources:
        report['errors'].append({'error': 'No Greek source records found in frozen packets'})
    for packet, ids in expected.items():
        path = Path(raw_dir) / f'{packet}.proposals.json'
        if not path.exists():
            report['missing_packets'].append(packet)
            continue
        try:
            raw = read_json(path)
        except (ValueError, OSError) as error:
            report['errors'].append({'packet': packet, 'error': str(error)})
            continue
        received = [row['id'] for row in raw['decisions']]
        if set(received) != ids or len(received) != len(set(received)):
            report['errors'].append({'packet': packet, 'error': 'coverage mismatch',
                'missing': sorted(ids-set(received)), 'extra': sorted(set(received)-ids)})
        counts = Counter()
        for decision in raw['decisions']:
            try:
                valid = validate_decision(decision, sources)
                counts[valid['status']] += 1
                counts.update(label['theme'] for label in valid['labels'])
            except (ValueError, KeyError, TypeError) as error:
                report['errors'].append({'packet': packet, 'id': decision.get('id'), 'error': str(error)})
        report['packets'][packet] = dict(counts)
    report['literal_validation_passed'] = not report['errors'] and not report['missing_packets']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packets', type=Path, default=ROOT / '.benchmarks/visual-themes/packets')
    parser.add_argument('--raw', type=Path, default=ROOT / 'data/annotations/visual-themes/raw')
    args = parser.parse_args()
    result = audit(args.packets, args.raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['literal_validation_passed'] else 1)
