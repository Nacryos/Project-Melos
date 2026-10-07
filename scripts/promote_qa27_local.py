"""Reversibly switch the *local* default index to accepted QA27 artifacts.

The default command is a read-only preflight. Promotion requires --promote,
stopped local listeners, exact accepted hashes, and a verified rollback copy.
This never changes raw sources, evidence, rows, or vectors. Do not run before
the separately authorized remote deployment and independent local review.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
# 8790 is the user's static tools/serve.py preview and does not open SQLite;
# main verified that exception. The two local API listeners must be stopped.
PORTS = {8793, 8794}


@dataclass(frozen=True)
class Binding:
    sha256: str
    size: int
    mtime_ns: int | None = None


BASE_CORPUS = Binding('0c3ea08788999df75b7c5a378c81d7b9344c61f438ba94e345bea61559f5b4d6',
                      1_655_599_104, 1790811186037359700)
BASE_MANIFEST = Binding('f4b39dcac1a3334cf4038422b9a5eedc9f8e6043e1c5fdf3f49c22ecae58a614', 1554)
CANDIDATE_CORPUS = Binding('be68b1afac0c87f17db7bb1f38d74c580fc28a5a5f29e200eba2f16509eaa4fe',
                           1_655_746_560, 1791229540096282800)
CANDIDATE_MANIFEST = Binding('17361055065988d3205d9f4094772f4ebf28a0c9d753b4362ec64f453a0d4d23',
                             2388)
ACCEPTANCE_SHA256 = '0edb8ee41fc84f2fb10848f19b70d7c3912c164fc09721a5e11a2e6ebea56ab4'
REPORT_SHA256 = 'bf7efa04ef937adc38fa6aa07cf2b378a75c972644c1923ab58652726f734954'
ROWS_SHA256 = '0864001ae572751a1838e0d720f2ee8a650595006375a86f1c0dfe2e31a0dac9'
VECTORS_SHA256 = 'fa4d08fff2a78c1cafb0fbf417debe202589403838976a241fbdfaabf08b9496'
RULE_SHA256 = '64c748fbe7ae9d7c68fa972d75f0a621e8624b7602653a04b9205468552d4565'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, binding: Binding) -> None:
    stat = path.stat()
    if (stat.st_size != binding.size or
            (binding.mtime_ns is not None and stat.st_mtime_ns != binding.mtime_ns) or
            sha256(path) != binding.sha256):
        raise ValueError(f'File differs from exact accepted binding: {path}')


def _listening_ports() -> set[int]:
    result = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True,
                            text=True, errors='replace', timeout=15, check=True)
    listening = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != 'TCP' or parts[3].upper() not in {'LISTENING', 'LISTEN'}:
            continue
        try:
            listening.add(int(parts[1].rsplit(':', 1)[-1]))
        except ValueError:
            continue
    return listening


def _require_stopped() -> None:
    occupied = PORTS & _listening_ports()
    if occupied:
        raise RuntimeError(f'Local listener(s) still active: {sorted(occupied)}; stop them before switching')


def _require_no_sqlite_sidecars(*databases: Path) -> None:
    # A main-file SHA does not bind a committed WAL. Refuse even empty/stale
    # sidecars, and let the operator resolve their provenance before switching.
    for database in databases:
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                raise RuntimeError(f'Unbound SQLite sidecar beside {database}: {sidecar.name}')


def _paths(root: Path) -> dict[str, Path]:
    root = root.resolve()
    return {
        'active_corpus': root / 'data/corpus.sqlite',
        'active_manifest': root / 'data/embeddings/manifest.json',
        'candidate_corpus': root / 'data/staging/qa27-search-repair/corpus.sqlite',
        'candidate_manifest': root / 'data/staging/qa27-search-repair/embeddings/manifest.json',
        'acceptance': root / 'data/staging/qa27-search-repair/independent-acceptance.json',
        'report': root / 'data/staging/qa27-search-repair/repair-report.json',
        'rows': root / 'data/embeddings/rows-456b8517c04a467aa1dd4face27d3e22.json',
        'vectors': root / 'data/embeddings/vectors-456b8517c04a467aa1dd4face27d3e22.npy',
        'rule': root / 'backend/textutils.py',
        'staging': root / 'data/staging',
    }


def _verify_shared_dependencies(root: Path) -> None:
    paths = _paths(root)
    if (sha256(paths['rows']) != ROWS_SHA256
            or sha256(paths['vectors']) != VECTORS_SHA256
            or sha256(paths['rule']) != RULE_SHA256):
        raise ValueError('Shared embedding assets or active search rule differ from accepted bytes')


def _verify_manifest(path: Path, corpus: Binding) -> None:
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('corpus_mtime_ns'), data.get('corpus_size')) != (corpus.mtime_ns, corpus.size):
        raise ValueError('Embedding manifest does not bind the exact corpus stat')
    if (data.get('rows_file') != 'rows-456b8517c04a467aa1dd4face27d3e22.json'
            or data.get('vectors_file') != 'vectors-456b8517c04a467aa1dd4face27d3e22.npy'):
        raise ValueError('Embedding manifest selects different assets')


def preflight(root: Path = ROOT) -> dict:
    _require_stopped()
    paths = _paths(root)
    _require_no_sqlite_sidecars(paths['active_corpus'], paths['candidate_corpus'])
    verify_file(paths['active_corpus'], BASE_CORPUS)
    verify_file(paths['active_manifest'], BASE_MANIFEST)
    verify_file(paths['candidate_corpus'], CANDIDATE_CORPUS)
    verify_file(paths['candidate_manifest'], CANDIDATE_MANIFEST)
    if sha256(paths['acceptance']) != ACCEPTANCE_SHA256 or sha256(paths['report']) != REPORT_SHA256:
        raise ValueError('Independent acceptance or producer report hash differs')
    _verify_shared_dependencies(root)
    acceptance = json.loads(paths['acceptance'].read_text(encoding='utf-8'))
    if (acceptance.get('verdict') != 'PASS'
            or acceptance.get('source_corpus_sha256') != BASE_CORPUS.sha256
            or acceptance.get('candidate_corpus_sha256') != CANDIDATE_CORPUS.sha256
            or acceptance.get('embedding_manifest_sha256') != CANDIDATE_MANIFEST.sha256
            or acceptance.get('source_records_unchanged') != 288584
            or acceptance.get('unchanged_embedding_model_inputs') != 116191):
        raise ValueError('Independent acceptance does not bind this exact artifact pair')
    _verify_manifest(paths['active_manifest'], BASE_CORPUS)
    _verify_manifest(paths['candidate_manifest'], CANDIDATE_CORPUS)
    return {'status': 'PREFLIGHT_PASS_NO_WRITES', 'baseline_corpus_sha256': BASE_CORPUS.sha256,
            'candidate_corpus_sha256': CANDIDATE_CORPUS.sha256,
            'candidate_manifest_sha256': CANDIDATE_MANIFEST.sha256,
            'acceptance_sha256': ACCEPTANCE_SHA256}


def _copy_bound(source: Path, destination: Path, binding: Binding) -> None:
    with source.open('rb') as original, destination.open('xb') as copied:
        shutil.copyfileobj(original, copied, length=1024 * 1024)
    if binding.mtime_ns is not None:
        os.utime(destination, ns=(source.stat().st_atime_ns, binding.mtime_ns))
    verify_file(destination, binding)


def _write_receipt(directory: Path, receipt: dict) -> None:
    target = directory / 'promotion-receipt.json'
    temporary = directory / f'.promotion-receipt-{uuid.uuid4().hex}.tmp'
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, target)


def _verify_runtime(root: Path, expected: Binding, candidate: bool) -> dict:
    from backend.semantic import SemanticIndex
    from backend.textutils import normalize
    paths = _paths(root)
    _verify_shared_dependencies(root)
    verify_file(paths['active_corpus'], expected)
    manifest_binding = CANDIDATE_MANIFEST if candidate else BASE_MANIFEST
    verify_file(paths['active_manifest'], manifest_binding)
    _verify_manifest(paths['active_manifest'], expected)
    with closing(sqlite3.connect(paths['active_corpus'].as_uri() + '?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Active corpus quick_check failed')
        bad = connection.execute('SELECT count(*) FROM tokens WHERE passage_id=? AND normalized=?',
                                 ('p2_cgl_anthology:292', normalize('μαπ'))).fetchone()[0]
        good = connection.execute('SELECT count(*) FROM tokens WHERE passage_id=? AND normalized=?',
                                  ('p2_cgl_anthology:187', normalize('ἀντιπέρας'))).fetchone()[0]
    if candidate and (bad != 0 or good != 1):
        raise ValueError('QA27 damaged/clean search controls failed')
    if not SemanticIndex(paths['active_manifest'].parent).ready:
        raise ValueError('Semantic index is not ready for active corpus')
    verify_file(paths['active_corpus'], expected)
    verify_file(paths['active_manifest'], manifest_binding)
    _verify_shared_dependencies(root)
    return {'quick_check': 'ok', 'semantic_ready': True,
            'cgl292_bad_token_count': bad, 'cgl187_clean_token_count': good}


def _restore(root: Path, directory: Path, receipt: dict) -> dict:
    _require_stopped()
    paths = _paths(root)
    backup_corpus = directory / 'old-corpus.sqlite'
    backup_manifest = directory / 'old-manifest.json'
    _require_no_sqlite_sidecars(paths['active_corpus'], paths['candidate_corpus'], backup_corpus)
    verify_file(backup_corpus, BASE_CORPUS)
    verify_file(backup_manifest, BASE_MANIFEST)
    for active, allowed in ((paths['active_corpus'], {BASE_CORPUS.sha256, CANDIDATE_CORPUS.sha256}),
                            (paths['active_manifest'], {BASE_MANIFEST.sha256, CANDIDATE_MANIFEST.sha256})):
        if active.exists() and sha256(active) not in allowed:
            raise ValueError(f'Active file is neither original nor QA27 candidate: {active}')
    ready_corpus = paths['active_corpus'].with_name(f'.qa27-rollback-{uuid.uuid4().hex}.sqlite')
    ready_manifest = paths['active_manifest'].with_name(f'.qa27-rollback-{uuid.uuid4().hex}.json')
    _copy_bound(backup_corpus, ready_corpus, BASE_CORPUS)
    _copy_bound(backup_manifest, ready_manifest, BASE_MANIFEST)
    _require_stopped()
    _require_no_sqlite_sidecars(paths['active_corpus'], backup_corpus)
    os.replace(ready_corpus, paths['active_corpus'])
    os.replace(ready_manifest, paths['active_manifest'])
    verified = _verify_runtime(root, BASE_CORPUS, False)
    receipt['status'] = 'ROLLED_BACK'
    receipt['rollback_validation'] = verified
    _write_receipt(directory, receipt)
    return {'status': 'ROLLED_BACK', 'receipt': str(directory / 'promotion-receipt.json')}


def promote(root: Path = ROOT) -> dict:
    root = root.resolve()
    preflight(root)
    paths = _paths(root)
    directory = Path(tempfile.mkdtemp(prefix='qa27-local-promotion-', dir=paths['staging']))
    receipt = {'status': 'PREPARING', 'created_utc': datetime.now(timezone.utc).isoformat(),
               'scope': 'local default corpus and semantic manifest only',
               'baseline': {'corpus_sha256': BASE_CORPUS.sha256, 'manifest_sha256': BASE_MANIFEST.sha256},
               'candidate': {'corpus_sha256': CANDIDATE_CORPUS.sha256,
                             'manifest_sha256': CANDIDATE_MANIFEST.sha256},
               'independent_acceptance_sha256': ACCEPTANCE_SHA256}
    _write_receipt(directory, receipt)
    _copy_bound(paths['active_corpus'], directory / 'old-corpus.sqlite', BASE_CORPUS)
    _copy_bound(paths['active_manifest'], directory / 'old-manifest.json', BASE_MANIFEST)
    ready_corpus = paths['active_corpus'].with_name(f'.qa27-ready-{directory.name}.sqlite')
    ready_manifest = paths['active_manifest'].with_name(f'.qa27-ready-{directory.name}.json')
    _copy_bound(paths['candidate_corpus'], ready_corpus, CANDIDATE_CORPUS)
    _copy_bound(paths['candidate_manifest'], ready_manifest, CANDIDATE_MANIFEST)
    receipt['status'] = 'PREPARED'
    receipt['backup_directory'] = str(directory)
    _write_receipt(directory, receipt)
    try:
        # Only the main agent stops/restarts local servers. Check once more
        # immediately before the first of the two necessarily separate swaps.
        _require_stopped()
        _require_no_sqlite_sidecars(paths['active_corpus'], paths['candidate_corpus'])
        _verify_shared_dependencies(root)
        verify_file(paths['active_corpus'], BASE_CORPUS)
        verify_file(paths['active_manifest'], BASE_MANIFEST)
        os.replace(ready_corpus, paths['active_corpus'])
        receipt['status'] = 'CORPUS_REPLACED'
        _write_receipt(directory, receipt)
        _require_stopped()
        _require_no_sqlite_sidecars(paths['active_corpus'], paths['candidate_corpus'])
        os.replace(ready_manifest, paths['active_manifest'])
        receipt['status'] = 'MANIFEST_REPLACED'
        _write_receipt(directory, receipt)
        receipt['validation'] = _verify_runtime(root, CANDIDATE_CORPUS, True)
        receipt['status'] = 'PASS'
        _write_receipt(directory, receipt)
        return {'status': 'PASS', 'receipt': str(directory / 'promotion-receipt.json'),
                'corpus_sha256': CANDIDATE_CORPUS.sha256,
                'manifest_sha256': CANDIDATE_MANIFEST.sha256}
    except BaseException as error:
        receipt['failure'] = type(error).__name__ + ': ' + str(error)
        try:
            _restore(root, directory, receipt)
        except BaseException as rollback_error:
            receipt['status'] = 'MANUAL_ROLLBACK_REQUIRED'
            receipt['rollback_failure'] = type(rollback_error).__name__ + ': ' + str(rollback_error)
            _write_receipt(directory, receipt)
        raise


def rollback(root: Path, receipt_directory: Path) -> dict:
    root = root.resolve()
    directory = receipt_directory.resolve()
    staging = (root / 'data/staging').resolve()
    if not directory.is_relative_to(staging) or not directory.name.startswith('qa27-local-promotion-'):
        raise ValueError('Rollback receipt must be a QA27 directory under this workspace staging root')
    receipt = json.loads((directory / 'promotion-receipt.json').read_text(encoding='utf-8'))
    if (receipt.get('baseline', {}).get('corpus_sha256') != BASE_CORPUS.sha256
            or receipt.get('candidate', {}).get('corpus_sha256') != CANDIDATE_CORPUS.sha256):
        raise ValueError('Rollback receipt does not bind QA27 baseline/candidate')
    return _restore(root, directory, receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--promote', action='store_true', help='Execute the reversible local switch')
    group.add_argument('--rollback', type=Path, help='Restore a QA27 backup directory')
    args = parser.parse_args()
    outcome = (rollback(ROOT, args.rollback) if args.rollback else
               promote(ROOT) if args.promote else preflight(ROOT))
    print(json.dumps(outcome))
