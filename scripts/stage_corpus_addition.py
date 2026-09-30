"""Append independently accepted collector rows to an immutable corpus clone.

Never rebuild the active corpus from collector files: doing so can lose indexed
policy changes. This tool requires a PASS base audit binding corpus/evidence
hashes and a PASS collector audit binding the exact new JSONL hash/count. It
copies only into a fresh data/staging directory and emits PENDING integration
acceptance. No claims are inferred; evidence.sqlite remains byte-identical.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import copy
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.author_aliases import canonical, canonical_key, component_keys
from backend.textutils import normalize, search_text, text_key, tokenize
from scripts.build_corpus import SEARCHABLE_QUALITIES


def sha(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def no_journal(path):
    for suffix in ('-wal', '-journal'):
        journal = Path(str(path) + suffix)
        if journal.exists() and journal.stat().st_size:
            raise ValueError('Immutable input has an active SQLite journal: ' + str(path))


def work_identity(row):
    values = [row[field] for field in ('source', 'author', 'work', 'edition', 'language')]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:20]


def accepted_rows(path, acceptance, root, source):
    approval = read_json(acceptance).get('files', {}).get(path.name, {})
    if approval.get('verdict') != 'PASS' or approval.get('sha256') != sha(path):
        raise ValueError('New collector output is not independently accepted at its current hash')
    rows, raw_hashes = {}, {}
    required = ('id', 'source', 'source_url', 'raw_path', 'raw_sha256', 'text', 'author',
                'work', 'edition', 'citation', 'language', 'license', 'kind', 'quality')
    for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
            raise ValueError(f'Invalid required source fields at line {line_number}')
        if row['id'] in rows:
            raise ValueError('Duplicate new ID: ' + row['id'])
        if row['source'] != source:
            raise ValueError('Collector source exceeds the declared append scope')
        if row.get('metadata') is not None and not isinstance(row['metadata'], dict):
            raise ValueError('Invalid metadata object')
        if row.get('parent_id') is not None and (not isinstance(row['parent_id'], str) or not row['parent_id']):
            raise ValueError('Invalid explicit parent ID')
        if 'work_id' in row and row['work_id'] != work_identity(row):
            raise ValueError('Source work_id conflicts with the established derived identity')
        raw = (root / row['raw_path']).resolve()
        if not raw.is_relative_to(root) or not raw.is_file():
            raise ValueError('Raw artifact missing or outside project')
        if raw not in raw_hashes:
            raw_hashes[raw] = sha(raw)
        if raw_hashes[raw] != row['raw_sha256']:
            raise ValueError('Raw artifact hash mismatch: ' + row['raw_path'])
        rows[row['id']] = row
    if not rows or len(rows) != approval.get('records'):
        raise ValueError('Accepted record count mismatch or empty addition')
    return rows, approval, raw_hashes


def preflight(con, rows):
    manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
    columns = {r[1] for r in con.execute('PRAGMA table_info(passages)')}
    if manifest.get('schema') != 2 or not {'author_canonical', 'text_key'} <= columns:
        raise ValueError('Append requires an accepted schema-2 corpus; migrate separately')
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='passage_authors'").fetchone():
        raise ValueError('Schema-2 author membership table is missing')
    for identifier, row in rows.items():
        if con.execute('SELECT 1 FROM passages WHERE id=?', (identifier,)).fetchone():
            raise ValueError('New ID collides with existing corpus: ' + identifier)
        parent = row.get('parent_id')
        if parent and parent not in rows and not con.execute('SELECT 1 FROM passages WHERE id=?', (parent,)).fetchone():
            raise ValueError('Dangling explicit parent: ' + identifier)
        seen = {identifier}
        while parent in rows:
            if parent in seen:
                raise ValueError('Cycle in new explicit parent links')
            seen.add(parent)
            parent = rows[parent].get('parent_id')
    return manifest


def append_rows(con, rows, manifest, filename, source_hash):
    affected_works, token_keys = {}, set()
    for original in rows.values():
        row = copy.deepcopy(original)
        wid = work_identity(row)
        row['work_id'] = wid
        if wid not in affected_works:
            existing = con.execute('SELECT source,author,work,edition,language,count FROM works WHERE id=?', (wid,)).fetchone()
            identity = tuple(row[k] for k in ('source', 'author', 'work', 'edition', 'language'))
            n, highest = con.execute('SELECT count(*),max(sequence) FROM passages WHERE work_id=?', (wid,)).fetchone()
            if existing:
                if existing[:5] != identity or existing[5] != n or highest != n - 1:
                    raise ValueError('Existing work identity/count/sequence mismatch')
            elif n:
                raise ValueError('Passages refer to a missing work')
            affected_works[wid] = {'identity': identity, 'old_count': n, 'count': n, 'new': not bool(existing)}
        work = affected_works[wid]
        indexed = search_text(row['text']) if row['language'] == 'grc' else row['text']
        folded, author = normalize(indexed), canonical(row['author'])
        values = (row['id'], wid, row['source'], row['author'], row['work'], row['edition'], row['citation'],
                  row['language'], row['kind'], row['quality'], row['text'], folded,
                  json.dumps(row, ensure_ascii=False), work['count'], author,
                  text_key(row['language'], row['kind'], row['text']))
        con.execute('INSERT INTO passages (id,work_id,source,author,work,edition,citation,language,kind,quality,'
                    'text,normalized,data,sequence,author_canonical,text_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
        con.executemany('INSERT INTO passage_authors (passage_id,author_key) VALUES (?,?)',
                        [(row['id'], key) for key in component_keys(row['author'])])
        fts_author = row['author'] + ' ' + author if author != row['author'] else author
        con.execute('INSERT INTO passage_fts (id,normalized,citation,author,work) VALUES (?,?,?,?,?)',
                    (row['id'], folded, normalize(row['citation']), normalize(fts_author), normalize(row['work'])))
        if row['quality'] in SEARCHABLE_QUALITIES and row['kind'] in ('text', 'translation'):
            counts = Counter(tokenize(indexed))
            con.executemany('INSERT INTO tokens (passage_id,form,normalized,count) VALUES (?,?,?,?)',
                            [(row['id'], form, normalize(form), count) for form, count in counts.items()])
            token_keys.update(normalize(form) for form in counts)
        work['count'] += 1
    for wid, work in affected_works.items():
        source, author, title, edition, language = work['identity']
        if work['new']:
            con.execute('INSERT INTO works (id,author,work,edition,source,language,count,author_canonical) VALUES (?,?,?,?,?,?,?,?)',
                        (wid, author, title, edition, source, language, work['count'], canonical(author)))
        else:
            con.execute('UPDATE works SET count=? WHERE id=?', (work['count'], wid))
    for key in token_keys:
        form, count = con.execute('SELECT min(form),sum(count) FROM tokens WHERE normalized=?', (key,)).fetchone()
        con.execute('INSERT OR REPLACE INTO vocabulary (normalized,form,count) VALUES (?,?,?)', (key, form, count))
    sources = dict(con.execute('SELECT source,count(*) FROM passages GROUP BY source'))
    labels = [r[0] for r in con.execute('SELECT DISTINCT author FROM passages')]
    manifest.update(passages=sum(sources.values()), sources=sources,
                    works=con.execute('SELECT count(*) FROM works').fetchone()[0],
                    vocabulary=con.execute('SELECT count(*) FROM vocabulary').fetchone()[0])
    target_path = 'data/processed/' + filename
    if target_path not in manifest.setdefault('files', []):
        manifest['files'].append(target_path)
    manifest['statistics'] = {
        'languages': [{'language': k, 'count': n} for k, n in con.execute('SELECT language,count(*) FROM passages GROUP BY language ORDER BY count(*) DESC,language')],
        'quality': [{'quality': k, 'count': n} for k, n in con.execute('SELECT quality,count(*) FROM passages GROUP BY quality ORDER BY quality')],
        'sources': [{'source': k, 'count': n} for k, n in sorted(sources.items())],
        'authors': len({canonical_key(label) for label in labels}), 'author_labels': len(labels)}
    manifest.setdefault('staged_additions', []).append({'file': filename, 'sha256': source_hash,
        'records': len(rows), 'integration_status': 'PENDING_INDEPENDENT_AUDIT'})
    con.execute("UPDATE metadata SET value=? WHERE key='manifest'", (json.dumps(manifest),))
    return affected_works, token_keys


def verify_preserved(original, revised, rows, affected_works, token_keys):
    """Compare all old source/derived rows, not merely unrelated text counts."""
    sentinel = object()
    counts = {}
    for table, key, order in (('passages', 'id', 'id'), ('tokens', 'passage_id', 'rowid'),
                              ('passage_authors', 'passage_id', 'rowid'), ('passage_fts', 'id', 'rowid')):
        columns = [r[1] for r in original.execute('PRAGMA table_info(' + table + ')')]
        at = columns.index(key)
        before = original.execute('SELECT * FROM ' + table + ' ORDER BY ' + order)
        after = (r for r in revised.execute('SELECT * FROM ' + table + ' ORDER BY ' + order) if r[at] not in rows)
        n = 0
        for a, b in itertools.zip_longest(before, after, fillvalue=sentinel):
            if a != b:
                raise RuntimeError('Existing rows changed in ' + table)
            n += 1
        counts[table] = n
    work_columns = [r[1] for r in original.execute('PRAGMA table_info(works)')]
    count_index = work_columns.index('count')
    for old in original.execute('SELECT * FROM works'):
        new = revised.execute('SELECT * FROM works WHERE id=?', (old[0],)).fetchone()
        expected = list(old)
        if old[0] in affected_works:
            expected[count_index] = affected_works[old[0]]['count']
        if tuple(expected) != new:
            raise RuntimeError('Existing work fields changed outside appended count')
    before = (r for r in original.execute('SELECT * FROM vocabulary ORDER BY normalized') if r[0] not in token_keys)
    after = (r for r in revised.execute('SELECT * FROM vocabulary ORDER BY normalized') if r[0] not in token_keys)
    if any(a != b for a, b in itertools.zip_longest(before, after, fillvalue=sentinel)):
        raise RuntimeError('Unrelated vocabulary changed')
    for key, value in original.execute("SELECT key,value FROM metadata WHERE key!='manifest'"):
        if revised.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone() != (value,):
            raise RuntimeError('Unrelated corpus metadata changed')
    if revised.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise RuntimeError('Staged corpus quick_check failed')
    return counts


def stage_addition(records_path, source_acceptance, output_dir, *, corpus, evidence,
                   base_audit, runtime_acceptance, source, root=ROOT):
    root = Path(root).resolve()
    records_path, source_acceptance, output = map(lambda p: Path(p).resolve(), (records_path, source_acceptance, output_dir))
    corpus, evidence, base_audit, runtime_acceptance = map(lambda p: Path(p).resolve(), (corpus, evidence, base_audit, runtime_acceptance))
    if not output.is_relative_to(root / 'data/staging') or output.exists():
        raise ValueError('Output must be a fresh directory beneath data/staging')
    if records_path.name in {'corpus.sqlite', 'evidence.sqlite'} or records_path.suffix != '.jsonl':
        raise ValueError('Collector output must be a JSONL file')
    files = [corpus, evidence, records_path, source_acceptance, base_audit, runtime_acceptance,
             Path(__file__).resolve(), ROOT / 'backend/author_aliases.py', ROOT / 'backend/author_aliases.json',
             ROOT / 'backend/textutils.py', ROOT / 'scripts/build_corpus.py']
    for path in (corpus, evidence):
        no_journal(path)
    before = {str(path): sha(path) for path in files}
    audit = read_json(base_audit)
    if audit.get('verdict') != 'PASS':
        raise ValueError('Base integration audit is not PASS')
    for path, field in ((corpus, 'corpus_sha256'), (evidence, 'evidence_sha256')):
        if before[str(path)] != audit.get(field):
            raise ValueError('Base artifact differs from accepted audit: ' + path.name)
    rows, approval, raw_hashes = accepted_rows(records_path, source_acceptance, root, source)
    acceptance = read_json(runtime_acceptance)
    previous_approval = acceptance.get('files', {}).get(records_path.name)
    if previous_approval and previous_approval.get('sha256') != approval['sha256']:
        raise ValueError('Append would replace an existing collector acceptance entry')
    before.update({str(path): digest for path, digest in raw_hashes.items()})
    with closing(sqlite3.connect(corpus.as_uri() + '?mode=ro', uri=True)) as original:
        original.execute('BEGIN')
        manifest = preflight(original, rows)
        output.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(records_path, output / records_path.name)
        copied_rows = {row['id']: row for row in (
            json.loads(line) for line in (output / records_path.name).read_text(encoding='utf-8-sig').splitlines() if line.strip())}
        if sha(output / records_path.name) != approval['sha256'] or copied_rows != rows:
            raise RuntimeError('Collector input changed between validation and copy')
        shutil.copyfile(evidence, output / 'evidence.sqlite')
        with closing(sqlite3.connect(output / 'corpus.sqlite')) as revised:
            original.backup(revised)
            works, keys = append_rows(revised, rows, manifest, records_path.name, approval['sha256'])
            revised.commit()
            preserved = verify_preserved(original, revised, rows, works, keys)
    for path in (corpus, evidence):
        no_journal(path)
    if any(sha(Path(path)) != digest for path, digest in before.items()):
        raise RuntimeError('Input changed during staging; candidate is not publishable')
    if sha(output / 'evidence.sqlite') != audit['evidence_sha256']:
        raise RuntimeError('Evidence changed; append may not invent or update claims')
    acceptance.setdefault('files', {})[records_path.name] = approval
    write_json(output / 'audit-acceptance.candidate.json', acceptance)
    write_json(output / 'index.json', manifest)
    report = {'status': 'PENDING_INDEPENDENT_AUDIT', 'operation': 'accepted_collector_append',
              'source': source, 'source_records': len(rows), 'source_sha256': approval['sha256'],
              'source_acceptance': str(source_acceptance), 'base_audit': str(base_audit),
              'input_hashes': before, 'added_ids': list(rows),
              'affected_works': {key: value for key, value in works.items()},
              'existing_rows_preserved': preserved, 'vocabulary_keys_recomputed': len(keys),
              'evidence': {'unchanged': True, 'new_structured_claims': 0,
                           'reason': 'Collector text/translation records are not new adjudicated structured claims.'},
              'embeddings': {'status': 'REBUILD_REQUIRED', 'reason': 'New corpus membership; rebuild rows and encode newly eligible texts with the pinned contract.'},
              'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'artifacts': {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in output.iterdir() if p.is_file()}}
    write_json(output / 'addition-manifest.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('records', 'source-acceptance', 'output-dir', 'corpus', 'evidence', 'base-audit', 'runtime-acceptance'):
        parser.add_argument('--' + option, type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = stage_addition(args.records, args.source_acceptance, args.output_dir, corpus=args.corpus,
        evidence=args.evidence, base_audit=args.base_audit, runtime_acceptance=args.runtime_acceptance,
        source=args.source, root=args.root)
    print(json.dumps({'status': result['status'], 'records': result['source_records'], 'output': str(args.output_dir)}))
