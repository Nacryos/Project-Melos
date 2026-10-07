"""Synthetic tiny files; never promote the real accepted corpus in tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

from scripts import promote_qa27_local as local


def _put(path: Path, payload: bytes, mtime_ns: int | None = None) -> local.Binding:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    stat = path.stat()
    return local.Binding(local.sha256(path), stat.st_size, stat.st_mtime_ns if mtime_ns is not None else None)


def _fixture(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    paths = local._paths(root)
    old_db = _put(paths['active_corpus'], b'old SQLite fixture', 1_700_000_000_000_000_000)
    new_db = _put(paths['candidate_corpus'], b'new SQLite fixture', 1_700_000_000_000_000_100)
    asset_names = ('rows-456b8517c04a467aa1dd4face27d3e22.json',
                   'vectors-456b8517c04a467aa1dd4face27d3e22.npy')
    _put(paths['rows'], b'fixture rows')
    _put(paths['vectors'], b'fixture vectors')
    _put(paths['rule'], b'fixture search rule')
    old_manifest = _put(paths['active_manifest'], json.dumps({
        'corpus_mtime_ns': old_db.mtime_ns, 'corpus_size': old_db.size,
        'rows_file': asset_names[0], 'vectors_file': asset_names[1],
    }).encode())
    new_manifest = _put(paths['candidate_manifest'], json.dumps({
        'corpus_mtime_ns': new_db.mtime_ns, 'corpus_size': new_db.size,
        'rows_file': asset_names[0], 'vectors_file': asset_names[1],
    }).encode())
    _put(paths['report'], b'fixture report')
    acceptance = {
        'verdict': 'PASS', 'source_corpus_sha256': old_db.sha256,
        'candidate_corpus_sha256': new_db.sha256,
        'embedding_manifest_sha256': new_manifest.sha256,
        'source_records_unchanged': 288584,
        'unchanged_embedding_model_inputs': 116191,
    }
    _put(paths['acceptance'], json.dumps(acceptance).encode())
    for name, value in {
        'BASE_CORPUS': old_db, 'BASE_MANIFEST': old_manifest,
        'CANDIDATE_CORPUS': new_db, 'CANDIDATE_MANIFEST': new_manifest,
        'ACCEPTANCE_SHA256': local.sha256(paths['acceptance']),
        'REPORT_SHA256': local.sha256(paths['report']),
        'ROWS_SHA256': local.sha256(paths['rows']),
        'VECTORS_SHA256': local.sha256(paths['vectors']),
        'RULE_SHA256': local.sha256(paths['rule']),
    }.items():
        monkeypatch.setattr(local, name, value)
    monkeypatch.setattr(local, '_listening_ports', lambda: set())
    return root, paths, old_db, new_db, old_manifest, new_manifest


def test_netstat_listener_parser_catches_ipv4_and_ipv6(monkeypatch):
    output = ('  TCP    127.0.0.1:8790   0.0.0.0:0   LISTENING   1\n'
              '  TCP    127.0.0.1:8793   0.0.0.0:0   LISTENING   1\n'
              '  TCP    [::]:8794       [::]:0      LISTENING   2\n'
              '  TCP    127.0.0.1:9000   1.2.3.4:80 ESTABLISHED 3\n')
    monkeypatch.setattr(local.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, output, ''))
    assert {8790, 8793, 8794} <= local._listening_ports()
    assert local.PORTS == {8793, 8794}


def test_preflight_refuses_live_listener_before_any_write(tmp_path, monkeypatch):
    root, *_ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(local, '_listening_ports', lambda: {8793})
    with pytest.raises(RuntimeError, match='8793'):
        local.preflight(root)
    assert not list((root / 'data/staging').glob('qa27-local-promotion-*'))


def test_static_preview_8790_is_not_a_database_listener(tmp_path, monkeypatch):
    root, *_ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(local, '_listening_ports', lambda: {8790})
    assert local.preflight(root)['status'] == 'PREFLIGHT_PASS_NO_WRITES'


def test_preflight_refuses_changed_baseline(tmp_path, monkeypatch):
    root, paths, *_ = _fixture(tmp_path, monkeypatch)
    paths['active_corpus'].write_bytes(b'other corpus')
    with pytest.raises(ValueError, match='exact accepted binding'):
        local.preflight(root)
    assert not list((root / 'data/staging').glob('qa27-local-promotion-*'))


def test_preflight_refuses_unbound_sqlite_sidecar(tmp_path, monkeypatch):
    root, paths, *_ = _fixture(tmp_path, monkeypatch)
    Path(str(paths['active_corpus']) + '-wal').write_bytes(b'fixture WAL')
    with pytest.raises(RuntimeError, match='sidecar'):
        local.preflight(root)
    assert not list((root / 'data/staging').glob('qa27-local-promotion-*'))


def test_preflight_refuses_changed_search_rule(tmp_path, monkeypatch):
    root, paths, *_ = _fixture(tmp_path, monkeypatch)
    paths['rule'].write_bytes(b'changed search rule')
    with pytest.raises(ValueError, match='search rule'):
        local.preflight(root)


def test_preflight_refuses_changed_embedding_asset(tmp_path, monkeypatch):
    root, paths, *_ = _fixture(tmp_path, monkeypatch)
    paths['vectors'].write_bytes(b'changed vectors')
    with pytest.raises(ValueError, match='embedding assets'):
        local.preflight(root)


def test_promote_keeps_verified_backup_and_explicit_rollback(tmp_path, monkeypatch):
    root, paths, old_db, new_db, old_manifest, new_manifest = _fixture(tmp_path, monkeypatch)

    def runtime_check(root_path, expected, candidate):
        local.verify_file(paths['active_corpus'], expected)
        local.verify_file(paths['active_manifest'], new_manifest if candidate else old_manifest)
        return {'quick_check': 'ok', 'semantic_ready': True}

    monkeypatch.setattr(local, '_verify_runtime', runtime_check)
    result = local.promote(root)
    assert result['status'] == 'PASS'
    local.verify_file(paths['active_corpus'], new_db)
    local.verify_file(paths['active_manifest'], new_manifest)
    receipt_dir = Path(result['receipt']).parent
    local.verify_file(receipt_dir / 'old-corpus.sqlite', old_db)
    local.verify_file(receipt_dir / 'old-manifest.json', old_manifest)
    assert json.loads(Path(result['receipt']).read_text())['status'] == 'PASS'
    assert local.rollback(root, receipt_dir)['status'] == 'ROLLED_BACK'
    local.verify_file(paths['active_corpus'], old_db)
    local.verify_file(paths['active_manifest'], old_manifest)
    local.verify_file(paths['candidate_corpus'], new_db)


def test_failed_postflight_restores_old_pair(tmp_path, monkeypatch):
    root, paths, old_db, new_db, old_manifest, _ = _fixture(tmp_path, monkeypatch)

    def runtime_check(root_path, expected, candidate):
        if candidate:
            raise ValueError('synthetic semantic failure')
        return {'quick_check': 'ok', 'semantic_ready': True}

    monkeypatch.setattr(local, '_verify_runtime', runtime_check)
    with pytest.raises(ValueError, match='synthetic semantic failure'):
        local.promote(root)
    local.verify_file(paths['active_corpus'], old_db)
    local.verify_file(paths['active_manifest'], old_manifest)
    receipts = list((root / 'data/staging').glob('qa27-local-promotion-*/promotion-receipt.json'))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())['status'] == 'ROLLED_BACK'


def test_keyboard_interrupt_between_pair_swaps_restores_old_pair(tmp_path, monkeypatch):
    root, paths, old_db, _, old_manifest, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(local, '_verify_runtime', lambda *args: {'quick_check': 'ok', 'semantic_ready': True})
    original_replace = local.os.replace
    interrupted = False

    def replace_then_interrupt(source, target):
        nonlocal interrupted
        original_replace(source, target)
        if Path(target) == paths['active_corpus'] and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('synthetic interruption after corpus swap')

    monkeypatch.setattr(local.os, 'replace', replace_then_interrupt)
    with pytest.raises(KeyboardInterrupt, match='synthetic interruption'):
        local.promote(root)
    local.verify_file(paths['active_corpus'], old_db)
    local.verify_file(paths['active_manifest'], old_manifest)
    receipts = list((root / 'data/staging').glob('qa27-local-promotion-*/promotion-receipt.json'))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())['status'] == 'ROLLED_BACK'


def test_postflight_rejects_same_binding_but_modified_manifest_bytes(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    paths = local._paths(root)
    paths['active_corpus'].parent.mkdir(parents=True)
    with sqlite3.connect(paths['active_corpus']) as connection:
        connection.execute('CREATE TABLE tokens (passage_id TEXT, normalized TEXT)')
    stat = paths['active_corpus'].stat()
    corpus = local.Binding(local.sha256(paths['active_corpus']), stat.st_size, stat.st_mtime_ns)
    manifest_data = {'corpus_mtime_ns': stat.st_mtime_ns, 'corpus_size': stat.st_size,
                     'rows_file': 'rows-456b8517c04a467aa1dd4face27d3e22.json',
                     'vectors_file': 'vectors-456b8517c04a467aa1dd4face27d3e22.npy'}
    accepted = _put(paths['active_manifest'], json.dumps(manifest_data).encode())
    monkeypatch.setattr(local, 'CANDIDATE_MANIFEST', accepted)
    monkeypatch.setattr(local, '_verify_shared_dependencies', lambda _: None)
    paths['active_manifest'].write_text(json.dumps(manifest_data, indent=2), encoding='utf-8')
    with pytest.raises(ValueError, match='exact accepted binding'):
        local._verify_runtime(root, corpus, True)
