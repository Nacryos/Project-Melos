"""Discovery contracts over isolated synthetic fixtures, never corpus additions."""
import hashlib
import json
from threading import RLock
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest

from backend import discovery, server


@pytest.fixture
def dictionary(tmp_path, monkeypatch):
    entries = [
        {'id': 'test:b', 'lemma': 'βῆτα', 'source': 'test', 'entry_text': 'a letter, love in an etymology'},
        {'id': 'test:a2', 'lemma': 'ἄλφα', 'lemma_beta': 'a2', 'source': 'test', 'entry_text': 'love'},
        {'id': 'test:a1', 'lemma': 'ἄλφα', 'lemma_beta': 'a1', 'source': 'test', 'entry_text': 'love'},
    ]
    path = tmp_path / 'data/lexica/entries.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in entries), encoding='utf-8')
    audit = tmp_path / 'data/reports/audit-lexica.json'
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps({'files': {'entries.jsonl': {'verdict': 'PASS',
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}}), encoding='utf-8')
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    def senses(row):
        text = 'letter' if row['id'] == 'test:b' else 'love'
        return {'dictionary_senses_status': 'source_structured', 'dictionary_senses': [
            {'id': row['id'] + ':sense', 'text': text, 'source': 'test',
             'source_url': 'https://example.org/test-only', 'lexicon_entry_id': row['id'],
             'form_scope': {'relation': 'headword'}}]}
    monkeypatch.setattr('backend.lexicon_senses.dictionary_senses', senses)
    discovery._lexicon_index.cache_clear()
    return path


def test_headword_browse_stable_pagination_and_homographs(dictionary):
    first = discovery.lexicon(limit=1, offset=0)
    second = discovery.lexicon(limit=1, offset=1)
    assert first['total'] == 3
    assert first['results'][0]['id'] == 'test:a1'
    assert second['results'][0]['id'] == 'test:a2'
    assert first['results'][0]['homograph'] == '1'
    assert first['has_more']
    assert discovery.lexicon(prefix='β', limit=10, offset=0)['total'] == 1


def test_english_matches_verified_meaning_not_entry_etymology(dictionary):
    result = discovery.lexicon(q='love', mode='english', limit=10, offset=0)
    assert result['total'] == 2
    assert all(row['meaning'] == 'love' for row in result['results'])
    assert all(row['id'] != 'test:b' for row in result['results'])


def test_no_legacy_gloss_fallback(dictionary, monkeypatch):
    monkeypatch.setattr('backend.lexicon_senses.dictionary_senses', lambda row: {'dictionary_senses': []})
    assert discovery.lexicon(q='love', mode='english', limit=10, offset=0)['total'] == 0
    assert discovery.lexicon(limit=10, offset=0)['results'][0]['meaning'] == ''


def test_subform_senses_not_generalized_to_headword(dictionary, monkeypatch):
    monkeypatch.setattr('backend.lexicon_senses.dictionary_senses', lambda row: {'dictionary_senses': [
        {'text': 'love', 'form_scope': {'relation': 'variant'}}]})
    assert discovery.lexicon(q='love', mode='english', limit=10, offset=0)['total'] == 0


def test_transliteration_and_actual_source_forms(dictionary, monkeypatch):
    monkeypatch.setattr(server, 'morph_service', lambda: SimpleNamespace(_form_lemmas={'λογου': {'βητα'}}))
    result = discovery.lexicon(q='logou', mode='auto', limit=10, offset=0)
    assert result['mode'] == 'greek'
    assert [row['id'] for row in result['results']] == ['test:b']


def test_audit_gate_fails_closed(dictionary):
    dictionary.write_text(dictionary.read_text() + '{}\n')
    with pytest.raises(Exception) as error:
        discovery.lexicon(limit=10, offset=0)
    assert error.value.status_code == 503


def test_bounded_english_counts_disclosed(dictionary, monkeypatch):
    monkeypatch.setattr(discovery, 'MAX_ENGLISH_CANDIDATES', 1)
    result = discovery.lexicon(q='love', mode='english', limit=10, offset=0)
    assert result['total'] == 1
    assert result['search_contract']['complete'] is False
    assert result['warnings']


def parent(identifier='p:1', text='κύματα θάλασσα.\nἄνθεα καὶ ἄλσος.'):
    return {'id': identifier, 'text': text, 'author': 'Test author', 'work': 'Test work',
            'source': 'test-only', 'source_url': 'https://example.org/test-only',
            'kind': 'text', 'language': 'grc', 'quality': 'source_text'}


@pytest.fixture
def parents(monkeypatch):
    rows = [parent(), parent('p:2', 'μέλος\n\nφίλος')]
    monkeypatch.setattr(discovery, '_parents', lambda q, theme, author: (rows, 2, 'test retrieval', []))
    monkeypatch.setattr(discovery, '_semantic_children', lambda q, rows: (rows, {'available': False}))
    return rows


