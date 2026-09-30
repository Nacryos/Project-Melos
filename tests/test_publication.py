"""Public deployment must not expose local-only fixtures through alternate routes."""
import json
import sqlite3
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_api import client
from backend import server
from backend.evidence import EvidenceIndex
from backend.morphology import Morphology
from backend.publication import record_allowed
from backend.publication import accepted_ids


@pytest.fixture
def public_client(client, monkeypatch):
    monkeypatch.delenv('MELOS_PUBLICATION_POLICY',raising=False)
    with sqlite3.connect(server.DB) as con:
        con.execute("UPDATE passages SET source='perseus',data=json_set(data,'$.source','perseus','$.license','unknown')")
        con.execute("UPDATE passages SET data=json_set(data,'$.license','CC BY-SA 4.0') WHERE id IN ('p1','t1')")
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT','1')
    server.corpus_statistics.cache_clear()
    return client


def test_public_navigation_direct_ids_and_counts(public_client):
    status=public_client.get('/api/status').json()
    assert status['passages']==2
    assert status['works']==2
    assert sum(row['count'] for row in status['sources'])==2
    assert any('Kaikki' in warning for warning in status['warnings'])
    assert any('Structured evidence' in warning for warning in status['warnings'])
    assert public_client.get('/api/passage',params={'id':'p2'}).status_code==404
    result=public_client.get('/api/passage',params={'id':'p1'}).json()
    assert result['next_id'] is None
    assert {r['id'] for r in result['related']}=={'t1'}
    assert result['license']=='CC BY-SA 4.0'
    works=public_client.get('/api/works').json()['works']
    assert sum(w['count'] for w in works)==2
    for work in works:
        rows=public_client.get('/api/passages',params={'work_id':work['id']}).json()
        assert rows['total']==1
        assert all(row['id'] in {'p1','t1'} for row in rows['results'])
    authors=public_client.get('/api/authors').json()['authors']
    assert sum(row['count'] for row in authors)==2
    assert public_client.get('/api/sources').json()['reports']==[]


def test_public_search_word_and_usage_do_not_leak(public_client,monkeypatch):
    class Sem:
        def search(self,*a,**kw):
            return [{'id':'p2','score':1},{'id':'p1','score':0.5}]
        def vectors_for(self,ids):
            raise RuntimeError('fixture has no vectors')
    monkeypatch.setattr(server,'semantic_service',lambda:Sem())
    for mode in ('words','forms','themes','hybrid'):
        response=public_client.get('/api/search',params={'q':'μοῦσα','mode':mode,'include_reference':'true'})
        assert response.status_code==200,response.text
        assert all(r['id'] in {'p1','t1'} for r in response.json()['results'])
    word=public_client.get('/api/word',params={'form':'μοῦσα','passage_id':'p2'}).json()
    assert word['context'] is None
    assert all(r['id'] in {'p1','t1'} for r in word['occurrences'])
    assert word['structured_evidence']['claims']==[]
    usage=public_client.get('/api/usage-space',params={'q':'μοῦσα'}).json()
    assert all(p['id'] in {'p1','t1'} for p in usage['points'])


def test_public_evidence_and_merged_wiktionary_fail_closed(public_client):
    for params in ({'form':'μοῦσα'},{'passage_id':'p2'},{'claim_id':'restricted#form:1'}):
        payload=public_client.get('/api/evidence',params=params).json()
        assert payload['ready'] is False
        assert payload['claims']==[]
    assert public_client.get('/api/claim',params={'id':'restricted#form:1'}).status_code==503
    assert public_client.get('/api/wiktionary',params={'form':'μοῦσα'}).json()['ready'] is False
    with pytest.raises(RuntimeError,match='redistribution'):
        EvidenceIndex('nonexistent.sqlite').get_claim('restricted')


def test_morphology_public_source_allowlist(tmp_path,monkeypatch):
    monkeypatch.delenv('MELOS_PUBLICATION_POLICY',raising=False)
    entries=tmp_path/'entries.jsonl'
    forms=tmp_path/'forms.jsonl'
    entries.write_text('\n'.join(json.dumps(row) for row in [
        {'lemma':'μοῦσα','source':'PerseusDL LSJ TEI','license':'CC-BY-SA-4.0'},
        {'lemma':'μοῖρα','source':'Perseus Autenrieth TEI via Homerica','license':'unknown'},
    ]),encoding='utf-8')
    forms.write_text('',encoding='utf-8')
    monkeypatch.setenv('MELOS_PUBLIC_DEPLOYMENT','1')
    assert Morphology(entries,forms).counts()['entries']==1
    monkeypatch.setenv('MELOS_PUBLICATION_POLICY','source-labels')
    assert Morphology(entries,forms).counts()['entries']==2
    monkeypatch.delenv('MELOS_PUBLIC_DEPLOYMENT')
    assert Morphology(entries,forms).counts()['entries']==2
    assert not record_allowed({'source':'unknown-new-source','license':'CC-BY-SA-4.0'})
    assert not record_allowed({'source':'perseus','license':'public_domain_us'})


