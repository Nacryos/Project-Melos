"""Synthetic QA19 runner fixtures only; no source corpus entries or paid calls."""
from __future__ import annotations

import json

import pytest

from backend import classifier
from scripts import run_exact_entry_sense_eval as qa19


def fixture(tmp_path, *, control=False):
    files = {}
    for relative in sorted(qa19.REQUIRED_INPUTS | {'data/staging/qa19/source-fixtures.json'}):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('source-fixtures.json'):
            path.write_bytes(qa19.receipt_io.encode({
                'schema_version': 1, 'artifact_type': 'qa19_homograph_source_evidence',
                'paid_calls': 0,
                'cases': [{'id': f'synthetic-case-{index}', 'form': 'λόγος',
                           'passage_id': f'synthetic-passage-{index}'} for index in range(3)],
                'accepted_sense_claims': [{'id': 'claim:sense', 'status': 'source_claim',
                                            'assertion_type': 'source_extraction'}]}))
        else:
            path.write_bytes(('SYNTHETIC ' + relative).encode())
        files[relative] = {'sha256': qa19.receipt_io.sha(path.read_bytes()),
                           'bytes': path.stat().st_size}
    cases, reviews = [], []
    for index in range(3 if control else 2):
        case_id = f'synthetic-case-{index}'
        passage = {'id': f'synthetic-passage-{index}', 'text': 'λόγος',
                   'author': 'Fixture', 'language': 'grc', 'kind': 'text'}
        candidate = {'id': 'choice:a', 'lemma': 'fixture-lemma', 'analysis': 'noun',
                     'claim_ids': ['claim:grammar'], 'source_references': [{
                         'id': 'choice:a:source_url', 'url': 'https://example.test/fixture',
                         'scope': 'candidate metadata; verify source scope'}]}
        old_state = {'form': 'λόγος', 'passage': passage, 'candidates': [candidate],
                     'claims': [{'id': 'claim:grammar'}], 'author_profile': [],
                     'dialect_rules': [], 'constraints': [], 'warnings': []}
        new_candidate = dict(candidate, entry_sense_claim_ids=['claim:sense'])
        new_state = dict(old_state, candidates=[new_candidate],
                         claims=[{'id': 'claim:grammar'}, {'id': 'claim:sense'}],
                         entry_sense_catalog={'claim:sense': {'claim_id': 'claim:sense',
                             'glosses': ['Synthetic test sense, not corpus data.']}},
                         entry_sense_reference_format=qa19.SENSE_REFERENCE_FORMAT)
        old_criteria = {'choice:a': {'candidate_id': 'choice:a', 'analysis': 'noun'},
                        'abstain': 'Fixture abstention'}
        new_criteria = {'choice:a': {**old_criteria['choice:a'],
                                    'entry_sense_claim_ids': ['claim:sense']},
                        'abstain': 'Fixture abstention'}
        def body(state, criteria):
            return {'model': 'fixture-pinned', 'state': state, 'questions': {'contextual_parse': {
                'type': 'choice', 'instructions': 'Same fixed fixture instructions.',
                'criteria': criteria}}}
        old_body, new_body = body(old_state,old_criteria), body(new_state,new_criteria)
        case = {'id': case_id, 'role': 'control' if index==2 else 'homograph_context',
                'form': 'λόγος', 'passage_id': passage['id'],
                'entry_sense_claim_ids': ['claim:sense'],
                'old_request': old_body, 'new_request': new_body}
        cases.append(case)
        reviews.append({'id': case_id, 'entry_sense_claim_ids': ['claim:sense'],
                        'requests': {arm: qa19.receipt_io.sha(qa19.receipt_io.encode(body,canonical=True))
                                     for arm, body in (('old',old_body),('new',new_body))},
                        'outcomes': {'choice:a': 'supported_proposal',
                                     'abstain': 'conservative_abstention'},
                        'default_outcome': 'unsupported_choice'})
    bundle = {'schema_version':1, 'artifact_type':qa19.ARTIFACT_TYPE,
              'source_fixture':'data/staging/qa19/source-fixtures.json',
              'input_files':files, 'baseline_revision':'fixture-baseline',
              'classifier_sha256':{'old':'a'*64,'new':'b'*64},
              'model':'fixture-pinned', 'cases':cases}
    packet_path = tmp_path / 'qa19-packets.json'
    packet_path.write_bytes(qa19.receipt_io.encode(bundle))
    rubric = {'schema_version':1,'artifact_type':qa19.REVIEW_TYPE,
              'review_status':'approved','packet_sha256':qa19.receipt_io.sha(packet_path.read_bytes()),
              'cases':reviews}
    rubric_path = tmp_path / 'qa19-rubric.json'
    rubric_path.write_bytes(qa19.receipt_io.encode(rubric))
    return packet_path, rubric_path