@pytest.mark.parametrize('unit', list(discovery.UNIT_METHODS))
def test_unit_source_offsets_and_parent_links(parents, unit):
    result = discovery.theme_search(q='κύματα', unit=unit, limit=60, offset=0)
    sources = {row['id']: row for row in parents}
    for row in result['results']:
        assert row['text'] == sources[row['parent_id']]['text'][row['start']:row['end']]
        assert row['quote'] == row['text']
        assert row['passage_id'] == row['parent_id']
        assert row['independent_unit_embedding'] is False
    assert result['search_contract']['independent_unit_embeddings'] is False


def test_unit_pagination_stable_and_actual_word_filter(parents):
    first = discovery.theme_search(q='κύματα', unit='word', limit=2, offset=0)
    second = discovery.theme_search(q='κύματα', unit='word', limit=2, offset=2)
    assert first['total'] == second['total']
    assert not {row['id'] for row in first['results']} & {row['id'] for row in second['results']}
    assert first['results'][0]['quote'] == 'κύματα'
    assert first['results'][0]['score'] == 1


def test_literal_support_retains_punctuation_boundaries(parents):
    parents[0]['text'] = 'κύματα, θάλασσα.'
    for unit in ('line', 'sentence', 'phrase'):
        result = discovery.theme_search(q='κύματα', unit=unit, limit=60, offset=0)
        assert result['results'][0]['score'] == 1
        assert result['results'][0]['lexical_matches'] == ['κυματα']


def test_literary_prompt_is_query_not_annotation(parents):
    result = discovery.theme_search(theme='politics', limit=20, offset=0)
    assert result['query'] == discovery.THEME_MAP['politics'][3]
    assert all(not row.get('visual_themes') for row in result['results'])


def test_annotation_evidence_must_belong_to_exact_parent(parents):
    parents[0]['visual_themes'] = {'labels': [{'theme': 'sea_coast', 'evidence': [
        {'id': 'p:other', 'start': 0, 'end': 6}]}]}
    result = discovery.theme_search(theme='sea_coast', unit='word', limit=60, offset=0)
    assert all(row['score'] == 0 for row in result['results'])
    parents[0]['visual_themes']['labels'][0]['evidence'][0]['id'] = 'p:1'
    result = discovery.theme_search(theme='sea_coast', unit='word', limit=60, offset=0)
    assert result['results'][0]['quote'] == 'κύματα'
    assert result['results'][0]['score'] == 1


def test_actual_child_embedding_and_cache(monkeypatch):
    from backend.discovery_units import segment_record
    calls = []
    class Model:
        max_seq_length = 512
        def tokenizer(self, texts, **kwargs):
            return {'input_ids': [[1] * (len(text) + 2) for text in texts]}
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return np.array([[1., 0.], [0., 1.], [1., 0.]])
    semantic = SimpleNamespace(ready=True, _state_lock=RLock(), _encode_lock=RLock(),
                              _manifest={}, _get_model=lambda manifest: Model())
    monkeypatch.setattr(server, 'semantic_service', lambda: semantic)
    monkeypatch.setattr(discovery, '_cache_identity', lambda server: ('test-child',))
    discovery._CHILD_CACHE.clear()
    rows = [{**row, 'parent_rank': 1, 'score': 0} for row in segment_record(parent(text='ἄλφα βῆτα'), 'word')]
    result, metadata = discovery._semantic_children('love', rows)
    assert result[0]['quote'] == 'βῆτα'
    assert result[0]['score'] == 1
    assert result[0]['retrieval_score_kind'] == 'on_demand_child_cosine'
    assert metadata['encoded_units'] == 2
    discovery._semantic_children('love', rows)
    assert len(calls) == 1
    assert calls[0] == ['love', 'ἄλφα', 'βῆτα']


def test_child_encoder_never_silently_truncates(monkeypatch):
    from backend.discovery_units import segment_record
    calls = []
    class Model:
        max_seq_length = 8
        def tokenizer(self, texts, **kwargs):
            assert kwargs['truncation'] is False
            assert kwargs['add_special_tokens'] is True
            return {'input_ids': [[1] * (2 * len(text) + 2) for text in texts]}
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return np.array([[1., 0.], [1., 0.]])
    semantic = SimpleNamespace(ready=True, _state_lock=RLock(), _encode_lock=RLock(),
                              _manifest={}, _get_model=lambda manifest: Model())
    monkeypatch.setattr(server, 'semantic_service', lambda: semantic)
    monkeypatch.setattr(discovery, '_cache_identity', lambda server: ('token-bound-test',))
    rows = [{**row, 'parent_rank': 1, 'score': 0} for row in segment_record(parent(text='α αβγδεζ'), 'word')]
    result, metadata = discovery._semantic_children('q', rows)
    assert calls == [['q', 'α']]
    assert [row['quote'] for row in result] == ['α']
    assert metadata['tokenizer_rejected_units'] == 1
    assert metadata['sampled'] is True


