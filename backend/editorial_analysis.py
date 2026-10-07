"""Bounded source-only lookups conditional on printed editorial projections.

Callers supply the same read-only (form, passage_id) adapter as /api/word. This
module always passes an empty passage identity, never requests a machine fetch
or ranking, and never changes the original source token/claim inventory.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from .editorial_readings import editorial_readings
from .interlinear import candidate_identity, interlinear_reading


MAX_LOOKUPS = 26
_SOURCE_FIELDS = ('source', 'source_url', 'license', 'analysis_format', 'analysis_text',
                  'source_tags', 'match_kind', 'matched_form', 'matched_form_variants',
                  'gloss_source', 'gloss_source_url', 'gloss_license', 'gloss_entry_id',
                  'lexicon_entry_ids', 'claim_ids', 'entry_sense_claim_ids', 'raw_sha256')


def _source_candidate(candidate):
    if not isinstance(candidate, dict):
        return False
    if (candidate.get('quarantined') or candidate.get('source_consistent') is False
            or candidate.get('source_inconsistent')
            or candidate.get('assertion_type') == 'model_inference'
            or candidate.get('candidate_kind') == 'machine_analysis'
            or candidate.get('basis') == 'machine_analysis'):
        return False
    return not any(re.search(r'quarantin|inconsisten|rejected|needs_review|machine_proposed',
                            str(candidate.get(key, '')), re.I)
                   for key in ('status', 'quality', 'link_status', 'lemma_link_status'))


def _conditional_display(form, source):
    """Reuse literal dictionary rendering on a private virtual word only.

    Its offsets, source_candidate object, occurrence records and raw claims
    are never returned. Source-backed linked dictionary paths are revalidated
    by the existing interlinear projection before their meanings are admitted.
    """
    source_rows = [deepcopy(c) for c in source.get('candidates') or [] if _source_candidate(c)]
    contextual_rows = [deepcopy(c) for c in source.get('contextual_candidates') or [] if _source_candidate(c)]
    identities, collisions = {}, set()
    for candidate in [*source_rows, *contextual_rows]:
        identifier = candidate_identity(candidate)
        if identifier in identities and identities[identifier] != candidate:
            collisions.add(identifier)
        else:
            identities[identifier] = candidate
    # A shared transport ID cannot redirect one row's meaning to another row's
    # provenance. Retain unrelated rows, but fail closed on every colliding ID.
    source_rows = [c for c in source_rows if candidate_identity(c) not in collisions]
    contextual_rows = [c for c in contextual_rows if candidate_identity(c) not in collisions]
    token = {'id': 'editorial-virtual-word', 'text': form, 'kind': 'word',
             'start': 0, 'end': len(form), 'start_utf16': 0,
             'end_utf16': len(form.encode('utf-16-le'))//2,
             'source_candidates': source_rows, 'contextual_candidates': contextual_rows,
             'machine': {'status': 'not_requested', 'machine_candidates': []},
             'claim_applications': {}}
    # Needed only by pure source-validation/definition projectors. Do not
    # forward these records or any passage/occurrence context to the caller.
    for key in ('analysis_match_status', 'lexicon_entries', 'structured_evidence',
                'contextual_supporting_claims', 'linked_dictionary'):
        if key in source:
            token[key] = deepcopy(source[key])
    view = interlinear_reading({'selection': {'text': form, 'start': 0, 'end': len(form)},
                               'tokens': [token], 'syntax': {'state': 'unavailable', 'tokens': []},
                               'ranking': {'status': 'not_requested', 'items': []}})['readings'][0]['tokens'][0]
    by_id = {candidate_identity(c): c for c in [*source_rows, *contextual_rows]}
    meanings = []
    for item in view.get('candidate_meanings') or []:
        row = deepcopy(item)
        original = by_id.get(row['candidate_id']) or {}
        row['source_basis'] = row.pop('basis', None)
        row.update(basis='conditional_editorial_lookup', status='conditional_alternative',
                   word_attestation=False, occurrence_verified=False, raw_surface_match=False,
                   source_provenance={key: deepcopy(original[key]) for key in _SOURCE_FIELDS if key in original})
        meanings.append(row)
    display = {key: deepcopy(view.get(key)) for key in ('lemma', 'features', 'parse_short', 'gloss',
               'selection_basis', 'candidate_id', 'supporting_parse_candidate_ids') if key in view}
    return {'status': 'available' if meanings else 'unavailable', 'lookup_form': form,
            'lookup_scope': 'general_form_no_passage', 'analysis_basis': 'conditional_on_printed_editorial_reading',
            'word_attestation': False, 'occurrence_verified': False, 'raw_surface_match': False,
            'syntax_status': 'not_requested', 'ranking_status': 'not_requested',
            'display': display, 'candidate_meanings': meanings,
            'candidate_count': len(meanings),
            'rejected_candidate_identity_collisions': sorted(collisions),
            'source_lookup_warnings': deepcopy(source.get('warnings') or []),
            'candidates_with_parse_fields': sum(bool(c.get('features')) for c in meanings),
            'candidates_with_literal_meanings': sum(bool(c.get('gloss', {}).get('text') or c.get('gloss', {}).get('alternatives')) for c in meanings),
            'warnings': ['All alternatives depend on the printed editorial reading. They do not attest the original bracketed token or resolve its occurrence meaning.']}


def analyze_editorial_readings(passage, start, end, word_lookup, *, max_lookups=MAX_LOOKUPS):
    """Analyze only fully selected eligible editorial words; never expand silently.

    Partial intersections return expansion hints with no lookup. The callback
    must be a trusted source-only adapter; it is always called as (form, '').
    Repeated forms share one result, including failures, within this request.
    Every skipped row remains explicit, including exhausted-budget rows.
    """
    if not isinstance(passage, dict) or not isinstance(passage.get('text'), str):
        raise ValueError('An exact source passage is required')
    text = passage['text']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError('Selection must be a forward span of source codepoint offsets')
    if type(max_lookups) is not int or not 0 <= max_lookups <= MAX_LOOKUPS:
        raise ValueError('Editorial lookup budget must be between 0 and 26')
    if not callable(word_lookup):
        raise ValueError('A trusted source-only word adapter is required')
    projected = editorial_readings(passage)
    selected, hints = [], []
    for source_row in projected['rows']:
        if source_row['start'] >= end or source_row['end'] <= start:
            continue
        row = deepcopy(source_row)
        if not start <= row['start'] < row['end'] <= end:
            row.update(selection_relation='partial_intersection', lookup_status='not_requested_partial_selection',
                       expansion_note='Select the complete original bracketed word to request its conditional editorial analysis.')
            hints.append(row)
        else:
            row['selection_relation'] = 'fully_contained'
            selected.append(row)
    cache, calls = {}, 0
    for row in selected:
        row['analysis'] = {'status': 'not_requested', 'candidate_meanings': [], 'candidate_count': 0}
        if not row['lookup_eligible']:
            row['lookup_status'] = 'ineligible_projection'
            continue
        form = row['projected_text']
        if form not in cache:
            if calls >= max_lookups:
                row['lookup_status'] = 'request_limit'
                continue
            calls += 1
            try:
                source = word_lookup(form, '')
                if not isinstance(source, dict):
                    raise ValueError('Source adapter did not return an object')
                cache[form] = _conditional_display(form, source)
            except Exception:
                cache[form] = {'status': 'lookup_failed', 'candidate_meanings': [], 'candidate_count': 0,
                               'error_code': 'source_lookup_failed',
                               'warnings': ['Conditional source lookup failed; no replacement meaning or parse was invented.']}
        row['analysis'] = deepcopy(cache[form])
        row['lookup_status'] = 'lookup_failed' if row['analysis']['status'] == 'lookup_failed' else 'complete'
    eligible = sum(row['lookup_eligible'] for row in selected)
    complete = sum(row['lookup_status'] == 'complete' for row in selected)
    skipped = {}
    for row in selected:
        if row['lookup_status'] != 'complete':
            skipped[row['lookup_status']] = skipped.get(row['lookup_status'], 0)+1
    return {'version': 1, 'status': 'available' if selected else 'partial_selection' if hints else 'not_applicable',
            'scope': 'conditional_editorial_readings', 'passage_id': passage['id'],
            'source_text_sha256': projected['source_text_sha256'],
            'selection': {'start': start, 'end': end, 'offset_unit': 'codepoint',
                          'text_sha256': hashlib.sha256(text[start:end].encode()).hexdigest()},
            'rows': selected, 'selection_expansion_hints': hints,
            'counts': {'fully_contained': len(selected), 'eligible': eligible, 'processed': complete,
                       'skipped': len(selected)-complete, 'skipped_by_reason': skipped,
                       'partial_intersections': len(hints)},
            'limits': {'max_lookups': max_lookups, 'lookups': calls, 'machine_fetches': 0},
            'ranking_status': 'not_requested',
            'scope_note': 'Separate conditional analysis of explicitly printed editorial letters; original passage, selections, tokens, and source claims are unchanged.'}
