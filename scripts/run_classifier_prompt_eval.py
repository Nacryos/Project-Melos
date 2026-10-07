"""Explicit, receipt-bounded QA16 experiment; dry-run unless --allow-paid.

Send reviewed frozen bodies, not reconstructed prompts. A reserved, interrupted,
or failed arm is never retried automatically. This dedicated experiment budget
is separate from the production gateway and makes at most fourteen attempts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_ATTEMPTS = 14
TIMEOUT_SECONDS = 8
RECEIPT_NAME = 'evaluation_receipt.json'
OUTCOMES = frozenset({'supported_proposal', 'supported_partial_analysis', 'supported_lemma_only',
    'appropriate_abstention', 'conservative_abstention', 'unwarranted_resolution', 'unsupported_choice'})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, 'Redirects are disabled for this experiment', headers, response)


def urlopen(request, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def encode(value, *, canonical=False):
    return json.dumps(value, ensure_ascii=False, sort_keys=canonical,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def load_plan(packet_path, rubric_path):
    raw = packet_path.read_bytes()
    rubric_raw = rubric_path.read_bytes()
    bundle, rubric = json.loads(raw), json.loads(rubric_raw)
    if (bundle.get('schema_version') != 1 or rubric.get('schema_version') != 1
            or rubric.get('review_status') != 'approved'
            or rubric.get('packet_sha256') != sha(raw)):
        raise ValueError('Reviewed packet binding is missing or inconsistent')
    cases = bundle.get('cases')
    reviews = rubric.get('cases')
    if not isinstance(cases, list) or not cases or len(cases) * 2 > MAX_ATTEMPTS or not isinstance(reviews, list):
        raise ValueError('Invalid or oversized reviewed case set')
    review_by_id = {row['id']: row for row in reviews}
    case_ids = [row['id'] for row in cases]
    if len(set(case_ids)) != len(case_ids) or len(review_by_id) != len(reviews) or set(review_by_id) != set(case_ids):
        raise ValueError('Duplicate or unmatched reviewed case identity')
    model = bundle.get('model')
    if not isinstance(model, str) or not model:
        raise ValueError('Missing pinned model')
    plan = []
    for case in cases:
        review = review_by_id[case['id']]
        if not isinstance(review.get('outcomes'), dict) or not isinstance(review.get('default_outcome'), str):
            raise ValueError('Candidate-specific reviewer outcomes are required')
        for arm in ('old', 'new'):
            body = case[f'{arm}_request']
            canonical_sha = sha(encode(body, canonical=True))
            question = body.get('questions', {}).get('contextual_parse', {})
            choices = question.get('criteria')
            if (body.get('model') != model or review.get('requests', {}).get(arm) != canonical_sha
                    or question.get('type') != 'choice' or not isinstance(choices, dict) or 'abstain' not in choices):
                raise ValueError('Frozen request differs from its reviewed identity')
            if (not set(review['outcomes']).issubset(choices)
                    or review['default_outcome'] not in OUTCOMES
                    or any(not isinstance(label, str) or label not in OUTCOMES for label in review['outcomes'].values())):
                raise ValueError('Reviewer outcome identity or label is invalid')
            wire = encode(body)  # Preserve the frozen object's order and content.
            plan.append({'case_id': case['id'], 'arm': arm, 'model': model,
                         'request_sha256': sha(wire), 'canonical_request_sha256': canonical_sha,
                         'wire': wire, 'choices': set(choices), 'review': review})
    return {'packet_sha256': sha(raw), 'rubric_sha256': sha(rubric_raw), 'model': model,
            'plan': plan}


@contextmanager
def receipt_lock(path):
    """OS lock releases on process death; the persistent file is not a lease."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Evaluation receipt is locked by another process') from None
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError('Evaluation receipt is locked by another process') from None
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix=path.name + '.', suffix='.tmp',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_receipt(path, frozen):
    binding = {key: frozen[key] for key in ('packet_sha256', 'rubric_sha256', 'model')}
    if not path.exists():
        return {'schema_version': 1, **binding, 'max_attempts': MAX_ATTEMPTS, 'attempts': []}
    receipt = json.loads(path.read_bytes())
    if (receipt.get('schema_version') != 1 or receipt.get('max_attempts') != MAX_ATTEMPTS
            or any(receipt.get(key) != value for key, value in binding.items())):
        raise ValueError('Receipt belongs to a different reviewed experiment')
    attempts = receipt.get('attempts')
    expected = {(item['case_id'], item['arm']): item for item in frozen['plan']}
    seen = set()
    if not isinstance(attempts, list) or len(attempts) > MAX_ATTEMPTS:
        raise ValueError('Receipt attempt budget is invalid')
    for item in attempts:
        key = (item.get('case_id'), item.get('arm'))
        specification = expected.get(key)
        if (key in seen or not specification or item.get('status') not in ('reserved', 'completed', 'failed')
                or item.get('request_bytes') != len(specification['wire'])
                or any(item.get(field) != specification[field] for field in
                       ('model', 'request_sha256', 'canonical_request_sha256'))):
            raise ValueError('Receipt attempt identity is invalid')
        seen.add(key)
    return receipt


