#!/usr/bin/env python3
"""Validate exhaustive review proposals against frozen packets and live source.

Run: python scripts/build_visual_annotations.py
The source DB is always opened read-only. Missing reviews abort; they are never
silently converted to abstentions. Raw proposals remain separate from output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.visual_themes import MODIFIERS, POETS, THEMES, source_identity, text_sha256


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same_context(left, right):
    if left['id'] == right['id']:
        return True
    # Only explicit line/section citations within the same edition's work can
    # establish shared ode context. Anthology-wide inference is forbidden.
    if any(left.get(key) != right.get(key) for key in ('source', 'author', 'work_id')):
        return False
    a = re.match(r'^(\d+)\.', left.get('citation') or '')
    b = re.match(r'^(\d+)\.', right.get('citation') or '')
    return bool(a and b and a.group(1) == b.group(1))


def validate_decision(decision, sources):
    record_id = decision.get('id')
    if record_id not in sources:
        raise ValueError(f'Unknown Greek record: {record_id}')
    source = sources[record_id]
    status = decision.get('status')
    reason = decision.get('reason', '')
    labels = decision.get('labels', [])
    if status not in ('label', 'abstain') or not isinstance(reason, str) or not reason.strip():
        raise ValueError(f'Missing decision/reason: {record_id}')
    if (status == 'label') != bool(labels):
        raise ValueError(f'Inconsistent status/labels: {record_id}')
    validated, seen = [], set()
    for label in labels:
        theme = label.get('theme')
        if theme not in THEMES or theme in seen:
            raise ValueError(f'Invalid/duplicate theme: {record_id}: {theme}')
        seen.add(theme)
        if label.get('kind') not in ('scene', 'simile') or label.get('strength') != 'strong':
            raise ValueError(f'Unsupported strength/kind: {record_id}')
        modifiers = label.get('modifiers', [])
        if not isinstance(modifiers, list) or any(x not in MODIFIERS for x in modifiers) or len(set(modifiers)) != len(modifiers):
            raise ValueError(f'Invalid modifiers: {record_id}')
        spans = []
        for evidence in label.get('evidence', []):
            other = sources.get(evidence.get('id'))
            quote = evidence.get('quote')
            if not other or not same_context(source, other):
                raise ValueError(f'Unrelated evidence context: {record_id}: {evidence.get("id")}')
            if not isinstance(quote, str) or not quote.strip() or quote not in other['text']:
                raise ValueError(f'Nonliteral evidence: {record_id}: {quote!r}')
            start = other['text'].index(quote)
            spans.append({'id': other['id'], 'quote': quote, 'start': start,
                          'end': start + len(quote), 'source_text_sha256': text_sha256(other['text']),
                          'source_identity': source_identity(other)})
        if not any(span['id'] == record_id for span in spans):
            raise ValueError(f'Label lacks own-record evidence: {record_id}')
        validated.append({'theme': theme, 'kind': label['kind'], 'strength': 'strong',
                          'modifiers': modifiers, 'evidence': spans})
    return {'id': record_id, 'author': source['author'], 'work_id': source['work_id'],
            'citation': source['citation'], 'source_text_sha256': text_sha256(source['text']),
            'source_identity': source_identity(source),
            'status': status, 'reason': reason, 'labels': validated}


def build(packet_dir, raw_dir, database):
    packets = sorted(Path(packet_dir).glob('packet-*.json'))
    if not packets:
        raise ValueError('No frozen packets')
    sources, packet_ids, packet_translations = {}, {}, {}
    for path in packets:
        packet_rows = read_json(path)
        greek = [row for row in packet_rows if row['kind'] == 'text' and row['language'] == 'grc']
        packet_translations.update({row['id']: row for row in packet_rows if row['kind'] == 'translation'})
        packet_ids[path.stem] = {row['id'] for row in greek}
        for row in greek:
            if row['id'] in sources:
                raise ValueError(f'Duplicate packet record: {row["id"]}')
            if row['author'] not in POETS or row['quality'] != 'source_text':
                raise ValueError('Packet contains out-of-scope source')
            sources[row['id']] = row
    decisions, raw_files = {}, []
    for packet, expected in packet_ids.items():
        if not expected:
            continue
        path = Path(raw_dir) / f'{packet}.proposals.json'
        raw = read_json(path)
        if raw.get('packet') != packet or raw.get('reviewed_all_records') is not True or not raw.get('reviewer'):
            raise ValueError(f'Incomplete/invalid review declaration: {packet}')
        ids = [row['id'] for row in raw['decisions']]
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ValueError(f'Review coverage differs: {packet}; missing={len(expected-set(ids))}; extra={len(set(ids)-expected)}')
        for decision in raw['decisions']:
            decisions[decision['id']] = validate_decision(decision, sources)
            decisions[decision['id']]['reviewer'] = raw['reviewer']
            decisions[decision['id']]['raw_proposal_file'] = path.name
        raw_files.append({'path': path.name, 'sha256': file_hash(path)})
    connection = sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ','.join('?' for _ in POETS)
        live = {row['id']: dict(row) for row in connection.execute(
            f"SELECT id,text,source,author_canonical,work_id,citation,language,kind,quality,data FROM passages "
            f"WHERE author_canonical IN ({placeholders}) AND kind='text' AND language='grc' AND quality='source_text'", POETS)}
        missing = set(live) - set(sources)
        # Frozen tally may omit exact duplicate copies. Report them explicitly;
        # no unevaluated source row is silently declared reviewed.
        if missing or set(sources) - set(live):
            raise ValueError(f'Frozen/live Greek scope differs: missing_from_packets={len(missing)}, removed={len(set(sources)-set(live))}')
        for record_id, source in sources.items():
            actual = live[record_id]
            if (actual['text'] != source['text'] or actual['work_id'] != source['work_id'] or
                    actual['citation'] != source['citation'] or actual['source'] != source['source'] or
                    actual['author_canonical'] != source['author']):
                raise ValueError(f'Frozen source changed: {record_id}')
        translations = []
        for row in connection.execute("SELECT id,text,data FROM passages WHERE kind='translation' AND quality='source_text'"):
            payload = json.loads(row['data'])
            parent_id = payload.get('parent_id')
            if parent_id not in decisions:
                continue
            parent = decisions[parent_id]
            translations.append({'id': row['id'], 'source_text_sha256': text_sha256(row['text']),
                'source_identity': source_identity(payload),
                'parent_id': parent_id, 'parent_text_sha256': parent['source_text_sha256'],
                'parent_source_identity': parent['source_identity'],
                'author': parent['author'], 'status': parent['status'], 'labels': parent['labels'],
                'reason': 'Inherited only through the recorded Greek parent; translation not independently classified.'})
        mapped_ids = {row['id'] for row in translations}
        translation_exclusions = []
        for record_id in sorted(set(packet_translations) - mapped_ids):
            parent_id = packet_translations[record_id].get('parent_id')
            parent = connection.execute('SELECT quality FROM passages WHERE id=?', (parent_id,)).fetchone()
            translation_exclusions.append({'id': record_id, 'parent_id': parent_id,
                'parent_quality': parent['quality'] if parent else None,
                'reason': 'Parent is outside the reviewed core Greek source_text scope.'})
    finally:
        connection.close()
    rows = sorted(decisions.values(), key=lambda row: row['id'])
    counts = Counter(label['theme'] for row in rows for label in row['labels'])
    author_counts = {poet: {'reviewed': sum(row['author'] == poet for row in rows),
        'labeled': sum(row['author'] == poet and row['status'] == 'label' for row in rows)} for poet in POETS}
    manifest = {'available': True, 'review_complete': True, 'scope': 'core_ten_greek_source_text_records',
        'reviewed_records': len(rows), 'labeled_records': sum(row['status'] == 'label' for row in rows),
        'abstained_records': sum(row['status'] == 'abstain' for row in rows),
        'mapped_translation_records': len(translations),
        'packet_translation_records': len(packet_translations),
        'unmapped_packet_translation_records': len(translation_exclusions),
        'translation_exclusions': translation_exclusions,
        'themes': dict(counts), 'authors': author_counts,
        'interpretation': 'Model aesthetic proposals with literal evidence validation; not verified literary facts.',
        'limitations': ['Record counts are not poem counts.', 'OCR and non-core authors are excluded.',
            'Abstention means insufficient fit under this rubric, not absence of all nature imagery.',
            'Translations inherit only from actual parent_id; distinct editions are not inferred or merged.',
            'Literal validators cannot establish semantic correctness of model judgments.'],
        'packet_files': [{'path': p.name, 'sha256': file_hash(p)} for p in packets], 'proposal_files': raw_files,
        'retained_raw_artifacts': [{'path': p.name, 'sha256': file_hash(p)}
            for p in sorted(Path(raw_dir).iterdir()) if p.is_file() and p.suffix in ('.json', '.py')]}
    return {'schema_version': 1, 'manifest': manifest, 'records': rows + sorted(translations, key=lambda row: row['id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packets', type=Path, default=ROOT / '.benchmarks/visual-themes/packets')
    parser.add_argument('--raw', type=Path, default=ROOT / 'data/annotations/visual-themes/raw')
    parser.add_argument('--database', type=Path, default=ROOT / 'data/corpus.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/annotations/visual-themes/validated.json')
    args = parser.parse_args()
    result = build(args.packets, args.raw, args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staged = args.output.with_suffix(args.output.suffix + '.tmp')
    staged.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    staged.replace(args.output)
    print(json.dumps(result['manifest'], indent=2))


if __name__ == '__main__':
    main()
