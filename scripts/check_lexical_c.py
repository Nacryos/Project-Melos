"""Bounded operational checks, not a philological accuracy benchmark.

Uses the accepted Campbell text to select exact existing occurrences. Never
requests model ranking or a remote parser fetch. Raw request/response receipts
are retained, and an interrupted request is never automatically repeated.
"""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def run(origin, output, require_source_precedence=False):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.path not in {'', '/'}:
        raise ValueError('An origin without credentials or a path is required')
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'origin.json'
    origin_bytes = json.dumps({'origin': origin.rstrip('/')}, sort_keys=True).encode()
    if manifest.exists():
        if manifest.read_bytes() != origin_bytes:
            raise ValueError('Output directory belongs to a different origin')
    else:
        with manifest.open('xb') as handle:
            handle.write(origin_bytes)
    records = [json.loads(line) for line in
               (ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl').read_text(encoding='utf-8').splitlines()]
    reports = []
    # Existing source forms are query targets, not authored lexical data.
    targets = [('350', 'ἦλθες'), ('350', 'παχέων'), ('129', 'δᾶμον'),
               ('130b', 'τάλαις'), ('130b', 'ὄππᾳ')]
    for fragment, form in targets:
        record = next(row for row in records if row['id'] == f'campbell-glp:alcaeus:{fragment}')
        start = record['text'].index(form)
        payload = {'passage_id': record['id'], 'selected_text': form,
                   'start': start, 'end': start + len(form), 'offset_unit': 'codepoint',
                   'rerank': False, 'fetch_machine': False}
        key = fragment + '-' + digest(form.encode())[:12]
        request_file, response_file = output / (key + '.request.json'), output / (key + '.response.json')
        raw_request = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        if request_file.exists():
            if request_file.read_bytes() != raw_request or not response_file.exists():
                raise RuntimeError('Changed or interrupted request; inspect receipt instead of retrying: ' + key)
            raw_response = response_file.read_bytes()
        else:
            request_file.write_bytes(raw_request)
            req = urllib.request.Request(origin.rstrip('/') + '/api/analyze-passage', raw_request,
                                         {'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=120) as response:
                raw_response = response.read()
            response_file.write_bytes(raw_response)
        result = json.loads(raw_response)
        assert result['passage']['text_sha256'] == digest(record['text'].encode()), 'Source text changed'
        assert result['selection']['text'] == form, 'Selection changed'
        assert result.get('ranking', {}).get('status') == 'not_requested', 'Unexpected ranking'
        assert result.get('limits', {}).get('machine_fetches') == 0, 'Unexpected parser fetch'
        words = [row for row in result['tokens'] if row['kind'] == 'word']
        assert len(words) == 1 and words[0]['text'] == form
        readings = result.get('interlinear') or {}
        # Use the documented projection field without silently selecting a
        # different interpretation if the contract changes.
        assert readings.get('text') == form and len(readings.get('readings', [])) == 1
        rows = readings['readings'][0]['tokens']
        reading = next((row for row in rows if row.get('text') == form), None)
        assert reading, 'Missing interlinear token'
        if form == 'ἦλθες':
            assert reading['parse_short'] == '2nd sg. aor. ind. act.'
        if form in {'τάλαις', 'ὄππᾳ'}:
            assert words[0].get('lexical_variants'), 'Missing expected exact source variant'
            if require_source_precedence:
                assert reading.get('features') == {}, 'Conflicting syntax prediction still displayed'
                assert reading.get('selection_basis') == 'lexical_source_syntax_conflict'
        if require_source_precedence and form == 'δᾶμον':
            assert reading.get('features', {}).get('Case') == 'Acc'
            assert reading.get('features', {}).get('Number') == 'Sing'
            assert reading.get('selection_basis') == 'source_morphology_consensus'
            assert reading.get('syntax_conflict') is True
        reports.append({'form': form, 'passage_id': record['id'],
                        'response_sha256': digest(raw_response),
                        'source_text_sha256': digest(record['text'].encode()),
                        'parse_short': reading.get('parse_short') if reading else None,
                        'features': reading.get('features') if reading else None,
                        'selection_basis': reading.get('selection_basis'),
                        'syntax_conflict': reading.get('syntax_conflict'),
                        'gloss': reading.get('gloss') if reading else None,
                        'lexical_variants': words[0].get('lexical_variants', []),
                        'interlinear_contract_present': bool(reading)})
    report = {'scope': 'Operational source-bound checks; not semantic accuracy', 'origin': origin,
              'request_count': len(targets), 'paid_ranking_requested': False, 'results': reports}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'report.json'),
                      'results': [{k: row[k] for k in ('form', 'parse_short', 'interlinear_contract_present')}
                                  for row in reports]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-source-precedence', action='store_true')
    args = parser.parse_args()
    run(args.origin, args.output, args.require_source_precedence)