def send_frozen(item, key):
    request = Request(ENDPOINT, data=item['wire'], headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Provider response exceeds limit')
    return json.loads(raw)


def safe_answer(payload, item):
    if not isinstance(payload, dict) or payload.get('model') != item['model']:
        raise ValueError('Provider did not return the pinned model')
    answer = payload.get('answers', {}).get('contextual_parse', {})
    if (not isinstance(answer, dict) or answer.get('type') != 'choice'
            or answer.get('choice') not in item['choices']):
        raise ValueError('Provider did not return a supplied choice')
    result = {'choice': answer['choice'], 'model': payload['model'],
              'review_outcome': item['review']['outcomes'].get(answer['choice'], item['review']['default_outcome'])}
    for original, label in (('confidence', 'model_confidence_uncalibrated'),
                            ('probabilities', 'model_probabilities_uncalibrated')):
        if answer.get(original) is not None:
            signal = answer[original]
            values = list(signal.values()) if original == 'probabilities' and isinstance(signal, dict) else [signal]
            if (original == 'probabilities' and (not isinstance(signal, dict) or not set(signal).issubset(item['choices']))
                    or not all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 for value in values)):
                raise ValueError('Invalid raw model signal')
            result[label] = signal
    if isinstance(payload.get('usage'), dict):
        result['usage'] = {key: value for key, value in payload['usage'].items()
                           if key in ('input_tokens', 'output_tokens', 'total_tokens')
                           and type(value) is int and value >= 0}
    if len(encode(result)) > 65536:
        raise ValueError('Provider result exceeds limit')
    return result


def run(packet_path, rubric_path, *, allow_paid=False, transport=send_frozen):
    frozen = load_plan(packet_path, rubric_path)
    receipt_path = packet_path.parent / RECEIPT_NAME
    with receipt_lock(receipt_path.with_suffix('.lock')):
        receipt = load_receipt(receipt_path, frozen)
        used = {(item['case_id'], item['arm']) for item in receipt['attempts']}
        pending = [item for item in frozen['plan'] if (item['case_id'], item['arm']) not in used]
        if not allow_paid:
            return {'mode': 'dry_run', 'attempted': len(used), 'pending': len(pending),
                    'max_attempts': MAX_ATTEMPTS, 'model': frozen['model']}
        key = os.environ.get('TYPESAFE_API_KEY') or os.environ.get('JEV_API_KEY')
        if not key:
            raise RuntimeError('Existing Jev environment key is not configured')
        for item in pending:
            if len(receipt['attempts']) >= MAX_ATTEMPTS:
                raise RuntimeError('Evaluation attempt budget exhausted')
            attempt = {field: item[field] for field in
                       ('case_id', 'arm', 'model', 'request_sha256', 'canonical_request_sha256')}
            attempt.update(status='reserved', reserved_at=timestamp(), request_bytes=len(item['wire']))
            receipt['attempts'].append(attempt)
            atomic_receipt(receipt_path, receipt)  # Durable reservation BEFORE HTTP.
            started = time.monotonic()
            try:
                answer = safe_answer(transport(item, key), item)
            except Exception as exc:
                attempt.update(status='failed', completed_at=timestamp(),
                    elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                    error_kind='http_error' if isinstance(exc, HTTPError) else 'provider_or_transport_error')
                if isinstance(exc, HTTPError):
                    attempt['http_status'] = exc.code
                atomic_receipt(receipt_path, receipt)
                # No exception text, headers, response body, key or retry.
                return {'mode': 'stopped_on_failure', 'attempted': len(receipt['attempts']),
                        'pending': len(frozen['plan']) - len(receipt['attempts'])}
            attempt.update(status='completed', completed_at=timestamp(), result=answer,
                           elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            atomic_receipt(receipt_path, receipt)
        return {'mode': 'complete', 'attempted': len(receipt['attempts']),
                'completed': sum(item['status'] == 'completed' for item in receipt['attempts']),
                'failed_or_indeterminate': sum(item['status'] != 'completed' for item in receipt['attempts'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packets', type=Path, required=True)
    parser.add_argument('--rubric', type=Path, required=True)
    parser.add_argument('--allow-paid', action='store_true')
    args = parser.parse_args()
    try:
        summary = run(args.packets, args.rubric, allow_paid=args.allow_paid)
    except Exception:
        print('Evaluation stopped: validation, receipt, configuration or I/O failure. No automatic retry.')
        raise SystemExit(2) from None
    print(json.dumps(summary))
    if summary['mode'] == 'stopped_on_failure':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
