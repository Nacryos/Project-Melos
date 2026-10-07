"""Project audited, different-edition translations into a separate sidecar.

No source prose is generated or shortened. This does not create aligned English
translations of Campbell, corpus parent links, model evidence, or lexical data.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'runtime/alcaeus-translations/translation-candidates.jsonl'
APPROVAL = ROOT / 'runtime/alcaeus-translations/final-output-audit.json'
NOTES = ROOT / 'runtime/alcaeus-translations/chs-source-notes.json'
GREEK = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
GREEK_APPROVAL = ROOT / 'docs/audits/campbell-assignment-approval.json'
OUTPUT = ROOT / 'runtime/alcaeus-translations/translation-comparisons.public.json'
PINS = {
    'source': '1499aff600c1fc4eef254bb1eb9c6f35c3d0851d63ddaf85df9093702c600497',
    'approval': 'c50c6fcac052d8a5003c2de567ea3599a7f12d64d64304c861557ff5bb5c184e',
    'notes': '5ae6184824807d8d7b4c8be657048440fa3809a2c640bc66832563d06169449a',
    'greek': 'afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b',
    'greek_approval': 'dbbd588e3068e106dfa771ed3038e7c1c43f91b40cde7e0e84740fab8e8c1ce5',
    'source_pdf': '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f',
}
FRAGMENTS = ('34a', '129', '130b', '326', '350')
MAX_INPUT_BYTES = 2_000_000


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, expected: str, *, limit: int = MAX_INPUT_BYTES) -> bytes:
    raw = path.read_bytes()
    if len(raw) > limit or digest(raw) != expected:
        raise ValueError('Source receipt mismatch: ' + path.name)
    return raw


def _artifact(relative: str, expected: str) -> bytes:
    path = (ROOT / relative).resolve()
    allowed = [ROOT / 'runtime/alcaeus-translations', ROOT / 'runtime/campbell-assignment']
    if not any(path.is_relative_to(base.resolve()) for base in allowed):
        raise ValueError('Source artifact escaped approved staging directories')
    return _read(path, expected, limit=12_000_000)


def _rows(raw: bytes) -> list[dict]:
    rows = [json.loads(line) for line in raw.decode('utf8').splitlines() if line.strip()]
    if len(rows) != 5 or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Expected five approved source records')
    return rows


def _image(receipt: dict) -> dict:
    _artifact(receipt['path'], receipt['sha256'])
    return {key: receipt[key] for key in ('url', 'page_url', 'printed_page', 'scan_leaf', 'sha256')}


def build(source: Path = SOURCE, approval: Path = APPROVAL, notes: Path = NOTES,
          greek: Path = GREEK, greek_approval: Path = GREEK_APPROVAL) -> dict:
    audit = json.loads(_read(approval, PINS['approval']))
    greek_audit = json.loads(_read(greek_approval, PINS['greek_approval']))
    if (audit.get('verdict') != 'PASS'
            or audit.get('approved_candidate_hashes', {}).get(SOURCE.relative_to(ROOT).as_posix()) != PINS['source']
            or audit.get('supporting_artifact_hashes', {}).get(NOTES.relative_to(ROOT).as_posix()) != PINS['notes']
            or audit.get('counts', {}).get('total_candidates') != 5
            or audit.get('counts', {}).get('exact_campbell_translations') != 0
            or greek_audit.get('package', {}).get('verdict') != 'PASS'
            or greek_audit.get('package', {}).get('sha256') != PINS['greek']
            or greek_audit.get('source_sha256') != PINS['source_pdf']):
        raise ValueError('Approval chain changed')
    sources = _rows(_read(source, PINS['source']))
    poems = _rows(_read(greek, PINS['greek']))
    source_notes = json.loads(_read(notes, PINS['notes']))
    by_fragment = {row.get('assignment_fragment'): row for row in sources}
    poem_by_fragment = {row.get('metadata', {}).get('assignment_fragment'): row for row in poems}
    if set(by_fragment) != set(FRAGMENTS) or set(poem_by_fragment) != set(FRAGMENTS):
        raise ValueError('Source fragment inventory changed')
    records = []
    for fragment in FRAGMENTS:
        row, poem = by_fragment[fragment], poem_by_fragment[fragment]
        metadata = poem.get('metadata') or {}
        comparison = row.get('campbell_comparison') or {}
        record_id = 'campbell-glp:alcaeus:' + fragment
        if (poem.get('id') != record_id or poem.get('source') != 'campbell_assignment'
                or poem.get('kind') != 'text' or poem.get('language') != 'grc'
                or poem.get('quality') != 'machine_corrected_ocr'
                or metadata.get('source_pdf_sha256') != PINS['source_pdf']
                or comparison.get('campbell_id') != record_id
                or comparison.get('campbell_text') != poem.get('text')
                or row.get('translation_of') is not None or 'parent_id' in row
                or row.get('alignment_status') != 'different_edition_do_not_assign_translation_of'
                or row.get('kind') != 'translation' or row.get('language') != 'eng'
                or not isinstance(row.get('text'), str) or not row['text']):
            raise ValueError('Source comparison identity mismatch: ' + fragment)
        _artifact(poem['raw_path'], poem['raw_sha256'])
        citations = []
        if row['source'] == 'alcaeus_translations_chs':
            _artifact(row['raw_path'], row['raw_sha256'])
            citations.append({'source_url': row['source_url'], 'raw_sha256': row['raw_sha256'],
                              'source_selectors': deepcopy(row['source_selectors'])})
        elif row['source'] == 'alcaeus_translations_edmonds':
            for chunk in row['source_chunks']:
                parsed = json.loads(_artifact(chunk['ocr_path'], chunk['ocr_sha256']))
                if parsed['blocks'][chunk['block_index']]['text'] != chunk['text']:
                    raise ValueError('Source OCR block differs from approved prose')
                citations.append({'language': chunk['language'], 'source_image': _image(chunk['image_receipt']),
                                  'ocr_sha256': chunk['ocr_sha256'], 'source_block_index': chunk['block_index']})
            english = '\n'.join(chunk['text'] for chunk in row['source_chunks'] if chunk['language'] == 'eng')
            if english != row['text']:
                raise ValueError('Whole English source passage changed')
        else:
            raise ValueError('Unapproved translation source')
        image_sources = [_image(receipt) for receipt in row.get('paired_greek_images', [])]
        if fragment == '326' and (row.get('paired_greek') is not None or not image_sources):
            raise ValueError('Vetoed Greek OCR was exposed as accepted text')
        selected_notes = [deepcopy(note) for note in source_notes
                          if note['number'] in ({27, 28, 29, 30} if fragment == '129'
                                                else {48, 49, 50, 51} if fragment == '130b' else set())]
        item = {
            'comparison_id': row['id'], 'evidence_type': 'different_edition_translation_comparison',
            'scope': 'whole_poem_other_edition', 'selection_aligned': False,
            'exact_edition_alignment': False, 'word_attestation': False, 'line_attestation': False,
            'model_eligible': False, 'language': 'eng', 'text': row['text'],
            'translator': row['translator'], 'edition': row['edition'], 'citation': row['citation'],
            'source_url': row['source_url'], 'quality': row['quality'],
            'license': row['license'], 'license_url': row.get('license_url'),
            'reuse_status': row.get('reuse_status', 'public_domain_us_edition'),
            'license_unrestricted': False,
            'source_provenance': citations,
            'paired_greek': row['paired_greek'],
            'paired_greek_transcription_status': row.get('paired_greek_transcription_status', 'source_html_extraction'),
            'paired_greek_images': image_sources,
            'source_note_markers': deepcopy(row.get('source_note_markers', [])),
            'source_notes': selected_notes,
            'edition_difference_metadata': {
                'exact_token_differences': deepcopy(comparison['exact_token_differences']),
                'difference_status': comparison.get('difference_status', 'exact_token_diff'),
                'extraction_metadata_note': row.get('source_note'),
            },
        }
        records.append({'campbell_record_id': record_id, 'assignment_fragment': fragment,
            'campbell_identity': {**{key: poem[key] for key in
                ('source', 'kind', 'language', 'quality', 'author', 'work', 'edition', 'source_url', 'raw_sha256')},
                'text_sha256': digest(poem['text'].encode('utf8')),
                'edition_fragment': metadata['edition_fragment'], 'source_pdf_sha256': metadata['source_pdf_sha256']},
            'translation_comparisons': [item]})
    return {'schema_version': 1, 'schema': 'translation_comparisons', 'record_count': len(records),
            'comparison_count': len(records), 'source_package_sha256': PINS['source'],
            'source_approval_sha256': PINS['approval'], 'greek_package_sha256': PINS['greek'],
            'greek_approval_sha256': PINS['greek_approval'], 'source_notes_sha256': PINS['notes'],
            'source_pdf_sha256': PINS['source_pdf'], 'selection_aligned': False,
            'exact_edition_alignment': False, 'records': records}


def write(output: Path = OUTPUT, **inputs) -> str:
    raw = (json.dumps(build(**inputs), ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf8')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != raw:
            raise FileExistsError('Existing staged comparison differs; use a fresh output path')
        return digest(raw)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name+'.', suffix='.tmp', delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(raw)
    try:
        if output.exists():
            raise FileExistsError('Output appeared during projection')
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest(raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    print(write(parser.parse_args().output))
