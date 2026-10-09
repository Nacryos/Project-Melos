"""Project verified public-domain comparison translations onto the Campbell GLP records.

Input:  data/campbell_glp/evidence/translations/T*.json  (image-verified English, see docs/audits/campbell-glp-full.md)
        data/open/pd-translations/translations.jsonl (release U: open-survey renderings for 17 former gaps,
                                                       English only, checked against the IA scans)
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
# Release U: the open-sources survey's public-domain translations for former gaps
# (data/open/pd-translations, scripts/ingest_open_pd_translations.py). Only the English
# records of these poems are projected; German-only renderings (Mimnermus 13,
# Phocylides 8) and German secondary records await an owner decision.
OPEN = ROOT / 'data/open/pd-translations'
OPEN_ACCEPTED = frozenset('campbell-glp:' + p for p in (
    'hipponax:24a', 'hipponax:24b', 'hipponax:25', 'hipponax:29', 'hipponax:70', 'hipponax:81',
    'archilochus:71', 'archilochus:88', 'archilochus:89', 'archilochus:92a', 'archilochus:103',
    'archilochus:104', 'archilochus:112', 'archilochus:118', 'archilochus:79a',
    'phocylides:3', 'phocylides:4'))
# Renderings that do not cover the whole poem; the reader shows the label above the text.
OPEN_PARTIAL = {
    'campbell-glp:phocylides:3': ('paraphrase', 'Partial: an indirect English paraphrase in a literary history '
                                  '(Jevons 1886), not a verse-by-verse translation.'),
    'campbell-glp:archilochus:79a': ('opening_missing', 'Partial: Perry leaves out the opening words of the poem; '
                                     'his rendering begins at “At Salmydessus”.'),
    'campbell-glp:hipponax:24a': ('shared_rendering', 'Partial: Knox renders his fragments 56 and 57 together, so '
                                  'Campbell 24a and 24b share one rendering; 24a’s request for clothes and gold is '
                                  'Knox fragment 59.'),
    'campbell-glp:hipponax:24b': ('shared_rendering', 'Partial: Knox renders his fragments 56 and 57 together, so '
                                  'Campbell 24a and 24b share one rendering, which also covers the Hermes '
                                  'invocation of 24a.'),
}
# Old-print spacing kept by the OCR text layer (a space before ; : ? ! and inside quotation marks)
# and quotation marks of the surrounding prose are removed for display; every change is listed in
# the item's text_normalisation.
OPEN_TEXT_EDITS = {
    'campbell-glp:archilochus:103': [("'the fox uses many arts, but the hedgehog has one great one,'",
                                      'the fox uses many arts, but the hedgehog has one great one')],
    'campbell-glp:hipponax:81': [('to the end.”', 'to the end.')],
}
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


def _iiif(ia: str, leaf: int) -> str:
    return (f'https://iiif.archive.org/image/iiif/3/{ia}%2F{ia}_jp2.zip%2F{ia}_jp2%2F{ia}_{int(leaf):04d}.jp2'
            '/full/1200,/0/default.jpg')


def _open_page(record: dict, page: dict) -> dict:
    image = OPEN / page['image'] if page.get('image') else None
    if image is None or not image.is_file():
        raise ValueError(f'{record["campbell_id"]}: scan image {page.get("image")} not stored')
    return {'scan_leaf': int(page['leaf']), 'printed_page': page.get('printed_page'),
            'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
            'iiif_url': page.get('image_url') or _iiif(record['ia_item'], page['leaf'])}


def _display_text(poem_id: str, text: str) -> tuple[str, list[str]]:
    import re
    notes = []
    for old, new in OPEN_TEXT_EDITS.get(poem_id, []):
        if old not in text:
            raise ValueError(f'{poem_id}: expected source text {old!r} not found')
        text = text.replace(old, new)
        notes.append(f'surrounding quotation marks of the source prose removed: {old!r} -> {new!r}')
    spaced = re.sub(r' +([;:?!])', r'\1', text)
    spaced = re.sub(r'([‘“]) +', r'\1', spaced)
    spaced = re.sub(r'(\w) +’(?=\w)', r'\1’', spaced)
    if spaced != text:
        notes.append('old-print spaces before ; : ? ! and inside quotation marks removed')
    return spaced, notes


def open_items() -> list[dict]:
    """Builder items (the T*.json shape plus extras) for the accepted English open records."""
    items = []
    for line in (OPEN / 'translations.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        poem_id = record['campbell_id']
        if poem_id not in OPEN_ACCEPTED or record.get('language') != 'eng' or record.get('role') != 'primary':
            continue
        if record.get('model_eligible') is not False:
            raise ValueError(f'{poem_id}: open record must not be model-eligible')
        text, notes = _display_text(poem_id, record['text'])
        coverage = OPEN_PARTIAL.get(poem_id)
        items.append({
            'campbell_id': poem_id,
            'citation': record['translator_reference'],
            'coverage_note': record.get('rendering_note', ''),
            'edition': f'{record["title"]} ({record["year"]}), {record["publisher"]}',
            'english_pages': [_open_page(record, p) for p in record.get('pages') or []],
            'greek_pages': [_open_page(record, p) for p in record.get('greek_pages') or []],
            'match_evidence': record.get('identification', ''),
            'publication_year': int(record['year']),
            'source_url': record['ia_url'],
            'text': text,
            'translator': record['translator'],
            'verified_against_image': record.get('verified_against_image'),
            '_open': {'source_id': record['source_id'], 'license_basis': record['us_pd_basis'],
                      'host': record.get('host'), 'verified_on': record.get('verified_on'),
                      'ocr_corrections': len(record.get('ocr_corrections') or []),
                      'text_normalisation': notes, 'coverage': coverage},
        })
    found = {i['campbell_id'] for i in items}
    if found != OPEN_ACCEPTED:
        raise ValueError(f'open translations missing for {sorted(OPEN_ACCEPTED - found)}')
    return items


def _with_open_fields(entry: dict, item: dict, poem_id: str) -> dict:
    extra = item.get('_open')
    if not extra:
        return entry
    entry['comparison_id'] = f'{poem_id.replace("campbell-glp:", "glp-translation:")}:{extra["source_id"]}:1'
    entry['license_basis'] = extra['license_basis']
    entry['quality'] = 'source_scan_OCR_corrected_against_image'
    entry['source_record'] = {'dataset': 'data/open/pd-translations', 'source_id': extra['source_id'],
                              'host': extra['host'], 'verified_on': extra['verified_on'],
                              'ocr_corrections_applied': extra['ocr_corrections']}
    if extra['text_normalisation']:
        entry['text_normalisation'] = extra['text_normalisation']
    if extra['coverage']:
        entry['coverage'] = 'partial'
        entry['coverage_kind'], entry['coverage_label'] = extra['coverage']
    return entry


def build() -> dict:
    poems = {r['id']: r for r in map(json.loads, RECORDS.read_text(encoding='utf-8').splitlines()) if r}
    by_poem, gaps = {}, {}
    for path in sorted(WORK.glob('T*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        for item in data.get('items', []):
            by_poem.setdefault(item['campbell_id'], []).append(item)
        for gap in data.get('gaps', []):
            gaps[gap['campbell_id']] = gap['reason']
    for item in open_items():
        if item['campbell_id'] in by_poem:
            raise ValueError(f'{item["campbell_id"]}: open translation for a poem that already has one')
        by_poem[item['campbell_id']] = [item]
    unknown = sorted((set(by_poem) | set(gaps)) - set(poems))
    if unknown:
        raise ValueError(f'translations for unknown poem ids: {unknown}')
    records = []
    for poem_id in sorted(by_poem):
        poem = poems[poem_id]
        items = [_with_open_fields(comparison(item, poem_id, n), item, poem_id)
                 for n, item in enumerate(by_poem[poem_id], 1)]
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
    survey = {item['id']: item for item in
              json.loads((OPEN / 'gaps-2026-10-09.json').read_text(encoding='utf-8'))['items']}
    rows = []
    for k, v in sorted(gaps.items()):
        row = {'id': k, 'reason': v}
        found = survey.get(k)
        if found:
            status = found['status']
            row['open_survey_2026_10_09'] = {
                'status': status,
                'note': {'found_other_language': 'Only a non-English public-domain rendering was found '
                                                 f'({found.get("source")}); not added pending an owner decision.',
                         'becomes_pd_2027': 'Edmonds, Elegy and Iambus (1931) becomes US public domain on 2027-01-01.',
                         'none_found': 'No public-domain translation found.'}.get(status, status)}
        rows.append(row)
    GAPS.write_bytes((json.dumps(rows, ensure_ascii=False, indent=1) + '\n').encode('utf-8'))
    return {'records_with_translation': len(records), 'comparisons': payload['comparison_count'],
            'gaps': len(gaps), 'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(), 'bytes': len(raw.encode('utf-8'))}


if __name__ == '__main__':
    print(json.dumps(build(), indent=1))
    sys.exit(0)
