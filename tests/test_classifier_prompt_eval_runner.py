"""Synthetic offline receipts only. No real source data, keys or model calls."""
import json
import io
from urllib.error import HTTPError
from urllib.request import Request
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import run_classifier_prompt_eval as runner
from backend.classifier import _state_json


def fixture(tmp_path, cases=1):
    rows, reviews = [], []
    for number in range(cases):
        row = {'id': f'case{number}'}
        hashes = {}
        for arm in ('old', 'new'):
            body = {'model': 'fixture-pinned', 'state': {'literal': '<source fixture>', 'candidates': [{'id': 'a'}]},
                    'questions': {'contextual_parse': {'type': 'choice', 'instructions': f'Frozen {arm}',
                                                      'criteria': {'a': 'fixture analysis', 'abstain': 'fixture abstention'}}}}
            row[f'{arm}_request'] = body
            hashes[arm] = runner.sha(runner.encode(body, canonical=True))
        rows.append(row)
        reviews.append({'id': row['id'], 'requests': hashes,
                        'outcomes': {'a': 'supported_proposal', 'abstain': 'conservative_abstention'},
                        'default_outcome': 'unsupported_choice'})
    packet = tmp_path / 'packets.json'
    packet.write_bytes(runner.encode({'schema_version': 1, 'model': 'fixture-pinned', 'cases': rows}))
    rubric = tmp_path / 'reviewed_rubric.json'
    rubric.write_bytes(runner.encode({'schema_version': 1, 'review_status': 'approved',
        'packet_sha256': runner.sha(packet.read_bytes()), 'cases': reviews}))
    return packet, rubric


def response(item, key):
    return {'model': item['model'], 'answers': {'contextual_parse': {
        'type': 'choice', 'choice': 'a', 'confidence': .3, 'probabilities': {'a': .4, 'abstain': .6}}},
        'usage': {'input_tokens': 12, 'private': key}}


def receipt(tmp_path):
    return json.loads((tmp_path / runner.RECEIPT_NAME).read_bytes())


