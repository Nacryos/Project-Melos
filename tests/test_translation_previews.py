"""Synthetic pairing fixtures. No text here is an ancient/published claim."""
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from backend.translation_previews import enrich_results, project, MAX_PREVIEWS
from backend import translation_previews


def parent(number=1):
    return {'id': f'p2_cgl_anthology:{number}', 'source': 'p2_cgl_anthology',
            'kind': 'text', 'quality': 'source_text', 'language': 'grc', 'text': 'Synthetic Greek fixture',
            'raw_path': f'data/fixture/page_{number}.html', 'raw_sha256': 'a' * 64,
            'source_url': f'https://www.greek-language.gr/digitalResources/ancient_greek/anthology/poetry/browse.html?text_id={number}',
            'metadata': {'text_id': number}}


def translation(number=1, index=1, *, inline=False):
    base = parent(number)
    return {**base, 'id': f'{base["id"]}:tr{index}', 'kind': 'translation', 'language': 'ell',
            'parent_id': base['id'], 'text': 'Literal synthetic translation.\nSecond synthetic line.',
            'source_url': base['source_url'] + ('' if inline else f'#m{index}'),
            'edition': 'Synthetic published edition', 'citation': 'Synthetic citation', 'license': 'Fixture licence',
            'metadata': {**base['metadata'], 'translation_of': base['id'], 'translator': 'Fixture translator',
                'source_translation_locator': {'layout': 'inline_adjacent_credit', 'block_ordinal': index,
                    'credit_selector': 'adjacent div.pull-right > i'} if inline else
                    {'layout': 'linked_tab', 'pane_id': f'm{index}'}}}


@pytest.mark.parametrize('inline', [False, True])
def test_verified_whole_source_pair_preserves_literal_text_credit_and_proof(inline):
    original, translated = parent(), translation(inline=inline)
    before = deepcopy(translated)
    result = project(original, [translated], full_text=True)
    preview = result['translation_previews'][0]
    assert preview['text'] == translated['text']
    assert preview['text_excerpt'] == translated['text']
    assert preview['translator'] == 'Fixture translator'
    assert preview['scope'] == 'whole_source_passage'
    assert preview['alignment'] == 'not_line_aligned'
    assert 'Greek base edition' not in preview['scope_note']
    assert preview['pairing_proof']['raw_sha256'] == 'a' * 64
    assert preview['pairing_proof']['source_translation_locator'] == translated['metadata']['source_translation_locator']
    assert 'raw_path' not in json.dumps(preview)
    assert translated == before


@pytest.mark.parametrize('change', [
    {'source': 'perseus'}, {'parent_id': 'wrong-parent'}, {'quality': 'machine_ocr'},
    {'kind': 'commentary'}, {'language': 'eng'}, {'raw_sha256': 'b' * 64}, {'raw_path': 'different.html'},
    {'source_url': 'https://example.test/different-page'}, {'source_url': 'javascript:alert(1)'},
    {'id': 'p2_cgl_anthology:2:tr1'},
])
def test_nonmatching_or_unsafe_source_record_cannot_supply_preview(change):
    row = translation(); row.update(change)
    assert project(parent(), [row])['translation_previews'] == []


@pytest.mark.parametrize('change', [
    {'translation_of': None}, {'translation_of': 'different'}, {'text_id': True},
    {'scope': 'source_section'}, {'scope': 'page'}, {'scope': 'line'},
    {'source_translation_locator': None},
    {'source_translation_locator': {'layout': 'unknown'}},
    {'source_translation_locator': {'layout': 'linked_tab', 'pane_id': 'wrong-pane'}},
    {'source_translation_locator': {'layout': 'inline_adjacent_credit', 'block_ordinal': True, 'credit_selector': 'guessed'}},
])
def test_parent_link_without_explicit_valid_source_pairing_is_not_alignment(change):
    row = translation(); row['metadata'].update(change)
    assert project(parent(), [row])['translation_previews'] == []


def test_unknown_translator_does_not_get_inferred_from_ancient_author():
    row = translation(); row['metadata'].pop('translator'); row['author'] = 'Ancient fixture poet'
    preview = project(parent(), [row])['translation_previews'][0]
    assert preview['translator'] is None
    assert 'Ancient fixture poet' not in json.dumps(preview)


def test_mirror_or_same_number_record_does_not_inherit_translation():
    copy = parent(); copy['id'] = 'mirror:1'; copy['source'] = 'mirror'
    copy['mirrored_ids'] = [parent()['id']]
    assert project(copy, [translation()])['translation_previews'] == []


def test_excerpt_is_bounded_literal_prefix_and_full_text_keeps_linebreaks():
    row = translation(); row['text'] = ('Synthetic original line and qualifying words.\n' * 25)
    search_preview = project(parent(), [row])['translation_previews'][0]
    assert search_preview['excerpt_truncated'] is True
    assert len(search_preview['text_excerpt']) <= 241
    assert row['text'].startswith(search_preview['text_excerpt'][:-1])
    assert 'text' not in search_preview
    assert project(parent(), [row], full_text=True)['translation_previews'][0]['text'] == row['text']


