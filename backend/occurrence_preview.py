"""Conservative presentation groups, never occurrence/evidence deduplication.

Only groups the supplied preview sample. No numbering concordance, textual
variant normalization, or transitive work-equivalence inference is performed.
"""
from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

from .author_aliases import profile


def _exact(value):
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).split())


def _url(value):
    value = str(value or '')
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.netloc else ''
    except ValueError:
        return ''


def _upstream(record):
    # This field explicitly identifies the reproduced source page, unlike a
    # collection homepage or a guessed URL reconstructed from a fragment ID.
    metadata = record.get('metadata') or {}
    extra = metadata.get('ogc_extra') or {}
    return _url((extra.get('provenance') or {}).get('url'))


def _identity(record):
    author = profile(record.get('author', ''))
    values = tuple(_exact(record.get(key)) for key in
                   ('language', 'kind', 'quality', 'citation', 'text'))
    if not author or not record.get('id') or not all(values):
        return None
    metadata = record.get('metadata') or {}
    # A coarse citation can cover several explicitly labelled columns or
    # extents. Missing labels do not authorize merging with a labelled span.
    scope = tuple(_exact(metadata.get(key)) for key in (
        'source_section', 'source_citation_scheme', 'citation_scheme',
        'numbering_scheme', 'cited_edition_token'))
    line_scope = tuple((index, _exact(line.get('label')), _exact(line.get('section')))
                       for index, line in enumerate(record.get('lines') or [])
                       if _exact(line.get('label')) or _exact(line.get('section')))
    return (author['canonical'], *values, scope, line_scope)


def group_preview(records):
    """Return preview groups without changing or dropping any source records.

    A mirror's different work label can resolve through exactly one explicit
    provenance hop to direct records in this sample. All eligible direct
    targets must agree on their work label; otherwise that mirror is kept
    alone. Original mirror labels never serve as additional joining edges.
    """
    prepared = [(record, _identity(record), _exact(record.get('work')).casefold(),
                 _upstream(record)) for record in records]
    groups = []
    positions = {}
    for index, (record, identity, work, upstream) in enumerate(prepared):
        proof = {'method': 'same_printed_work_and_reference'}
        conflict = False
        if identity and upstream:
            targets = [(other, other_work) for other, other_identity, other_work, other_upstream in prepared
                       if not other_upstream and other_identity == identity and other_work
                       and _url(other.get('source_url')) == upstream]
            target_works = {other_work for _, other_work in targets}
            if len(target_works) == 1:
                work = next(iter(target_works))
                proof = {'method': 'explicit_one_hop_upstream_work',
                         'source_url': upstream,
                         'source_record_ids': sorted(other['id'] for other, _ in targets)}
            elif len(target_works) > 1:
                conflict = True
        key = (identity, work) if identity and work and not conflict else ('singleton', index)
        if key not in positions:
            positions[key] = len(groups)
            groups.append({'representative_id': record.get('id'), 'members': [],
                           'grouping_proofs': [],
                           'scope': 'Supplied occurrence preview only; identical full text and printed reference, not witness or numbering equivalence.'})
        group = groups[positions[key]]
        group['members'].append(record)
        group['grouping_proofs'].append({'record_id': record.get('id'), **proof})
    for group in groups:
        group['member_count'] = len(group['members'])
    return groups
