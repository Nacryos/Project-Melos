"""Read-only feature checks; no paid calls, model downloads or source edits."""
import argparse
import hashlib
import json
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    args = parser.parse_args()
    timings = []

    def get(path, **params):
        started = time.monotonic()
        with urlopen(args.origin.rstrip('/') + path + ('?' + urlencode(params) if params else ''), timeout=240) as response:
            result = json.load(response)
        timings.append({'path': path, 'params': params, 'seconds': round(time.monotonic() - started, 3)})
        return result

    catalog = get('/api/discovery-catalog')
    assert len(catalog['themes']) >= 13
    assert {row['id'] for row in catalog['units']} == {'passage', 'stanza', 'line', 'sentence', 'phrase', 'word'}
    assert catalog['independent_unit_embeddings'] is False
    authors = get('/api/authors')['authors']
    assert any(row['author'] == 'Sappho' and row.get('author_chronology') for row in authors)
    for params in ({'limit': 3}, {'q': 'love', 'mode': 'english', 'limit': 3}):
        lexicon = get('/api/lexicon', **params)
        assert lexicon['results']
        assert all(row['headword'] and row['source'] and row['source_url'] for row in lexicon['results'])
        if params.get('mode') == 'english':
            assert all(row['meanings'] and row['meaning_status'] == 'source_structured' for row in lexicon['results'])
            assert all(sense['source_locator'] for row in lexicon['results'] for sense in row['meanings'])
    checked = 0
    parents = {}
    for unit in ('passage', 'stanza', 'line', 'sentence', 'phrase', 'word'):
        result = get('/api/theme-search', theme='sea_coast', unit=unit, limit=5)
        assert result['unit'] == unit
        if unit != 'stanza':
            assert result['results'], unit
        for row in result['results']:
            pid = row['parent_id']
            if pid not in parents:
                parents[pid] = get('/api/passage', id=pid)
            parent = parents[pid]
            assert row['quote'] == row['text'] == parent['text'][row['start']:row['end']]
            assert parent['kind'] == 'text' and parent['language'] == 'grc'
            assert row['visual_themes']['source_text_sha256'] == hashlib.sha256(parent['text'].encode()).hexdigest()
            assert 'sea_coast' in row['visual_themes']['themes']
            checked += 1
    semantic = get('/api/theme-search', q='love and longing', author='Sappho', unit='line', limit=3)
    assert semantic['results']
    rerank = semantic['search_contract']['child_semantic_reranking']
    assert rerank['available'] is True and 0 < rerank['encoded_units'] <= 64
    assert rerank['parent_limit'] == 16
    repeated = get('/api/theme-search', q='love and longing', author='Sappho', unit='line', limit=3)
    assert [row['id'] for row in repeated['results']] == [row['id'] for row in semantic['results']]
    words = get('/api/theme-search', theme='unrequited_love', author='Sappho', unit='word', limit=2)
    assert words['search_contract']['child_semantic_reranking']['available'] is True
    assert 'sampled' in words['search_contract']['total_scope']
    for row in words['results']:
        parent = get('/api/passage', id=row['parent_id'])
        assert row['text'] == row['quote'] == parent['text'][row['start']:row['end']]
        assert row['retrieval_score_kind'] == 'on_demand_child_cosine'
    repeated_words = get('/api/theme-search', theme='unrequited_love', author='Sappho', unit='word', limit=2)
    assert words['results'] == repeated_words['results']
    all_lines = get('/api/theme-search', q='love and longing', author='Sappho', unit='line', limit=60)
    assert all_lines['results']
    assert all(any(char.isalpha() and 'GREEK' in unicodedata.name(char, '')
                   for char in row['quote']) for row in all_lines['results']), 'Editorial-only child was semantically ranked'
    assert all_lines['search_contract']['child_semantic_reranking']['non_greek_letter_units_omitted'] > 0
    print(json.dumps({'passed': True, 'source_spans_checked': checked,
                      'dictionary_browse_and_english': True, 'nature_annotation_hashes': True,
                      'local_child_semantic_units': rerank['encoded_units'],
                      'independent_unit_embeddings': False, 'timings': timings}))


if __name__ == '__main__':
    main()
