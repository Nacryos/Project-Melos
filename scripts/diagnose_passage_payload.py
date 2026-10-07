"""Measure a saved passage-analysis response without making API/model calls.

The optional source catalog is an in-memory transport experiment, not a change
to the API. Its round trip must reproduce the *exact* saved JSON bytes. Output
contains counts, hashes and sizes only; it never copies passage/dictionary text.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BODY = (ROOT / 'runtime/lexical-release-g/root-editorial/receipts'
                / '0ab76a479f481af4a4f5c824e2b5bb67a265879151187d3d127f47c6adef0fca.body')
DEFAULT_OUTPUT = ROOT / '.benchmarks/lexical-g-payload/diagnosis.json'
MAX_BODY_BYTES = 64 * 1024 * 1024
REF_KEY = '__melos_source_catalog_ref__'
CATALOG_FIELDS = frozenset({'dictionary_senses', 'entry_text', 'rendered_entry_text',
                            'gloss', 'alternatives', 'candidate_meanings'})
MIN_CATALOG_BYTES = 256


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def value_size(value):
    return len(encoded(value))


def field_sizes(rows):
    totals = Counter()
    for row in rows:
        if isinstance(row, dict):
            totals.update({key: value_size(value) for key, value in row.items()})
    return dict(sorted(totals.items(), key=lambda item: -item[1]))


def catalog_trial(body, raw):
    """Deduplicate repeated *exact* JSON subtrees and prove byte round trip."""
    occurrences = Counter()
    sizes = {}
    stack = [body]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if len(item) == 1 and REF_KEY in item:
                raise ValueError('Saved source already uses the reserved catalog reference shape.')
            for key, value in item.items():
                if key in CATALOG_FIELDS:
                    content = encoded(value)
                    if len(content) >= MIN_CATALOG_BYTES:
                        digest = sha(content)
                        occurrences[digest] += 1
                        sizes[digest] = len(content)
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    eligible = {digest for digest, count in occurrences.items() if count >= 2}
    catalog = {}
    reference_count = 0

    def pack(item):
        nonlocal reference_count
        if isinstance(item, dict):
            packed = {}
            for key, value in item.items():
                content = encoded(value) if key in CATALOG_FIELDS else b''
                digest = sha(content) if len(content) >= MIN_CATALOG_BYTES else None
                if digest in eligible:
                    if digest not in catalog:
                        catalog[digest] = pack(value)
                    packed[key] = {REF_KEY: digest}
                    reference_count += 1
                else:
                    packed[key] = pack(value)
            return packed
        if isinstance(item, list):
            return [pack(value) for value in item]
        return item

    payload = pack(body)
    envelope = {'schema': 'diagnostic-source-catalog-v1', 'payload': payload,
                'source_catalog': catalog}
    wire = encoded(envelope)
    # Decode after an actual JSON serialization boundary, not merely from the
    # original Python objects. Nested catalog references are resolved too.
    received = json.loads(wire)
    received_catalog = received['source_catalog']

    def hydrate(item):
        if isinstance(item, dict):
            if len(item) == 1 and REF_KEY in item:
                return hydrate(received_catalog[item[REF_KEY]])
            return {key: hydrate(value) for key, value in item.items()}
        if isinstance(item, list):
            return [hydrate(value) for value in item]
        return item

    reconstructed = encoded(hydrate(received['payload']))
    if reconstructed != raw:
        raise AssertionError('Catalog reconstruction differs from original saved bytes.')
    return {
        'catalog_fields': sorted(CATALOG_FIELDS), 'minimum_field_bytes': MIN_CATALOG_BYTES,
        'catalog_items': len(catalog), 'references': reference_count,
        'eligible_repeated_values': len(eligible),
        'nested_duplicate_field_bytes_nonadditive': sum(
            (occurrences[digest] - 1) * sizes[digest] for digest in eligible),
        'envelope_bytes': len(wire), 'saved_bytes': len(raw) - len(wire),
        'gzip_level1_original_bytes': len(gzip.compress(raw, compresslevel=1)),
        'gzip_level1_envelope_bytes': len(gzip.compress(wire, compresslevel=1)),
        'roundtrip_exact_bytes': True, 'roundtrip_sha256': sha(reconstructed),
    }


def diagnose(body_path):
    body_path = Path(body_path).resolve(strict=True)
    raw = body_path.read_bytes()
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError('Saved body exceeds the bounded diagnostic limit.')
    body = json.loads(raw)
    if not isinstance(body, dict) or not isinstance(body.get('tokens'), list):
        raise ValueError('Expected a saved passage-analysis JSON response.')
    if encoded(body) != raw:
        raise ValueError('Saved body is not the canonical compact response encoding.')
    receipt_path = body_path.with_suffix('.json')
    receipt_match = None
    receipt_seconds = None
    receipt_sha256 = None
    if receipt_path.is_file():
        receipt_raw = receipt_path.read_bytes()
        receipt_sha256 = sha(receipt_raw)
        receipt = json.loads(receipt_raw)
        receipt_match = (receipt.get('raw_body_sha256') == sha(raw)
                         and receipt.get('raw_body_file') == body_path.name
                         and receipt.get('http_status') == 200
                         and sha(encoded(receipt.get('body'))) == sha(raw))
        receipt_seconds = receipt.get('seconds')
        if not receipt_match:
            raise ValueError('Saved HTTP receipt does not bind this body.')
    tokens = body['tokens']
    reading_tokens = [token for reading in (body.get('interlinear') or {}).get('readings') or []
                      for token in reading.get('tokens') or []]
    source_candidates = [row for token in tokens for row in token.get('source_candidates') or []]
    lexicon_entries = [row for token in tokens for row in token.get('lexicon_entries') or []]
    candidate_meanings = [row for token in reading_tokens for row in token.get('candidate_meanings') or []]
    top_sizes = {key: value_size(value) for key, value in body.items()}
    return {
        'schema': 'melos-saved-passage-payload-diagnosis-v1',
        'input': {'path': body_path.relative_to(ROOT).as_posix() if body_path.is_relative_to(ROOT) else str(body_path),
                  'sha256': sha(raw), 'bytes': len(raw),
                  'receipt_path': receipt_path.relative_to(ROOT).as_posix() if receipt_path.is_file() and receipt_path.is_relative_to(ROOT) else None,
                  'receipt_sha256': receipt_sha256,
                  'receipt_hash_status_200_match': receipt_match, 'receipt_seconds': receipt_seconds,
                  'passage_id': (body.get('passage') or {}).get('id'),
                  'passage_text_sha256': (body.get('passage') or {}).get('text_sha256'),
                  'selection_sha256': sha((body.get('selection') or {}).get('text', '').encode('utf-8'))},
        'counts': {'tokens': len(tokens), 'word_tokens': sum(token.get('kind') == 'word' for token in tokens),
                   'distinct_word_forms': len({token.get('text') for token in tokens if token.get('kind') == 'word'}),
                   'source_candidates': len(source_candidates), 'lexicon_entries': len(lexicon_entries),
                   'interlinear_tokens': len(reading_tokens), 'candidate_meanings': len(candidate_meanings),
                   'dictionary_lemma_lookups': (body.get('limits') or {}).get('dictionary_lemma_lookups'),
                   'machine_fetches': (body.get('limits') or {}).get('machine_fetches')},
        'non_overlapping_value_bytes': {
            'top_level': dict(sorted(top_sizes.items(), key=lambda item: -item[1])),
            'token_fields': field_sizes(tokens),
            'source_candidate_fields': field_sizes(source_candidates),
            'lexicon_entry_fields': field_sizes(lexicon_entries),
            'interlinear_token_fields': field_sizes(reading_tokens),
            'candidate_meaning_fields': field_sizes(candidate_meanings),
            'note': 'Fields within each named parent group are non-overlapping; groups at different nesting levels must not be summed.'},
        'lossless_catalog_trial': catalog_trial(body, raw),
        'transport_proposal': {
            'mode': 'opt-in source_catalog_v1; leave default response unchanged',
            'shape': 'Envelope contains payload and SHA-256-keyed exact source_catalog; repeated values become reserved references.',
            'client_contract': 'Validate catalog hashes and fully hydrate before existing rendering; reject missing/colliding references.',
            'server_contract': 'Build and rank from the unchanged full internal result, then compact only the serialized copy.',
            'source_contract': 'Retain every alternative, ID, scope, citation and original field; no meaning cap or inferred merge.',
            'latency_caveat': 'Wire compression/serialization savings do not establish lookup-time savings; instrument form lookups separately.'},
        'interpretation': ('This measures saved response bytes, not server CPU. '
                           'The catalog is an opt-in transport experiment; existing API behavior is unchanged.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--body', type=Path, default=DEFAULT_BODY)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = diagnose(args.body)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{report['input']['bytes']} saved bytes; catalog {report['lossless_catalog_trial']['envelope_bytes']} bytes; exact round trip PASS")


if __name__ == '__main__':
    main()
