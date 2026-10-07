"""Conditional word-local projections of explicitly printed editorial letters.

No integration, lookup, normalization, restoration, or new linguistic data is
performed here. The accepted Campbell artifact is the source of every emitted
character. Only paired square brackets within one uninterrupted orthographic
run may be omitted in the parallel projection. Original text remains primary.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import unicodedata


APOSTROPHES = frozenset("'\u2019\u02bc\u1fbd")
UNSUPPORTED_MARKS = frozenset('<>⟨⟩⟦⟧†‡…')
BOUNDARY_MARKS = frozenset('[]') | UNSUPPORTED_MARKS

# Reviewed safety metadata, never replacement Greek. The two ranges correspond
# to the possible omitted mu/phi underdots in the accepted 34a line-3 audit note.
# Both the source text and exact uncertainty-note list must match this receipt.
# A changed/unrecognized uncertainty note disables all affected-record lookups
# until its scope is independently reviewed; it never reuses these offsets.
_REVIEWED_UNCERTAINTY = {
    ('campbell-glp:alcaeus:34a',
     '7cae61943576b9ec55cb1a71e648090875df1fe89cc3a3cca06fe141c701ca97',
     'b80da0f74ffb097f7972470da06a37ae06cc19ee92552892f41dd2da0f9be930'):
        ((78, 84), (85, 96)),
}


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _utf16(text, offset):
    return len(text[:offset].encode('utf-16-le')) // 2


def _word_character(char):
    return unicodedata.category(char)[0] in 'LM' or char in APOSTROPHES or char in BOUNDARY_MARKS


def _runs(text):
    cursor = 0
    while cursor < len(text):
        if not _word_character(text[cursor]):
            cursor += 1
            continue
        start = cursor
        while cursor < len(text) and _word_character(text[cursor]):
            cursor += 1
        if any(unicodedata.category(c).startswith('L') for c in text[start:cursor]):
            yield start, cursor


def _project(text, start, end, max_word_characters):
    raw = text[start:end]
    errors = []
    if len(raw) > max_word_characters:
        return None, [], [], ['source_word_character_limit']
    if any(c in UNSUPPORTED_MARKS for c in raw):
        errors.append('unsupported_or_uncertain_editorial_marks')
    if '\u0323' in unicodedata.normalize('NFD', raw):
        errors.append('printed_uncertain_letter')
    if any(c not in APOSTROPHES and unicodedata.category(c).startswith('L') and 'GREEK' not in unicodedata.name(c, '') for c in raw):
        errors.append('non_greek_letter')
    opened = None
    pairs, mapping, output = [], [], []
    for offset in range(start, end):
        char = text[offset]
        if char == '[':
            if opened is not None:
                errors.append('nested_square_brackets')
            else:
                opened = offset
        elif char == ']':
            if opened is None:
                errors.append('unmatched_closing_bracket')
            else:
                inside = text[opened+1:offset]
                if not any(c not in APOSTROPHES and unicodedata.category(c).startswith('L') for c in inside):
                    errors.append('no_printed_letter_in_brackets')
                pairs.append({'open': opened, 'close': offset})
                opened = None
        else:
            mapping.append({'projected_start': len(output), 'projected_end': len(output)+1,
                            'source_start': offset, 'source_end': offset+1,
                            'source_start_utf16': _utf16(text, offset),
                            'source_end_utf16': _utf16(text, offset+1),
                            'printed_inside_square_brackets': opened is not None})
            output.append(char)
    if opened is not None:
        errors.append('unmatched_opening_bracket')
    if not pairs:
        errors.append('no_complete_square_bracket_pair')
    projected = ''.join(output)
    if not projected or projected[0] in APOSTROPHES or not unicodedata.category(projected[0]).startswith('L'):
        errors.append('no_initial_base_letter')
    # There is deliberately no transliteration or case/accent normalization.
    # No partial projection is usable when any structure check fails.
    return (None, [], [], list(dict.fromkeys(errors))) if errors else (projected, mapping, pairs, [])


def editorial_readings(passage, *, max_word_characters=200):
    """Return diagnostic rows without changing the passage or adding claims.

    ``lookup_eligible`` only admits a conditional lookup of printed letters.
    It is not a claim that the reading, lemma, morphology, or English meaning
    is correct. Uncertain projections may be displayed but cannot be looked up
    through this eligibility flag. Returned offsets always address raw source.
    """
    if not isinstance(passage, dict) or not isinstance(passage.get('text'), str):
        raise ValueError('A passage with exact source text is required')
    if not isinstance(passage.get('id'), str) or not passage['id'].strip():
        raise ValueError('A stable source passage identity is required')
    if type(max_word_characters) is not int or not 1 <= max_word_characters <= 2000:
        raise ValueError('Word projection limit must be between 1 and 2000 characters')
    metadata = passage.get('metadata')
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError('Source metadata must be an object')
    text, passage_id = passage['text'], passage.get('id')
    source_hash = _sha(text)
    notes = metadata.get('transcription_uncertainty', [])
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise ValueError('Source uncertainty notes must be a list of literal source strings')
    note_hash = _sha(json.dumps(notes, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    reviewed_ranges = (_REVIEWED_UNCERTAINTY.get((passage_id, source_hash, note_hash))
                       if passage.get('source') == 'campbell_assignment' else None)
    known_uncertain_passage = any(key[0] == passage_id for key in _REVIEWED_UNCERTAINTY)
    rows = []
    for start, end in _runs(text):
        raw = text[start:end]
        if '[' not in raw and ']' not in raw:
            continue
        projected, mapping, pairs, structural_errors = _project(text, start, end, max_word_characters)
        uncertainty = []
        if notes or known_uncertain_passage:
            if reviewed_ranges is None:
                uncertainty.append('unscoped_or_changed_source_metadata_uncertainty')
            elif any(a < end and b > start for a,b in reviewed_ranges):
                uncertainty.append('reviewed_source_metadata_uncertainty')
        eligible = not structural_errors and not uncertainty
        rows.append({'id': f'{passage_id}@{start}:{end}:editorial',
                     'passage_id': passage_id, 'start': start, 'end': end,
                     'start_utf16': _utf16(text, start), 'end_utf16': _utf16(text, end),
                     'original_text': raw, 'original_text_sha256': _sha(raw),
                     'source_text_sha256': source_hash,
                     'source_url': passage.get('source_url'), 'edition': passage.get('edition'),
                     'source_raw_sha256': passage.get('raw_sha256'),
                     'source_pdf_sha256': metadata.get('source_pdf_sha256'),
                     'projected_text': projected, 'character_source_map': mapping,
                     'square_bracket_pairs': pairs,
                     'status': 'unavailable' if structural_errors else
                               'uncertain_editorial_reading' if uncertainty else 'conditional_editorial_reading',
                     'evidence_type': 'printed_editorial_projection',
                     'lookup_eligible': eligible, 'word_attestation': False, 'line_attestation': False,
                     'occurrence_verified': False, 'raw_surface_match': False,
                     'analysis_basis': 'conditional_on_printed_editorial_reading',
                     'structural_errors': structural_errors, 'uncertainty_reasons': uncertainty,
                     'source_uncertainty_notes': deepcopy(notes),
                     'uncertainty_note_sha256': note_hash,
                     'scope_note': 'Printed editorial letters projected for conditional lookup; not an attested raw word or a verified grammatical or English reading.'})
    return {'version': 1, 'passage_id': passage_id, 'source_text_sha256': source_hash,
            'rows': rows, 'structurally_projectable': sum(r['projected_text'] is not None for r in rows),
            'lookup_eligible': sum(r['lookup_eligible'] for r in rows),
            'uncertain_projectable': sum(r['status']=='uncertain_editorial_reading' for r in rows)}
