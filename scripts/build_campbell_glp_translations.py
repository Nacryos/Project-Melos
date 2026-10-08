"""Project verified public-domain comparison translations onto the Campbell GLP records.

Input:  data/campbell_glp/evidence/translations/T*.json  (image-verified English, see docs/audits/campbell-glp-full.md)
        data/campbell_glp/campbell_glp.jsonl         (Greek records the comparisons attach to)
Output: backend/translation_comparisons_glp_data.json (sidecar read by backend/translation_comparisons.py)
        data/campbell_glp/translation_gaps.json      (poems with no verified public-domain translation)

Items carry the same comparison-only contract as the five live Alcaeus comparisons:
whole poem, other edition, never aligned to Campbell's text, never model-eligible.
Only translations published in 1930 or earlier are accepted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'data/campbell_glp/evidence/translations'
RECORDS = ROOT / 'data/campbell_glp/campbell_glp.jsonl'
OUTPUT = ROOT / 'backend/translation_comparisons_glp_data.json'
GAPS = ROOT / 'data/campbell_glp/translation_gaps.json'
PDF_SHA256 = '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f'
FORBIDDEN = ('campbell', 'elegy and iambus', 'west', 'lattimore', 'davenport', 'svarlien', 'rayor', 'miller', 'poochigian')
IDENTITY = ('source', 'kind', 'language', 'quality', 'author', 'work', 'edition', 'source_url', 'raw_sha256')


def comparison(item: dict, poem_id: str, n: int) -> dict:
    year = int(item['publication_year'])
    if year > 1930:
        raise ValueError(f'{poem_id}: {year} is after the US public-domain cutoff')
    if any(word in (item['translator'] + ' ' + item['edition']).lower() for word in FORBIDDEN):
        raise ValueError(f'{poem_id}: forbidden translation source {item["translator"]} / {item["edition"]}')
    if item.get('verified_against_image') is not True or not item['text'].strip():
        raise ValueError(f'{poem_id}: translation not verified against the scan image')
    slug = item['translator'].split()[-1].lower().strip('.')
    pages = item.get('english_pages') or []
    return {
        'citation': item['citation'],
        'comparison_id': f'{poem_id.replace("campbell-glp:", "glp-translation:")}:{slug}-{year}:{n}',
        'edition': item['edition'],
        'edition_difference_metadata': {'difference_status': 'not_computed_different_edition',
                                        'exact_token_differences': None,
                                        'extraction_metadata_note': item.get('coverage_note', '')},
        'evidence_type': 'different_edition_translation_comparison',
        'exact_edition_alignment': False,
        'language': 'eng',
        'license': f'Public domain in the United States (published {year})',
        'license_unrestricted': False,
        'license_url': None,
        'line_attestation': False,
        'match_evidence': item.get('match_evidence', ''),
        'model_eligible': False,
        'paired_greek': None,
        'paired_greek_images': [{k: p.get(k) for k in ('scan_leaf', 'printed_page', 'sha256', 'iiif_url')}
                                for p in item.get('greek_pages') or []],
        'paired_greek_transcription_status': 'withheld_use_source_scan',
        'quality': 'source_scan_OCR_independently_visually_audited',
        'reuse_status': 'public_domain_us_edition',
        'scope': 'whole_poem_other_edition',
        'selection_aligned': False,
        'source_note_markers': [],
        'source_notes': [],
        'source_provenance': [{'language': 'eng', 'source_image': {k: p.get(k) for k in
                               ('scan_leaf', 'printed_page', 'sha256', 'iiif_url')}} for p in pages],
        'source_url': item['source_url'],
        'text': item['text'],
        'translator': item['translator'],
        'word_attestation': False,
    }


def build() -> dict:
    poems = {r['id']: r for r in map(json.loads, RECORDS.read_text(encoding='utf-8').splitlines()) if r}
    by_poem, gaps = {}, {}
    for path in sorted(WORK.glob('T*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        for item in data.get('items', []):
            by_poem.setdefault(item['campbell_id'], []).append(item)
        for gap in data.get('gaps', []):
            gaps[gap['campbell_id']] = gap['reason']
    unknown = sorted((set(by_poem) | set(gaps)) - set(poems))
    if unknown:
        raise ValueError(f'translations for unknown poem ids: {unknown}')
    records = []
    for poem_id in sorted(by_poem):
        poem = poems[poem_id]
        items = [comparison(item, poem_id, n) for n, item in enumerate(by_poem[poem_id], 1)]
        identity = {key: poem[key] for key in IDENTITY}
        identity.update(edition_fragment=poem['metadata']['edition_fragment'], source_pdf_sha256=PDF_SHA256,
                        text_sha256=hashlib.sha256(poem['text'].encode('utf-8')).hexdigest())
        records.append({'campbell_record_id': poem_id, 'campbell_identity': identity, 'translation_comparisons': items})
        gaps.pop(poem_id, None)
    missing = sorted(set(poems) - set(by_poem) - set(gaps))
    for poem_id in missing:
        gaps[poem_id] = 'no verified public-domain translation recorded'
    payload = {'schema': 'translation_comparisons_glp', 'schema_version': 1, 'source_pdf_sha256': PDF_SHA256,
               'selection_aligned': False, 'exact_edition_alignment': False,
               'record_count': len(records), 'comparison_count': sum(len(r['translation_comparisons']) for r in records),
               'records': records}
    raw = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    OUTPUT.write_bytes(raw.encode('utf-8'))
    GAPS.write_bytes((json.dumps([{'id': k, 'reason': v} for k, v in sorted(gaps.items())], ensure_ascii=False, indent=1)
                      + '\n').encode('utf-8'))
    return {'records_with_translation': len(records), 'comparisons': payload['comparison_count'],
            'gaps': len(gaps), 'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(), 'bytes': len(raw.encode('utf-8'))}


if __name__ == '__main__':
    print(json.dumps(build(), indent=1))
    sys.exit(0)