def test_all_translators_remain_separate_with_explicit_bounded_overflow():
    rows = [translation(index=index) for index in range(1, 10)]
    response = project(parent(), rows, full_text=True)
    assert len(response['translation_previews']) == MAX_PREVIEWS
    assert response['translation_preview_count'] == 9
    assert response['translation_previews_truncated'] is True
    assert len(project(parent(), rows)['translation_previews']) == 1


def database(rows):
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE passages (id TEXT, source TEXT, kind TEXT, data TEXT)')
    connection.executemany('INSERT INTO passages VALUES (?, ?, ?, ?)',
                          [(row['id'], row['source'], row['kind'], json.dumps(row)) for row in rows])
    return connection


def test_batch_uses_one_query_preserves_order_and_does_not_modify_input():
    rows = [parent(2), parent(1)]
    before = deepcopy(rows)
    connection = database([translation(1), translation(2), translation(3)])
    queries = []; connection.set_trace_callback(queries.append)
    enriched = enrich_results(connection, rows)
    assert [row['id'] for row in enriched] == [row['id'] for row in rows]
    assert len([query for query in queries if query.startswith('SELECT')]) == 1
    assert [row['translation_previews'][0]['parent_id'] for row in enriched] == [row['id'] for row in rows]
    assert rows == before


def test_publication_filtered_connection_cannot_leak_held_translation():
    connection = database([translation()])
    connection.execute('ALTER TABLE passages RENAME TO source_passages')
    connection.execute('CREATE TEMP VIEW passages AS SELECT * FROM source_passages WHERE 0')
    assert enrich_results(connection, [parent()])[0]['translation_previews'] == []


def test_empty_or_ineligible_batch_does_not_query():
    class NoQuery:
        def execute(self, *args):
            raise AssertionError('Must not query for ineligible results')
    assert enrich_results(NoQuery(), []) == []
    assert enrich_results(NoQuery(), [{'id': 'perseus:fixture', 'source': 'perseus'}]) == [
        {'id': 'perseus:fixture', 'source': 'perseus'}]


def test_search_api_only_enriches_final_page_without_changing_ranks_or_total(monkeypatch):
    from backend import server
    final = {'results': [{**parent(2), 'rank': 31}, {**parent(1), 'rank': 32}], 'total': 77, 'mode': 'hybrid'}
    calls = []
    monkeypatch.setattr(server, 'search', lambda **kwargs: (calls.append(kwargs), deepcopy(final))[1])
    connection = database([translation(1), translation(2), translation(3)])
    monkeypatch.setattr(server, 'connect', lambda: connection)
    response = server.search_response(q='fixture', mode='hybrid', limit=2, offset=30)
    assert calls[0]['offset'] == 30 and calls[0]['limit'] == 2
    assert response['total'] == 77
    assert [row['rank'] for row in response['results']] == [31, 32]
    assert all(row['translation_previews'] for row in response['results'])


def perseus_fixture(tmp_path, monkeypatch):
    greek = {'id': 'perseus:fixture-grc:1', 'source': 'perseus', 'kind': 'text', 'language': 'grc',
             'quality': 'source_text', 'text': 'Synthetic complete Greek text.', 'raw_sha256': 'b' * 64,
             'source_url': 'https://example.test/fixture-grc.xml', 'lines': [{'label': '1', 'text': 'Synthetic complete Greek text.'}],
             'metadata': {'cts_urn': 'tlg0000.tlg001.fixture-grc', 'commit': 'fixturecommit'}}
    english = {**greek, 'id': 'perseus:fixture-eng:1', 'kind': 'translation', 'language': 'eng',
               'text': 'Synthetic complete English text.', 'raw_sha256': 'c' * 64,
               'source_url': 'https://example.test/fixture-eng.xml', 'parent_id': greek['id'],
               'metadata': {'cts_urn': 'tlg0000.tlg001.fixture-eng', 'commit': 'fixturecommit'}}
    def binding(row):
        return {'text_sha256': hashlib.sha256(row['text'].encode()).hexdigest(), 'raw_sha256': row['raw_sha256'],
                'source_url': row['source_url'], 'cts_urn': row['metadata']['cts_urn'], 'commit': 'fixturecommit'}
    pair = {'parent_id': greek['id'], 'translation_id': english['id'], 'work_urn': 'tlg0000.tlg001',
            'parent': binding(greek), 'translation': {**binding(english), 'translators': ['Source fixture translator']},
            'boundary_proof': {'method': 'complete_source_bodies',
                'parent_span': {'start_index': 0, 'end_index_exclusive': 1, 'at_source_end': True, 'next_anchor': None},
                'translation_span': {'start_index': 0, 'end_index_exclusive': 1, 'at_source_end': True, 'next_anchor': None},
                'raw_path': '/private/source.xml'},
            'cts_proof': {'source_url': 'https://example.test/__cts__.xml', 'sha256': 'd' * 64,
                          'edition_urn': greek['metadata']['cts_urn'], 'translation_urn': english['metadata']['cts_urn'],
                          'raw_path': '/private/cts.xml'}}
    path = tmp_path / 'synthetic_pairings.json'
    path.write_text(json.dumps({'schema_version': 1, 'pairs': [pair]}), encoding='utf-8')
    monkeypatch.setattr(translation_previews, 'PROOF_MANIFEST', path)
    return greek, english, pair, path


