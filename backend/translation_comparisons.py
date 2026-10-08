"""Fail-closed, exact-record lookup of other-edition translation comparisons.

This separate sidecar is reader context. It never supplies aligned English,
selection evidence, parent translation links, or model-eligible source claims.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

DATA_PATH = Path(__file__).with_name('translation_comparisons_data.json')
DATA_SHA256 = '0b0f87dd1aba066b0f5d1bf6a539af2ca3d10d5a1ff32fb0bfffc38e57db780b'
SOURCE_PACKAGE_SHA256 = '1499aff600c1fc4eef254bb1eb9c6f35c3d0851d63ddaf85df9093702c600497'
GREEK_PACKAGE_SHA256 = 'ab2e1487885431669ebff57c566419bdceb1d6af69740e6ed05e8b7190d84457'
SOURCE_PDF_SHA256 = '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f'
FRAGMENTS = frozenset(('34a', '129', '130b', '326', '350'))
MAX_BYTES = 150_000


def _read(path: Path) -> dict:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Comparison sidecar exceeds approved size limit')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError('Approved comparison projection hash mismatch')
    payload = json.loads(raw)
    if (payload.get('schema_version') != 1 or payload.get('schema') != 'translation_comparisons'
            or payload.get('record_count') != 5 or payload.get('comparison_count') != 5
            or payload.get('source_package_sha256') != SOURCE_PACKAGE_SHA256
            or payload.get('greek_package_sha256') != GREEK_PACKAGE_SHA256
            or payload.get('source_pdf_sha256') != SOURCE_PDF_SHA256
            or payload.get('selection_aligned') is not False
            or payload.get('exact_edition_alignment') is not False
            or not isinstance(payload.get('records'), list) or len(payload['records']) != 5):
        raise ValueError('Approved comparison schema mismatch')
    return payload


def _bound(record: dict, passage: dict) -> bool:
    metadata = passage.get('metadata')
    identity = record['campbell_identity']
    return (isinstance(metadata, dict)
            and passage.get('id') == record['campbell_record_id']
            and passage.get('id') == 'campbell-glp:alcaeus:' + record['assignment_fragment']
            and all(passage.get(key) == identity[key] for key in
                    ('source', 'kind', 'language', 'quality', 'author', 'work', 'edition', 'source_url', 'raw_sha256'))
            and metadata.get('assignment_fragment') == record['assignment_fragment']
            and metadata.get('edition_fragment') == identity['edition_fragment']
            and metadata.get('source_pdf_sha256') == identity['source_pdf_sha256'] == SOURCE_PDF_SHA256
            and isinstance(passage.get('text'), str)
            and hashlib.sha256(passage['text'].encode('utf8')).hexdigest() == identity['text_sha256'])


def for_passage(passage: dict, *, path: Path = DATA_PATH) -> dict | None:
    """Return whole source translations under the comparison-only schema.

