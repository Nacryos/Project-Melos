"""The literary dialect a passage is written in (release R).

Used as context for ranking parses and as a calibration feature, never as proof that a word belongs to that
dialect. The table is the conventional one (Campbell, Greek Lyric Poetry (1967), introductions to each
poet; Buck, The Greek Dialects, pp. 14-16): Sappho and Alcaeus write Lesbian Aeolic; Alcman Laconian Doric;
the choral poets, the bucolic poets and Epicharmus a literary Doric; Corinna Boeotian. Homer, Hesiod and the
Ionic and Attic poets are "other": their texts carry no dialect rule here.
"""
from __future__ import annotations

import unicodedata

LESBIAN = "lesbian"
DORIC = "doric"
BOEOTIAN = "boeotian"

_POETS = {
    LESBIAN: ("sappho", "sapho", "σαπφω", "ψαπφω", "alcaeus", "alkaios", "alcaeus of mytilene", "αλκαιος"),
    DORIC: ("alcman", "αλκμαν", "pindar", "pindarus", "πινδαρος", "bacchylides", "βακχυλιδης", "stesichorus",
            "στησιχορος", "ibycus", "ιβυκος", "theocritus", "theocritus-bucolic", "θεοκριτος", "bion",
            "bion-bucolic", "moschus", "epicharmus", "timocreon", "praxilla", "pratinas"),
    BOEOTIAN: ("corinna", "κοριννα"),
}
_LOOKUP = {name: dialect for dialect, names in _POETS.items() for name in names}
# Collections named in passage ids (campbell-glp:<poet>:<number>, cgl-anthology:<poet>:...).
_ID_POETS = {name for names in _POETS.values() for name in names if name.isascii() and " " not in name}


def _key(text):
    text = unicodedata.normalize("NFD", str(text or "")).casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def passage_dialect(passage):
    """'lesbian', 'doric', 'boeotian' or None for a passage dict (author label, id)."""
    if not isinstance(passage, dict):
        return None
    if "dialect" in passage:
        # Release U: a draft text (POST /api/analyze-text) names its dialect; "ionic", "attic" or "epic" carry
        # no dialect rule here, as for an Ionic or Attic poet. Otherwise its author hint decides, as below.
        hint = _key(passage.get("dialect"))
        if hint in (LESBIAN, DORIC, BOEOTIAN):
            return hint
        if hint:
            return None
    try:
        from .author_aliases import canonical
        names = [passage.get("author"), canonical(passage.get("author") or "")]
    except Exception:  # noqa: BLE001 - the alias table is optional here
        names = [passage.get("author")]
    for name in names:
        dialect = _LOOKUP.get(_key(name))
        if dialect:
            return dialect
    for part in str(passage.get("id") or "").split(":")[1:2]:
        if _key(part) in _ID_POETS:
            return _LOOKUP[_key(part)]
    return None


def dialect_labels(dialect):
    """The Morpheus `dial` label words that name the passage dialect."""
    return {LESBIAN: ("aeolic", "lesbian"), DORIC: ("doric", "laconia"), BOEOTIAN: ("boeot", "aeolic")}.get(dialect, ())


__all__ = ["passage_dialect", "dialect_labels", "LESBIAN", "DORIC", "BOEOTIAN"]
