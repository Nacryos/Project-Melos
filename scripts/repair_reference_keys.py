"""Repair U+1FBF-derived reference keys in separate, validated SQLite copies.

No claim, source JSON, spelling, offset, acceptance hash or scholarly status
may change. The normalizer supplies lookup keys only, not new evidence.
"""
import argparse
from contextlib import closing
import itertools
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.morphology import normalize
from backend.wiktionary import approved_source_hash, _key_rows, SCHEMA_VERSION
from scripts.build_evidence import _accepted_files
from backend.normalization_contract import NORMALIZATION_VERSION

MARK = '\u1fbf'
ROOT = Path(__file__).resolve().parents[1]


def _rows_equal(original, revised, query, transform=None):
    sentinel = object()
    count = 0
    for before, after in itertools.zip_longest(original.execute(query), revised.execute(query), fillvalue=sentinel):
        expected = transform(before) if transform is not None and before is not sentinel else before
        if expected != after:
            raise RuntimeError('Unexpected reference/source field change; do not deploy output')
        count += 1
    return count


def _identity(con, kind, root):
    if kind == 'evidence':
        accepted = _accepted_files(root, root/'data/reports/p2-claim-acceptance.json')
        expected = sorted((path.name, digest, count) for path, digest, count in accepted)
        actual = con.execute('SELECT name,sha256,records FROM input_files ORDER BY name').fetchall()
        counts = dict(con.execute('SELECT source_file,count(*) FROM claims GROUP BY source_file'))
        if actual != expected or counts != {name: count for name, _, count in expected if count}:
            raise RuntimeError('Evidence index does not match accepted files/counts')
        return actual
    digest = approved_source_hash(root/'data/lexica/wiktionary-entries.jsonl', root/'data/reports/wiktionary-audit.json')
    metadata = dict(con.execute('SELECT key,value FROM metadata'))
    if metadata.get('schema_version') != SCHEMA_VERSION or metadata.get('approved_source_sha256') != digest:
        raise RuntimeError('Wiktionary index does not match accepted source identity')
    return metadata


def _evidence(original, con):
    changes, verified = {}, {}
    for table in ('claims', 'form_edges'):
        changed = 0
        for rowid, form, old in original.execute(f'SELECT rowid,form,normalized_form FROM {table} WHERE instr(form,?)', (MARK,)):
            new = normalize(form)
            if new != old:
                con.execute(f'UPDATE {table} SET normalized_form=? WHERE rowid=?', (new, rowid))
                changed += 1
        columns = [row[1] for row in original.execute(f'PRAGMA table_info({table})')]
        form_index, key_index = columns.index('form'), columns.index('normalized_form')
        def permitted_change(row):
            values = list(row)
            if MARK in (values[form_index] or ''):
                values[key_index] = normalize(values[form_index])
            return tuple(values)
        verified[table] = _rows_equal(original, con, f'SELECT * FROM {table} ORDER BY rowid', permitted_change)
        changes[table] = changed
    _rows_equal(original, con, 'SELECT * FROM input_files ORDER BY rowid')
    return {'changed_normalized_rows': changes, 'verified_source_rows': verified}