No matching by selected text, fragment number alone, author alias, or words is
performed. License/reuse limits and source-edition Greek remain in each item.
Deployers must copy the audited projection unchanged; a missing or altered
sidecar returns an explicit unavailable result without source content.
"""
    if not isinstance(passage, dict):
        return None
    record_id = passage.get('id')
    if not isinstance(record_id, str) or not record_id.startswith('campbell-glp:'):
        return None
    if (not record_id.startswith('campbell-glp:alcaeus:')
            or record_id.removeprefix('campbell-glp:alcaeus:') not in FRAGMENTS):
        return glp_for_passage(passage)
    base = {'evidence_type': 'different_edition_translation_comparison',
            'scope': 'whole_poem_other_edition', 'selection_aligned': False,
            'exact_edition_alignment': False, 'word_attestation': False,
            'line_attestation': False, 'model_eligible': False}
    try:
        payload = _read(Path(path))
        records = [row for row in payload['records'] if row.get('campbell_record_id') == record_id]
        if len(records) != 1 or not _bound(records[0], passage):
            raise ValueError('Accepted Campbell source identity differs')
        items = records[0]['translation_comparisons']
        if (len(items) != 1 or any(item.get('selection_aligned') is not False
                or item.get('exact_edition_alignment') is not False or item.get('model_eligible') is not False
                or 'translation_of' in item or 'parent_id' in item for item in items)):
            raise ValueError('Comparison-only contract changed')
        return {**base, 'status': 'available', 'campbell_record_id': record_id,
                'comparison_count': len(items), 'translation_comparisons': deepcopy(items)}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {**base, 'status': 'unavailable', 'reason': 'Approved comparison source identity unavailable.',
                'comparison_count': 0, 'translation_comparisons': []}


# Full Campbell GLP selection (scripts/build_campbell_glp_translations.py). Same
# comparison-only contract; a poem without a verified public-domain translation
# has no record and gets no panel (None), never an authored substitute.
GLP_DATA_PATH = Path(__file__).with_name('translation_comparisons_glp_data.json')
GLP_DATA_SHA256 = '22c492acc2b54dad801f0f700b01a3ff803a0db289445b267c4f21bbd645f544'
GLP_MAX_BYTES = 3_000_000
GLP_IDENTITY = ('source', 'kind', 'language', 'quality', 'author', 'work', 'edition', 'source_url', 'raw_sha256')
_GLP_CACHE: dict = {}


def _read_glp(path: Path) -> dict:
    key = (str(path), path.stat().st_mtime_ns)
    if key in _GLP_CACHE:
        return _GLP_CACHE[key]
    if path.stat().st_size > GLP_MAX_BYTES:
        raise ValueError('GLP comparison sidecar exceeds approved size limit')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != GLP_DATA_SHA256:
        raise ValueError('Approved GLP comparison projection hash mismatch')
    payload = json.loads(raw)
    if (payload.get('schema') != 'translation_comparisons_glp' or payload.get('schema_version') != 1
            or payload.get('source_pdf_sha256') != SOURCE_PDF_SHA256
            or payload.get('selection_aligned') is not False or payload.get('exact_edition_alignment') is not False
            or not isinstance(payload.get('records'), list) or len(payload['records']) != payload.get('record_count')):
        raise ValueError('Approved GLP comparison schema mismatch')
    index = {row['campbell_record_id']: row for row in payload['records']}
    _GLP_CACHE.clear()
    _GLP_CACHE[key] = index
    return index


def _glp_bound(record: dict, passage: dict) -> bool:
    identity, metadata = record['campbell_identity'], passage.get('metadata')
    return (isinstance(metadata, dict)
            and all(passage.get(key) == identity[key] for key in GLP_IDENTITY)
            and metadata.get('edition_fragment') == identity['edition_fragment']
            and metadata.get('source_pdf_sha256') == identity['source_pdf_sha256'] == SOURCE_PDF_SHA256
            and isinstance(passage.get('text'), str)
            and hashlib.sha256(passage['text'].encode('utf8')).hexdigest() == identity['text_sha256'])


def glp_for_passage(passage: dict, *, path: Path = GLP_DATA_PATH) -> dict | None:
    """Comparison translations for the wider Campbell selection, fail-closed like for_passage."""
    record_id = passage.get('id')
    base = {'evidence_type': 'different_edition_translation_comparison',
            'scope': 'whole_poem_other_edition', 'selection_aligned': False,
            'exact_edition_alignment': False, 'word_attestation': False,
            'line_attestation': False, 'model_eligible': False}
    try:
        record = _read_glp(Path(path)).get(record_id)
        if record is None:
            return None
        if not _glp_bound(record, passage):
            raise ValueError('Accepted Campbell source identity differs')
        items = record['translation_comparisons']
        if (not items or any(item.get('selection_aligned') is not False
                or item.get('exact_edition_alignment') is not False or item.get('model_eligible') is not False
                or item.get('language') != 'eng' or 'translation_of' in item or 'parent_id' in item for item in items)):
            raise ValueError('Comparison-only contract changed')
        return {**base, 'status': 'available', 'campbell_record_id': record_id,
                'comparison_count': len(items), 'translation_comparisons': deepcopy(items)}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {**base, 'status': 'unavailable', 'reason': 'Approved comparison source identity unavailable.',
                'comparison_count': 0, 'translation_comparisons': []}
