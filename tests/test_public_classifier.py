"""Synthetic gateway integration checks; no corpus or live model calls."""
import pytest
from fastapi.testclient import TestClient
from backend import classifier, server
from test_classifier import PASSAGE, CANDIDATES


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT','1')
    monkeypatch.setenv('MELOS_PUBLIC_CLASSIFIER','1')
    monkeypatch.setenv('TYPESAFE_API_KEY','synthetic-test-secret-only')
    monkeypatch.setenv('MELOS_CLASSIFIER_STATE',str(tmp_path/'classifier.sqlite'))
    monkeypatch.setenv('MELOS_CLASSIFIER_DAILY_LIMIT','2')
    monkeypatch.setenv('MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT','1')
    class Provider:
        model = 'fixture-jev'
        calls = 0
        def decide(self,packet):
            self.calls += 1
            return {'choice':'parse_a','model':self.model}
    provider = Provider()
    monkeypatch.setattr(classifier,'configured_provider',lambda:provider)
    monkeypatch.setattr(server,'word',lambda form,pid:{
        'context':{**PASSAGE,'id':pid}, 'contextual_candidates':CANDIDATES,
        'structured_evidence':{'claims':[]}})
    return TestClient(server.app),provider


def test_public_cache_session_limit_and_no_secret(enabled):
    client,provider=enabled
    payload={'form':'α','passage_id':'fixture:one'}
    first=client.post('/api/classify-context',json=payload)
    assert first.status_code==200,first.text
    assert first.json()['status']=='proposed'
    assert first.json()['cache_hit'] is False
    assert 'HttpOnly' in first.headers['set-cookie']
    assert 'Secure' in first.headers['set-cookie']
    # HTTPS is required for browser session cookies in public mode.
    cookie=first.headers['set-cookie'].split(';')[0]
    headers={'Cookie':cookie,'X-Forwarded-For':'203.0.113.1'}
    again=client.post('/api/classify-context',json=payload,headers=headers)
    assert again.json()['cache_hit'] is True
    limited=client.post('/api/classify-context',json={**payload,'passage_id':'fixture:two'},
                        headers={**headers,'X-Forwarded-For':'203.0.113.2'})
    assert limited.status_code==429,limited.text
    assert 'retry-after' in limited.headers
    assert provider.calls==1
    assert 'synthetic-test-secret-only' not in first.text+first.headers['set-cookie']


def test_public_rejects_large_and_extra_requests_before_provider(enabled):
    client,provider=enabled
    assert client.post('/api/classify-context',content='x'*2049,
                       headers={'Content-Type':'application/json'}).status_code==413
    assert client.post('/api/classify-context',json={'form':'α','passage_id':'p','prompt':'ignored?'}).status_code==422
    assert client.post('/api/classify-context',content='{}').status_code==415
    assert provider.calls==0


def test_public_disable_switch_and_missing_key_fail_closed(enabled,monkeypatch):
    client,provider=enabled
    monkeypatch.delenv('TYPESAFE_API_KEY')
    monkeypatch.delenv('JEV_API_KEY',raising=False)
    assert client.post('/api/classify-context',json={}).status_code==503
    monkeypatch.setenv('MELOS_PUBLIC_CLASSIFIER','0')
    assert client.post('/api/classify-context',json={}).status_code==403
    assert provider.calls==0
