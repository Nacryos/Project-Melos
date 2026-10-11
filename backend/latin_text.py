"""Latin text normalisation for the corpus partition, the attestation index and the lint bank.

normalize_la: lower case, combining marks (macrons, breves, diaereses) stripped, ligatures expanded, v -> u, j -> i,
so a typed 'Vivamus' and an edition's 'uiuamus' meet. tokenize_la: runs of letters (with inner apostrophes) in order.
"""
from __future__ import annotations

import re
import unicodedata

_LIG = {"æ": "ae", "œ": "oe", "Æ": "ae", "Œ": "oe"}
_WORD = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]+(?:['’][A-Za-z]+)?")


def normalize_la(text: str) -> str:
    t = "".join(_LIG.get(ch, ch) for ch in unicodedata.normalize("NFD", str(text or "")).lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.replace("v", "u").replace("j", "i")


def tokenize_la(text: str) -> list[str]:
    return [m.group(0) for m in _WORD.finditer(str(text or ""))]
