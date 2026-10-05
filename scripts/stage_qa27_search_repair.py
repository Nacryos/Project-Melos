"""Stage a derived-only Greek search repair; never publish or alter source rows.

The destination directory must not exist. The SQLite copy, selected embedding
files, rebound manifest, and audit report stay pending independent review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import gc
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize, search_text, tokenize
from scripts.build_corpus import SEARCHABLE_QUALITIES
from scripts.build_embeddings import source_rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _same_rows(before: sqlite3.Connection, after: sqlite3.Connection,
               query: str, label: str) -> int:
    missing = object()
    count = 0
    for left, right in itertools.zip_longest(before.execute(query), after.execute(query), fillvalue=missing):
        if left != right:
            raise ValueError(f'{label} changed; candidate is not deployable')
        count += 1
    return count


def _source_signature(path: Path) -> tuple[int, int, int, int, str]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size, sha256(path)


def _reject_unbound_journals(source: Path) -> None:
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError(f'Nonempty SQLite {suffix} sidecar is not bound by the corpus hash')


def _embedding_assets(embedding_dir: Path, manifest: dict) -> tuple[Path, Path]:
    names = [manifest.get('rows_file'), manifest.get('vectors_file')]
    if any(not isinstance(name, str) or not name or Path(name).name != name for name in names):
        raise ValueError('Embedding asset names must be plain basenames')
    if names[0] == names[1]:
        raise ValueError('Embedding row and vector assets must be distinct')
    paths = tuple((embedding_dir / name).resolve() for name in names)
    if any(not path.is_relative_to(embedding_dir) or not path.is_file() for path in paths):
        raise ValueError('Embedding asset missing or outside index directory')
    return paths


def _tokens(connection: sqlite3.Connection, identifier: str) -> dict[tuple[str, str], int]:
    rows = connection.execute(
        'SELECT form,normalized,count FROM tokens WHERE passage_id=?', (identifier,)
    ).fetchall()
    values = {(form, key): count for form, key, count in rows}
    if len(values) != len(rows):
        raise ValueError(f'Duplicate token rows for {identifier}')
    return values


def _expected_tokens(indexed: str) -> dict[tuple[str, str], int]:
    return {(form, normalize(form)): count for form, count in Counter(tokenize(indexed)).items()}


def _passage_columns(connection: sqlite3.Connection) -> list[str]:
    columns = [row[1] for row in connection.execute('PRAGMA table_info(passages)')]
    if 'normalized' not in columns or not {'id', 'text', 'language', 'kind', 'quality', 'data'} <= set(columns):
        raise ValueError('Unexpected passage schema')
    return columns


def _source_rows_equal(before: sqlite3.Connection, after: sqlite3.Connection) -> int:
    # Compare every current/future passage column except the one derived search key.
    columns = [name for name in _passage_columns(before) if name != 'normalized']
    if _passage_columns(after) != _passage_columns(before):
        raise ValueError('Passage schema changed')
    projection = ','.join('"' + name.replace('"', '""') + '"' for name in columns)
    count = _same_rows(before, after, f'SELECT {projection} FROM passages ORDER BY rowid',
                       'Source-bearing passage rows')
    for table in ('works', 'passage_authors'):
        _same_rows(before, after, f'SELECT * FROM {table} ORDER BY rowid', table)
    return count


def _validate_fts(before: sqlite3.Connection, after: sqlite3.Connection) -> None:
    old = before.execute('SELECT rowid,id,normalized,citation,author,work FROM passage_fts ORDER BY rowid')
    new = after.execute('SELECT rowid,id,normalized,citation,author,work FROM passage_fts ORDER BY rowid')
    missing = object()
    for left, right in itertools.zip_longest(old, new, fillvalue=missing):
        if left is missing or right is missing or left[:2] != right[:2] or left[3:] != right[3:]:
            raise ValueError('FTS identity or non-search fields changed')
        expected = after.execute('SELECT normalized FROM passages WHERE id=?', (right[1],)).fetchone()
        if expected is None or right[2] != expected[0]:
            raise ValueError(f'FTS normalized value differs from passage {right[1]}')


def _validate_vocabulary(connection: sqlite3.Connection) -> int:
    expected = dict(connection.execute(
        'SELECT normalized,sum(count) FROM tokens GROUP BY normalized'
    ))
    actual = {key: (form, count) for key, form, count in connection.execute(
        'SELECT normalized,form,count FROM vocabulary'
    )}
    if set(expected) != set(actual):
        raise ValueError('Vocabulary keys differ from token keys')
    for key, count in expected.items():
        form, stored = actual[key]
        if stored != count or normalize(form) != key:
            raise ValueError(f'Vocabulary aggregate/display mismatch: {key}')
    return len(expected)


def _validate_embedding_inputs(source: Path, candidate: Path, manifest_path: Path,
                               embedding_dir: Path, target_dir: Path,
                               verified_source_records: int,
                               assets_start: dict[Path, tuple[int, int, int, int, str]]) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    old_stat = source.stat()
    if (manifest.get('corpus_mtime_ns'), manifest.get('corpus_size')) != (old_stat.st_mtime_ns, old_stat.st_size):
        raise ValueError('Embedding manifest is not bound to the active corpus')
    old_inputs = source_rows(source)
    new_inputs = source_rows(candidate)
    if old_inputs != new_inputs:
        raise ValueError('Embedding model inputs or row metadata changed; rebuild vectors')
    rows_path, vectors_path = _embedding_assets(embedding_dir, manifest)
    if set(assets_start) != {rows_path, vectors_path}:
        raise ValueError('Embedding asset selection changed during staging')
    rows = json.loads(rows_path.read_text(encoding='utf-8'))
    if len(rows) != manifest.get('eligible_count') or len(rows) != len(old_inputs):
        raise ValueError('Published embedding row count differs from eligible source rows')
    fields = ('id', 'source', 'language', 'kind', 'author', 'parent_id', 'context_authors')
    for actual, source_row in zip(rows, old_inputs):
        if any(actual.get(key) != source_row.get(key) for key in fields):
            raise ValueError('Published embedding row metadata differs from corpus inputs')
    target_dir.mkdir()
    files = {}
    for input_path in (rows_path, vectors_path):
        output_path = target_dir / input_path.name
        shutil.copyfile(input_path, output_path)
        before_hash = assets_start[input_path][-1]
        after_hash = sha256(output_path)
        if before_hash != after_hash or _source_signature(input_path) != assets_start[input_path]:
            raise ValueError('Copied embedding asset changed')
        files[input_path.name] = {'sha256': before_hash, 'bytes': assets_start[input_path][3]}
    new_stat = candidate.stat()
    rebound = dict(manifest)
    rebound['corpus_mtime_ns'] = new_stat.st_mtime_ns
    rebound['corpus_size'] = new_stat.st_size
    rebound['search_only_rebind'] = {
        'previous_corpus_sha256': sha256(source),
        'candidate_corpus_sha256': sha256(candidate),
        'verified_unchanged_source_records': verified_source_records,
        'verified_unchanged_model_inputs': len(old_inputs),
        'original_manifest_sha256': sha256(manifest_path),
        'unchanged_embedding_files': files,
    }
    new_manifest = target_dir / 'manifest.json'
    new_manifest.write_text(json.dumps(rebound, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'eligible_rows': len(old_inputs), 'original_manifest_sha256': sha256(manifest_path),
            'candidate_manifest_sha256': sha256(new_manifest), 'unchanged_files': files}


def stage(source: Path, destination: Path, embedding_dir: Path, expected_delta: Path) -> dict:
    source, destination, embedding_dir = (Path(item).resolve() for item in (source, destination, embedding_dir))
    expected_delta = Path(expected_delta).resolve()
    if not source.is_file() or destination.exists() or destination == source.parent:
        raise ValueError('Require an existing corpus and a distinct nonexistent staging directory')
    manifest_path = embedding_dir / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Embedding manifest missing')
    _reject_unbound_journals(source)
    starting = _source_signature(source)
    manifest_start = _source_signature(manifest_path)
    rule_path = ROOT / 'backend/textutils.py'
    rule_start = _source_signature(rule_path)
    delta_start = _source_signature(expected_delta)
    selected_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assets_start = {path: _source_signature(path) for path in
                    _embedding_assets(embedding_dir, selected_manifest)}
    expected = json.loads(expected_delta.read_text(encoding='utf-8'))
    if (expected.get('corpus_sha256') != starting[-1]
            or expected.get('textutils_sha256') != rule_start[-1]):
        raise ValueError('Independent read-only delta is stale for corpus or search rule')
    expected_ids = [record['id'] for record in expected['records']]
    if len(expected_ids) != expected.get('changed_record_count') or len(expected_ids) != len(set(expected_ids)):
        raise ValueError('Invalid reviewed delta inventory')
    expected_by_id = {record['id']: record for record in expected['records']}
    # Never populate the final candidate name until every gate/report succeeds.
    staging = Path(tempfile.mkdtemp(prefix=f'.{destination.name}.building-', dir=destination.parent))
    output = staging / 'corpus.sqlite'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as monitor, \
         closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        version = monitor.execute('PRAGMA data_version').fetchone()[0]
        original.execute('BEGIN')
        original.execute('SELECT count(*) FROM sqlite_master').fetchone()
        with closing(sqlite3.connect(output)) as candidate:
            original.backup(candidate)
            candidate.execute('BEGIN')
            fts_ids = dict(candidate.execute('SELECT id,rowid FROM passage_fts'))
            if len(fts_ids) != candidate.execute('SELECT count(*) FROM passage_fts').fetchone()[0]:
                raise ValueError('Duplicate FTS IDs')
            changed = []
            changed_keys = set()
            candidate_rows = original.execute(
                "SELECT id,text,normalized,kind,quality FROM passages WHERE language='grc' ORDER BY rowid"
            )
            for identifier, text, old_normalized, kind, quality in candidate_rows:
                indexed = search_text(text)
                folded = normalize(indexed)
                old_tokens = _tokens(candidate, identifier)
                eligible = quality in SEARCHABLE_QUALITIES and kind in ('text', 'translation')
                new_tokens = _expected_tokens(indexed) if eligible else old_tokens
                normalized_changed = folded != old_normalized
                tokens_changed = eligible and new_tokens != old_tokens
                if not normalized_changed and not tokens_changed:
                    continue
                expected_row = expected_by_id.get(identifier)
                if not expected_row:
                    raise ValueError(f'Unreviewed changed record: {identifier}')
                old_search = expected_row.get('old_search_text')
                if (expected_row.get('original_text') != text
                        or expected_row.get('quality') != quality
                        or not isinstance(old_search, str)
                        or normalize(old_search) != old_normalized
                        or expected_row.get('new_search_text') != indexed
                        or expected_row.get('normalized_changed') != normalized_changed):
                    raise ValueError(f'Reviewed source/search projection differs: {identifier}')
                old_forms, new_forms = Counter(tokenize(old_search)), Counter(tokenize(indexed))
                if (expected_row.get('removed_search_tokens') != dict(old_forms - new_forms)
                        or expected_row.get('added_search_tokens') != dict(new_forms - old_forms)):
                    raise ValueError(f'Reviewed token delta differs: {identifier}')
                if eligible and (old_tokens != _expected_tokens(old_search)
                                 or new_tokens != _expected_tokens(indexed)):
                    raise ValueError(f'Stored or staged token inventory differs: {identifier}')
                if normalized_changed:
                    if identifier not in fts_ids:
                        raise ValueError(f'Passage lacks FTS row: {identifier}')
                    candidate.execute('UPDATE passages SET normalized=? WHERE id=?', (folded, identifier))
                    candidate.execute('UPDATE passage_fts SET normalized=? WHERE rowid=?',
                                      (folded, fts_ids[identifier]))
                if tokens_changed:
                    changed_keys.update(key for _, key in old_tokens)
                    changed_keys.update(key for _, key in new_tokens)
                    candidate.execute('DELETE FROM tokens WHERE passage_id=?', (identifier,))
                    candidate.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                                          [(identifier, form, key, count)
                                           for (form, key), count in new_tokens.items()])
                changed.append({
                    'id': identifier,
                    'normalized_changed': normalized_changed,
                    'tokens_changed': tokens_changed,
                    'old_normalized_sha256': hashlib.sha256(old_normalized.encode()).hexdigest(),
                    'new_normalized_sha256': hashlib.sha256(folded.encode()).hexdigest(),
                    'old_tokens': [[form, key, count] for (form, key), count in sorted(old_tokens.items())],
                    'new_tokens': [[form, key, count] for (form, key), count in sorted(new_tokens.items())],
                })
            if set(item['id'] for item in changed) != set(expected_ids):
                raise ValueError('Staged derived delta differs from independent full-corpus inventory')
            for key in sorted(changed_keys):
                count, form = candidate.execute(
                    'SELECT sum(count),min(form) FROM tokens WHERE normalized=?', (key,)
                ).fetchone()
                if count:
                    candidate.execute('INSERT OR REPLACE INTO vocabulary VALUES (?,?,?)', (key, form, count))
                else:
                    candidate.execute('DELETE FROM vocabulary WHERE normalized=?', (key,))
            old_meta = dict(original.execute('SELECT key,value FROM metadata'))
            prior = json.loads(old_meta['manifest'])
            updated = dict(prior)
            updated['vocabulary'] = candidate.execute('SELECT count(*) FROM vocabulary').fetchone()[0]
            updated['search_layout_version'] = 2
            updated['search_layout_rule_sha256'] = rule_start[-1]
            candidate.execute('UPDATE metadata SET value=? WHERE key=?',
                              (json.dumps(updated, ensure_ascii=False), 'manifest'))
            candidate.commit()
            source_count = _source_rows_equal(original, candidate)
            _validate_fts(original, candidate)
            new_meta = dict(candidate.execute('SELECT key,value FROM metadata'))
            if {k: v for k, v in old_meta.items() if k != 'manifest'} != \
                    {k: v for k, v in new_meta.items() if k != 'manifest'}:
                raise ValueError('Non-manifest metadata changed')
            repair_keys = ('vocabulary', 'search_layout_version', 'search_layout_rule_sha256')
            if ({k: v for k, v in updated.items() if k not in repair_keys} !=
                    {k: v for k, v in prior.items() if k not in repair_keys}):
                raise ValueError('Unrelated manifest values changed')
            vocabulary_count = _validate_vocabulary(candidate)
            if candidate.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Candidate SQLite integrity check failed')
        embedding = _validate_embedding_inputs(source, output, manifest_path,
                                               embedding_dir, staging / 'embeddings',
                                               source_count, assets_start)
        if (monitor.execute('PRAGMA data_version').fetchone()[0] != version
                or _source_signature(source) != starting
                or _source_signature(manifest_path) != manifest_start
                or _source_signature(rule_path) != rule_start
                or _source_signature(expected_delta) != delta_start
                or any(_source_signature(path) != signature for path, signature in assets_start.items())):
            raise ValueError('Active input changed during staging or embedding validation')
        _reject_unbound_journals(source)
    report = {
        'verdict': 'PENDING_INDEPENDENT_REVIEW',
        'source_corpus': {'path': str(source), 'sha256': starting[-1], 'bytes': starting[3],
                          'mtime_ns': starting[2]},
        'candidate_corpus': {'path': str(destination / 'corpus.sqlite'), 'sha256': sha256(output),
                             'bytes': output.stat().st_size, 'mtime_ns': output.stat().st_mtime_ns},
        'source_records_unchanged': source_count,
        'searchable_qualities': list(SEARCHABLE_QUALITIES),
        'changed_records': len(changed),
        'changed_token_keys': sorted(changed_keys),
        'changes': changed,
        'vocabulary_keys': vocabulary_count,
        'embedding': embedding,
        'integrity': 'quick_check ok; FTS identities and other fields unchanged',
        'rule_sha256': rule_start[-1],
        'expected_delta_sha256': delta_start[-1],
    }
    report_path = staging / 'repair-report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report_hash = sha256(report_path)
    if destination.exists():
        raise ValueError('Final staging destination appeared during validation')
    # build_embeddings.source_rows uses sqlite3's transaction context manager,
    # which does not itself close the connection; collect any closed-scope
    # cursor/connection cycle before Windows directory rename.
    gc.collect()
    os.rename(staging, destination)
    return {'report': str(destination / 'repair-report.json'), 'report_sha256': report_hash,
            'changed_records': len(changed), 'source_records_unchanged': source_count,
            'candidate_corpus_sha256': report['candidate_corpus']['sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--embeddings', type=Path, required=True)
    parser.add_argument('--expected-delta', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.destination, args.embeddings, args.expected_delta)))
