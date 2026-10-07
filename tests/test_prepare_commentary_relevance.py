"""Comparison preparation never changes facts or calls a network provider."""
from copy import deepcopy
import json

import pytest

from scripts.prepare_commentary_relevance import (
    BASE, ROOT, captured_request, encoded, exact_delta, sha,
)

PREPARED = ROOT / 'runtime/lexical-relevance-comparison-03'


@pytest.mark.parametrize('case', [0, 2])
def test_frozen_pair_retains_complete_inventory_and_only_bounded_delta(case):
    old = json.loads((BASE / f'{case}-commentary_only.packet.json').read_bytes())
    new = json.loads((PREPARED / f'{case}-relevance.packet.json').read_bytes())
    delta = exact_delta(old, new)
    assert delta['source_candidates_byte_equal'] is True
    assert old['inventory_sha256'] == new['inventory_sha256']
    assert old['morphology_alternatives'] == new['morphology_alternatives']
    for key in ('text', 'scope_text', 'entry_id', 'supporting_candidate_ids'):
        assert [r.get(key) for r in old['candidates']] == [r.get(key) for r in new['candidates']]


@pytest.mark.parametrize('mutation', ['candidate', 'syntax', 'instruction'])
def test_unreviewed_semantic_packet_changes_are_rejected(mutation):
    old = json.loads((BASE / '0-commentary_only.packet.json').read_bytes())
    new = json.loads((PREPARED / '0-relevance.packet.json').read_bytes())
    if mutation == 'candidate':
        new['candidates'][0]['text'] = 'invented'
    elif mutation == 'syntax':
        new['selected_morphology']['lemma'] = 'invented'
    else:
        new['constraints'][0] = 'invented'
    with pytest.raises(ValueError):
        exact_delta(old, new)


def test_offline_provider_body_matches_frozen_request_and_not_credentials(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'MUST_NOT_APPEAR')
    packet = json.loads((PREPARED / '0-relevance.packet.json').read_bytes())
    raw = captured_request(packet, 'jev-1.13.0')
    assert b'MUST_NOT_APPEAR' not in raw
    assert b'offline-serialization-only' not in raw
    assert raw == (PREPARED / '0-relevance.request.json').read_bytes()
    assert json.loads(raw)['state'] == packet


def test_preparation_manifest_hashes_all_frozen_bytes():
    manifest = json.loads((PREPARED / 'manifest.json').read_bytes())
    assert manifest['maximum_new_provider_calls'] == 2
    assert manifest['maximum_attempts_per_case'] == 1
    assert manifest['execution_authorized'] is False
    assert manifest['retries_permitted'] is False
    for row in manifest['cases']:
        assert sha((PREPARED / row['packet_file']).read_bytes()) == row['packet_sha256']
        assert sha((PREPARED / row['request_file']).read_bytes()) == row['request_sha256']
        assert len(json.loads((PREPARED / row['packet_file']).read_bytes())['candidates']) == row['choices']
