"""Lossy *search keys*, never replacements for an edition's printed text.

Unicode canonical decomposition: Unicode Standard Annex #15.
https://www.unicode.org/reports/tr15/
"""
import re
import unicodedata


def search_text(text):
    """Join explicit Greek line-end word divisions in a search-only copy.

    No lacunae, editorial brackets, spaces within a line, or uncertain letters
    are supplied. The source's printed text remains untouched. Only a hyphen
    immediately between Greek letters across one newline is removed; this is
    layout normalization, not a proposed reconstruction or dialect conversion.
    """
    text = unicodedata.normalize('NFC', str(text))
    greek = r'[\u0370-\u03ff\u1f00-\u1fff]'
    return re.sub(r'(' + greek + r')[-\u2010\u00ad][ \t]*\r?\n[ \t]*(?=' + greek + r')', r'\1', text)


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