def test_routes_and_invalid_parameters():
    client = TestClient(server.app)
    assert client.get('/api/discovery-catalog').status_code == 200
    for url in ('/api/theme-search?unit=poem', '/api/theme-search?theme=made_up',
                '/api/theme-search?limit=200', '/api/lexicon?mode=made_up', '/api/lexicon?offset=-1'):
        assert client.get(url).status_code == 422


def test_no_invented_stanzas(monkeypatch):
    monkeypatch.setattr(discovery, '_parents', lambda *args: ([parent()], 1, 'test', []))
    result = discovery.theme_search(unit='stanza', limit=20, offset=0)
    assert result['total'] == 0
    assert any('blank-line' in warning for warning in result['warnings'])


def test_nature_query_intersection_discloses_bounded_semantic_window(monkeypatch):
    selected = parent()
    monkeypatch.setattr(discovery, '_nature_parents', lambda *args: [selected])
    monkeypatch.setattr(discovery, '_cache_identity', lambda server: ('bounded-nature-query',))
    monkeypatch.setattr(server, 'search', lambda **kwargs: {
        'results': [selected] + [parent(f'p:{i}') for i in range(2, 121)],
        'total': 500, 'warnings': []})
    discovery._PARENT_CACHE.clear()
    result = discovery.theme_search(q='waves', theme='sea_coast', unit='passage', limit=20, offset=0)
    assert result['total'] == 1
    assert result['search_contract']['parent_candidates_total'] == 1
    assert result['search_contract']['complete'] is False
    scope = result['search_contract']['parent_scope']
    assert scope['semantic_parent_candidates_total'] == 500
    assert scope['semantic_parents_retrieved'] == 120
    assert scope['intersection_matches_in_window'] == 1
    assert scope['intersection_bounded'] is True
    assert any('additional category matches' in warning for warning in result['warnings'])


def test_successful_child_sample_total_scope_is_encoded_units(parents, monkeypatch):
    def sampled(query, rows):
        return rows[:2], {'available': True, 'encoded_units': 2,
                         'candidate_units': len(rows), 'sampled': True}
    monkeypatch.setattr(discovery, '_semantic_children', sampled)
    result = discovery.theme_search(q='love', unit='word', limit=20, offset=0)
    assert result['total'] == 2
    assert result['search_contract']['complete'] is False
    assert result['search_contract']['total_scope'] == 'sampled, encoded child units from the bounded retrieved parent window'
    assert result['search_contract']['child_semantic_reranking']['candidate_units'] > 2
    assert any('totals count only sampled, encoded child units' in warning for warning in result['warnings'])


def test_child_semantic_candidates_omit_editorial_only_spans(monkeypatch):
    from backend.discovery_units import segment_record
    calls = []
    class Model:
        max_seq_length = 512
        def tokenizer(self, texts, **kwargs):
            return {'input_ids': [[1] * (len(text) + 2) for text in texts]}
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return np.array([[1., 0.], [1., 0.]])
    semantic = SimpleNamespace(ready=True, _state_lock=RLock(), _encode_lock=RLock(),
                              _manifest={}, _get_model=lambda manifest: Model())
    monkeypatch.setattr(server, 'semantic_service', lambda: semantic)
    monkeypatch.setattr(discovery, '_cache_identity', lambda server: ('editorial-test',))
    source = parent(text='⟨ ⟩\n[ . . . ]\n123\n†\nἀ[ ]γάπη')
    rows = [{**row, 'parent_rank': 1, 'score': 0} for row in segment_record(source, 'line')]
    result, metadata = discovery._semantic_children('love', rows)
    assert calls == [['love', 'ἀ[ ]γάπη']]
    assert [row['quote'] for row in result] == ['ἀ[ ]γάπη']
    assert metadata['non_greek_letter_units_omitted'] == 4
    assert metadata['candidate_units'] == 5
    assert source['text'] == '⟨ ⟩\n[ . . . ]\n123\n†\nἀ[ ]γάπη'


def test_editorial_only_child_query_empty_without_encoding(monkeypatch):
    from backend.discovery_units import segment_record
    monkeypatch.setattr(server, 'semantic_service', lambda: pytest.fail('Must not encode editorial gaps'))
    rows = [{**row, 'parent_rank': 1, 'score': 0} for row in segment_record(parent(text='⟨ ⟩'), 'line')]
    result, metadata = discovery._semantic_children('love', rows)
    assert result == []
    assert metadata['available'] is False
    assert metadata['non_greek_letter_units_omitted'] == 1
