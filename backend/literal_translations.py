"""Fail-closed lookup of the owner-commissioned literal translations (reader fallback and search rows).

These are unpublished machine translations made line by line from Campbell's Greek for the site
owner (owner decision 2026-10-10, docs/decisions.md). They are never a published source, never
model-eligible evidence for word meanings, and the reader shows them only when a poem has no
published English translation (`display_policy: fallback_only`). Each record is bound to the exact
Campbell text it was made from (record id, edition fragment, PDF hash, text hash, line count); a
text that no longer matches gets `status: unavailable`, never a stale English line.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

DATA_PATH = Path(__file__).with_name('literal_translations_data.json')
DATA_SHA256 = 'ac62dda8253729bcba6379e79114c7ca9d38cae91055116206afc2a861526245'
SOURCE_PDF_SHA256 = '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f'
MAX_BYTES = 600_000
EVIDENCE_TYPE = 'literal_machine_translation'
_CACHE: dict = {}


def _read(path: Path) -> dict:
    key = (str(path), path.stat().st_mtime_ns)
    if key in _CACHE:
        return _CACHE[key]
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Literal translation sidecar exceeds approved size limit')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError('Literal translation projection hash mismatch')
    payload = json.loads(raw)
    if (payload.get('schema') != 'literal_interlinear_translations' or payload.get('schema_version') != 1
            or payload.get('source_pdf_sha256') != SOURCE_PDF_SHA256 or payload.get('model_eligible') is not False
            or payload.get('display_policy') != 'fallback_only' or payload.get('selection_aligned') is not False
            or not isinstance(payload.get('records'), list) or len(payload['records']) != payload.get('record_count')):
        raise ValueError('Literal translation schema mismatch')
    index = {row['campbell_record_id']: (row, payload) for row in payload['records']}
    _CACHE.clear()
    _CACHE[key] = index
    return index


def _bound(record: dict, passage: dict) -> bool:
    identity, metadata, lines = record['campbell_identity'], passage.get('metadata'), passage.get('lines')
    return (isinstance(metadata, dict) and isinstance(lines, list)
            and passage.get('language') == 'grc' and passage.get('kind') == 'text'
            and metadata.get('edition_fragment') == identity['edition_fragment']
            and metadata.get('source_pdf_sha256') == identity['source_pdf_sha256'] == SOURCE_PDF_SHA256
            and passage.get('raw_sha256') == identity['raw_sha256']
            and len(lines) == identity['line_count'] == len(record['lines'])
            and isinstance(passage.get('text'), str)
            and hashlib.sha256(passage['text'].encode('utf8')).hexdigest() == identity['text_sha256'])


def published_english_available(passage: dict) -> bool:
    """True when the passage already carries published English (previews or other-edition comparisons)."""
    previews = passage.get('translation_previews')
    if isinstance(previews, list) and any(isinstance(p, dict) and p.get('text') for p in previews):
        return True
    comparisons = passage.get('translation_comparisons')
    return (isinstance(comparisons, dict) and comparisons.get('status') == 'available'
            and bool(comparisons.get('translation_comparisons')))


def for_passage(passage: dict, *, path: Path = DATA_PATH) -> dict | None:
    """The literal translation projection for one Campbell poem, or None when there is none."""
    record_id = passage.get('id')
    base = {'evidence_type': EVIDENCE_TYPE, 'scope': 'whole_poem_line_by_line', 'display_policy': 'fallback_only',
            'model_eligible': False, 'selection_aligned': False, 'exact_edition_alignment': False,
            'word_attestation': False, 'published_source': False}
    try:
        found = _read(Path(path)).get(record_id)
        if found is None:
            return None
        record, payload = found
        if not _bound(record, passage):
            raise ValueError('Campbell source identity differs from the text the translation was made from')
        return {**base, 'status': 'available', 'campbell_record_id': record_id, 'line_aligned': True,
                'published_english_available': published_english_available(passage),
                'translator': payload['translator'], 'produced_at': payload['produced_at'],
                'translation_status': payload['status'], 'method': payload['method'],
                'line_count': len(record['lines']), 'lines': deepcopy(record['lines']), 'text': record['text'],
                'note': record.get('note', ''), 'love_theme': bool(record.get('love_theme'))}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {**base, 'status': 'unavailable', 'campbell_record_id': record_id, 'line_count': 0, 'lines': [],
                'reason': 'The literal translation is bound to a Campbell text that no longer matches.'}