def fake_response(item, key):
    return {'model':item['model'], 'answers':{'contextual_parse':{
        'type':'choice','choice':'choice:a','confidence':.4}},
        'usage':{'input_tokens':30,'private_key':key}}


def rewrite_reviewed_packet(packet, rubric, mutate):
    bundle=json.loads(packet.read_bytes())
    mutate(bundle['cases'][0]['new_request'])
    packet.write_bytes(qa19.receipt_io.encode(bundle))
    review=json.loads(rubric.read_bytes())
    review['packet_sha256']=qa19.receipt_io.sha(packet.read_bytes())
    review['cases'][0]['requests']['new']=qa19.receipt_io.sha(qa19.receipt_io.encode(
        bundle['cases'][0]['new_request'],canonical=True))
    rubric.write_bytes(qa19.receipt_io.encode(review))


def test_dry_run_has_no_key_or_provider_access_and_reports_exact_sizes(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.delenv('JEV_API_KEY', raising=False)
    def forbidden(*args):
        raise AssertionError('No transport in dry-run')
    result = qa19.run(packet,rubric,root=tmp_path,modules={'old':classifier,'new':classifier},
                      transport=forbidden)
    assert result['mode']=='dry_run' and result['pending']==4 and result['max_attempts']==6
    assert len(result['request_bytes'])==len(result['state_chars'])==4
    assert not (tmp_path/qa19.RECEIPT_NAME).exists()


def test_six_attempt_cap_reservation_no_retry_and_real_postflight_claim_ids(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path, control=True)
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-private-key')
    sent=[]
    def transport(item,key):
        receipt=json.loads((tmp_path/qa19.RECEIPT_NAME).read_bytes())
        assert receipt['attempts'][-1]['status']=='reserved'
        sent.append((item['case_id'],item['arm']))
        return fake_response(item,key)
    first=qa19.run(packet,rubric,allow_paid=True,root=tmp_path,
                   modules={'old':classifier,'new':classifier},transport=transport)
    second=qa19.run(packet,rubric,allow_paid=True,root=tmp_path,
                    modules={'old':classifier,'new':classifier},transport=transport)
    assert first['completed']==second['completed']==len(sent)==6
    assert len(set(sent))==6
    receipt=json.loads((tmp_path/qa19.RECEIPT_NAME).read_bytes())
    assert receipt['max_attempts']==6
    assert 'fixture-private-key' not in str(receipt)
    old,new=receipt['attempts'][:2]
    assert old['production_validation']['status']=='proposed'
    assert old['production_validation']['evidence_ids']==['claim:grammar','choice:a:source_url']
    assert new['production_validation']['evidence_ids']==[
        'claim:grammar','claim:sense','choice:a:source_url']
    assert new['production_validation']['selected_entry_sense_claim_ids']==['claim:sense']
    assert new['production_validation']['all_packet_claim_ids']==['claim:grammar','claim:sense']
    assert old['local_gateway_cache_bypassed'] is True


def test_unknown_prompt_or_packet_delta_and_hash_change_fail_before_transport(tmp_path):
    packet,rubric=fixture(tmp_path)
    rewrite_reviewed_packet(packet,rubric,lambda body:
        body['state']['candidates'][0].update(analysis='verb'))
    with pytest.raises(ValueError,match='outside'):
        qa19.load_plan(packet,rubric,root=tmp_path)
    packet,rubric=fixture(tmp_path)
    (tmp_path/'data/evidence.sqlite').write_bytes(b'tampered synthetic evidence')
    with pytest.raises(ValueError,match='size/hash'):
        qa19.load_plan(packet,rubric,root=tmp_path)


@pytest.mark.parametrize('mutation', [
    lambda body: body.update(temperature=0),
    lambda body: body['questions'].update(other_question={'type':'choice','criteria':{'a':'b'}}),
    lambda body: body['questions']['contextual_parse'].update(extra='unreviewed option'),
])
def test_unrelated_model_visible_envelope_change_is_rejected(tmp_path,mutation):
    packet,rubric=fixture(tmp_path)
    rewrite_reviewed_packet(packet,rubric,mutation)
    with pytest.raises(ValueError,match='prompt'):
        qa19.load_plan(packet,rubric,root=tmp_path)


@pytest.mark.parametrize('mutation', [
    lambda state: state['entry_sense_catalog'].update(
        {'unreviewed':{'claim_id':'unreviewed','glosses':['synthetic']}}),
    lambda state: state['entry_sense_catalog']['claim:sense'].update(claim_id='wrong'),
    lambda state: state.update(entry_sense_reference_format='Different instruction'),
    lambda state: state.update(source_catalog={'s1':{'url':'https://example.test',
                                                      'scope':'synthetic extra'}}),
    lambda state: state.update(source_reference_format='Unreviewed instruction'),
])
def test_catalog_payload_or_format_cannot_disappear_from_comparison(tmp_path,mutation):
    packet,rubric=fixture(tmp_path)
    rewrite_reviewed_packet(packet,rubric,lambda body: mutation(body['state']))
    with pytest.raises(ValueError,match='catalog|sense'):
        qa19.load_plan(packet,rubric,root=tmp_path)


def test_arbitrary_sense_format_without_catalog_is_rejected(tmp_path):
    packet,rubric=fixture(tmp_path)
    bundle=json.loads(packet.read_bytes())
    bundle['cases'][0]['old_request']['state']['entry_sense_reference_format']='Unreviewed instruction'
    packet.write_bytes(qa19.receipt_io.encode(bundle))
    review=json.loads(rubric.read_bytes())
    review['packet_sha256']=qa19.receipt_io.sha(packet.read_bytes())
    review['cases'][0]['requests']['old']=qa19.receipt_io.sha(qa19.receipt_io.encode(
        bundle['cases'][0]['old_request'],canonical=True))
    rubric.write_bytes(qa19.receipt_io.encode(review))
    with pytest.raises(ValueError,match='sense catalog'):
        qa19.load_plan(packet,rubric,root=tmp_path)


def test_failed_or_interrupted_arm_is_never_sent_again(tmp_path,monkeypatch):
    packet,rubric=fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-private-key')
    calls=[]
    def fail(item,key):
        calls.append((item['case_id'],item['arm']))
        raise RuntimeError('do not expose '+key)
    result=qa19.run(packet,rubric,allow_paid=True,root=tmp_path,
                    modules={'old':classifier,'new':classifier},transport=fail)
    assert result['mode']=='stopped_on_failure' and result['attempted']==1
    qa19.run(packet,rubric,allow_paid=True,root=tmp_path,
             modules={'old':classifier,'new':classifier},transport=lambda item,key:
             (calls.append((item['case_id'],item['arm'])),fake_response(item,key))[1])
    assert len(calls)==len(set(calls))==4
    receipt=json.loads((tmp_path/qa19.RECEIPT_NAME).read_bytes())
    assert receipt['attempts'][0]['status']=='failed'
    assert 'fixture-private-key' not in str(receipt)
