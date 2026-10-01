"""Synthetic API wiring/security checks; no external or paid requests."""
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import classifier, jev_gateway, machine_morphology, server


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('MELOS_PUBLIC_CLASSIFIER','0')
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT','0')
    monkeypatch.delenv('TYPESAFE_API_KEY',raising=False)
    monkeypatch.delenv('JEV_API_KEY',raising=False)

    class Service:
        calls = []
        receipt_calls = []
        result = {'status':'ok','form':'α','machine_candidates':[],
                  'receipt':{'id':'fixture-receipt'},'warnings':[]}
        def analyze(self,form,visitor_id,fetch=True):
            self.calls.append((form,visitor_id,fetch))
            return self.result
        def load_receipt(self,receipt_id,*,form):
            self.receipt_calls.append((receipt_id,form))
            return self.result
    service=Service()
    service.calls=[]
    service.receipt_calls=[]
    monkeypatch.setattr(machine_morphology,'get_service',lambda:service)
    monkeypatch.setattr(server,'word',lambda form,pid:{
        'context':{'id':pid,'text':form,'language':'grc','kind':'text'},
        'contextual_candidates':[], 'structured_evidence':{'claims':[]},
        'candidates':[{'id':'fixture-source','lemma':'α','source_url':'https://example.test/source'}]})
    return TestClient(server.app),service


def test_explicit_machine_endpoint_has_separate_signed_throttle_cookie(api):
    client,service=api
    result=client.post('/api/machine-analysis',json={'form':'α'})
    assert result.status_code==200
    assert len(service.calls)==1 and service.calls[0][0]=='α' and service.calls[0][2] is True
    cookie=result.headers['set-cookie']
    assert cookie.startswith('melos_morph_visitor=') and 'HttpOnly' in cookie
    assert 'melos_visitor=' not in cookie
    first_visitor=service.calls[0][1]
    assert len(first_visitor)==64
    client.post('/api/machine-analysis',json={'form':'α'},headers={'X-Forwarded-For':'203.0.113.44'})
    assert service.calls[1][1]==first_visitor
    client.cookies.clear()
    client.post('/api/machine-analysis',json={'form':'α'},
                headers={'Cookie':'melos_morph_visitor='+'a'*32+'.forged'})
    assert service.calls[2][1]!=hashlib.sha256(('a'*32).encode()).hexdigest()


def test_machine_endpoint_body_guards_precede_service(api):
    client,service=api
    assert client.post('/api/machine-analysis',content='x'*2049,
                       headers={'Content-Type':'application/json'}).status_code==413
    assert client.post('/api/machine-analysis',content='{}').status_code==415
    assert client.post('/api/machine-analysis',json={'form':'α','candidates':[]}).status_code==422
    assert client.post('/api/machine-analysis',json={'form':'α','url':'https://example.test'}).status_code==422
    assert not service.calls


def test_non_ascii_cookie_signature_is_replaced_not_a_server_error(api):
    client,service=api
    cookie=('melos_morph_visitor='+'a'*32+'.').encode()+b'\xe9'
    response=client.post('/api/machine-analysis',json={'form':'α'},headers=[(b'cookie',cookie)])
    assert response.status_code==200
    assert service.calls[0][1]!=hashlib.sha256(('a'*32).encode()).hexdigest()


@pytest.mark.parametrize('status,code',[('invalid_form',422),('rate_limited',429),
    ('busy',409),('cache_full',503),('disabled',503),('upstream_error',502),
    ('invalid_response',502),('cache_miss',404),('no_analyses',200)])
def test_machine_failures_keep_explicit_status(api,status,code):
    client,service=api
    service.result={'status':status,'machine_candidates':[],'warnings':['Synthetic status']}
    response=client.post('/api/machine-analysis',json={'form':'α'})
    assert response.status_code==code and response.json()['status']==status
    if code in (409,429):
        assert response.headers['retry-after']=='60'


def test_missing_passage_never_fetches_machine(api,monkeypatch):
    client,service=api
    connection=sqlite3.connect(':memory:',check_same_thread=False)
    connection.execute('CREATE TABLE passages(id TEXT)')
    monkeypatch.setattr(server,'connect',lambda:connection)
    try:
        response=client.post('/api/machine-analysis',json={'form':'α','passage_id':'missing'})
        assert response.status_code==404 and not service.calls
    finally:
        connection.close()


