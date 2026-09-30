"""Read-only regression probes for failures reproduced in the live browser.

These checks inspect known source-backed records, not model accuracy rates.
No classifier/provider request is made. They supplement, not replace, browser QA.
"""
import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(origin):
    def get(path, **params):
        with urlopen(origin.rstrip('/') + path + '?' + urlencode(params), timeout=60) as response:
            return json.load(response)

    for form, identifier in [('τεθυμιάμενοι','dcc-sappho:frag-2'), ('φωνείσας','dcc-sappho:frag-31')]:
        result = get('/api/search', q=form, mode='words', match='exact', author='Sappho', limit=100)
        assert identifier in {row['id'] for row in result['results']}, (form, result)
        source = get('/api/passage', id=identifier)
        assert '-\n' in source['text'], 'Printed source line division must remain intact'
        print(json.dumps({'query': form, 'matches': result['total'], 'source_text_preserved': True}), flush=True)
    result = get('/api/search', q='Ibycus 286', mode='hybrid')
    assert result['mode'] == 'reference'
    assert result['total'] == 1
    assert result['results'][0]['reference_match']['coverage'] == 'reference_only'
    print('Ibycus 286: exact catalogue-only result; no unrelated fallback.', flush=True)
    result = get('/api/word', form='φαίνεταί', passage_id='dcc-sappho:frag-31')
    assert result['expansion_lemmas'] == []
    assert any(row['lemma'] == 'ἐγώ' for row in result['candidates']), 'Original conflicting evidence must remain visible'
    assert not any(row['automatic_expansion_eligible'] for row in result['candidates'])
    print('Conflicting source lemma links remain visible but do not drive automatic expansion.', flush=True)
    source = get('/api/passage', id='dcc-sappho:brothers-poem')
    form = 'βασί̣λ̣η̣αν'
    assert form in source['text'], 'Original underdots must remain present in the edition text'
    result = get('/api/word', form=form, passage_id=source['id'])
    assert source['id'] in {row['id'] for row in result['occurrences']}, 'Underdotted word must remain one occurrence token'
    print('Underdotted Brothers Poem form remains intact and its original occurrence is discoverable.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    verify(parser.parse_args().origin)
