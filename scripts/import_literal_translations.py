"""Append the literal-translation rows to a COPY of corpus.sqlite (never the mounted live file).

Rows come from data/campbell_glp/literal_translations_rows.jsonl (scripts/build_literal_translations.py):
kind translation, language eng, quality machine_translation, parent_id = the Campbell poem. They are
appended with the schema-2 routine (scripts/stage_corpus_addition.append_rows); every existing row stays
unchanged; re-running on the output is a no-op. The semantic manifest can be rebound to the new corpus
with the new ids listed as pending embedding (scripts/embed_release_o.py then encodes and assembles them).

usage:
  python scripts/import_literal_translations.py --corpus /path/to/copy/corpus.sqlite \
      [--records data/campbell_glp/literal_translations_rows.jsonl] \
      [--semantic-manifest old/manifest.json --semantic-output new/manifest.json --base-corpus old/corpus.sqlite]
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import stage_corpus_addition as append  # noqa: E402
from scripts.build_literal_translations import CORPUS_SOURCE, QUALITY  # noqa: E402

RECORDS = ROOT / 'data/campbell_glp/literal_translations_rows.jsonl'
REQUIRED = ('id', 'source', 'source_url', 'raw_path', 'raw_sha256', 'text', 'author', 'work', 'edition',
            'citation', 'language', 'license', 'kind', 'quality', 'parent_id')


def load_records(path: Path) -> dict:
    rows = {}
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in REQUIRED):
            raise ValueError(f'record {n}: missing required field')
        if (row['source'] != CORPUS_SOURCE or row['quality'] != QUALITY or row['kind'] != 'translation'
                or row['language'] != 'eng' or row['id'] != row['parent_id'] + ':literal'
                or row.get('metadata', {}).get('model_eligible') is not False):
            raise ValueError(f'record {n}: outside the literal-translation scope')
        if row['id'] in rows:
            raise ValueError('duplicate id ' + row['id'])
        raw = (ROOT / row['raw_path']).resolve()
        if not raw.is_file() or append.sha(raw) != row['raw_sha256']:
            raise ValueError('source file hash mismatch for ' + row['id'])
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
        present, new = [], {}
        for identifier, row in rows.items():
            parent = stored(con, row['parent_id'])
            if parent is None:
                raise ValueError('parent poem missing from the corpus: ' + row['parent_id'])
            if parent.get('text') != '\n'.join(l['greek'] for l in _source_lines(row)):
                raise ValueError('parent text differs from the text the translation was made from: ' + row['parent_id'])
            existing = stored(con, identifier)
            if existing is None:
                new[identifier] = row
                continue
            existing.pop('work_id', None)
            if existing != row:
                raise ValueError('existing row differs from the record (refusing to overwrite): ' + identifier)
            present.append(identifier)
        if new:
            manifest = append.preflight(con, new)
            con.execute('BEGIN')
            try:
                works, keys = append.append_rows(con, new, manifest, records.name, records_sha)
                manifest['staged_additions'][-1]['integration_status'] = 'literal_translation_import'
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
            'passages_after': after, 'added_ids': sorted(new)}


_SIDECAR_LINES: dict | None = None


def _source_lines(row: dict) -> list[dict]:
    """Greek lines the translation was made from, read from the reader sidecar (same build)."""
    global _SIDECAR_LINES
    if _SIDECAR_LINES is None:
        payload = json.loads((ROOT / 'backend/literal_translations_data.json').read_text(encoding='utf-8'))
        _SIDECAR_LINES = {r['campbell_record_id']: r['lines'] for r in payload['records']}
    return _SIDECAR_LINES[row['parent_id']]


def rebind_semantic(manifest_path: Path, base_corpus: Path, corpus: Path, added_ids, output: Path) -> dict:
    from scripts.integrate_campbell_assignment import retained_semantic_manifest
    revised = retained_semantic_manifest(manifest_path, base_corpus, corpus, added_ids)
    revised['corpus_rebinding']['method'] = 'append-only literal-translation import; existing rows verified unchanged'
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
