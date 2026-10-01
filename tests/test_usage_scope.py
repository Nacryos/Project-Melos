"""Synthetic retrieval/projection fixtures, no real encoder or corpus writes."""
import numpy as np
import pytest
from backend import server
from test_api import client


class NoVectors:
    def vectors_for(self, ids):
        raise RuntimeError('Synthetic test forces existing TF-IDF fallback')


@pytest.mark.parametrize('count', [0, 1, 2])
def test_exact_scope_is_forwarded_once_without_sparse_theme_expansion(monkeypatch, count):
    calls = []
    rows = [{'id': str(i), 'text': 'αβ', 'author': 'Synthetic translator', 'language': 'ell',
             'kind': 'translation', 'quality': 'needs_review'} for i in range(count)]
    def search(**kwargs):
        calls.append(kwargs)
        return {'results': rows, 'total': count, 'method': 'Synthetic reference navigation',
                'warnings': ['Synthetic upstream warning']}
    monkeypatch.setattr(server, 'search', search)
    monkeypatch.setattr(server, 'semantic_service', lambda: NoVectors())
    scope = dict(q='αβ', author='Ibycus', mode='words', match='exact', language='ell',
                 edition='Synthetic edition', include_reference=True, order='chronological', commentary_assisted=False)
    result = server.usage_space(**scope, limit=80)
    assert calls == [{**scope, 'limit': 80, 'offset': 0}]
    assert result['scope'] == scope
    assert result['retrieval_method'] == 'Synthetic reference navigation'
    assert 'Synthetic upstream warning' in result['warnings']
    assert result['retrieved_count'] == result['plotted_count'] == count
    assert result['omitted_count'] == 0
    for point in result['points']:
        assert (point['author'], point['language'], point['kind'], point['quality']) == (
            'Synthetic translator', 'ell', 'translation', 'needs_review')


def test_projection_omissions_and_bounded_search_count_are_explicit(monkeypatch):
    rows = [{'id': str(i), 'text': 'αβ', 'author': 'Synthetic'} for i in range(4)]
    monkeypatch.setattr(server, 'search', lambda **kwargs: {'results': rows, 'total': 12, 'method': 'Synthetic search'})
    class Partial:
        def vectors_for(self, ids):
            return ids[:3], np.eye(3, dtype=np.float32)
    monkeypatch.setattr(server, 'semantic_service', lambda: Partial())
    result = server.usage_space(q='αβ', limit=80)
    assert (result['retrieved_count'], result['plotted_count'], result['omitted_count']) == (4, 3, 1)
    assert result['search_total'] == 12 and result['candidate_limit'] == 80
    assert any('1 retrieved records omitted' in warning for warning in result['warnings'])
    assert any('not the complete corpus' in warning for warning in result['warnings'])


@pytest.mark.parametrize('client', [[
    {'id': 'scope-grc', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'G', 'text': 'αβ γδ'},
    {'id': 'scope-ell', 'author': 'Translator', 'work': 'Synthetic', 'citation': 'M', 'text': 'αβ γδ',
     'language': 'ell', 'kind': 'translation', 'parent_id': 'scope-grc'},
    {'id': 'scope-reference', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'R', 'text': 'αβ γδ',
     'quality': 'needs_review'},
    {'id': 'scope-other-edition', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'E', 'text': 'αβ γδ',
     'edition': 'Other edition'},
]], indirect=True)
def test_api_filters_match_the_same_search_scope(client, monkeypatch):
    monkeypatch.setattr(server, 'semantic_service', lambda: NoVectors())
    base = {'q': 'αβ', 'mode': 'words', 'match': 'exact', 'author': 'Alpha', 'edition': 'Synthetic test edition'}
    for changes, expected in [({'language': 'grc'}, {'scope-grc'}),
                              ({'language': 'ell'}, {'scope-ell'}),
                              ({'language': 'grc', 'include_reference': 'true'}, {'scope-grc', 'scope-reference'}),
                              ({'language': 'grc', 'edition': 'missing'}, set())]:
        params = base | changes
        result = client.get('/api/usage-space', params=params).json()
        search = client.get('/api/search', params=params).json()
        assert {point['id'] for point in result['points']} == expected == {row['id'] for row in search['results']}
        if changes.get('language') == 'ell':
            assert result['points'][0]['author'] == 'Translator'
