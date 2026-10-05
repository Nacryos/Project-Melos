"""Synthetic derived-index mechanics only; no source transcription is authored."""
from __future__ import annotations

from collections import Counter
import json
import sqlite3

import pytest

from backend.textutils import normalize, search_text, tokenize
from scripts.build_corpus import SCHEMA
from scripts.build_embeddings import source_rows
from scripts.stage_qa27_search_repair import ROOT, sha256, stage


def _fixture(tmp_path):
    source = tmp_path / 'old.sqlite'
    text = 'αβ-\nγδ'
    untouched = 'English fixture.'
    with sqlite3.connect(source) as con:
        con.executescript(SCHEMA)
        for identifier, raw, language, normalized in (
            ('greek', text, 'grc', normalize(text)),
            ('english', untouched, 'eng', normalize(untouched)),
        ):
            data = json.dumps({'id': identifier, 'text': raw, 'source_url': 'https://example.org/fixture'})
            con.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (identifier, 'work', 'fixture', 'Fixture', 'Work', 'Edition', '1',
                         language, 'text', 'source_text', raw, normalized, data, 0,
                         'Fixture', identifier))
            con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)',
                        (identifier, normalized, '1', 'fixture', 'work'))
        con.execute('INSERT INTO works VALUES (?,?,?,?,?,?,?,?)',
                    ('work', 'Fixture', 'Work', 'Edition', 'fixture', 'grc', 2, 'Fixture'))
        con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                        [('greek', 'αβ', normalize('αβ'), 1),
                         ('greek', 'γδ', normalize('γδ'), 1),
                         ('english', 'English', normalize('English'), 1),
                         ('english', 'fixture', normalize('fixture'), 1)])
        for form in ('αβ', 'γδ', 'English', 'fixture'):
            con.execute('INSERT INTO vocabulary VALUES (?,?,?)', (normalize(form), form, 1))
        con.execute('INSERT INTO metadata VALUES (?,?)',
                    ('manifest', json.dumps({'passages': 2, 'vocabulary': 4})))
    embedding_dir = tmp_path / 'embeddings'
    embedding_dir.mkdir()
    (embedding_dir / 'rows.json').write_text(json.dumps([
        {key: record[key] for key in
         ('id', 'source', 'language', 'kind', 'author', 'parent_id', 'context_authors')}
        for record in source_rows(source)
    ]), encoding='utf-8')
    (embedding_dir / 'vectors.npy').write_bytes(b'fixture-vector-bytes')
    stat = source.stat()
    (embedding_dir / 'manifest.json').write_text(json.dumps({
        'corpus_mtime_ns': stat.st_mtime_ns, 'corpus_size': stat.st_size,
        'eligible_count': 2, 'rows_file': 'rows.json', 'vectors_file': 'vectors.npy',
    }), encoding='utf-8')
    delta = tmp_path / 'delta.json'
    old_forms = Counter(tokenize(text))
    new_forms = Counter(tokenize(search_text(text)))
    delta.write_text(json.dumps({
        'corpus_sha256': sha256(source),
        'textutils_sha256': sha256(ROOT / 'backend/textutils.py'),
        'changed_record_count': 1,
        'records': [{
            'id': 'greek', 'original_text': text, 'quality': 'source_text',
            'old_search_text': text, 'new_search_text': search_text(text),
            'normalized_changed': True,
            'removed_search_tokens': dict(old_forms - new_forms),
            'added_search_tokens': dict(new_forms - old_forms),
        }],
    }), encoding='utf-8')
    return source, embedding_dir, delta


def test_stage_changes_only_derived_search_and_rebinds_identical_embeddings(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    before = sha256(source)
    destination = tmp_path / 'stage'
    result = stage(source, destination, embedding_dir, delta)
    assert result['changed_records'] == 1
    assert sha256(source) == before
    with sqlite3.connect(destination / 'corpus.sqlite') as con:
        assert con.execute("SELECT normalized FROM passages WHERE id='greek'").fetchone()[0] == \
            normalize(search_text('αβ-\nγδ'))
        assert con.execute("SELECT text,data FROM passages WHERE id='greek'").fetchone() == \
            ('αβ-\nγδ', json.dumps({'id': 'greek', 'text': 'αβ-\nγδ',
                                   'source_url': 'https://example.org/fixture'}))
        assert con.execute("SELECT form,count FROM tokens WHERE passage_id='greek'").fetchall() == \
            [('αβγδ', 1)]
    assert sha256(destination / 'embeddings' / 'rows.json') == sha256(embedding_dir / 'rows.json')
    assert sha256(destination / 'embeddings' / 'vectors.npy') == sha256(embedding_dir / 'vectors.npy')
    rebound = json.loads((destination / 'embeddings' / 'manifest.json').read_text(encoding='utf-8'))
    assert rebound['search_only_rebind']['verified_unchanged_model_inputs'] == 2
    assert json.loads((destination / 'repair-report.json').read_text(encoding='utf-8'))['verdict'] == \
        'PENDING_INDEPENDENT_REVIEW'


def test_stage_rejects_stale_rule_delta_before_creating_candidate(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    data = json.loads(delta.read_text(encoding='utf-8'))
    data['textutils_sha256'] = '0' * 64
    delta.write_text(json.dumps(data), encoding='utf-8')
    destination = tmp_path / 'rejected'
    with pytest.raises(ValueError, match='stale'):
        stage(source, destination, embedding_dir, delta)
    assert not destination.exists()


def test_stage_rejects_missing_expected_change(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    data = json.loads(delta.read_text(encoding='utf-8'))
    data['changed_record_count'] = 0
    data['records'] = []
    delta.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='Unreviewed changed record'):
        stage(source, tmp_path / 'rejected', embedding_dir, delta)


def test_stage_rejects_stale_embedding_manifest(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    manifest = embedding_dir / 'manifest.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['corpus_size'] += 1
    manifest.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='not bound'):
        stage(source, tmp_path / 'rejected', embedding_dir, delta)


def test_stage_rejects_unreviewed_per_record_projection(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    data = json.loads(delta.read_text(encoding='utf-8'))
    data['records'][0]['new_search_text'] = 'αβγx'
    delta.write_text(json.dumps(data), encoding='utf-8')
    destination = tmp_path / 'rejected'
    with pytest.raises(ValueError, match='projection differs'):
        stage(source, destination, embedding_dir, delta)
    assert not destination.exists()


def test_stage_rejects_nonempty_live_wal_before_snapshot(tmp_path):
    source, embedding_dir, delta = _fixture(tmp_path)
    writer = sqlite3.connect(source)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE fixture_wal (value INTEGER)')
        writer.commit()
        assert (tmp_path / 'old.sqlite-wal').stat().st_size > 0
        destination = tmp_path / 'rejected'
        with pytest.raises(ValueError, match='sidecar'):
            stage(source, destination, embedding_dir, delta)
        assert not destination.exists()
    finally:
        writer.close()
