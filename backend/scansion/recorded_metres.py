"""Recorded metres of stored poems (release V). The corpus records no metre, so this is a short, sourced table;
the metre lock (lock.py) applies only to poems listed here, and only to lines the scanner can parse in it.
Nothing is guessed from the scan.
"""
from __future__ import annotations

import re
import unicodedata

RECORDS = [
    {"id": "sappho-book-1", "metre": "sapphic", "label": "Sapphic stanza",
     "source": "Sappho, Book 1 of the Alexandrian edition: poems in Sapphic stanzas, frr. 1–42 "
               "(Lobel–Page and Voigt numbering; D. A. Campbell, Greek Lyric I, Loeb 1982, introduction)"},
    {"id": "epic-hexameter", "metre": "hexameter", "label": "dactylic hexameter",
     "source": "Homer, Iliad and Odyssey; Hesiod, Theogony and Works and Days: epic hexameter"},
]
_BY_ID = {r["id"]: r for r in RECORDS}


def _key(text) -> str:
    text = unicodedata.normalize("NFD", str(text or "")).casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def _number(passage: dict) -> int | None:
    """The fragment number when the citation is a bare whole number ("16", "Fragment 16", id ...:fr16:1)."""
    for value in (passage.get("citation"), passage.get("work")):
        m = re.fullmatch(r"(?:fr(?:agment|\.)?\s*)?(\d{1,3})", _key(value))
        if m:
            return int(m.group(1))
    m = re.search(r":(?:fr|frag-[\d-]+:)?(\d{1,3})(?::\d+)?$", str(passage.get("id") or ""))
    return int(m.group(1)) if m else None


def recorded_metre(passage: dict) -> dict | None:
    author = _key(passage.get("author_canonical") or passage.get("author"))
    work = _key(passage.get("work"))
    if author in ("sappho", "σαπφω"):
        n = _number(passage)
        if n is not None and 1 <= n <= 42:
            return _BY_ID["sappho-book-1"]
    if author in ("homer", "ομηρος") and any(w in work for w in ("iliad", "odyssey", "ιλιας", "οδυσσεια")):
        return _BY_ID["epic-hexameter"]
    if author in ("hesiod", "ησιοδος") and any(w in work for w in ("theogony", "works and days", "θεογονια", "εργα")):
        return _BY_ID["epic-hexameter"]
    return None
