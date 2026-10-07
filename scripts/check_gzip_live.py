"""Bounded real-HTTP gzip negotiation checks; no inference or parser fetches."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_pair(identity, compressed):
    assert identity['status'] == compressed['status'] == 200
    assert not identity['headers'].get('content-encoding')
    assert compressed['headers'].get('content-encoding') == 'gzip'
    for response in (identity, compressed):
        assert 'accept-encoding' in response['headers'].get('vary', '').lower()
        assert int(response['headers']['content-length']) == len(response['body'])
    restored = gzip.decompress(compressed['body'])
    assert restored == identity['body'], 'Decoded body differs; do not discard dynamic fields'
    assert len(compressed['body']) < len(identity['body'])
    return {'identity_bytes': len(identity['body']), 'gzip_bytes': len(compressed['body']),
            'decoded_sha256': sha(restored), 'byte_exact': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipts = []

    def fetch(label, path, accept):
        request = Request(args.origin.rstrip('/') + path,
                          headers={'Accept-Encoding': accept, 'User-Agent': 'Melos-gzip-readonly-check/1'})
        started = time.monotonic()
        try:
            response = urlopen(request, timeout=180)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            headers = {name.lower(): ', '.join(response.headers.get_all(name))
                       for name in response.headers.keys()}
            result = {'status': response.status, 'headers': headers, 'body': body}
        receipt = {'path': path, 'accept_encoding': accept, 'status': result['status'],
                   'headers': headers, 'bytes': len(body), 'sha256': sha(body),
                   'seconds': round(time.monotonic() - started, 3)}
        (args.output / (label + '.body')).write_bytes(body)
        (args.output / (label + '.json')).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        receipts.append({'label': label, **receipt})
        return result

    report = {'status': 'FAIL', 'origin': args.origin, 'paid_calls': 0, 'parser_fetches': 0}
    try:
        passage_path = '/api/passage?' + urlencode({'id': 'campbell-glp:alcaeus:350'})
        identity = fetch('passage-identity', passage_path, 'identity')
        compressed = fetch('passage-gzip', passage_path, 'gzip')
        report['passage'] = verify_pair(identity, compressed)
        refusal = fetch('passage-q0', passage_path, 'gzip;q=0, *;q=1')
        assert refusal['status'] == 200 and not refusal['headers'].get('content-encoding')
        assert refusal['body'] == identity['body']
        word_path = '/api/word?' + urlencode({'form': 'ἦλθες', 'passage_id': 'campbell-glp:alcaeus:350'})
        report['word'] = verify_pair(fetch('word-identity', word_path, 'identity'),
                                     fetch('word-gzip', word_path, 'gzip'))
        # This API has no dedicated small health endpoint. Exercise the actual
        # non-JSON reader and small JSON unknown-passage response instead.
        for label, path, expected in [('reader', '/', 200),
                                      ('small-json', '/api/passage?id=melos-gzip-check-absent', 404)]:
            plain = fetch(label + '-identity', path, 'identity')
            accepted = fetch(label + '-gzip', path, 'gzip')
            assert plain['status'] == accepted['status'] == expected
            assert not plain['headers'].get('content-encoding')
            assert not accepted['headers'].get('content-encoding')
            assert plain['body'] == accepted['body']
        report['status'] = 'PASS'
    finally:
        report['receipts'] = receipts
        (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'receipts'}, indent=2))


if __name__ == '__main__':
    main()
