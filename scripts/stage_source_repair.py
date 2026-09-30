"""Stage a bounded, audited source reparse without modifying active artifacts.

Inputs are accepted old JSONL plus a separately produced parser output, never
model-authored readings. Outputs remain PENDING independent source/claim audit.
The cloned corpus and evidence must be deployed together with freshly built
embedding metadata/vectors; rebinding old vectors after changed text is unsafe.
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
import sqlite3
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize, search_text, tokenize
from backend.morphology import normalize as form_normalize
from scripts import extract_p2_notes as notes
from scripts.build_evidence import _validate, _listed_forms, _has_greek_letter, _json


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def records(path):
    rows, lines = {}, {}
    for raw in Path(path).read_bytes().splitlines(keepends=True):
        if not raw.strip():
            continue
        row = json.loads(raw)
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in rows:
            raise ValueError('Missing/duplicate record ID in ' + str(path))
        rows[identifier], lines[identifier] = row, raw
    return rows, lines


def accepted(path, acceptance):
    entry = json.loads(Path(acceptance).read_text(encoding='utf-8'))['files'][Path(path).name]
    rows, lines = records(path)
    if entry.get('verdict') != 'PASS' or entry.get('sha256') != sha(path) or entry.get('records') != len(rows):
        raise ValueError('Old input does not match independent acceptance: ' + str(path))
    return rows, lines


def diff(old, new):
    return {'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
            'changed': sorted(key for key in old.keys() & new.keys() if old[key] != new[key])}


def changed_ids(delta):
    return set().union(*delta.values())


def detailed_diff(old, new, old_lines, new_lines):
    result = []
    for identifier in sorted(changed_ids(diff(old, new))):
        before, after = old.get(identifier), new.get(identifier)
        result.append({'id': identifier, 'operation': 'added' if before is None else 'removed' if after is None else 'changed',
                       'changed_fields': sorted(key for key in (before or {}).keys() | (after or {}).keys()
                                                if (before or {}).get(key) != (after or {}).get(key)),
                       'before_record_sha256': hashlib.sha256(old_lines[identifier].rstrip(b'\r\n')).hexdigest() if before else None,
                       'after_record_sha256': hashlib.sha256(new_lines[identifier].rstrip(b'\r\n')).hexdigest() if after else None,
                       'before_text_sha256': hashlib.sha256(before['text'].encode()).hexdigest() if before and 'text' in before else None,
                       'after_text_sha256': hashlib.sha256(after['text'].encode()).hexdigest() if after and 'text' in after else None})
    return result


def write_records(path, order, rows, old_rows, old_lines):
    """Retain every unchanged record's original serialization, not just values."""
    with Path(path).open('xb') as handle:
        for identifier in order:
            if identifier in old_rows and old_rows[identifier] == rows[identifier]:
                line = old_lines[identifier]
            else:
                line = (json.dumps(rows[identifier], ensure_ascii=False, sort_keys=True) + '\n').encode()
            handle.write(line if line.endswith(b'\n') else line + b'\n')


def validate_raw(root, rows):
    validated = {}
    for row in rows.values():
        for field in ('source', 'source_url', 'raw_path', 'raw_sha256', 'text'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'{row["id"]}: missing {field}')
        artifact = (Path(root) / row['raw_path']).resolve()
        if not artifact.is_relative_to(Path(root).resolve()) or not artifact.is_file():
            raise ValueError('Raw artifact missing or outside root')
        if artifact in validated and validated[artifact] != row['raw_sha256']:
            raise ValueError('Conflicting raw hashes for one artifact')
        if artifact not in validated and sha(artifact) != row['raw_sha256']:
            raise ValueError('Raw artifact hash mismatch: ' + str(artifact))
        validated[artifact] = row['raw_sha256']
        if row.get('parent_id') and row['parent_id'] not in rows:
            raise ValueError('Dangling staged parent: ' + row['id'])
    return {str(path): digest for path, digest in validated.items()}


