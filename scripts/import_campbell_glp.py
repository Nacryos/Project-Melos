"""Idempotently add the verified Campbell GLP passages to a corpus snapshot.

Operates on a COPY of corpus.sqlite (never the mounted live file). Rows whose
id already exists must be byte-identical to the record (JSON data column);
they are left untouched. Missing rows are appended with the established
schema-2 append routine (scripts/stage_corpus_addition.append_rows), which
keeps every existing passage, token, author, FTS and work row unchanged apart
from appended work counts. Re-running on the output is a no-op.

Optionally rebinds the semantic-search manifest to the new corpus snapshot
(existing vectors retained; new ids listed as pending embedding), exactly as
the five-poem Campbell integration did.

usage:
  python scripts/import_campbell_glp.py --corpus /path/to/copy/corpus.sqlite \
      [--records data/campbell_glp/campbell_glp.jsonl] \
      [--semantic-manifest old/manifest.json --semantic-output new/manifest.json --base-corpus old/corpus.sqlite]
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import stage_corpus_addition as append  # noqa: E402

RECORDS = ROOT / 'data/campbell_glp/campbell_glp.jsonl'
APPROVED_FIVE = ('campbell-glp:alcaeus:34a', 'campbell-glp:alcaeus:129', 'campbell-glp:alcaeus:130b',
                 'campbell-glp:alcaeus:326', 'campbell-glp:alcaeus:350')
SOURCE = 'campbell_assignment'


def load_records(path: Path) -> dict:
    rows = {}
    required = ('id', 'source', 'source_url', 'raw_path', 'raw_sha256', 'text', 'author',
                'work', 'edition', 'citation', 'language', 'license', 'kind', 'quality')
    for n, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
            raise ValueError(f'record {n}: missing required field')
        if row['source'] != SOURCE or not row['id'].startswith('campbell-glp:'):
            raise ValueError(f'record {n}: outside the Campbell GLP scope')
        if row['id'] in rows:
            raise ValueError('duplicate id ' + row['id'])
        if row['id'] in APPROVED_FIVE:
            raise ValueError('the five owner-approved passages are not re-imported: ' + row['id'])
        raw = (ROOT / row['raw_path']).resolve()
        if raw.is_file() and append.sha(raw) != row['raw_sha256']:
            raise ValueError('raw evidence hash mismatch for ' + row['id'])
        rows[row['id']] = row
    return rows


def stored(con, identifier):
    found = con.execute('SELECT data FROM passages WHERE id=?', (identifier,)).fetchone()
    return None if found is None else json.loads(found[0])


def import_rows(corpus: Path, records: Path) -> dict:
    rows = load_records(records)
    records_sha = append.sha(records)
    append.no_journal(corpus)
    with closing(sqlite3.connect(corpus)) as con:
        before = con.execute('SELECT count(*) FROM passages').fetchone()[0]
        missing_five = [i for i in APPROVED_FIVE if stored(con, i) is None]
        present, new = [], {}
        for identifier, row in rows.items():
            existing = stored(con, identifier)
            if existing is None:
                new[identifier] = row
                continue
            existing.pop('work_id', None)
            if existing != row:
                raise ValueError('existing row differs from verified record (refusing to overwrite): ' + identifier)
            present.append(identifier)
        if new:
            manifest = append.preflight(con, new)
            con.execute('BEGIN')
            try:
                works, keys = append.append_rows(con, new, manifest, records.name, records_sha)
                manifest['staged_additions'][-1]['integration_status'] = 'campbell_glp_import'
                con.execute("UPDATE metadata SET value=? WHERE key='manifest'", (json.dumps(manifest),))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        after = con.execute('SELECT count(*) FROM passages').fetchone()[0]
        check = con.execute('PRAGMA quick_check').fetchone()[0]
    if check != 'ok' or after != before + len(new):
        raise RuntimeError('post-import integrity check failed')
    return {'corpus': str(corpus), 'records': len(rows), 'records_sha256': records_sha,
            'already_present': len(present), 'added': len(new), 'passages_before': before,
            'passages_after': after, 'approved_five_missing': missing_five, 'added_ids': sorted(new)}


def rebind_semantic(manifest_path: Path, base_corpus: Path, corpus: Path, added_ids, output: Path) -> dict:
    from scripts.integrate_campbell_assignment import retained_semantic_manifest
    revised = retained_semantic_manifest(manifest_path, base_corpus, corpus, added_ids)
    revised['corpus_rebinding']['method'] = 'append-only Campbell GLP import; existing rows verified unchanged'
    output.write_bytes((json.dumps(revised, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return {'semantic_manifest': str(output), 'pending_embedding_added': len(added_ids)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--corpus', type=Path, required=True, help='corpus.sqlite COPY to modify in place')
    parser.add_argument('--records', type=Path, default=RECORDS)
    parser.add_argument('--semantic-manifest', type=Path)
    parser.add_argument('--semantic-output', type=Path)
    parser.add_argument('--base-corpus', type=Path, help='unmodified corpus the semantic manifest is bound to')
    args = parser.parse_args()
    report = import_rows(args.corpus, args.records)
    if args.semantic_manifest:
        if not (args.semantic_output and args.base_corpus):
            parser.error('--semantic-output and --base-corpus are required with --semantic-manifest')
        report.update(rebind_semantic(args.semantic_manifest, args.base_corpus, args.corpus,
                                      report['added_ids'], args.semantic_output))
    report['added_ids'] = len(report['added_ids'])
    print(json.dumps(report, ensure_ascii=False, indent=1))
