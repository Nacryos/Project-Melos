"""Synthetic transport fixtures only; no source content or network calls."""
import json

import pytest

from scripts.diagnose_passage_payload import catalog_trial, diagnose, encoded, sha


def test_catalog_trial_exactly_restores_nested_repeated_source_payloads():
    senses = [{'id': 'source-sense-1', 'text': 'synthetic ' + 'x' * 300}]
    entry = {'id': 'source-entry', 'dictionary_senses': senses,
             'entry_text': 'source excerpt ' + 'y' * 300}
    body = {'passage': {'id': 'fixture'}, 'tokens': [
        {'source_candidates': [entry, entry], 'lexicon_entries': [entry]},
        {'source_candidates': [entry], 'lexicon_entries': [entry]}]}
    raw = encoded(body)
    trial = catalog_trial(body, raw)
    assert trial['roundtrip_exact_bytes'] is True
    assert trial['roundtrip_sha256'] == sha(raw)
    assert trial['catalog_items'] >= 2
    assert trial['references'] >= 4
    assert trial['envelope_bytes'] < len(raw)
    assert body['tokens'][0]['source_candidates'][0]['dictionary_senses'] == senses


def test_catalog_trial_rejects_ambiguous_reserved_source_shape():
    body = {'tokens': [{'gloss': {'__melos_source_catalog_ref__': 'not-a-source-ref'}}]}
    with pytest.raises(ValueError, match='reserved catalog reference'):
        catalog_trial(body, encoded(body))


def test_receipt_hash_and_embedded_response_must_match(tmp_path):
    body = {'passage': {'id': 'fixture', 'text_sha256': 'a' * 64},
            'selection': {'text': 'synthetic'}, 'tokens': []}
    raw = encoded(body)
    path = tmp_path / 'fixture.body'
    path.write_bytes(raw)
    receipt = {'raw_body_sha256': sha(raw), 'raw_body_file': path.name,
               'http_status': 200, 'body': {'wrong': True}, 'seconds': 1}
    path.with_suffix('.json').write_text(json.dumps(receipt), encoding='utf8')
    with pytest.raises(ValueError, match='does not bind'):
        diagnose(path)
