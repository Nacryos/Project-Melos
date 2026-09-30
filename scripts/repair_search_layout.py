"""Create a separate, verified search-index snapshot; never edit source text.

Reads the existing accepted database and updates only derived search columns,
tokens, vocabulary and search metadata. Output must not already exist. Deploy
by atomically replacing the index only after checking this output and retaining
the original for rollback. No source/edition records are created or modified.
"""
import argparse
import collections
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.textutils import normalize, search_text, tokenize


def repair(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_file() or output.exists() or source == output:
        raise ValueError('Require an existing input and a distinct, nonexistent output')
    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as original:
        con = sqlite3.connect(output)
        try:
            original.backup(con)
            changed = 0
            changed_keys = set()
            # The FTS id is UNINDEXED; use its real rowid instead of rescanning
            # the entire corpus for each repaired passage.
            fts_rows = dict(con.execute('SELECT id,rowid FROM passage_fts'))
            rows = con.execute("SELECT id,text,normalized,kind,quality FROM passages WHERE language='grc' AND (instr(text,'-') OR instr(text,char(8208)) OR instr(text,char(173)))").fetchall()
            for identifier, text, old, kind, quality in rows:
                indexed = search_text(text)
                folded = normalize(indexed)
                if folded == old:
                    continue
                changed += 1
                con.execute('UPDATE passages SET normalized=? WHERE id=?', (folded, identifier))
                con.execute('UPDATE passage_fts SET normalized=? WHERE rowid=?', (folded, fts_rows[identifier]))
                if quality not in ('mixed_content', 'machine_ocr', 'needs_review') and kind in ('text', 'translation'):
                    changed_keys.update(r[0] for r in con.execute('SELECT normalized FROM tokens WHERE passage_id=?', (identifier,)))
                    con.execute('DELETE FROM tokens WHERE passage_id=?', (identifier,))
                    counts = collections.Counter(tokenize(indexed))
                    con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                                    [(identifier, form, normalize(form), n) for form, n in counts.items()])
                    changed_keys.update(normalize(form) for form in counts)
            for key in sorted(changed_keys):
                count, form = con.execute('SELECT sum(count),min(form) FROM tokens WHERE normalized=?', (key,)).fetchone()
                if count:
                    con.execute('INSERT OR REPLACE INTO vocabulary VALUES (?,?,?)', (key, form, count))
                else:
                    con.execute('DELETE FROM vocabulary WHERE normalized=?', (key,))
            manifest = con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
            if manifest:
                value = json.loads(manifest[0])
                value['vocabulary'] = con.execute('SELECT count(*) FROM vocabulary').fetchone()[0]
                value['search_layout_version'] = 1
                con.execute("UPDATE metadata SET value=? WHERE key='manifest'", (json.dumps(value),))
            con.commit()
            # Compare every source-bearing field. Only normalized was changed.
            con.execute('ATTACH DATABASE ? AS original', (str(source),))
            fields = 'id,work_id,source,author,work,edition,citation,language,kind,quality,text,data,sequence'
            for first, second in [('main', 'original'), ('original', 'main')]:
                if con.execute(f'SELECT {fields} FROM {first}.passages EXCEPT SELECT {fields} FROM {second}.passages LIMIT 1').fetchone():
                    raise RuntimeError('Source-bearing fields changed; do not deploy')
            if con.execute('PRAGMA main.quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Index integrity check failed; do not deploy')
            return {'changed_passages': changed, 'vocabulary_keys_checked': len(changed_keys),
                    'source_records_unchanged': True, 'quick_check': 'ok'}
        finally:
            con.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.source, args.output)))
