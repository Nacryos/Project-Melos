"""Lossy *search keys*, never replacements for an edition's printed text.

Unicode canonical decomposition: Unicode Standard Annex #15.
https://www.unicode.org/reports/tr15/
"""
import re
import unicodedata


def search_text(text):
    """Join explicit Greek line-end word divisions in a search-only copy.

    A maximal chain is checked as a whole before removing any divisions. A
    damaged outer component or uncertain letter rejects the entire chain; a
    plausible-looking suffix is not salvaged. Printed terminal elision/psili
    stays literal. This is layout normalization, never a reconstruction.

    Only a search copy changes. The lexer and disjoint chain/edge scans are
    linear in source length; no per-word copies of the whole prefix/suffix.
    """
    text = unicodedata.normalize('NFC', str(text))
    if '\n' not in text or not any(sign in text for sign in _DIVISION_SIGNS):
        return text
    words = _literal_greek_spans(text)
    removals = []
    index = 0
    while index < len(words):
        end = index
        while end + 1 < len(words) and _LINE_DIVISION.fullmatch(text, words[end][1], words[end + 1][0]):
            end += 1
        if end > index:
            first, last = words[index][0], words[end][1]
            before = first
            while before and not text[before - 1].isspace():
                before -= 1
            after = last
            while after < len(text) and not text[after].isspace():
                after += 1
            safe = (not _EDITORIAL_EDGE.search(text, before, first)
                    and not _EDITORIAL_EDGE.search(text, last, after)
                    and not _DOTTED_GAP.match(text, last)
                    and not _orphan_division_before(text, first)
                    and all('\u0323' not in text[start:stop] for start, stop in words[index:end + 1])
                    and all(_greek_letter(text[words[i][1] - 1]) for i in range(index, end)))
            if safe:
                removals.extend((words[i][1], words[i + 1][0]) for i in range(index, end))
        # Advance on rejection too: never retry the same chain's clean suffix.
        index = end + 1
    result, previous = [], 0
    for start, stop in removals:
        result.append(text[previous:start])
        previous = stop
    result.append(text[previous:])
    return ''.join(result)


_DIVISION_SIGNS = '-\u2010\u00ad'
_LINE_DIVISION = re.compile(r'[-\u2010\u00ad][ \t]*\r?\n[ \t]*')
_EDITORIAL_EDGE = re.compile(r'[\[\]<>\{\}⟨⟩〈〉‹›⟦⟧⸢⸣⸤⸥†‡…\u0323\u2010\u00ad-]|\.{2,}')
_DOTTED_GAP = re.compile(r'\.(?:[ \t]*\.)+')
_JOIN_SIGNS = "'\u2019\u1fbd\u02bc\u1fbf"


def _greek_letter(char):
    return unicodedata.category(char).startswith('L') and 'GREEK' in unicodedata.name(char, '')


def _literal_greek_spans(text):
    """Literal word spans; mixed-script units cannot donate a Greek suffix."""
    spans, start, end, mixed = [], None, 0, False
    for offset, char in enumerate(text):
        if char in _JOIN_SIGNS:
            if start is not None:
                end = offset + 1
                following = text[end:end + 1]
                if not following or following in _JOIN_SIGNS or not unicodedata.category(following).startswith('L'):
                    if not mixed:
                        spans.append((start, end))
                    start, mixed = None, False
        elif unicodedata.category(char).startswith('L'):
            if start is None:
                start = offset
            end = offset + 1
            mixed = mixed or not _greek_letter(char)
        elif unicodedata.category(char).startswith('M'):
            if start is not None:
                end = offset + 1
        elif start is not None:
            if not mixed:
                spans.append((start, end))
            start, mixed = None, False
    if start is not None and not mixed:
        spans.append((start, end))
    return spans


def _orphan_division_before(text, start):
    """A skipped non-Greek/damaged component must not enable suffix salvage."""
    cursor = start
    while cursor and text[cursor - 1] in ' \t':
        cursor -= 1
    if not cursor or text[cursor - 1] != '\n':
        return False
    cursor -= 1
    if cursor and text[cursor - 1] == '\r':
        cursor -= 1
    while cursor and text[cursor - 1] in ' \t':
        cursor -= 1
    return bool(cursor and text[cursor - 1] in _DIVISION_SIGNS)


def normalize(text):
    # lower(), not casefold(): casefold promotes Greek iota subscript to a
    # spacing iota before we can fold diacritics, making accented and unaccented
    # query keys inconsistent with the morphology index.
    text = unicodedata.normalize('NFD', str(text).lower())
    return ''.join(c for c in text if not unicodedata.combining(c)).translate(str.maketrans({'ς':'σ','ϲ':'σ','Ϲ':'σ','’':"'",'᾽':"'",'ʼ':"'"}))


def tokenize(text):
    r"""Keep combining marks and attached apostrophes with their letters.

    Python's Unicode \w excludes combining marks. Using it alone splits
    uncertain Greek words into spurious fragments. Marks remain in the surface
    token; only normalize() produces the separate lossy lookup key. U+1FBF
    spacing psili is retained as a DISTINCT printed sign, never folded to an
    apostrophe or used to supply an ending. A terminal
    apostrophe is a printed sign, not permission to supply an elided vowel.
    Adjacent quotation/apostrophe signs are preserved conservatively without
    guessing their editorial function; orphan signs are not word tokens.
    """
    text = unicodedata.normalize('NFC', text)
    tokens, current = [], []
    for index, char in enumerate(text):
        # U+02BC is a Unicode letter: test this branch BEFORE the base class so
        # all four known apostrophe glyphs have the same boundary behavior.
        if char in _WORD_SIGNS:
            if current:
                current.append(char)
                if index + 1 == len(text) or text[index + 1] in _WORD_SIGNS or not _WORD_BASE.fullmatch(text[index + 1]):
                    tokens.append(''.join(current))
                    current = []
        elif _WORD_BASE.fullmatch(char):
            current.append(char)
        elif current and unicodedata.category(char).startswith('M'):
            current.append(char)
        elif current:
            tokens.append(''.join(current))
            current = []
    if current:
        tokens.append(''.join(current))
    return tokens


_WORD_BASE = re.compile(r"[^\W\d_]", re.UNICODE)
_WORD_SIGNS = "’'᾽ʼ᾿"


def text_key(language, kind, text):
    """Identity of one text copy: same words, language and record kind.

    Mirrors of one edition (an aggregator copy of a Perseus or DCC text) share
    this key and are grouped in search. Distinct editions with identical words
    also share it; the reader lists the collapsed copies so nothing is hidden.
    The key is a search-grouping device, never a claim about witnesses.
    """
    import hashlib
    collapsed = ' '.join(unicodedata.normalize('NFC', str(text)).split())
    return hashlib.sha1(f'{language}\x1f{kind}\x1f{collapsed}'.encode('utf-8')).hexdigest()[:24]
