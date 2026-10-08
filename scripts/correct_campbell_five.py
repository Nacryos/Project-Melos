"""Apply the image-verified corrections to the five live Campbell Alcaeus passages.

Corrections: data/campbell_glp/alcaeus_five_corrections.json (old -> new printed line,
PDF page, reason). Each is applied only where the line still reads exactly `old`.

  python scripts/correct_campbell_five.py package
      runtime/campbell-assignment/campbell_assignment.jsonl (approved package, sha256 afe896...)
      -> data/campbell_glp/alcaeus_five_corrected.jsonl (same serialization) and a re-approval
         entry in docs/audits/campbell-assignment-approval.json
  python scripts/correct_campbell_five.py corpus --corpus /path/to/COPY/corpus.sqlite
      Rewrites the five rows (text, normalized, data, text_key, tokens, FTS, vocabulary) in a
      corpus copy. Idempotent: rows already corrected are left alone; rows that are neither the
      approved original nor the corrected text are refused.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORRECTIONS = ROOT / 'data/campbell_glp/alcaeus_five_corrections.json'
ORIGINAL = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
ORIGINAL_SHA256 = 'afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b'
CORRECTED = ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl'
APPROVAL = ROOT / 'docs/audits/campbell-assignment-approval.json'
REVISION_DATE = '2026-10-08'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_corrections() -> list:
    data = json.loads(CORRECTIONS.read_text(encoding='utf-8'))
    if data.get('base_package_sha256') != ORIGINAL_SHA256:
        raise ValueError('corrections are not based on the approved package')
    for c in data['corrections']:
        c['old'], c['new'] = unicodedata.normalize('NFC', c['old']), unicodedata.normalize('NFC', c['new'])
        c['reason'] = f"corrected to Campbell page image, PDF p.{c['pdf_page']} (printed p. {c['printed_page']}, line {c['printed_line']}): {c['what']}"
    return data['corrections']


def correct_record(record: dict, corrections: list) -> dict:
    """Return the corrected copy of one approved record (unchanged if no correction applies)."""
    mine = [c for c in corrections if c['id'] == record['id']]
    if not mine:
        return copy.deepcopy(record)
    row = copy.deepcopy(record)
    for c in mine:
        line = row['lines'][c['line_index']]
        if line['text'] != c['old']:
            raise ValueError(f"{c['id']} line {c['line_index']} does not read the expected old text")
        line['text'] = c['new']
        hits = 0
        for chunk in row['metadata'].get('source_excerpt_chunks', []):
            for chunk_line in chunk.get('lines', []):
                if chunk_line.get('text') == c['old']:
                    chunk_line['text'] = c['new']
                    hits += 1
        if hits != 1:
            raise ValueError(f"{c['id']}: source chunk line for {c['old']!r} found {hits} times")
    text = '\n'.join(line['text'] for line in row['lines'])
    expected = record['text']
    for c in mine:
        if expected.count(c['old']) != 1:
            raise ValueError('old line is not unique in the passage text')
        expected = expected.replace(c['old'], c['new'])
    if text != expected:
        raise ValueError(f"{record['id']}: rebuilt text differs from line-wise replacement")
    row['text'] = text
    row['metadata']['text_corrections'] = [
        {'line_index': c['line_index'], 'printed_line': c['printed_line'], 'pdf_page': c['pdf_page'],
         'printed_page': c['printed_page'], 'previous': c['old'], 'corrected': c['new'], 'reason': c['reason'],
         'date': REVISION_DATE, 'audit_path': 'docs/audits/campbell-glp-full.md'} for c in mine]
    row['metadata']['previous_text_sha256'] = sha(record['text'].encode('utf-8'))
    return row


def originals() -> list:
    raw = ORIGINAL.read_bytes()
    if sha(raw) != ORIGINAL_SHA256:
        raise ValueError('approved package hash mismatch')
    return [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]


def corrected_rows() -> list:
    return [json.loads(line) for line in CORRECTED.read_text(encoding='utf-8').splitlines() if line.strip()]


def build_package() -> dict:
    corrections = load_corrections()
    rows = [correct_record(r, corrections) for r in originals()]
    applied = sum(len(r['metadata'].get('text_corrections', [])) for r in rows)
    if applied != len(corrections):
        raise ValueError(f'applied {applied} of {len(corrections)} corrections')
    raw = ''.join(json.dumps(r, ensure_ascii=False) + '\r\n' for r in rows).encode('utf-8')
    CORRECTED.write_bytes(raw)
    package_sha = sha(raw)
    approval = json.loads(APPROVAL.read_text(encoding='utf-8'))
    previous_sha = approval['package']['sha256']
    if previous_sha not in (ORIGINAL_SHA256, package_sha):
        raise ValueError('approval file is bound to an unexpected package')
    approval['package'].update(path='data/campbell_glp/alcaeus_five_corrected.jsonl', sha256=package_sha)
    approval['files'][CORRECTED.name] = {'verdict': 'PASS', 'sha256': package_sha, 'records': 5}
    approval['files']['campbell_assignment.jsonl']['superseded_by'] = CORRECTED.name
    approval['revisions'] = [{
        'date': REVISION_DATE, 'verdict': 'PASS', 'previous_package_sha256': ORIGINAL_SHA256,
        'package_sha256': package_sha, 'package_path': 'data/campbell_glp/alcaeus_five_corrected.jsonl',
        'reason': 'Corrected to the Campbell page images after two independent re-transcriptions, image adjudication and coordinator confirmation (PDF pp. 89-90); see docs/audits/campbell-glp-full.md.',
        'unchanged': 'Line structure, labels, brackets elsewhere, metadata, raw source bundles and the 34a glyph-uncertainty note.',
        'corrections': [{'id': c['id'], 'printed_line': c['printed_line'], 'pdf_page': c['pdf_page'],
                         'previous': c['old'], 'corrected': c['new'], 'reason': c['reason']} for c in corrections]}]
    APPROVAL.write_bytes((json.dumps(approval, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return {'package': str(CORRECTED.relative_to(ROOT)), 'package_sha256': package_sha,
            'approval_sha256': sha(APPROVAL.read_bytes()), 'corrections_applied': applied,
            'text_sha256': {r['id']: sha(r['text'].encode('utf-8')) for r in rows}}


def correct_corpus(corpus: Path) -> dict:
    from backend.author_aliases import canonical  # noqa: F401  (same derived fields as the append routine)
    from backend.textutils import normalize, search_text, text_key, tokenize
    from scripts.build_corpus import SEARCHABLE_QUALITIES
    fixed = {r['id']: r for r in corrected_rows()}
    raw = ORIGINAL.read_bytes() if ORIGINAL.exists() else None
    old = {r['id']: r for r in (json.loads(l) for l in raw.decode('utf-8').splitlines() if l.strip())} if raw else {}
    report = {'already_corrected': [], 'corrected': [], 'missing': []}
    with closing(sqlite3.connect(corpus)) as con:
        con.execute('BEGIN')
        try:
            touched = set()
            for identifier, row in fixed.items():
                found = con.execute('SELECT data,work_id FROM passages WHERE id=?', (identifier,)).fetchone()
                if found is None:
                    report['missing'].append(identifier)
                    continue
                stored, work_id = json.loads(found[0]), found[1]
                stored.pop('work_id', None)
                if stored == row:
                    report['already_corrected'].append(identifier)
                    continue
                previous = row['metadata']['previous_text_sha256']
                if sha(stored['text'].encode('utf-8')) != previous or (old and stored != old.get(identifier)):
                    raise ValueError('stored row is neither the approved original nor the corrected text: ' + identifier)
                data = dict(row, work_id=work_id)
                indexed = search_text(row['text'])
                con.execute('UPDATE passages SET text=?, normalized=?, data=?, text_key=? WHERE id=?',
                            (row['text'], normalize(indexed), json.dumps(data, ensure_ascii=False),
                             text_key(row['language'], row['kind'], row['text']), identifier))
                fts = con.execute('SELECT citation,author,work FROM passage_fts WHERE id=?', (identifier,)).fetchone()
                con.execute('DELETE FROM passage_fts WHERE id=?', (identifier,))
                con.execute('INSERT INTO passage_fts (id,normalized,citation,author,work) VALUES (?,?,?,?,?)',
                            (identifier, normalize(indexed), *fts))
                touched |= {r[0] for r in con.execute('SELECT normalized FROM tokens WHERE passage_id=?', (identifier,))}
                con.execute('DELETE FROM tokens WHERE passage_id=?', (identifier,))
                if row['quality'] in SEARCHABLE_QUALITIES and row['kind'] in ('text', 'translation'):
                    counts = Counter(tokenize(indexed))
                    con.executemany('INSERT INTO tokens (passage_id,form,normalized,count) VALUES (?,?,?,?)',
                                    [(identifier, form, normalize(form), n) for form, n in counts.items()])
                    touched |= {normalize(form) for form in counts}
                report['corrected'].append(identifier)
            for key in touched:
                form, count = con.execute('SELECT min(form),sum(count) FROM tokens WHERE normalized=?', (key,)).fetchone()
                if count:
                    con.execute('INSERT OR REPLACE INTO vocabulary (normalized,form,count) VALUES (?,?,?)', (key, form, count))
                else:
                    con.execute('DELETE FROM vocabulary WHERE normalized=?', (key,))
            con.commit()
        except BaseException:
            con.rollback()
            raise
        if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('quick_check failed after correction')
    if report['missing']:
        raise ValueError('approved passages missing from corpus: ' + ', '.join(report['missing']))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('package')
    corpus = sub.add_parser('corpus')
    corpus.add_argument('--corpus', type=Path, required=True)
    args = parser.parse_args()
    result = build_package() if args.command == 'package' else correct_corpus(args.corpus)
    print(json.dumps(result, ensure_ascii=False, indent=1))
