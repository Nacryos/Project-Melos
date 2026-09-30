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
    return re.findall(r"[^\W\d_]+(?:[’'᾽][^\W\d_]+)*", unicodedata.normalize('NFC', text), re.UNICODE)
