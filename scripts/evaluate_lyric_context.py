"""Bounded live comparison of existing source occurrences; never authors facts.

One-token requests can trigger at most one morphology and one sense decision.
Paid requests require --allow-rerank, are durably reserved before transmission,
and are never retried automatically. Output is evaluation evidence, not corpus.
"""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--passage-id', required=True)
    parser.add_argument('--forms', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-rerank', action='store_true')
    args = parser.parse_args()
    if not 1 <= len(args.forms) <= 3 or len(set(args.forms)) != len(args.forms):
        raise ValueError('One to three distinct targets per evaluation.')
    parsed = urllib.parse.urlparse(args.origin)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise ValueError('HTTPS or local test endpoint required.')
    rows = [json.loads(line) for line in args.records.read_text(encoding='utf-8').splitlines() if line.strip()]
    record = next(row for row in rows if row['id'] == args.passage_id)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    origin = args.origin.rstrip('/')
    with opener.open(origin + '/api/passage?id=' + urllib.parse.quote(record['id']), timeout=90) as stream:
        passage = json.load(stream)
    if passage['text'] != record['text']:
        raise ValueError('Live text differs from the accepted source artifact.')
    targets = []
    for form in args.forms:
        if any(char.isspace() for char in form) or record['text'].count(form) != 1:
            raise ValueError('Evaluation requires a unique source occurrence of each single form.')
        start = record['text'].index(form)
        targets.append((form, start, start + len(form)))
    args.output.mkdir(parents=True, exist_ok=True)
    ledger_path = args.output / 'receipt.json'
    if ledger_path.exists():
        raise ValueError('Evaluation already reserved; use existing receipts, no implicit retry.')
    receipt = {'origin': origin, 'passage_id': record['id'], 'text_sha256': digest(record['text']),
               'source_artifact_sha256': hashlib.sha256(args.records.read_bytes()).hexdigest(),
               'rerank': args.allow_rerank, 'max_requests': len(targets),
               'max_paid_decisions': len(targets) * 2 if args.allow_rerank else 0,
               'philological_accuracy_claim': False, 'attempts': []}
    def save():
        ledger_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    for index, (form, start, end) in enumerate(targets):
        request = {'version': 1, 'passage_id': record['id'], 'start': start, 'end': end,
                   'offset_unit': 'codepoint', 'selected_text': form,
                   'rerank': args.allow_rerank, 'fetch_machine': False}
        payload = json.dumps(request, ensure_ascii=False).encode()
        attempt = {'form': form, 'start': start, 'end': end, 'status': 'reserved',
                   'request_sha256': hashlib.sha256(payload).hexdigest()}
        receipt['attempts'].append(attempt)
        (args.output / f'{index}.request.json').write_bytes(payload)
        save()
        started = time.monotonic()
        try:
            req = urllib.request.Request(origin + '/api/analyze-passage', data=payload,
                                         headers={'Content-Type': 'application/json', 'Origin': origin})
            with opener.open(req, timeout=120) as stream:
                raw = stream.read()
            response = json.loads(raw)
            (args.output / f'{index}.response.json').write_bytes(raw)
            tokens = response.get('interlinear', {}).get('readings', [{}])[0].get('tokens', [])
            words = [token for token in tokens if token.get('kind') == 'word']
            if response.get('selection', {}).get('text') != form or len(words) != 1 or words[0]['text'] != form:
                raise ValueError('Response occurrence mismatch.')
            word = words[0]
            attempt.update(status='completed', seconds=round(time.monotonic()-started, 3),
                response_sha256=hashlib.sha256(raw).hexdigest(),
                selection_basis=word.get('selection_basis'), lemma=word.get('lemma'),
                parse=word.get('parse_short'), gloss=word.get('gloss'),
                morphology_status=response.get('ranking', {}).get('status'),
                sense_status=response.get('sense_ranking', {}).get('status'),
                sense_items=response.get('sense_ranking', {}).get('items'))
        except Exception as exc:
            attempt.update(status='failed_or_indeterminate', error_kind=type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError):
                attempt['http_status'] = exc.code
            save()
            raise SystemExit('Evaluation stopped; no automatic retry. Inspect saved receipt.') from None
        save()
        print(json.dumps({key: attempt.get(key) for key in ('form', 'status', 'seconds', 'selection_basis', 'parse', 'morphology_status', 'sense_status')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
