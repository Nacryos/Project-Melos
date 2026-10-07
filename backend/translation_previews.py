"""Display-only excerpts from admitted, explicitly paired published translations.

The CGL collector pairs a whole source passage with a translation pane or an
adjacent credited block. That relation does NOT establish line alignment.
Other collectors' parent_id links (including first-line overlap in Perseus)
are deliberately insufficient. A separately audited Perseus proof manifest
can admit an exact source-bound pair without scanning TEI on requests.
No texts, credits or alignments are generated.
"""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from .translation_languages import is_english_translation


SOURCE = "p2_cgl_anthology"
SCOPE = "whole_source_passage"
MAX_PARENTS = 100
MAX_PREVIEWS = 6
EXCERPT_CHARS = 240
PROOF_MANIFEST = Path(__file__).with_name('translation_pairings.json')


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _metadata(record):
    value = record.get('metadata')
    return value if isinstance(value, dict) else {}


def _cgl_parent(record):
    if not isinstance(record, dict):
        return False
    metadata = _metadata(record)
    number = metadata.get('text_id')
    return (record.get('source') == SOURCE and record.get('kind') == 'text'
            and record.get('language') == 'grc' and record.get('quality') == 'source_text'
            and type(number) is int and number > 0
            and metadata.get('scope') in (None, 'passage', SCOPE)
            and record.get('id') == f'{SOURCE}:{number}'
            and bool(_text(record.get('text'))))


def _cgl_pair(parent, translation):
    if not _cgl_parent(parent) or not isinstance(translation, dict):
        return False
    metadata = _metadata(translation)
    parent_metadata = _metadata(parent)
    if (translation.get('source') != SOURCE or translation.get('kind') != 'translation'
            or translation.get('quality') != 'source_text' or not is_english_translation(translation)
            or translation.get('parent_id') != parent['id']
            or metadata.get('translation_of') != parent['id']
            or type(metadata.get('text_id')) is not int
            or metadata.get('text_id') != parent_metadata.get('text_id')
            or not re.fullmatch(re.escape(parent['id']) + r':tr[1-9]\d*', _text(translation.get('id')))
            or not _text(translation.get('text'))
            or metadata.get('scope') not in (None, 'passage', SCOPE)):
        return False
    digest = _text(parent.get('raw_sha256'))
    if (not re.fullmatch(r'[0-9a-f]{64}', digest) or translation.get('raw_sha256') != digest
            or not _text(parent.get('raw_path')) or translation.get('raw_path') != parent.get('raw_path')):
        return False
    try:
        origin = urlsplit(_text(parent.get('source_url')))
        target = urlsplit(_text(translation.get('source_url')))
        if (origin.scheme != 'https' or origin.netloc != 'www.greek-language.gr'
                or origin.username or origin.password
                or origin.path != '/digitalResources/ancient_greek/anthology/poetry/browse.html'
                or parse_qs(origin.query).get('text_id') != [str(parent_metadata['text_id'])]
                or origin._replace(fragment='') != target._replace(fragment='')):
            return False
    except (ValueError, TypeError):
        return False
    locator = metadata.get('source_translation_locator')
    if not isinstance(locator, dict):
        return False
    if locator.get('layout') == 'linked_tab':
        pane = _text(locator.get('pane_id'))
        return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', pane) and target.fragment == pane)
    if locator.get('layout') == 'inline_adjacent_credit':
        return (type(locator.get('block_ordinal')) is int and locator['block_ordinal'] > 0
                and locator.get('credit_selector') == 'adjacent div.pull-right > i'
                and not target.fragment)
    return False


@lru_cache(maxsize=4)
def _read_proofs(path, stamp, size):
    """A build-time audited source projection, not a hand-written pairing list."""
    if size > 2_000_000:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return {}
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get('pairs'), list):
        return {}
    proofs = {}
    for pair in payload['pairs']:
        if not isinstance(pair, dict) or not _text(pair.get('parent_id')) or not _text(pair.get('translation_id')):
            return {}
        key = (pair['parent_id'], pair['translation_id'])
        if key in proofs:
            return {}  # Conflicting/duplicated source identity is not a choice.
        proofs[key] = pair
    return proofs


def _proofs():
    try:
        signature = PROOF_MANIFEST.stat()
    except OSError:
        return {}
    return _read_proofs(str(PROOF_MANIFEST), signature.st_mtime_ns, signature.st_size)