def patch_corpus(source, output, old, new, delta):
    touched = changed_ids(delta)
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as original:
        original.execute('BEGIN')
        with closing(sqlite3.connect(output)) as con:
            original.backup(con)
            # This tool consumes a complete accepted source collection, not a
            # partial page patch. Undeclared stale IDs must not survive silently.
            for source_name in {row['source'] for row in old.values()}:
                expected = {key for key, row in old.items() if row['source'] == source_name}
                actual = {row[0] for row in original.execute('SELECT id FROM passages WHERE source=?', (source_name,))}
                if actual != expected:
                    raise ValueError('Active source membership differs from accepted input: ' + source_name)
            for identifier, old_row in old.items():
                existing = original.execute('SELECT data FROM passages WHERE id=?', (identifier,)).fetchone()
                if not existing or any(json.loads(existing[0]).get(key) != value for key, value in old_row.items()):
                    raise ValueError('Active source record differs from accepted old input: ' + identifier)
            # Source-order changes can occur without changing a row's values.
            # Recompute all works represented by the complete reparsed input.
            old_works = {row[0] for identifier in old for row in
                         original.execute('SELECT work_id FROM passages WHERE id=?', (identifier,))}
            token_keys = {row[0] for identifier in touched for row in
                          original.execute('SELECT normalized FROM tokens WHERE passage_id=?', (identifier,))}
            fts_ids = dict(con.execute('SELECT id,rowid FROM passage_fts'))
            new_works = set()
            for identifier in sorted(touched):
                if identifier in delta['added'] and con.execute('SELECT 1 FROM passages WHERE id=?', (identifier,)).fetchone():
                    raise ValueError('New ID collides with unrelated corpus record: ' + identifier)
                con.execute('DELETE FROM tokens WHERE passage_id=?', (identifier,))
                if identifier in fts_ids:
                    con.execute('DELETE FROM passage_fts WHERE rowid=?', (fts_ids[identifier],))
                if identifier not in new:
                    con.execute('DELETE FROM passages WHERE id=?', (identifier,))
                    continue
                row = copy.deepcopy(new[identifier])
                for field in ('author', 'work', 'edition', 'citation', 'language', 'license'):
                    row.setdefault(field, 'unknown')
                row.setdefault('kind', 'reference')
                row.setdefault('quality', 'needs_review')
                identity = [row.get(field) for field in ('source', 'author', 'work', 'edition', 'language')]
                work_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
                row['work_id'] = work_id
                new_works.add(work_id)
                indexed = search_text(row['text']) if row['language'] == 'grc' else row['text']
                folded = normalize(indexed)
                values = (identifier, work_id, row['source'], row['author'], row['work'], row['edition'],
                          row['citation'], row['language'], row['kind'], row['quality'], row['text'], folded,
                          json.dumps(row, ensure_ascii=False), 0)
                con.execute('INSERT OR REPLACE INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
                con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)',
                            (identifier, folded, normalize(row['citation']), normalize(row['author']), normalize(row['work'])))
                if row['quality'] not in ('mixed_content', 'machine_ocr', 'needs_review') and row['kind'] in ('text', 'translation'):
                    counts = Counter(tokenize(indexed))
                    con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                                    [(identifier, form, normalize(form), count) for form, count in counts.items()])
                    token_keys.update(normalize(form) for form in counts)
            order = {identifier: index for index, identifier in enumerate(new)}
            sequence_changes = []
            for work_id in old_works | new_works:
                rows = con.execute('SELECT id,author,work,edition,source,language FROM passages WHERE work_id=?', (work_id,)).fetchall()
                if any(row[0] not in order for row in rows):
                    raise ValueError('Affected work includes records outside reparsed input; explicit ordering required')
                con.execute('DELETE FROM works WHERE id=?', (work_id,))
                if rows:
                    rows.sort(key=lambda row: order[row[0]])
                    con.execute('INSERT INTO works VALUES (?,?,?,?,?,?,?)', (work_id, *rows[0][1:], len(rows)))
                    for index, row in enumerate(rows):
                        before = original.execute('SELECT sequence FROM passages WHERE id=?', (row[0],)).fetchone()
                        if before is None or before[0] != index:
                            sequence_changes.append(row[0])
                    con.executemany('UPDATE passages SET sequence=? WHERE id=?', [(index, row[0]) for index, row in enumerate(rows)])
            for key in token_keys:
                count, form = con.execute('SELECT sum(count),min(form) FROM tokens WHERE normalized=?', (key,)).fetchone()
                if count:
                    con.execute('INSERT OR REPLACE INTO vocabulary VALUES (?,?,?)', (key, form, count))
                else:
                    con.execute('DELETE FROM vocabulary WHERE normalized=?', (key,))
            manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
            source_counts = dict(con.execute('SELECT source,count(*) FROM passages GROUP BY source'))
            authors = [row[0] for row in con.execute('SELECT DISTINCT author FROM passages')]
            manifest.update(passages=con.execute('SELECT count(*) FROM passages').fetchone()[0],
                            works=con.execute('SELECT count(*) FROM works').fetchone()[0], sources=source_counts,
                            vocabulary=con.execute('SELECT count(*) FROM vocabulary').fetchone()[0],
                            source_repair={'status': 'PENDING_INDEPENDENT_AUDIT', 'diff': delta})
            manifest['statistics'] = {'sources': [{'source': key, 'count': value} for key, value in source_counts.items()],
                'languages': [{'language': key, 'count': count} for key, count in con.execute('SELECT language,count(*) FROM passages GROUP BY language ORDER BY count(*) DESC')],
                'quality': [{'quality': key, 'count': count} for key, count in con.execute('SELECT quality,count(*) FROM passages GROUP BY quality ORDER BY quality')],
                'authors': len({unicodedata.normalize('NFC', value).casefold() for value in authors}), 'author_labels': len(authors)}
            con.execute("UPDATE metadata SET value=? WHERE key='manifest'", (json.dumps(manifest),))
            con.commit()
            # Unchanged source-bearing columns must retain exact stored bytes.
            con.execute('ATTACH DATABASE ? AS old', (str(Path(source).resolve()),))
            con.execute('CREATE TEMP TABLE touched(id TEXT PRIMARY KEY)')
            con.executemany('INSERT INTO touched VALUES (?)', [(identifier,) for identifier in touched])
            columns = 'id,work_id,source,author,work,edition,citation,language,kind,quality,text,normalized,data'
            for left, right in [('main', 'old'), ('old', 'main')]:
                if con.execute(f'SELECT {columns} FROM {left}.passages WHERE id NOT IN touched EXCEPT SELECT {columns} FROM {right}.passages WHERE id NOT IN touched LIMIT 1').fetchone():
                    raise RuntimeError('Unrelated source records changed')
            if con.execute('PRAGMA main.quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Corpus quick_check failed')
            return {'manifest': manifest, 'affected_work_ids': sorted(old_works | new_works),
                    'sequence_changed_ids': sorted(sequence_changes),
                    'vocabulary_keys_recomputed': len(token_keys), 'unrelated_source_records_unchanged': True}


