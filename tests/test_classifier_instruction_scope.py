"""Offline QA21 instruction-only adoption; synthetic fixtures are not source facts."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import classifier


OLD_INSTRUCTION = "Which supplied candidate best fits this exact Greek passage? Select abstain for unresolved ambiguity, conflicts, missing evidence, or inadequate context. Never create a new reading or assume the author's literary dialect makes every form exclusive."
SCOPE_ADDITION = "Choose a provisional contextual grammatical hypothesis, not a certification of source-attested parsing. Lack of an explicit passage annotation alone does not require abstention when the supplied Greek context supports an existing candidate."


def request_body(module, packet, model):
    captured = []

    def capture(request, timeout):
        captured.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'model': model, 'answers': {
            'contextual_parse': {'type': 'choice', 'choice': 'abstain'}}}).encode())

    with patch.object(module, 'urlopen', capture):
        module.JevProvider(api_key='synthetic-unused-key', model=model).decide(packet)
    assert len(captured) == 1
    return captured[0]


def test_provider_instruction_is_exact_reviewed_addition_without_state_change():
    state = {'candidates': [{'id': 'synthetic', 'analysis': 'partial'}],
             'claims': [{'id': 'synthetic-proof', 'quote': 'Synthetic uncertain source.'}],
             'constraints': ['Do not infer attestation.']}
    original = deepcopy(state)
    body = request_body(classifier, state, 'synthetic-pinned-model')
    expected = OLD_INSTRUCTION.replace(' Select abstain', ' ' + SCOPE_ADDITION + ' Select abstain')
    assert body['questions']['contextual_parse']['instructions'] == expected
    assert body['state'] == state == original
    assert body['model'] == 'synthetic-pinned-model'
    assert set(body['questions']['contextual_parse']['criteria']) == {'synthetic', 'abstain'}


def test_production_wire_equals_all_five_frozen_qa21_new_requests():
    path = Path(__file__).resolve().parents[1] / 'data/staging/qa21-instruction-scope-eval-v1/packets.json'
    if not path.exists():
        pytest.skip('Source-bound QA21 artifacts are local, not corpus fixtures shipped with tests')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '54c6c1f6bd58abb52f808b5027eadb026f3d6f5db02f4eec73c08c1a1c74260d'
    cases = json.loads(raw)['cases']
    assert len(cases) == 5
    for case in cases:
        old, new = case['old_request'], case['new_request']
        body = request_body(classifier, old['state'], old['model'])
        assert classifier._state_json(body).encode() == classifier._state_json(new).encode()
        body['questions']['contextual_parse']['instructions'] = old['questions']['contextual_parse']['instructions']
        assert classifier._state_json(body).encode() == classifier._state_json(old).encode()


def test_empty_candidate_inventory_still_stops_before_provider():
    class Forbidden:
        def decide(self, packet):
            raise AssertionError('No-candidate request must not reach a provider')

    result = classifier.classify_context('synthetic',
        {'id': 'synthetic', 'text': 'synthetic', 'kind': 'text', 'language': 'grc'},
        [], [], provider=Forbidden())
    assert result['status'] == 'abstained'
    assert result['decision_stage'] == 'preflight'