def _cts_name(value):
    return _text(value).removeprefix('urn:cts:greekLit:')


def _boundary_valid(boundary, parent, translation):
    spans = []
    for field, record in (('parent_span', parent), ('translation_span', translation)):
        span = boundary.get(field)
        lines = record.get('lines')
        if (not isinstance(span, dict) or type(span.get('start_index')) is not int
                or type(span.get('end_index_exclusive')) is not int
                or span['start_index'] < 0 or span['end_index_exclusive'] <= span['start_index']
                or 'next_anchor' not in span
                or type(span.get('at_source_end')) is not bool
                or not isinstance(lines, list) or len(lines) != span['end_index_exclusive'] - span['start_index']
                or (span['at_source_end'] and span.get('next_anchor') is not None)
                or (not span['at_source_end'] and not _text(span.get('next_anchor')))):
            return False
        spans.append(span)
    if boundary.get('method') == 'complete_source_bodies':
        return all(span['start_index'] == 0 and span['at_source_end'] for span in spans)
    anchors = boundary.get('anchors')
    return (boundary.get('method') == 'identical_ordered_source_anchors_and_successor'
            and isinstance(anchors, list) and bool(anchors)
            and all(isinstance(anchor, str) for anchor in anchors) and len(set(anchors)) == len(anchors)
            and all([line.get('label') if isinstance(line, dict) else None for line in record['lines']] == anchors
                    for record in (parent, translation))
            and spans[0]['next_anchor'] == spans[1]['next_anchor']
            and spans[0]['at_source_end'] == spans[1]['at_source_end'])


def _perseus_proof(parent, translation):
    if not isinstance(parent, dict) or not isinstance(translation, dict):
        return None
    proof = _proofs().get((parent.get('id'), translation.get('id')))
    if not proof or translation.get('parent_id') != parent.get('id'):
        return None
    boundary = proof.get('boundary_proof')
    cts = proof.get('cts_proof')
    if (not isinstance(boundary, dict) or boundary.get('method') not in {
            'complete_source_bodies', 'identical_ordered_source_anchors_and_successor'}
            or not _boundary_valid(boundary, parent, translation)
            or not isinstance(cts, dict) or not re.fullmatch(r'[0-9a-f]{64}', _text(cts.get('sha256')))):
        return None
    for row, field, language, kind, cts_role in ((parent, 'parent', 'grc', 'text', 'edition_urn'),
            (translation, 'translation', 'eng', 'translation', 'translation_urn')):
        binding = proof.get(field)
        metadata = _metadata(row)
        if (not isinstance(binding, dict) or row.get('source') != 'perseus'
                or (not is_english_translation(row) if language == 'eng' else row.get('language') != language)
                or row.get('kind') != kind or row.get('quality') != 'source_text'
                or not isinstance(row.get('text'), str)
                or hashlib.sha256(row['text'].encode('utf-8')).hexdigest() != binding.get('text_sha256')
                or row.get('raw_sha256') != binding.get('raw_sha256')
                or not re.fullmatch(r'[0-9a-f]{64}', _text(binding.get('raw_sha256')))
                or row.get('source_url') != binding.get('source_url')
                or metadata.get('cts_urn') != binding.get('cts_urn')
                or '.'.join(_cts_name(binding.get('cts_urn')).split('.')[:2]) != _cts_name(proof.get('work_urn'))
                or _cts_name(cts.get(cts_role)) != _cts_name(binding.get('cts_urn'))
                or (cts.get('work_urn') is not None and _cts_name(cts['work_urn']) != _cts_name(proof.get('work_urn')))
                or any(field in binding and row.get(field) != binding[field] for field in ('language','kind','quality','citation','edition'))
                or (binding.get('commit') is not None and metadata.get('commit') != binding.get('commit'))):
            return None
    return proof


def _parent(record):
    if _cgl_parent(record):
        return True
    return (isinstance(record, dict) and record.get('source') == 'perseus'
            and record.get('kind') == 'text' and record.get('language') == 'grc'
            and record.get('quality') == 'source_text'
            and any(parent_id == record.get('id') for parent_id, _ in _proofs()))


def _pair(parent, translation):
    return _cgl_pair(parent, translation) or bool(_perseus_proof(parent, translation))


