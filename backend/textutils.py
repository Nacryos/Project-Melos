"""Lossy *search keys*, never replacements for an edition's printed text.

Unicode canonical decomposition: Unicode Standard Annex #15.
https://www.unicode.org/reports/tr15/
"""
import re
import unicodedata


def normalize(text):
    # lower(), not casefold(): casefold promotes Greek iota subscript to a
    # spacing iota before we can fold diacritics, making accented and unaccented
    # query keys inconsistent with the morphology index.
    text = unicodedata.normalize('NFD', str(text).lower())
    return ''.join(c for c in text if not unicodedata.combining(c)).translate(str.maketrans({'ς':'σ','ϲ':'σ','Ϲ':'σ','’':"'",'᾽':"'",'ʼ':"'"}))


def tokenize(text):
    return re.findall(r"[^\W\d_]+(?:[’'᾽][^\W\d_]+)*", unicodedata.normalize('NFC', text), re.UNICODE)
