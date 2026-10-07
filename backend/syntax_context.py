"""Choose bounded, lossless source context for dependency predictions.

It selects source substrings only: it never normalizes, restores, or searches
for wording.
Blank lines are the only preferred boundary heuristic; otherwise neighboring
words are added by distance from the original selection (left wins ties).
"""
from __future__ import annotations

from copy import deepcopy
import re


def _utf16(text, position):
    return len(text[:position].encode('utf-16-le')) // 2


def syntax_context_window(full_text, start, end, *, max_words=80, max_characters=2000):
    """Return a source-exact codepoint window containing the entire selection.

    Limits count the reader's source word *segments*, including editorially
    interrupted pieces. A giant word may force a partial boundary; this is
    explicit, never a license to reconstruct it. Oversized selections fail.
    """
    # Lazy import avoids a cycle when PassageAnalysisService adopts this helper.
    from .passage_analysis import tokenize_span

    if not isinstance(full_text, str):
        raise ValueError('Source text must be a string')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(full_text):
        raise ValueError('Selection offsets must be forward source codepoint offsets')
    if type(max_words) is not int or type(max_characters) is not int or not 1 <= max_words <= 80 or not 1 <= max_characters <= 2000:
        raise ValueError('Context limits must be within 80 words and 2000 characters')
    words = [t for t in tokenize_span(full_text, 0, len(full_text)) if t['kind'] == 'word']

    def word_count(a, b):
        return sum(w['start'] < b and w['end'] > a for w in words)

    def fits(a, b):
        return b-a <= max_characters and word_count(a, b) <= max_words

    if not fits(start, end):
        raise ValueError('Selected source span exceeds the context limits')

    strategy = 'whole_passage'
    if fits(0, len(full_text)):
        a, b = 0, len(full_text)
    else:
        # Prefer an enclosing stanza only if both actual stanza boundaries fit.
        separators = list(re.finditer(r'\r?\n[^\S\r\n]*\r?\n', full_text))
        stanza_start, stanza_end = 0, len(full_text)
        for separator in separators:
            if separator.end() <= start:
                stanza_start = separator.end()
            elif separator.start() >= end:
                stanza_end = separator.start()
                break
        if separators and fits(stanza_start, stanza_end):
            a, b, strategy = stanza_start, stanza_end, 'enclosing_stanza'
        else:
            a, b, strategy = start, end, 'nearest_source_words'
            intersecting = [w for w in words if w['start'] < end and w['end'] > start]
            if intersecting:
                outer_a, outer_b = min(start, intersecting[0]['start']), max(end, intersecting[-1]['end'])
                if fits(outer_a, outer_b):
                    a, b = outer_a, outer_b
                else:
                    # Complete either boundary if both cannot fit together.
                    # Left-first tie breaking is deterministic and source-only.
                    if fits(outer_a, b):
                        a = outer_a
                    if fits(a, outer_b):
                        b = outer_b
            left = [w for w in words if w['end'] <= a]
            right = [w for w in words if w['start'] >= b]
            li, ri = len(left)-1, 0
            while li >= 0 or ri < len(right):
                options = []
                if li >= 0 and fits(left[li]['start'], b):
                    options.append((start-left[li]['end'], 0, left[li]['start'], b))
                if ri < len(right) and fits(a, right[ri]['end']):
                    options.append((right[ri]['start']-end, 1, a, right[ri]['end']))
                if not options:
                    break
                _, side, a, b = min(options)
                if side == 0:
                    li -= 1
                else:
                    ri += 1

    partial_start = any(w['start'] < a < w['end'] for w in words)
    partial_end = any(w['start'] < b < w['end'] for w in words)
    whole = a == 0 and b == len(full_text)
    warnings = [] if whole else [
        'Only this bounded source context was parsed; dependency attachments to words outside the context window cannot be resolved.'
    ]
    if partial_start or partial_end:
        warnings.append('A complete boundary word exceeds the context budget; the exact partial source text is preserved and its parse may be unreliable.')
    assert a <= start < end <= b and fits(a, b)
    return {'text': full_text[a:b], 'context_start': a, 'context_end': b,
            'context_start_utf16': _utf16(full_text, a), 'context_end_utf16': _utf16(full_text, b),
            'scope': 'whole_passage' if whole else 'bounded_context_window', 'strategy': strategy,
            'offset_unit': 'codepoint', 'word_count': word_count(a, b),
            'selection_start': start, 'selection_end': end,
            'selection_start_in_context': start-a, 'selection_end_in_context': end-a,
            'partial_start_word': partial_start, 'partial_end_word': partial_end,
            'warnings': warnings}


def project_syntax_tokens(tokens, window, full_text):
    """Copy provider tokens with validated absolute source and UTF-16 offsets.

    Repeated strings are never located using text search. Invalid provider
    offsets fail the whole projection, rather than binding another occurrence.
    """
    a, b = window.get('context_start'), window.get('context_end')
    start, end = window.get('selection_start'), window.get('selection_end')
    if (type(a) is not int or type(b) is not int or type(start) is not int or type(end) is not int
            or not 0 <= a <= start < end <= b <= len(full_text)
            or full_text[a:b] != window.get('text')):
        raise ValueError('Context does not match the exact source selection')
    if not isinstance(tokens, list):
        raise ValueError('Parser tokens must be a list')
    projected = []
    for source_token in tokens:
        if not isinstance(source_token, dict):
            raise ValueError('Parser token must be an object')
        begin, finish = source_token.get('start'), source_token.get('end')
        if (type(begin) is not int or type(finish) is not int
                or not 0 <= begin < finish <= b-a
                or full_text[a+begin:a+finish] != source_token.get('text')):
            raise ValueError('Parser offsets do not match the exact context source')
        token = deepcopy(source_token)
        token.update(absolute_start=a+begin, absolute_end=a+finish,
                     selected=a+begin < end and a+finish > start,
                     start_utf16=_utf16(full_text, a+begin), end_utf16=_utf16(full_text, a+finish))
        projected.append(token)
    return projected
