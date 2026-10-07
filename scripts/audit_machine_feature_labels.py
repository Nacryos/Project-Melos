"""Offline label coverage from archived morphology receipts; never fetches."""
import argparse
import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.machine_morphology import project
from backend.interlinear import canonical_features


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(receipt_exports=()):
    records, inputs = {}, []
    def add(identifier, metadata, raw, origin):
        if not isinstance(metadata, str):
            metadata = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if digest(metadata.encode()) != identifier:
            raise ValueError('Receipt metadata digest mismatch')
        parsed = json.loads(metadata)
        if digest(raw) != parsed['raw_sha256']:
            raise ValueError('Receipt raw digest mismatch')
        if identifier in records and records[identifier][:2] != (metadata, raw):
            raise ValueError('Conflicting receipt identity')
        records[identifier] = (metadata, raw, origin)
    if not receipt_exports:
        database = ROOT / 'runtime/alcaeus-morpheus-maintenance/machine.sqlite'
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            for identifier, metadata, raw in connection.execute('SELECT id,metadata,raw FROM receipts'):
                add(identifier, metadata, raw, database.relative_to(ROOT).as_posix())
        inputs.append({'path': str(database), 'sha256': digest(database.read_bytes())})
    sources = list(map(Path, receipt_exports)) or [ROOT / 'runtime/alcaeus-morpheus-maintenance/production-results.json']
    for path in sources:
        payload = json.loads(path.read_text(encoding='utf8'))
        rows = payload.get('entries') or (payload.get('journal') or {}).get('rows') or payload.get('receipts')
        if not isinstance(rows, list):
            raise ValueError('Unrecognized archived receipt envelope: ' + str(path))
        inputs.append({'path': str(path), 'sha256': digest(path.read_bytes())})
        for row in rows:
            metadata = row['metadata']
            if not isinstance(metadata, str):
                metadata = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            identifier = row.get('receipt_id') or row.get('id') or (row.get('result') or {}).get('receipt', {}).get('id')
            if not identifier:
                raise ValueError('Missing original receipt identifier')
            add(identifier, metadata, base64.b64decode(row['raw_base64'], validate=True), str(path))
    pairs, examples, statuses, candidate_count = Counter(), {}, Counter(), 0
    for identifier, (metadata, raw, origin) in sorted(records.items()):
        receipt = {'id': identifier, **json.loads(metadata)}
        form = receipt.get('source_form', receipt['request_form'])
        result = project(raw, form, receipt)
        statuses[result['status']] += 1
        for candidate in result.get('machine_candidates', []):
            before = deepcopy(candidate)
            canonical_features(candidate)
            if candidate != before:
                raise ValueError('Canonical adapter mutated source fields')
            candidate_count += 1
            for key, value in candidate.get('features', {}).items():
                pair = key, json.dumps(value, ensure_ascii=False, sort_keys=True)
                pairs[pair] += 1
                examples.setdefault(pair, {'receipt_id': identifier, 'candidate_id': candidate['id'],
                    'form': form, 'origin': origin})
    inventory = [{'field': key, 'raw_value': json.loads(value), 'count': count,
                  'canonical': canonical_features({'features': {key: json.loads(value)}}),
                  'source_example': examples[(key, value)]}
                 for (key, value), count in sorted(pairs.items())]
    return {'scope': 'literal archived parser labels, not validated philological readings',
            'network_calls': 0, 'inputs': inputs,
            'adapter_sha256': digest((ROOT / 'backend/interlinear.py').read_bytes()),
            'receipt_count': len(records), 'candidate_count': candidate_count,
            'receipt_statuses': dict(statuses), 'feature_pair_count': len(inventory),
            'all_source_features_preserved': True, 'inventory': inventory,
            'raw_only': [row for row in inventory if not row['canonical']],
            'raw_only_policy': 'Retain original engine dialect, declension, stem/derivation and morphological notes; no guessed expansion or exclusive author dialect.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipts', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.receipts)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({key: report[key] for key in ('receipt_count', 'candidate_count', 'feature_pair_count', 'receipt_statuses')}))
