"""Check an audited dictionary subentry through both actual reader APIs.

Two bounded requests, no parser fetching or model ranking. Expectations come
from the archived source-bound route fixture, not authored lexical answers.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_alcaeus_occurrences import Receipts, save, sha


def verify_envelope(actual, expected, form):
    assert actual['status'] == expected['status'] == 'available'
    assert actual['query_form'] == expected['query_form'] == form
    source = actual['machine_subentry_evidence']
    reference = expected['machine_subentry_evidence']
    # Deployment paths alter dependency catalog IDs. Source records and raw
    # parser receipt identities must nevertheless stay exactly the same.
    assert source['subentries'] == reference['subentries']
    assert source['receipts'] == reference['receipts']
    assert source['ranking_status'] == 'unsupported_source_type'
    tokens = [t for t in actual['tokens'] if t.get('kind') == 'word']
    old_tokens = [t for t in expected['tokens'] if t.get('kind') == 'word']
    assert len(tokens) == len(old_tokens) == 1
    assert tokens[0]['text'] == old_tokens[0]['text'] == form
    assert tokens[0]['machine']['machine_candidates'] == old_tokens[0]['machine']['machine_candidates']
    rendered = actual['interlinear']['readings'][0]['tokens'][0]
    old_rendered = expected['interlinear']['readings'][0]['tokens'][0]
    assert rendered['features'] == old_rendered['features']
    assert rendered['parse_short'] == old_rendered['parse_short']
    assert rendered['features']['Person'] == '1'
    assert rendered['candidate_meanings'][0]['machine_subentry_alternatives']
    return {'source_subentry_ids': list(source['subentries']),
            'receipt_ids': list(source['receipts']), 'parse_short': rendered['parse_short']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--fixture-sha256', required=True)
    args = parser.parse_args()
    fixture_path = ROOT / 'tests/fixtures/machine-subentry-word-actual.json'
    raw = fixture_path.read_bytes()
    if sha(raw) != args.fixture_sha256:
        raise ValueError('Reviewed full route fixture changed.')
    fixture = json.loads(raw)
    expected, form = fixture['machine_dictionary'], fixture['form']
    records = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    passage = next(json.loads(line) for line in records.read_text(encoding='utf-8').splitlines()
                   if json.loads(line)['id'] == 'campbell-glp:alcaeus:326')
    assert passage['text'].count(form) == 1
    start = passage['text'].index(form)
    api = Receipts(args.origin, args.output / 'receipts', timeout=180)
    word, word_receipt = api.call('/api/word', params={'form': form, 'passage_id': passage['id']})
    assert word['form'] == form
    word_check = verify_envelope(word['machine_dictionary'], expected, form)
    analysis, analysis_receipt = api.call('/api/analyze-passage', payload={
        'version': 1, 'passage_id': passage['id'], 'start': start, 'end': start + len(form),
        'offset_unit': 'codepoint', 'selected_text': form, 'rerank': False, 'fetch_machine': False})
    assert analysis['limits']['machine_fetches'] == 0
    assert analysis['ranking']['status'] == analysis['sense_ranking']['status'] == 'not_requested'
    # A passage result has the same source catalog/parse, but absolute offsets
    # and a passage token identity rather than a standalone query identity.
    passage_check = verify_envelope({**analysis, 'query_form': form, 'status': 'available'}, expected, form)
    assert analysis['selection']['text'] == passage['text'][start:start + len(form)]
    report = {'verdict': 'PASS', 'origin': args.origin, 'fixture_sha256': sha(raw),
              'source_records_sha256': sha(records.read_bytes()), 'form': form,
              'word': word_check, 'passage': passage_check,
              'receipts': [word_receipt, analysis_receipt], 'paid_calls': 0, 'parser_fetches': 0,
              'scope': 'Literal parser-lemma dictionary link and complete supplied parse; not contextual adjudication.'}
    save(args.output / 'report.json', report)
    print(json.dumps({'verdict': 'PASS', 'form': form, 'parse_short': word_check['parse_short']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
