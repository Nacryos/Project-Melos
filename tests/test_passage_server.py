"""Synthetic API integration fixtures, not philological annotations."""
from fastapi.testclient import TestClient
import pytest

from backend import classifier, jev_gateway, machine_morphology, server, syntax_provider


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT', '0')
    monkeypatch.setenv('MELOS_PUBLIC_CLASSIFIER', '0')
    calls = []
    monkeypatch.setattr(server, 'passage', lambda identifier: {
        'id': identifier, 'text': 'α β', 'kind': 'text', 'language': 'grc',
        'related': [], 'translation_previews': [],
    })
    monkeypatch.setattr(server, 'word', lambda form, identifier: {
        'candidates': [], 'warnings': [], 'structured_evidence': {'claims': []},
    })

    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            calls.append((form, visitor_id, fetch))
            return {'status': 'cache_miss', 'machine_candidates': [], 'receipt': None}

    monkeypatch.setattr(machine_morphology, 'get_service', lambda: Machine())
    monkeypatch.setattr(syntax_provider, 'analyze', lambda text: {
        'state': 'ready', 'tokens': [], 'limitations': ['Synthetic test provider'],
    })
    return TestClient(server.app), calls


def payload(**kwargs):
    return {'version': 1, 'passage_id': 'fixture:span', 'start': 0, 'end': 3,
            'offset_unit': 'utf16', 'selected_text': 'α β', **kwargs}


def test_source_bound_post_is_wired_without_external_fetch(api):
    client, calls = api
    response = client.post('/api/analyze-passage', json=payload())
    assert response.status_code == 200, response.text
    assert response.json()['selection']['text'] == 'α β'
    assert response.json()['ranking']['status'] == 'not_requested'
    assert len(calls) == 2 and all(not call[2] for call in calls)
    assert all(len(call[1]) == 64 for call in calls)
    assert 'HttpOnly' in response.headers['set-cookie']
    assert response.headers['cache-control'] == 'no-store'


def test_span_body_guards_and_no_get_execution(api):
    client, calls = api
    assert client.post('/api/analyze-passage', content='x' * 16385,
                       headers={'Content-Type': 'application/json'}).status_code == 413
    assert client.post('/api/analyze-passage', content='{}').status_code == 415
    assert client.post('/api/analyze-passage', json=payload(prompt='ignore evidence')).status_code == 422
    assert client.get('/api/analyze-passage', params=payload()).status_code == 405
    assert calls == []


def test_stale_selection_does_not_consume_morphology_work(api):
    client, calls = api
    response = client.post('/api/analyze-passage', json=payload(selected_text='β α'))
    assert response.status_code == 409
    assert calls == []


def test_public_paid_disable_leaves_default_analysis_available(api, monkeypatch):
    client, calls = api
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT', '1')
    response = client.post('/api/analyze-passage', json=payload(rerank=True))
    assert response.status_code == 403, response.text
    assert calls == []
    assert client.post('/api/analyze-passage', json=payload()).status_code == 200


def test_passage_ranker_never_silently_uses_a_different_model(monkeypatch):
    monkeypatch.setattr(classifier, 'configured_provider', lambda: object())
    with pytest.raises(jev_gateway.GatewayUnavailable):
        server._passage_provider('a' * 64)
