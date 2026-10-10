"""Project the owner-commissioned literal translations onto the Campbell GLP records.

Input: data/campbell_glp/literal_translations/<file>.json (one English line per printed Greek line,
produced by a language model for the site owner; an unpublished machine translation, never a
published source). Each poem is bound to the exact Campbell record it was made from: record id,
edition fragment, source-PDF hash, and the SHA-256 of the stored Greek text, and every Greek line in
the input must equal the stored line, so a later change to the Greek text makes the projection fail
closed instead of showing English for a text it was not made for.

Outputs:
  backend/literal_translations_data.json          reader sidecar (served by /api/passage as
                                                  `literal_translation`; display policy fallback_only)
  data/campbell_glp/literal_translations_rows.jsonl corpus rows (kind translation, quality
                                                  machine_translation, parent_id = the poem) for the
                                                  English BM25 bridge and the dense indexes

usage: python scripts/build_literal_translations.py [--source <json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/campbell_glp/literal_translations/claude-fable-5.1-2026-10-10.json'
GREEK = (ROOT / 'data/campbell_glp/campbell_glp.jsonl', ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl')
SIDECAR = ROOT / 'backend/literal_translations_data.json'
ROWS = ROOT / 'data/campbell_glp/literal_translations_rows.jsonl'
SOURCE_PDF_SHA256 = '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f'
CORPUS_SOURCE = 'literal_translation_claude'
QUALITY = 'machine_translation'
SOURCE_URL = 'https://github.com/Nacryos/Project-Melos/blob/HEAD/data/campbell_glp/literal_translations/'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def greek_records() -> dict:
    records = {}
    for path in GREEK:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                records[row['id']] = row
    return records


def build(source_path: Path) -> tuple[dict, list[dict]]:
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if source.get('schema') != 'literal_interlinear_translations_source' or source.get('model_eligible') is not False:
        raise ValueError('unexpected source schema')
    raw_sha = sha(source_path.read_bytes())
    raw_path = source_path.relative_to(ROOT).as_posix()
    greek = greek_records()
    records, rows = [], []
    for poem in source['poems']:
        record_id = poem['campbell_record_id']
        passage = greek[record_id]
        if passage.get('metadata', {}).get('source_pdf_sha256') != SOURCE_PDF_SHA256 or passage.get('language') != 'grc':
            raise ValueError('not a Campbell GLP record: ' + record_id)
        stored = [line['text'] for line in passage['lines']]
        given = [line['greek'] for line in poem['lines']]
        if len(stored) != len(given):
            raise ValueError(f'{record_id}: {len(given)} English lines for {len(stored)} Greek lines')
        for i, (a, b) in enumerate(zip(stored, given)):
            if a.strip() != b.strip():
                raise ValueError(f'{record_id} line {i}: Greek differs from the stored text')
        lines = [{'index': i, 'label': passage['lines'][i].get('label', ''), 'greek': stored[i],
                  'english': line['english']} for i, line in enumerate(poem['lines'])]
        english = '\n'.join(line['english'] for line in lines)
        identity = {'edition_fragment': passage['metadata']['edition_fragment'], 'source_pdf_sha256': SOURCE_PDF_SHA256,
                    'raw_sha256': passage['raw_sha256'], 'text_sha256': sha(passage['text'].encode('utf-8')),
                    'line_count': len(stored), 'author': passage['author']}
        records.append({'campbell_record_id': record_id, 'campbell_identity': identity, 'lines': lines,
                        'text': english, 'note': poem.get('note', ''), 'love_theme': bool(poem.get('love_theme'))})
        rows.append({
            'id': record_id + ':literal', 'source': CORPUS_SOURCE, 'source_url': SOURCE_URL + source_path.name,
            'raw_path': raw_path, 'raw_sha256': raw_sha, 'author': passage['author'], 'work': passage['work'],
            'edition': 'Literal line-by-line English rendering (Claude Fable 5.1 for the site owner, 2026-10-10; '
                       'unpublished machine translation) of ' + passage['edition'],
            'citation': passage['citation'] + ' (literal translation)', 'language': 'eng', 'kind': 'translation',
            'quality': QUALITY, 'license': 'owner-commissioned machine translation; not a published source',
            'text': english, 'parent_id': record_id,
            'lines': [{'label': line['label'], 'text': line['english']} for line in lines],
            'metadata': {'translation_of': record_id, 'translator': source['translator'],
                         'produced_at': source['produced_at'], 'method': source['method'],
                         'display_policy': 'fallback_only', 'model_eligible': False, 'line_aligned': True,
                         'campbell_text_sha256': identity['text_sha256'],
                         'source_pdf_sha256': SOURCE_PDF_SHA256, 'love_theme': bool(poem.get('love_theme'))}})
    sidecar = {'schema': 'literal_interlinear_translations', 'schema_version': 1,
               'source_file': raw_path, 'source_sha256': raw_sha, 'source_pdf_sha256': SOURCE_PDF_SHA256,
               'translator': source['translator'], 'produced_at': source['produced_at'], 'status': source['status'],
               'method': source['method'], 'display_policy': 'fallback_only', 'model_eligible': False,
               'selection_aligned': False, 'exact_edition_alignment': False, 'line_aligned': True,
               'record_count': len(records), 'line_count': sum(len(r['lines']) for r in records), 'records': records}
    return sidecar, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args = parser.parse_args()
    sidecar, rows = build(args.source.resolve())
    SIDECAR.write_bytes((json.dumps(sidecar, ensure_ascii=False, indent=1) + '\n').encode('utf-8'))
    ROWS.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    print(json.dumps({'records': sidecar['record_count'], 'lines': sidecar['line_count'],
                      'sidecar_sha256': sha(SIDECAR.read_bytes()), 'rows_sha256': sha(ROWS.read_bytes())}, indent=1))


if __name__ == '__main__':
    main()
