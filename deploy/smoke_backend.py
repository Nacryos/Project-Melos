"""Bounded hosted read-endpoint checks and timings; no paid classifier calls."""
import argparse
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen, Request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--origin', default='http://127.0.0.1:8791')
parser.add_argument('--expected-passages', type=int, default=287552,
                    help='Expected audited snapshot count (override when verifying a rollback)')
args = parser.parse_args()
BASE = args.origin.rstrip('/')


def get(path, **params):
    start = time.perf_counter()
    with urlopen(BASE + path + ('?' + urlencode(params) if params else ''), timeout=180) as response:
        result = json.load(response)
    print(json.dumps({'endpoint': path, 'seconds': round(time.perf_counter()-start, 3),
                      'ready': result.get('ready'), 'results': len(result.get('results', [])),
                      'warnings': result.get('warnings', [])}, ensure_ascii=False), flush=True)
    return result


status = get('/api/status')
assert status['passages'] == args.expected_passages, (status['passages'], args.expected_passages)
assert status['embeddings']['ready'] is True
assert status['evidence']['ready'] is True
assert status['publication_policy'] == 'source-labels', status['publication_policy']
assert get('/api/authors')['authors']
assert get('/api/works', author='Sappho')['works']
passage = get('/api/passage', id='dcc-sappho:brothers-poem')
assert passage['text']
word = get('/api/word', form='πέμπην', passage_id=passage['id'])
assert word['structured_evidence']['ready']
wiktionary = get('/api/wiktionary', form='ἄμμι')
assert wiktionary['ready']
assert get('/api/search', q='λύσις', mode='words')['results']
themes = get('/api/search', q='Sappho Cretan grove cold water and roses', mode='themes', limit=5)
assert themes['results']
assert themes['method'] == 'Local multilingual dense embeddings; similarity is not an influence claim.'
expected_notices = {
    'Semantic total counts only the first 1,000 ranked candidates; more indexed hits may exist.',
    'English translations/commentary are separate retrieval evidence; no automatic equivalence of senses is asserted.',
}
assert set(themes.get('warnings', [])) <= expected_notices, themes.get('warnings')
get('/api/search', q='Sappho Cretan grove cold water and roses', mode='themes', limit=5)
assert get('/api/usage-space', q='ἔρος', limit=10)['points']
try:
    urlopen(Request(BASE + '/api/classify-context', data=b'{}', headers={'Content-Type':'application/json'}), timeout=10)
    raise AssertionError('Invalid classifier request unexpectedly accepted')
except HTTPError as error:
    assert error.code == (422 if status.get('classifier',{}).get('configured') else 403)
print('Hosted read API checks passed; invalid classification request rejected without a paid call.', flush=True)