def regenerate_notes(old_records, new_records, new_lines, old_claims, old_claim_lines, touched, output):
    affected_notes = {identifier for rows in (old_records, new_records) for identifier, record in rows.items()
                      if identifier in touched or record.get('parent_id') in touched}
    retained = {identifier: claim for identifier, claim in old_claims.items()
                if not any(e.get('record_id') in affected_notes for e in claim['evidence'])
                and claim['subject'].get('passage_id') not in touched}
    hashes = {identifier: hashlib.sha256(line.rstrip(b'\r\n')).hexdigest() for identifier, line in new_lines.items()}
    regenerated = {}
    for identifier in new_records:
        if identifier not in affected_notes:
            continue
        record = new_records[identifier]
        parent = new_records.get(record.get('parent_id'))
        subtype = record.get('metadata', {}).get('subtype')
        if identifier.startswith('digital-sappho:') and subtype == 'vocabulary':
            claims = notes.digital_vocabulary(record, parent, hashes)
        elif identifier.startswith('dcc-sappho:') and subtype == 'notes':
            claims = notes.dcc_notes(record, parent, hashes)
        else:
            claims = []
        for claim in claims:
            if claim['id'] in retained or claim['id'] in regenerated:
                raise ValueError('Regenerated claim ID collision')
            if claim['id'] in old_claims:
                # A parser boundary repair is not authority to promote a
                # previously reviewed/uncertain assertion to source_claim.
                claim['status'] = old_claims[claim['id']]['status']
            _validate(claim, output.name, 0)
            subject = claim['subject']
            if subject.get('passage_id'):
                parent_text = new_records[subject['passage_id']]['text']
                if parent_text[subject['start']:subject['end']] != subject['form']:
                    raise ValueError('Regenerated claim offset mismatch')
            regenerated[claim['id']] = claim
    revised = retained | regenerated
    order = [key for key in old_claims if key in revised] + [key for key in regenerated if key not in old_claims]
    write_records(output, order, revised, old_claims, old_claim_lines)
    return revised, diff(old_claims, revised), sorted(affected_notes)


