"""Verify actual editorial API outputs against the approved printed source.

Read-only requests: no morphology fetches, ranking, or source-data edits.
This tests source binding and transport, not correctness of interpretations.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.editorial_readings import editorial_readings
from scripts.audit_alcaeus_occurrences import Receipts, blocks, chunks, save, sha


def verify_projection(record, request, result):
    text = record['text']
    start, end = request['start'], request['end']
    assert request['rerank'] is False and request['fetch_machine'] is False
    assert result['selection']['text'] == text[start:end]
    projected = result['editorial_analysis']
    assert projected['passage_id'] == record['id']
    assert projected['source_text_sha256'] == sha(text)
    assert projected['selection'] == {
        'start': start, 'end': end, 'offset_unit': 'codepoint',
        'text_sha256': sha(text[start:end])}
    assert projected['limits']['machine_fetches'] == 0
    assert projected['ranking_status'] == 'not_requested'
    expected = [r for r in editorial_readings(record)['rows'] if start <= r['start'] < r['end'] <= end]
    actual = projected['rows']
    assert [r['id'] for r in actual] == [r['id'] for r in expected]
    available = 0
    for source, row in zip(expected, actual):
        for key, value in source.items():
            assert row[key] == value, f'Changed editorial source field: {key}'
        analysis = row.get('analysis', {})
        if analysis.get('status') != 'available':
            continue
        available += 1
        assert source['lookup_eligible'] is True
        assert analysis['lookup_form'] == source['projected_text']
        assert analysis['lookup_scope'] == 'general_form_no_passage'
        assert analysis['ranking_status'] == analysis['syntax_status'] == 'not_requested'
        assert all(analysis[key] is False for key in ('word_attestation', 'occurrence_verified', 'raw_surface_match'))
        assert analysis['candidate_meanings']
        for candidate in analysis['candidate_meanings']:
            assert candidate['basis'] == 'conditional_editorial_lookup'
            assert all(candidate[key] is False for key in ('word_attestation', 'occurrence_verified', 'raw_surface_match'))
    return {'source_rows': len(actual), 'eligible': sum(r['lookup_eligible'] for r in actual),
            'available': available, 'source_text_sha256': sha(text)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--machine-bundle', type=Path)
    args = parser.parse_args()
    source_path = ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl'
    records = [json.loads(line) for line in source_path.read_text(encoding='utf-8').splitlines()]
    receipts = Receipts(args.origin, args.output / 'receipts', timeout=180)
    expected_machine, seen_machine = {}, set()
    if args.machine_bundle:
        from deploy.sync_morphology_receipts import read_bundle
        for _, receipt_id, _, _, info in read_bundle(args.machine_bundle):
            expected_machine[info['form']] = {'receipt_id': receipt_id, 'candidate_count': info['candidates']}
    results = []
    for record in records:
        for block in blocks(record):
            for a, b in chunks(record['text'][block['start']:block['end']]):
                start, end = block['start'] + a, block['start'] + b
                request = {'version': 1, 'passage_id': record['id'], 'start': start, 'end': end,
                           'offset_unit': 'codepoint', 'selected_text': record['text'][start:end],
                           'rerank': False, 'fetch_machine': False}
                result, receipt = receipts.call('/api/analyze-passage', payload=request)
                for token in result['tokens']:
                    expected = expected_machine.get(token['text'])
                    if expected is None:
                        continue
                    machine = token.get('machine') or {}
                    assert machine['status'] == 'ok', 'Audited parser receipt not available through passage analysis'
                    assert machine['receipt']['id'] == expected['receipt_id']
                    assert len(machine['machine_candidates']) == expected['candidate_count']
                    seen_machine.add(token['text'])
                results.append({'passage_id': record['id'], 'receipt': receipt,
                                **verify_projection(record, request, result)})
    assert seen_machine == set(expected_machine), 'Not all imported source forms were verified'
    report = {'verdict': 'PASS', 'origin': args.origin, 'source_sha256': sha(source_path.read_bytes()),
              'scope': 'Source-bound conditional editorial API transport, not accuracy certification',
              'paid_calls': 0, 'machine_fetches_requested': 0, 'results': results,
              'machine_bundle_sha256': sha(args.machine_bundle.read_bytes()) if args.machine_bundle else None,
              'verified_cached_forms': sorted(seen_machine),
              'totals': {key: sum(row[key] for row in results) for key in ('source_rows', 'eligible', 'available')}}
    save(args.output / 'report.json', report)
    print(json.dumps({'report': str(args.output / 'report.json'), 'totals': report['totals']}))


if __name__ == '__main__':
    main()