def test_default_is_dry_run_with_no_key_or_provider_access(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.delenv('JEV_API_KEY', raising=False)
    def forbidden(*args):
        raise AssertionError('Must not call provider')
    assert runner.run(packet, rubric, transport=forbidden)['mode'] == 'dry_run'
    assert not (tmp_path / runner.RECEIPT_NAME).exists()


def test_frozen_bodies_reserve_before_send_and_completed_arms_never_repeat(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    sent = []
    def transport(item, key):
        assert receipt(tmp_path)['attempts'][-1]['status'] == 'reserved'
        sent.append(item['wire'])
        return response(item, key)
    first = runner.run(packet, rubric, allow_paid=True, transport=transport)
    second = runner.run(packet, rubric, allow_paid=True, transport=transport)
    assert first['completed'] == second['completed'] == len(sent) == 2
    bundle = json.loads(packet.read_bytes())
    assert sent == [runner.encode(bundle['cases'][0][f'{arm}_request']) for arm in ('old', 'new')]
    saved = receipt(tmp_path)
    assert 'fixture-private-key' not in str(saved)
    assert saved['attempts'][0]['result']['model_confidence_uncalibrated'] == .3
    assert saved['attempts'][0]['result']['review_outcome'] == 'supported_proposal'


def test_failure_is_charged_sanitized_and_not_retried_on_resume(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    calls = []
    def fail(item, key):
        calls.append(item['arm'])
        raise RuntimeError('secret body ' + key)
    assert runner.run(packet, rubric, allow_paid=True, transport=fail)['mode'] == 'stopped_on_failure'
    assert len(receipt(tmp_path)['attempts']) == 1
    assert 'secret' not in str(receipt(tmp_path))
    runner.run(packet, rubric, allow_paid=True, transport=lambda item, key: (calls.append(item['arm']), response(item,key))[1])
    assert calls == ['old', 'new']
    assert receipt(tmp_path)['attempts'][0]['status'] == 'failed'


def test_interrupted_attempt_stays_reserved_and_is_not_retried(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    def interrupt(*args):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        runner.run(packet, rubric, allow_paid=True, transport=interrupt)
    assert receipt(tmp_path)['attempts'][0]['status'] == 'reserved'
    result = runner.run(packet, rubric, allow_paid=True, transport=response)
    assert result['attempted'] == 2 and result['failed_or_indeterminate'] == 1


def test_hard_fourteen_cap_and_no_duplicate_calls_on_repeat(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path, cases=7)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    calls = []
    def transport(item, key):
        calls.append((item['case_id'], item['arm']))
        return response(item,key)
    assert runner.run(packet,rubric,allow_paid=True,transport=transport)['completed'] == 14
    runner.run(packet,rubric,allow_paid=True,transport=transport)
    assert len(calls) == len(set(calls)) == 14
    other = tmp_path / 'oversized'; other.mkdir()
    with pytest.raises(ValueError, match='oversized'):
        runner.load_plan(*fixture(other,cases=8))


@pytest.mark.parametrize('mutation', ['packet', 'rubric', 'request'])
def test_unapproved_or_changed_inputs_fail_before_any_call(tmp_path, mutation):
    packet, rubric = fixture(tmp_path)
    value = json.loads(rubric.read_bytes())
    if mutation == 'packet':
        packet.write_bytes(packet.read_bytes() + b' ')
    elif mutation == 'rubric':
        value['review_status'] = 'pending'
    else:
        value['cases'][0]['requests']['old'] = '0' * 64
    rubric.write_bytes(runner.encode(value))
    with pytest.raises(ValueError):
        runner.run(packet,rubric)


def test_receipt_identity_mismatch_fails_closed(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    runner.run(packet,rubric,allow_paid=True,transport=response)
    saved = receipt(tmp_path); saved['attempts'][0]['request_sha256'] = '0' * 64
    runner.atomic_receipt(tmp_path / runner.RECEIPT_NAME, saved)
    with pytest.raises(ValueError, match='identity'):
        runner.run(packet,rubric,allow_paid=True,transport=response)


def test_invalid_choice_or_model_is_a_failed_charged_attempt(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    def bad(item,key):
        out=response(item,key); out['model']='not-pinned'; return out
    assert runner.run(packet,rubric,allow_paid=True,transport=bad)['mode'] == 'stopped_on_failure'
    assert receipt(tmp_path)['attempts'][0]['status'] == 'failed'


def test_atomic_reservation_failure_prevents_http(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-private-key')
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(runner, 'atomic_receipt', fail)
    calls=[]
    with pytest.raises(OSError):
        runner.run(packet,rubric,allow_paid=True,transport=lambda *args: calls.append(args))
    assert not calls


def test_lock_prevents_concurrent_runner(tmp_path):
    path=tmp_path/'receipt.lock'
    with runner.receipt_lock(path):
        with pytest.raises(RuntimeError,match='locked'):
            with runner.receipt_lock(path):
                raise AssertionError('second lock acquired')


def test_actual_wire_is_frozen_provider_serialization_without_reviewer_metadata(tmp_path, monkeypatch):
    packet, rubric = fixture(tmp_path)
    frozen = runner.load_plan(packet,rubric)
    bodies = json.loads(packet.read_bytes())['cases'][0]
    sent=[]
    def fake_urlopen(request,timeout):
        sent.append(request.data)
        return io.BytesIO(json.dumps(response(frozen['plan'][len(sent)-1], 'fixture')).encode())
    monkeypatch.setattr(runner,'urlopen',fake_urlopen)
    for item in frozen['plan']:
        runner.send_frozen(item,'fixture-private-key')
    assert sent == [_state_json(bodies[f'{arm}_request']).encode('utf-8') for arm in ('old','new')]
    for body in sent:
        assert b'outcomes' not in body and b'rationale' not in body and b'fixture-private-key' not in body


def test_receipts_measure_monotonic_elapsed_time_and_exact_request_bytes(tmp_path, monkeypatch):
    packet,rubric=fixture(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-private-key')
    ticks=iter([10,10.125,20,20.01])
    monkeypatch.setattr(runner.time,'monotonic',lambda:next(ticks))
    runner.run(packet,rubric,allow_paid=True,transport=response)
    attempts=receipt(tmp_path)['attempts']
    assert [item['elapsed_ms'] for item in attempts] == [125,10]
    assert [item['request_bytes'] for item in attempts] == [len(item['wire']) for item in runner.load_plan(packet,rubric)['plan']]


@pytest.mark.parametrize('field,value', [('confidence','fixture-secret'),('confidence',float('nan')),
    ('probabilities',{'unknown-choice':.4}),('probabilities',{'a':{'private':'fixture-secret'}})])
def test_arbitrary_optional_provider_metadata_is_rejected(tmp_path,field,value):
    item=runner.load_plan(*fixture(tmp_path))['plan'][0]
    payload=response(item,'fixture-private-key')
    payload['answers']['contextual_parse'][field]=value
    with pytest.raises(ValueError,match='signal'):
        runner.safe_answer(payload,item)


def test_null_optional_signals_are_absent_without_rejecting_a_valid_choice(tmp_path):
    item=runner.load_plan(*fixture(tmp_path))['plan'][0]
    payload=response(item,'fixture-private-key')
    payload['answers']['contextual_parse'].update(confidence=None,probabilities=None)
    result=runner.safe_answer(payload,item)
    assert result['choice'] == 'a'
    assert result['review_outcome'] == 'supported_proposal'
    assert 'model_confidence_uncalibrated' not in result
    assert 'model_probabilities_uncalibrated' not in result


@pytest.mark.parametrize('outcomes', [{'not-a-choice':'supported_proposal'}, {'a':'invented-label'}])
def test_review_outcome_ids_and_labels_are_validated(tmp_path,outcomes):
    packet,rubric=fixture(tmp_path)
    value=json.loads(rubric.read_bytes());value['cases'][0]['outcomes']=outcomes
    rubric.write_bytes(runner.encode(value))
    with pytest.raises(ValueError,match='outcome'):
        runner.load_plan(packet,rubric)


def test_redirects_never_forward_the_authenticated_request():
    request=Request(runner.ENDPOINT,data=b'{}',headers={'Authorization':'Bearer fixture-private-key'})
    with pytest.raises(HTTPError,match='Redirects are disabled'):
        runner.NoRedirect().redirect_request(request,None,302,'redirect',{},'https://example.test/elsewhere')