def claim_values(row, filename):
    subject, form = row['subject'], row['subject'].get('form')
    return (row['id'], subject['type'], subject.get('id'), subject.get('passage_id'), form,
            form_normalize(form) if form else None, subject.get('start'), subject.get('end'),
            row['predicate'], _json(subject), _json(row['object']), _json(row['evidence']), row['assertion_type'],
            row['status'], row['method'], row['source_family'], _json(row.get('metadata', {})), filename)


def patch_evidence(source, output, old_claims, new_claims, delta, claim_path, affected_records):
    touched = changed_ids(delta)
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as original:
        original.execute('BEGIN')
        existing = original.execute('SELECT sha256,records FROM input_files WHERE name=?', (claim_path.name,)).fetchone()
        if existing != (sha(claim_path), len(old_claims)):
            raise ValueError('Active evidence does not match accepted old claims')
        active_rows = {row[0]: row for row in original.execute('SELECT * FROM claims WHERE source_file=?', (claim_path.name,))}
        if active_rows.keys() != old_claims.keys():
            raise ValueError('Active note-claim membership differs from accepted input')
        for identifier, row in old_claims.items():
            expected = claim_values(row, claim_path.name)
            actual = active_rows[identifier]
            for index, value in enumerate(expected):
                if index == 5:  # Derived normalized key may have been repaired.
                    continue
                left, right = (json.loads(actual[index]), json.loads(value)) if index in (9, 10, 11, 16) else (actual[index], value)
                if left != right:
                    raise ValueError('Active note claim differs from accepted source: ' + identifier)
        for identifier, passage, subject_id, raw in original.execute('SELECT id,passage_id,subject_id,evidence_json FROM claims WHERE source_file!=?', (claim_path.name,)):
            if passage in affected_records or subject_id in affected_records or any(item.get('record_id') in affected_records for item in json.loads(raw)):
                raise ValueError('Other claim family references changed records; explicit regeneration needed: ' + identifier)
        with closing(sqlite3.connect(output)) as con:
            original.backup(con)
            for identifier in touched:
                con.execute('DELETE FROM form_edges WHERE claim_id=?', (identifier,))
                con.execute('DELETE FROM claims WHERE id=?', (identifier,))
                if identifier not in new_claims:
                    continue
                row = new_claims[identifier]
                _validate(row, claim_path.name, 0)
                con.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            claim_values(row, claim_path.name))
                for ordinal, form, value in _listed_forms(row):
                    if _has_greek_letter(form) and form_normalize(form):
                        con.execute('INSERT INTO form_edges VALUES (?,?,?,?,?)', (identifier, ordinal, form, form_normalize(form), _json(value)))
            revised_path = Path(output).parent / 'p2_notes.jsonl'
            con.execute('UPDATE input_files SET sha256=?,records=? WHERE name=?', (sha(revised_path), len(new_claims), claim_path.name))
            con.commit()
            sentinel = object()
            for table, id_field in [('claims', 'id'), ('form_edges', 'claim_id')]:
                before = (row for row in original.execute(f'SELECT * FROM {table} ORDER BY rowid') if row[0] not in touched)
                after = (row for row in con.execute(f'SELECT * FROM {table} ORDER BY rowid') if row[0] not in touched)
                if any(a != b for a, b in itertools.zip_longest(before, after, fillvalue=sentinel)):
                    raise RuntimeError('Unrelated evidence rows changed')
            if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Evidence quick_check failed')
            return {'claims': con.execute('SELECT count(*) FROM claims').fetchone()[0],
                    'changed_claim_ids': sorted(touched), 'unrelated_evidence_rows_unchanged': True}


