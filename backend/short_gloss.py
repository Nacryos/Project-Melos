"""Dictionary order and short head phrases for source definitions.

Nothing here writes English. ``short_head`` only cuts a source definition at
a printed delimiter or before a modifier word, keeping the dictionary's own
words in their order; a hard cut is marked with an ellipsis. Which dictionary
supplies the short gloss is a fixed, documented order, not a judgement about
the passage.
"""
from __future__ import annotations

import re
import unicodedata

# Order in which dictionaries are shown and tried for the short gloss.
# Middle Liddell and Autenrieth print short school-dictionary heads; the full
# LSJ follows (Logeion's corrected edition before the Perseus text it
# supersedes); Cunliffe (Homeric) next; Dodson (New Testament) last.
DICTIONARY_ORDER = (
    "Perseus Middle Liddell TEI (Hopper open-source texts)",
    "Perseus Autenrieth TEI via Homerica",
    "LSJ (Logeion edition, H. Dik) TEI",
    "PerseusDL LSJ TEI",
    "Perseus Cunliffe TEI via Homerica",
    "Dodson Greek Lexicon (NT; public domain)",
)
DICTIONARY_LABELS = {
    "Perseus Middle Liddell TEI (Hopper open-source texts)": "Middle Liddell",
    "Perseus Autenrieth TEI via Homerica": "Autenrieth",
    "LSJ (Logeion edition, H. Dik) TEI": "LSJ (Logeion)",
    "PerseusDL LSJ TEI": "LSJ",
    "Perseus Cunliffe TEI via Homerica": "Cunliffe",
    "Dodson Greek Lexicon (NT; public domain)": "Dodson (NT)",
}
_RANK = {source: index for index, source in enumerate(DICTIONARY_ORDER)}


def dictionary_rank(source: str | None) -> int:
    return _RANK.get(source or "", len(DICTIONARY_ORDER))


# An entry that defines a letter of the alphabet or its numeral value
# ("fifth letter of the Gr. alphabet: as numeral ..."). Matched on the source
# entry's own opening words only.
LETTER_OR_NUMERAL = re.compile(
    r"\b(?:letter\s+of\s+the\s+(?:Gr\.|Greek)\s+alphabet|letter\s+of\s+the\s+alphabet|as\s+(?:a\s+)?numeral)",
    re.I)
NON_NUMERAL_POS = {"PART", "CCONJ", "SCONJ", "ADV", "ADP", "DET", "PRON", "VERB", "NOUN", "ADJ", "INTJ"}


def letter_or_numeral_entry(entry: dict) -> bool:
    opening = str(entry.get("rendered_entry_text") or entry.get("entry_text") or "")[:220]
    return bool(LETTER_OR_NUMERAL.search(opening))


_WORDS = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# Only articles: "and", "or", "in", "on" are real glosses (τε, ἤ, ἐν, ἐπί).
_STOP = {"a", "an", "the"}
# Words that open a modifier after the head phrase: relatives, prepositions
# (not "of", which belongs to the head: "piece of land"), participles in -ed /
# -ing and a few irregular past participles common in definitions.
_BREAK = {"which", "that", "who", "whom", "whose", "where", "when", "while", "esp", "esp.", "especially",
          "as", "from", "by", "with", "for", "in", "on", "at", "into", "upon", "over", "under", "after",
          "before", "against", "among", "between", "through", "without", "so", "i.e.", "e.g.", "opp.",
          "cut", "set", "put", "made", "done", "given", "taken", "held", "kept", "left", "sent", "built",
          "brought", "known", "seen", "shown", "worn", "born", "drawn", "used", "being"}
MAX_WORDS = 4


def meaningful(text: str) -> bool:
    """A definition needs at least one word that is not a bare article/particle."""
    return any((len(word) > 1 or word in ("I", "O")) and word.lower() not in _STOP
               for word in _WORDS.findall(text or ""))


def short_head(text: str | None) -> dict | None:
    """Return the head phrase of a source definition, in its own words.

    1. Cut at the first printed delimiter (; : , parenthesis or dash).
    2. If that is longer than four words, cut before the first modifier word
       (after at least two words); otherwise keep the first four words and
       mark the cut with an ellipsis.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    value = unicodedata.normalize("NFC", " ".join(text.split()))
    head = re.split(r"\s*(?:[;:,(\[]|—|–|\s-\s)\s*", value, maxsplit=1)[0].strip().rstrip(".")
    if not head or not meaningful(head):
        head = value.rstrip(".")
    words = head.split(" ")
    method = "first_delimited_phrase"
    if len(words) > MAX_WORDS:
        cut = next((i for i, word in enumerate(words[:MAX_WORDS + 1])
                    if i >= 2 and (word.lower() in _BREAK or re.fullmatch(r"[a-z]+(?:ed|ing)", word.lower()))),
                   None)
        if cut is not None:
            words, method = words[:cut], "cut_before_modifier"
        else:
            words, method = words[:MAX_WORDS], "first_words_truncated"
    short = " ".join(words).strip(" ,.;:")
    if not meaningful(short):
        return None
    if method == "first_words_truncated":
        short += " …"
    return {"text": short, "method": method, "source_text": value}


__all__ = ["DICTIONARY_ORDER", "DICTIONARY_LABELS", "dictionary_rank", "letter_or_numeral_entry",
           "meaningful", "short_head", "NON_NUMERAL_POS"]
