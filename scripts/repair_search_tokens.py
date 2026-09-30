"""Repair disposable token/vocabulary indexes without changing source records.

Input is opened read-only and held at one SQLite snapshot. Output must not
exist, is not published automatically, and remains unvalidated on failure.
No embeddings are recomputed: raw passage text is verified unchanged. After
validation, use rebind_search_embeddings.py to rebind its existing manifest.
"""
import argparse
import collections
from contextlib import closing
import itertools
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.textutils import normalize, search_text, tokenize


TOKENIZER_VERSION = 2


def _same_rows(original, repaired, query, label):
    """Stream corresponding rows; never materialize/sort the entire corpus."""
    sentinel = object()
    count = 0
    for before, after in itertools.zip_longest(original.execute(query), repaired.execute(query), fillvalue=sentinel):
        if before != after:
            raise RuntimeError(f'{label} changed; output must not be deployed')
        count += 1
    return count


def repair(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_file() or output.exists() or source == output:
        raise ValueError('Require an existing input and a distinct, nonexistent output')
    # Exclusive creation prevents accidentally opening/overwriting a raced path.
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    uri = source.as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as monitor, closing(sqlite3.connect(uri, uri=True)) as original:
        version = monitor.execute('PRAGMA data_version').fetchone()[0]
        original.execute('BEGIN')
        original.execute('SELECT count(*) FROM sqlite_master').fetchone()
        con = sqlite3.connect(output)
        try:
            original.backup(con)
            con.execute('BEGIN')
            changed = scanned = 0
            changed_keys = set()
            rows = original.execute("SELECT id,text,language FROM passages WHERE (quality IS NULL OR quality NOT IN ('mixed_content','machine_ocr','needs_review')) AND kind IN ('text','translation') ORDER BY rowid")
            for identifier, text, language in rows:
                scanned += 1
                indexed = search_text(text) if language == 'grc' else text
                counts = collections.Counter(tokenize(indexed))
                expected = {(form, normalize(form)): count for form, count in counts.items()}
                stored = con.execute('SELECT form,normalized,count FROM tokens WHERE passage_id=?', (identifier,)).fetchall()
                actual = {(form, key): count for form, key, count in stored}
                if len(actual) == len(stored) and actual == expected:
                    continue
                changed += 1
                changed_keys.update(key for _, key, _ in stored)
                changed_keys.update(key for _, key in expected)
                con.execute('DELETE FROM tokens WHERE passage_id=?', (identifier,))
                con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                                [(identifier, form, key, count) for (form, key), count in expected.items()])
            for key in sorted(changed_keys):
                count, form = con.execute('SELECT sum(count),min(form) FROM tokens WHERE normalized=?', (key,)).fetchone()
                if count:
                    con.execute('INSERT OR REPLACE INTO vocabulary VALUES (?,?,?)', (key, form, count))
                else:
                    con.execute('DELETE FROM vocabulary WHERE normalized=?', (key,))
            old_metadata = dict(original.execute('SELECT key,value FROM metadata'))
            old_manifest = json.loads(old_metadata.get('manifest', '{}'))
            manifest = {**old_manifest, 'tokenizer_version': TOKENIZER_VERSION,
                        'vocabulary': con.execute('SELECT count(*) FROM vocabulary').fetchone()[0]}
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('manifest', json.dumps(manifest)))
            verified = _same_rows(original, con, 'SELECT * FROM passages ORDER BY rowid', 'Source passage fields, including normalized text')
            _same_rows(original, con, 'SELECT * FROM works ORDER BY rowid', 'Work metadata')
            _same_rows(original, con, 'SELECT rowid,* FROM passage_fts ORDER BY rowid', 'FTS records')
            new_metadata = dict(con.execute('SELECT key,value FROM metadata'))
            if {k:v for k,v in old_metadata.items() if k != 'manifest'} != {k:v for k,v in new_metadata.items() if k != 'manifest'}:
                raise RuntimeError('Unrelated metadata changed; output must not be deployed')
            checks = [row[0] for row in con.execute('PRAGMA quick_check')]
            if checks != ['ok']:
                raise RuntimeError('Output SQLite integrity check failed; do not deploy')
            if (monitor.execute('PRAGMA data_version').fetchone()[0] != version
                    or (source.stat().st_dev, source.stat().st_ino) != source_identity):
                raise RuntimeError('Input changed during repair; output must not be deployed')
            con.commit()
            return {'scanned_passages': scanned, 'changed_passages': changed,
                    'vocabulary_keys_checked': len(changed_keys), 'tokenizer_version': TOKENIZER_VERSION,
                    'verified_unchanged_source_records': verified, 'source_records_unchanged': True,
                    'normalized_and_fts_unchanged': True, 'input_snapshot_stable': True, 'quick_check': 'ok'}
        finally:
            con.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.source, args.output)))
