"""Literal source-heading retrieval cues, never commentary alignment claims.

No heading, gloss, or lexical association is authored here. Matches are exact
codepoint strings at whole-word boundaries; accents, quantity and diaeresis
are never removed. Printed note groups are source layout, not poem line spans.
"""
from copy import deepcopy
import hashlib
import unicodedata

from .edition_commentary import DATA_SHA256, for_passage

VERSION = 'literal-commentary-heading-cues-v1'
MAX_WINDOW_CHARACTERS = 1600
MAX_HEADING_CHARACTERS = 160
MAX_MATCHES = 24
_JOINERS = frozenset("'’᾽‐‑-[]⟦⟧⟨⟩<>")
_DAMAGE = frozenset('[]⟦⟧⟨⟩<>…†‡\u0323')


def _word_character(char):
    return unicodedata.category(char)[0] in {'L', 'M', 'N'} or char in _JOINERS


def _exact_spans(text, heading, start, end):
    """Literal matching only; return original source codepoint offsets."""
    cursor = start
    while cursor < end:
        at = text.find(heading, cursor, end)
        if at < 0:
            return
        stop = at + len(heading)
        cursor = at + 1
        if (at == 0 or not _word_character(text[at - 1])) and (stop == len(text) or not _word_character(text[stop])):
            yield at, stop


def _window(text, start, end):
    lines, cursor = [], 0
    for line in text.splitlines(keepends=True):
        stop = cursor + len(line)
        if line.strip():
            lines.append((cursor, stop))
        cursor = stop
    containing = next((index for index, (a, b) in enumerate(lines) if a <= start < end <= b), None)
    if containing is None:
        return None
    return lines[max(0, containing - 1)][0], lines[min(len(lines) - 1, containing + 1)][1]


def _groups(paragraphs):
    """Keep contiguous printed-note groups; never equate labels with offsets."""
    groups, previous = [], None
    for row in paragraphs:
        label = row.get('anchor_line_label')
        if not label:
            previous = None
            continue
        if (previous is None or previous['printed_anchor_label'] != label
                or row['ordinal'] != previous['paragraph_ordinals'][-1] + 1):
            previous = {'printed_anchor_label': label, 'paragraph_ordinals': [], 'printed_pages': []}
            groups.append(previous)
        previous['paragraph_ordinals'].append(row['ordinal'])
        if row['printed_page'] not in previous['printed_pages']:
            previous['printed_pages'].append(row['printed_page'])
    return groups


def retrieval_cues(passage, target, *, commentary=None):
    """Revalidate the approved local source before deriving optional cues.

    Passing a source view is an equality check, not an authority to manufacture
    headings. Unsupported editions return None; failed source identity returns
    an explicit unavailable cue status. Full commentary must remain available.
    """
    rebuilt = for_passage(passage, for_model=True)
    if rebuilt is None:
        return None
    base = {'method': VERSION, 'scope': 'source_heading_retrieval_not_occurrence_alignment',
            'selection_aligned': False, 'word_attestation': False, 'line_attestation': False,
            'source_commentary_sha256': DATA_SHA256}
    def unavailable(reason):
        return {**base, 'status': 'unavailable', 'reason': reason, 'matches': [], 'note_groups': []}
    if rebuilt.get('status') != 'available' or commentary is not None and commentary != rebuilt:
        return unavailable('Approved commentary source identity differs or is unavailable.')
    text = passage.get('text')
    a, b = target.get('start'), target.get('end')
    if (not isinstance(text, str) or type(a) is not int or type(b) is not int
            or not 0 <= a < b <= len(text) or text[a:b] != target.get('text')
            or any(c.isspace() or c in _DAMAGE for c in text[a:b])
            or not any('GREEK' in unicodedata.name(c, '') and unicodedata.category(c).startswith('L') for c in text[a:b])
            or target.get('partial_word') or target.get('editorial_fragment')
            or target.get('status') == 'partial_word' or target.get('selection_basis') == 'partial_word'
            or (a > 0 and _word_character(text[a - 1])) or (b < len(text) and _word_character(text[b]))):
        return unavailable('Target is not a complete literal source occurrence.')
    window = _window(text, a, b)
    if window is None or window[1] - window[0] > MAX_WINDOW_CHARACTERS:
        return unavailable('Literal local-line retrieval window exceeds cue bounds.')
    paragraphs = rebuilt['paragraphs']
    matches = []
    for row in paragraphs:
        heading = row.get('lemma')
        if (not isinstance(heading, str) or not heading or len(heading) > MAX_HEADING_CHARACTERS
                or not any('GREEK' in unicodedata.name(c, '') and unicodedata.category(c).startswith('L') for c in heading)):
            continue
        for start, end in _exact_spans(text, heading, *window):
            relation = ('exact_target_surface' if (start, end) == (a, b) else
                        'target_within_heading_phrase' if start <= a < b <= end else 'neighbor_surface')
            matches.append({'paragraph_ordinal': row['ordinal'], 'printed_heading': heading,
                'matched_surface': text[start:end], 'matched_start': start, 'matched_end': end,
                'relation_to_target': relation, 'printed_page': row['printed_page'],
                'printed_line_label': row.get('line_label'), 'printed_anchor_label': row.get('anchor_line_label'),
                'source_anchor_method': row.get('anchor_method'), 'citation': row.get('citation'),
                'source_field': 'paragraphs[ordinal=' + str(row['ordinal']) + '].lemma'})
            if len(matches) > MAX_MATCHES:
                return unavailable('Complete heading-match set exceeds cue bounds; no matches were selected.')
    matched_ordinals = {row['paragraph_ordinal'] for row in matches}
    groups = [group for group in _groups(paragraphs) if matched_ordinals.intersection(group['paragraph_ordinals'])]
    return {**base, 'status': 'available', 'commentary_id': rebuilt['commentary_id'],
            'source_pdf_sha256': rebuilt['source_pdf_sha256'],
            'passage_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'target_occurrence': {'text': target['text'], 'start': a, 'end': b},
            'window': {'start': window[0], 'end': window[1], 'offset_unit': 'codepoint',
                       'rule': 'target_nonempty_source_line_and_one_neighboring_nonempty_line_each_side'},
            'matches': matches, 'note_groups': deepcopy(groups),
            'scope_note': 'Literal heading matches indicate retrieval relevance only. Neighbor headings concern other words; same printed note-group membership does not establish occurrence alignment or a target gloss. Retain the complete source commentary and all lexical alternatives.'}