def test_source_bound_perseus_proof_supplies_english_credit_without_raw_paths(tmp_path, monkeypatch):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    preview = project(greek, [english], full_text=True)['translation_previews'][0]
    assert preview['translator'] == 'Source fixture translator'
    assert preview['text'] == english['text']
    assert preview['pairing_proof']['boundary_proof']['method'] == 'complete_source_bodies'
    assert 'raw_path' not in json.dumps(preview)
    assert '/private/' not in json.dumps(preview)
    assert preview['alignment'] == 'not_line_aligned'
    assert "The translator's Greek base edition is not established here." in preview['scope_note']


@pytest.mark.parametrize('side,field,value', [
    ('parent', 'text', 'Changed indexed Greek text'), ('translation', 'text', 'Changed indexed English text'),
    ('parent', 'raw_sha256', 'e' * 64), ('translation', 'raw_sha256', 'e' * 64),
    ('parent', 'source_url', 'https://example.test/unverified'), ('translation', 'quality', 'needs_review'),
    ('translation', 'parent_id', 'wrong'), ('parent', 'id', 'mirror-copy'),
])
def test_perseus_manifest_never_overrides_changed_or_ineligible_current_records(tmp_path, monkeypatch, side, field, value):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    (greek if side == 'parent' else english)[field] = value
    assert project(greek, [english])['translation_previews'] == []


def test_missing_wrong_version_duplicate_or_invalid_boundary_proofs_fail_closed(tmp_path, monkeypatch):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    for payload in [{'schema_version': 2, 'pairs': [pair]}, {'schema_version': 1, 'pairs': [pair, pair]},
                    {'schema_version': 1, 'pairs': [{**pair, 'boundary_proof': {'method': 'same_citation'}}]}]:
        path.write_text(json.dumps(payload), encoding='utf-8'); translation_previews._read_proofs.cache_clear()
        assert project(greek, [english])['translation_previews'] == []
    path.unlink()
    assert project(greek, [english])['translation_previews'] == []


def test_perseus_cts_work_and_commit_must_still_match_bound_source_identity(tmp_path, monkeypatch):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    english['metadata']['cts_urn'] = 'tlg0000.tlg002.fixture-eng'
    assert project(greek, [english])['translation_previews'] == []
    english['metadata']['cts_urn'] = pair['translation']['cts_urn']
    english['metadata']['commit'] = 'differentcommit'
    assert project(greek, [english])['translation_previews'] == []


def test_perseus_prefixed_cts_proof_and_identical_source_anchors_require_matching_successor(tmp_path, monkeypatch):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    pair['work_urn'] = 'urn:cts:greekLit:' + pair['work_urn']
    for key in ('edition_urn', 'translation_urn'):
        pair['cts_proof'][key] = 'urn:cts:greekLit:' + pair['cts_proof'][key]
    pair['cts_proof']['work_urn'] = pair['work_urn']
    pair['boundary_proof'] = {'method': 'identical_ordered_source_anchors_and_successor', 'anchors': ['1'],
        'parent_span': {'start_index': 5, 'end_index_exclusive': 6, 'next_anchor': '2', 'at_source_end': False},
        'translation_span': {'start_index': 8, 'end_index_exclusive': 9, 'next_anchor': '2', 'at_source_end': False}}
    def write():
        path.write_text(json.dumps({'schema_version': 1, 'pairs': [pair]}), encoding='utf-8')
        translation_previews._read_proofs.cache_clear()
    write()
    assert len(project(greek, [english])['translation_previews']) == 1
    pair['boundary_proof']['translation_span']['next_anchor'] = '3'; write()
    assert project(greek, [english])['translation_previews'] == []
    pair['boundary_proof']['translation_span']['next_anchor'] = '2'; write()
    english['lines'] = [{'label': 'different', 'text': english['text']}]
    assert project(greek, [english])['translation_previews'] == []


@pytest.mark.parametrize('change', [{'start_index': 1, 'end_index_exclusive': 2},
                                  {'at_source_end': False, 'next_anchor': '2'},
                                  {'end_index_exclusive': 2}])
def test_complete_body_proof_rejects_partial_or_length_mismatched_span(tmp_path, monkeypatch, change):
    greek, english, pair, path = perseus_fixture(tmp_path, monkeypatch)
    pair['boundary_proof']['parent_span'].update(change)
    path.write_text(json.dumps({'schema_version': 1, 'pairs': [pair]}), encoding='utf-8')
    translation_previews._read_proofs.cache_clear()
    assert project(greek, [english])['translation_previews'] == []