def _excerpt(value):
    value = _text(value)
    if len(value) <= EXCERPT_CHARS:
        return value, False
    end = EXCERPT_CHARS
    spaces = list(re.finditer(r'\s+', value[:end]))
    if spaces and spaces[-1].start() >= end // 2:
        end = spaces[-1].start()
    return value[:end].rstrip() + '…', True


def project(parent, related, *, full_text=False):
    """Return English-only source-scoped previews; never relabel source records."""
    valid = {row['id']: row for row in related if is_english_translation(row) and _pair(parent, row)}
    ordered = sorted(valid.values(), key=lambda row: (row.get('source') or '',
        int(row['id'].rsplit(':tr', 1)[1]) if row.get('source') == SOURCE else 0, row['id']))
    previews = []
    for row in ordered[:MAX_PREVIEWS if full_text else 1]:
        metadata = _metadata(row)
        excerpt, truncated = _excerpt(row['text'])
        item = {key: row.get(key) for key in ('source', 'source_url', 'edition', 'citation', 'language', 'license')}
        perseus = _perseus_proof(parent, row) if row.get('source') == 'perseus' else None
        if perseus:
            raw_credits = perseus['translation'].get('translators', [])
            credits = [credit for credit in raw_credits if isinstance(credit, str) and credit.strip()] if isinstance(raw_credits, list) else []
            translator = ' / '.join(credits) or None
            boundary = perseus['boundary_proof']
            public_boundary = {'method': boundary['method'], **{field: {
                key: boundary[field][key] for key in ('start_index', 'end_index_exclusive', 'next_anchor', 'at_source_end')}
                for field in ('parent_span', 'translation_span')}}
            if boundary['method'] == 'identical_ordered_source_anchors_and_successor':
                public_boundary['anchors'] = list(boundary['anchors'])
            pairing_proof = {'translation_of': parent['id'], 'parent_raw_sha256': parent['raw_sha256'],
                'raw_sha256': row['raw_sha256'], 'work_urn': perseus['work_urn'],
                'boundary_proof': public_boundary,
                'cts_proof': {key: perseus['cts_proof'].get(key) for key in
                    ('source_url', 'sha256', 'edition_urn', 'translation_urn')}}
        else:
            translator = _text(metadata.get('translator')) or None
            pairing_proof = {'translation_of': metadata['translation_of'],
                'source_translation_locator': dict(metadata['source_translation_locator']), 'raw_sha256': row['raw_sha256']}
        item.update({'record_id': row['id'], 'parent_id': parent['id'],
                     'translator': translator, 'text_excerpt': excerpt,
                     'excerpt_truncated': truncated, 'scope': SCOPE, 'alignment': 'not_line_aligned',
                     'pairing_proof': pairing_proof,
                     'scope_note': ('Published translation covering this source passage; not aligned to individual lines or a selected phrase. '
                         'The translator\'s Greek base edition is not established here.' if perseus else
                         'Translation of this complete source passage; not aligned to an individual line or selected phrase.')})
        if full_text:
            item['text'] = row['text']
        previews.append(item)
    return {'translation_previews': previews, 'translation_preview_count': len(ordered),
            'translation_previews_truncated': len(ordered) > len(previews)}


def enrich_results(connection, records):
    """One SQL query for the already paginated output, never the ranking pool.

    Callers supply their publication-filtered read connection. No lookup of
    mirrors, same-number fragments, inferred parents or unrelated translations.
    """
    parents = {row['id']: row for row in records if _parent(row)}
    if not parents:
        return records
    if len(parents) > MAX_PARENTS:
        raise ValueError('Translation previews require a paginated result batch of at most 100 records.')
    placeholders = ','.join('?' for _ in parents)
    found = connection.execute(
        f"SELECT data FROM passages WHERE source IN (?,?) AND kind='translation' "
        f"AND json_extract(data,'$.parent_id') IN ({placeholders}) ORDER BY id",
        [SOURCE, 'perseus', *parents])
    grouped = {key: [] for key in parents}
    for result in found:
        try:
            row = json.loads(result[0])
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict) and row.get('parent_id') in grouped:
            grouped[row['parent_id']].append(row)
    return [{**row, **project(row, grouped[row['id']])} if row.get('id') in parents else row
            for row in records]
