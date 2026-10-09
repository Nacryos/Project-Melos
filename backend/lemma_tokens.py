"""Word tokens of a stored passage text, with offsets, for the corpus headword index.

A token is a run of Greek letters and combining marks, possibly with editorial
brackets or underdots inside it and one final elision mark. Offsets are Python
code points in the unchanged ``passages.text``. The lookup spelling (``form``) is
the printed word without brackets and underdots, NFC, with the elision mark
written as U+2019 (the release N rule for /api/word). Nothing is restored.
"""
from __future__ import annotations

import re
import unicodedata

_GREEK = "Ͱ-ͳͶ-ͽͿ-ΆΈ-Ͽἀ-ᾼῂ-ῌῐ-Ίῠ-Ῥῲ-ῼ"
_MARKS = "̀-ͯ"
_EDITORIAL = r"\[\]⟦⟧⟨⟩〈〉<>{}"
_ELISION = "’'᾽ʼ᾿"
TOKEN = re.compile(f"[{_GREEK}{_MARKS}{_EDITORIAL}]*[{_GREEK}][{_GREEK}{_MARKS}{_EDITORIAL}]*[{_ELISION}]?")
_EDITORIAL_SIGNS = re.compile(f"[{_EDITORIAL}̣]")
LETTER = re.compile(f"[{_GREEK}]")


def clean_form(printed: str) -> str:
    """Lookup spelling: brackets and underdots removed, NFC, elision mark as U+2019."""
    text = _EDITORIAL_SIGNS.sub("", unicodedata.normalize("NFD", printed))
    text = unicodedata.normalize("NFC", text)
    if text and text[-1] in _ELISION:
        text = text[:-1] + "’"
    return text


def damaged(printed: str) -> bool:
    """Brackets or underdots inside the printed word (restored or uncertain letters)."""
    return bool(_EDITORIAL_SIGNS.search(unicodedata.normalize("NFD", printed)))


def word_tokens(text: str):
    """[(start, end, printed, form, damaged)] for every Greek word in ``text``."""
    out = []
    for match in TOKEN.finditer(text or ""):
        printed = match.group()
        # An edge bracket that opens or closes a gap with no letters of this word
        # stays outside the token's letters but inside its printed span.
        form = clean_form(printed)
        if not form or not LETTER.search(form):
            continue
        out.append((match.start(), match.end(), printed, form, damaged(printed)))
    return out


def fold(text: str) -> str:
    """Accent-, breathing- and case-free letters, final sigma folded (search key)."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in decomposed if unicodedata.category(c).startswith("L")).lower().replace("ς", "σ")


__all__ = ["word_tokens", "clean_form", "damaged", "fold", "TOKEN"]