def test_public_id_cache_concurrency_and_database_change(public_client):
    # Concurrent connections share one immutable allowlist, not request-local scans.
    def load():
        with sqlite3.connect(server.DB) as con:
            return accepted_ids(con,server.DB)
    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots=list(pool.map(lambda _:load(),range(4)))
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert snapshots[0]==frozenset({'p1','t1'})
    before=server.DB.stat()
    with sqlite3.connect(server.DB) as con:
        con.execute("UPDATE passages SET data=json_set(data,'$.license','unknown') WHERE id='p1'")
    # Explicitly separate timestamp ticks on coarse filesystems used by CI.
    os.utime(server.DB,ns=(before.st_atime_ns,before.st_mtime_ns+1_000_000_000))
    after=load()
    assert after is not snapshots[0]
    assert after==frozenset({'t1'})
    assert public_client.get('/api/passage',params={'id':'p1'}).status_code==404
    assert public_client.get('/api/status').json()['passages']==1


def test_explicit_source_labels_keeps_public_security_and_original_rights(public_client,monkeypatch):
    monkeypatch.setenv('MELOS_PUBLICATION_POLICY','source-labels')
    status=public_client.get('/api/status').json()
    assert status['passages']==12
    assert status['publication_policy']=='source-labels'
    assert not any('Kaikki' in warning for warning in status['warnings'])
    result=public_client.get('/api/passage',params={'id':'p2'}).json()
    assert result['license']=='unknown'
    assert result['source']=='perseus'
    assert public_client.post('/api/classify-context',json={'form':'μοῦσα','passage_id':'p1'}).status_code==403
    assert public_client.get('/api/sources').json()['reports']==[]
    monkeypatch.setenv('MELOS_PUBLICATION_POLICY','typo')
    assert public_client.get('/api/passage',params={'id':'p2'}).status_code==404


def test_source_labels_evidence_still_checks_audited_hash(public_client,monkeypatch,tmp_path):
    from test_evidence import _claim,_stage
    from scripts.build_evidence import build
    root=tmp_path/'evidence-fixture'
    source=_stage(root,[_claim('fixture:allowed',{'type':'form','form':'μοῦσα'},'lemma',{'form':'μοῦσα'})])
    build(root,root/'data/evidence.sqlite')
    monkeypatch.setattr(server,'ROOT',root)
    monkeypatch.setenv('MELOS_PUBLICATION_POLICY','source-labels')
    result=public_client.get('/api/claim',params={'id':'fixture:allowed'})
    assert result.status_code==200,result.text
    assert result.json()['evidence'][0]['source_url']=='https://example.org/synthetic-fixture'
    source.write_text(source.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    response=public_client.get('/api/claim',params={'id':'fixture:allowed'})
    assert response.status_code==503
    assert 'changed' in response.json()['detail']


def test_source_labels_wiktionary_still_checks_audited_hash(public_client,monkeypatch):
    from test_wiktionary import WiktionaryLookupTests
    from backend.wiktionary import WiktionaryLookup,build_index
    fixture=WiktionaryLookupTests()
    fixture.setUp()
    opened=[]
    try:
        build_index(fixture.source,fixture.audit,fixture.index)
        def service(stamps):
            lookup=WiktionaryLookup(fixture.source,fixture.audit,fixture.index)
            opened.append(lookup)
            return lookup
        monkeypatch.setattr(server,'_wiktionary_service',service)
        monkeypatch.setenv('MELOS_PUBLICATION_POLICY','source-labels')
        result=public_client.get('/api/wiktionary',params={'form':'ὀρέων'}).json()
        assert result['ready'] is True
        assert result['results'][0]['license']=='test-only'
        fixture.source.write_text(fixture.source.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        result=public_client.get('/api/wiktionary',params={'form':'ὀρέων'}).json()
        assert result['ready'] is False
        assert any('SHA-256' in warning for warning in result['warnings'])
    finally:
        for lookup in opened:
            lookup.close()
        fixture.doCleanups()