def stage(new_records_path, output_dir, root=ROOT, corpus=None, evidence=None,
          allowed_prefixes=('digital-sappho:',)):
    root, output = Path(root).resolve(), Path(output_dir).resolve()
    if not output.is_relative_to(root / 'data/staging') or output.exists():
        raise ValueError('Output must be a new directory below data/staging')
    old_path, claims_path = root / 'data/processed/sappho.jsonl', root / 'data/claims/p2_notes.jsonl'
    acceptance, claim_acceptance = root / 'data/reports/audit-acceptance.json', root / 'data/reports/p2-claim-acceptance.json'
    active = [old_path, claims_path, acceptance, claim_acceptance,
              Path(corpus or root / 'data/corpus.sqlite'), Path(evidence or root / 'data/evidence.sqlite')]
    before = {str(path): sha(path) for path in [*active, Path(new_records_path)]}
    old, old_lines = accepted(old_path, acceptance)
    old_claims, old_claim_lines = accepted(claims_path, claim_acceptance)
    new, _ = records(new_records_path)
    delta = diff(old, new)
    if not changed_ids(delta):
        raise ValueError('No source changes to stage')
    if not allowed_prefixes or any(not identifier.startswith(tuple(allowed_prefixes)) for identifier in changed_ids(delta)):
        raise ValueError('Source diff exceeds the explicitly allowed ID prefixes')
    if {row['source'] for row in new.values()} - {row['source'] for row in old.values()}:
        raise ValueError('A source reparse may not introduce a different source collection')
    raw_inputs = validate_raw(root, new)
    before.update(raw_inputs)
    output.mkdir(parents=True, exist_ok=False)
    # Any failure leaves only a visibly incomplete staging directory. No
    # deployment manifest is emitted until all mechanical gates finish.
    staged_records = output / 'sappho.jsonl'
    write_records(staged_records, list(new), new, old, old_lines)
    staged_rows, staged_lines = records(staged_records)
    new_claims, claim_delta, note_ids = regenerate_notes(old, new, staged_lines, old_claims, old_claim_lines,
                                                       changed_ids(delta), output / 'p2_notes.jsonl')
    corpus_report = patch_corpus(active[-2], output / 'corpus.sqlite', old, new, delta)
    evidence_report = patch_evidence(active[-1], output / 'evidence.sqlite', old_claims, new_claims,
                                     claim_delta, claims_path, changed_ids(delta))
    if any(sha(Path(path)) != digest for path, digest in before.items()):
        raise RuntimeError('Active input changed during staging; do not use snapshot')
    # Candidate manifests are not acceptance: changed files explicitly lose
    # PASS until an independent reviewer signs off on these exact hashes.
    for source_manifest, filename, destination, count in (
            (acceptance, 'sappho.jsonl', 'audit-acceptance.candidate.json', len(new)),
            (claim_acceptance, 'p2_notes.jsonl', 'p2-claim-acceptance.candidate.json', len(new_claims))):
        candidate = json.loads(source_manifest.read_text(encoding='utf-8'))
        candidate['files'][filename] = {'verdict': 'PENDING', 'sha256': sha(output / filename), 'records': count,
                                         'reason': 'Staged parser repair awaiting independent audit'}
        (output / destination).write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding='utf-8')
    _, new_claim_lines = records(output / 'p2_notes.jsonl')
    report = {'status': 'PENDING_INDEPENDENT_AUDIT', 'source_diff': delta, 'claim_diff': claim_delta,
              'allowed_id_prefixes': list(allowed_prefixes),
              'source_record_changes': detailed_diff(old, new, old_lines, staged_lines),
              'claim_record_changes': detailed_diff(old_claims, new_claims, old_claim_lines, new_claim_lines),
              'regenerated_note_record_ids': note_ids, 'raw_artifacts_verified': len(raw_inputs),
              'corpus': corpus_report, 'evidence': evidence_report, 'active_inputs': before,
              'artifacts': {path.name: {'sha256': sha(path), 'bytes': path.stat().st_size}
                            for path in output.iterdir() if path.is_file()},
              'embeddings': {'status': 'REBUILD_REQUIRED', 'reason': 'Changed text/IDs/parent metadata; do not rebind old vectors'},
              'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    (output / 'repair-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new-records', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--allowed-id-prefix', action='append', default=None)
    args = parser.parse_args()
    print(json.dumps(stage(args.new_records, args.output_dir, args.root, args.corpus, args.evidence,
                           args.allowed_id_prefix or ('digital-sappho:',)), ensure_ascii=False))