def _wiktionary(original, con):
    selected, headwords, key_rows = set(), 0, 0
    # The character may occur in notes rather than key-bearing fields. Only
    # deterministic headword/listed-form projections are eligible for repair.
    for identifier, headword, old_key, raw in original.execute('SELECT id,headword,headword_key,record_json FROM entries WHERE instr(record_json,?) OR instr(headword,?) OR instr(lower(record_json),?)', (MARK, MARK, '\\u1fbf')):
        record = json.loads(raw)
        if record.get('id') != identifier or record.get('entry', {}).get('word') != headword:
            raise RuntimeError('Wiktionary source projection disagrees with stored headword/id')
        forms = record.get('entry', {}).get('forms', [])
        if MARK not in headword and not any(isinstance(form, dict) and MARK in str(form.get('form') or '') for form in forms):
            continue
        expected = _key_rows(record, 0)
        actual = original.execute('SELECT key,entry_id,kind,form_index FROM lookup_keys WHERE entry_id=?', (identifier,)).fetchall()
        new_key = normalize(headword)
        if sorted(expected) == sorted(actual) and new_key == old_key:
            continue
        selected.add(identifier)
        if new_key != old_key:
            con.execute('UPDATE entries SET headword_key=? WHERE id=?', (new_key, identifier))
            headwords += 1
        if sorted(expected) != sorted(actual):
            con.execute('DELETE FROM lookup_keys WHERE entry_id=?', (identifier,))
            con.executemany('INSERT INTO lookup_keys VALUES (?,?,?,?)', expected)
            key_rows += len(set(expected).symmetric_difference(actual))
        observed = con.execute('SELECT key,entry_id,kind,form_index FROM lookup_keys WHERE entry_id=?', (identifier,)).fetchall()
        if sorted(expected) != sorted(observed):
            raise RuntimeError('Wiktionary derived lookup projection is inconsistent')
    def permitted_change(row):
        identifier, headword, old_key, raw = row
        return (identifier, headword, normalize(headword) if identifier in selected else old_key, raw)
    count = _rows_equal(original, con, 'SELECT id,headword,headword_key,record_json FROM entries ORDER BY rowid', permitted_change)
    # Compare every unaffected derived row without adding an expensive new index.
    before = (row for row in original.execute('SELECT * FROM lookup_keys ORDER BY rowid') if row[1] not in selected)
    after = (row for row in con.execute('SELECT * FROM lookup_keys ORDER BY rowid') if row[1] not in selected)
    sentinel = object()
    if any(left != right for left, right in itertools.zip_longest(before, after, fillvalue=sentinel)):
        raise RuntimeError('Unrelated Wiktionary lookup keys changed')
    _rows_equal(original, con, 'SELECT * FROM metadata ORDER BY rowid')
    return {'changed_entries': len(selected), 'changed_headword_keys': headwords,
            'lookup_key_row_difference': key_rows, 'verified_source_rows': {'entries': count}}


def repair(source, output, kind, root=ROOT):
    if kind not in ('evidence', 'wiktionary'):
        raise ValueError('Expected evidence or wiktionary index kind')
    source, output, root = (Path(path).resolve() for path in (source, output, root))
    if not source.is_file() or output.exists() or source == output:
        raise ValueError('Require existing input and distinct nonexistent output')
    if MARK not in normalize(MARK):
        raise RuntimeError('Runtime normalizer does not preserve U+1FBF; do not migrate yet')
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    uri = source.as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as monitor, closing(sqlite3.connect(uri, uri=True)) as original:
        version = monitor.execute('PRAGMA data_version').fetchone()[0]
        original.execute('BEGIN')
        identity = _identity(original, kind, root)
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(output)) as con:
            original.backup(con)
            con.execute('BEGIN')
            result = _evidence(original, con) if kind == 'evidence' else _wiktionary(original, con)
            _rows_equal(original, con, 'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY rowid')
            table = 'lookup_metadata' if kind == 'evidence' else 'metadata'
            exists = original.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone()
            old_metadata = dict(original.execute(f'SELECT key,value FROM {table}')) if exists else {}
            if old_metadata.get('normalization_version') not in (None, '1', NORMALIZATION_VERSION):
                raise RuntimeError('Unknown normalization version; refusing to relabel reference keys')
            if not exists:
                con.execute('CREATE TABLE lookup_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            con.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', ('normalization_version', NORMALIZATION_VERSION))
            metadata = dict(con.execute(f'SELECT key,value FROM {table}'))
            if metadata != {**old_metadata, 'normalization_version': NORMALIZATION_VERSION}:
                raise RuntimeError('Unexpected normalization metadata changes')
            if _identity(original, kind, root) != identity:
                raise RuntimeError('Accepted source identity changed during migration')
            if monitor.execute('PRAGMA data_version').fetchone()[0] != version or (source.stat().st_dev, source.stat().st_ino) != source_identity:
                raise RuntimeError('Input snapshot changed during migration')
            if [row[0] for row in con.execute('PRAGMA quick_check')] != ['ok']:
                raise RuntimeError('SQLite integrity failure; do not deploy output')
            con.commit()
    return {'kind': kind, **result, 'source_fields_unchanged': True,
            'acceptance_identity_unchanged': True, 'normalization_version': NORMALIZATION_VERSION,
            'input_snapshot_stable': True, 'quick_check': 'ok'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--kind', choices=('evidence', 'wiktionary'), required=True)
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args()
    print(json.dumps(repair(args.source, args.output, args.kind, args.root)))
