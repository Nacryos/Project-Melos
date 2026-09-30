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
    r"""Keep combining marks with their letters, including editorial underdots.

    Python's Unicode \w excludes combining marks. Using it alone splits
    uncertain Greek words into spurious fragments. Marks remain in the surface
    token; only normalize() produces the separate lossy lookup key.
    """
    text = unicodedata.normalize('NFC', text)
    tokens, current = [], []
    for index, char in enumerate(text):
        if _WORD_BASE.fullmatch(char):
            current.append(char)
        elif current and unicodedata.category(char).startswith('M'):
            current.append(char)
        elif current and char in "’'᾽" and index + 1 < len(text) and _WORD_BASE.fullmatch(text[index + 1]):
            current.append(char)
        elif current:
            tokens.append(''.join(current))
            current = []
    if current:
        tokens.append(''.join(current))
    return tokens


_WORD_BASE = re.compile(r"[^\W\d_]", re.UNICODE)