@pytest.mark.parametrize('extra',[
    {'candidate_basis':'machine'},
    {'machine_receipt_id':'fixture'},
    {'candidate_basis':'source','machine_receipt_id':'fixture'},
    {'candidate_basis':'invented'},
    {'candidate_basis':'machine','machine_receipt_id':'fixture','machine_candidates':[]},
])
def test_cross_basis_and_client_candidates_rejected(api,extra):
    client,service=api
    result=client.post('/api/classify-context',json={'form':'α','passage_id':'p',**extra})
    assert result.status_code==422
    assert not service.receipt_calls and not service.calls


def test_invalid_machine_receipt_cannot_reach_provider(api,monkeypatch):
    client,service=api
    service.result={'status':'invalid_receipt','warnings':['Receipt invalid.']}
    def forbidden():
        raise AssertionError('Provider must not be constructed')
    monkeypatch.setattr(classifier,'configured_provider',forbidden)
    result=client.post('/api/classify-context',json={'form':'α','passage_id':'p',
        'candidate_basis':'machine','machine_receipt_id':'fixture'})
    assert result.status_code==422
    assert service.receipt_calls==[('fixture','α')] and not service.calls


def test_machine_route_passes_reloaded_inventory_and_original_source_guards(api,monkeypatch):
    client,service=api
    # Synthetic transport contracts only; cryptographic/parser verification is
    # separately exercised against actual saved response fixtures.
    service.result={**service.result,'machine_candidates':[{'id':'fixture-machine'}]}
    observed={}
    def capture(form,passage,**kwargs):
        observed.update(kwargs)
        return {'status':'machine_proposed','warnings':[]}
    monkeypatch.setattr(classifier,'classify_context',capture)
    result=client.post('/api/classify-context',json={'form':'α','passage_id':'p',
        'candidate_basis':'machine','machine_receipt_id':'fixture'})
    assert result.status_code==200 and result.json()['candidate_origin']=='machine_analysis_receipt'
    assert observed['candidates']==service.result['machine_candidates']
    assert observed['machine_validation']==service.result
    assert observed['source_guard_candidates'][0]['id']=='fixture-source'
    assert service.receipt_calls==[('fixture','α')] and not service.calls


def test_default_source_route_never_loads_machine_receipt(api,monkeypatch):
    client,service=api
    observed={}
    def capture(form,passage,**kwargs):
        observed.update(kwargs)
        return {'status':'abstained','warnings':[]}
    monkeypatch.setattr(classifier,'classify_context',capture)
    result=client.post('/api/classify-context',json={'form':'α','passage_id':'p'})
    assert result.status_code==200
    assert 'machine_validation' not in observed and 'source_guard_candidates' not in observed
    assert not service.receipt_calls and not service.calls


def test_machine_route_retains_unproven_incomplete_source_in_guard_inventory(api,monkeypatch):
    client,service=api
    blocked={'id':'fixture-incomplete','candidate_kind':'grammatical_analysis',
             'lemma':'α','analysis':'synthetic branch','claim_ids':['missing-proof'],
             'source_projection_status':'incomplete_explicit_alternatives'}
    monkeypatch.setattr(server,'word',lambda form,pid:{
        'context':{'id':pid,'text':form,'language':'grc','kind':'text'},
        'contextual_candidates':[blocked], 'structured_evidence':{'claims':[]}})
    seen={}
    original=classifier.classify_context
    # The adapter is mocked here to isolate server inventory transport. The
    # real classifier's source guard still must abstain before a provider.
    from copy import deepcopy
    machine={'id':'fixture-machine','candidate_kind':'machine_analysis'}
    service.result={**service.result,'machine_candidates':[machine]}
    monkeypatch.setattr(classifier,'_validated_machine_inventory',
        lambda form,candidates,validation:(deepcopy(service.result),None))
    def capture(form,passage,**kwargs):
        seen.update(kwargs)
        return original(form,passage,**kwargs)
    monkeypatch.setattr(classifier,'classify_context',capture)
    def forbidden():
        raise AssertionError('Incomplete source inventory must not reach provider')
    monkeypatch.setattr(classifier,'configured_provider',forbidden)
    response=client.post('/api/classify-context',json={'form':'α','passage_id':'p',
        'candidate_basis':'machine','machine_receipt_id':'fixture'})
    assert response.status_code==200
    assert seen['source_guard_candidates']==[blocked]
    assert response.json()['decision_stage']=='preflight'
    assert response.json()['status']=='abstained'
    assert response.json()['packet']['incomplete_source_projections'][0]['id']==blocked['id']
