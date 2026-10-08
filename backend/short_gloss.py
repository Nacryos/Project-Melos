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


# Grammatical metalanguage a dictionary prints around its definitions
# ("formed with a comparative force", "Adv.", "poet. form"). A sense made only
# of these words is a label the extractor caught, not a meaning.
_GRAMMAR_TERMS = {
    "comparative", "superlative", "adverb", "adv", "adverbial", "particle", "enclitic", "proclitic",
    "conjunction", "conj", "preposition", "prep", "pronoun", "pron", "interjection", "aorist", "aor",
    "pf", "fut", "pres", "imperfect", "impf", "participle", "infinitive", "inf", "passive", "pass", "med",
    "poet", "poetic", "ep", "epic", "ion", "ionic", "dor", "doric", "aeol", "aeolic", "att", "attic",
    "dat", "gen", "acc", "nom", "voc", "pl", "plural", "sg", "singular", "masc", "fem", "neut", "irreg", "redupl",
}
_CONNECTORS = {"of", "and", "or", "the", "a", "an", "form", "forms", "also", "used", "only", "as", "in", "with",
               "force", "sense", "sometimes", "mostly", "usu", "usually"}


def metalanguage_only(text: str | None) -> bool:
    """True when a definition is only grammatical labels ("comparative", "Adv.").

    Every word must be a grammatical term or a connector, and at least one a
    grammatical term, so real one-word meanings ("in", "and", "old") pass.
    """
    if re.search(r"[Ͱ-Ͽἀ-῿]", text or ""):
        return False
    words = [word.lower().strip(".’'") for word in re.findall(r"[A-Za-z][A-Za-z.’']*", text or "")]
    return (bool(words) and all(word in _GRAMMAR_TERMS or word in _CONNECTORS for word in words)
            and any(word in _GRAMMAR_TERMS for word in words))


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


_LEAD = re.compile(r"^(?:to|a|an|the)\s+", re.I)


def _phrase_key(phrase: str) -> str:
    return _LEAD.sub("", " ".join(phrase.lower().split()).strip(" .,;:!?")).strip()


def _phrases(text: str, limit: int = 4) -> list[str]:
    return [part.strip() for part in re.split(r"\s*[;:,]\s*", " ".join(str(text or "").split()))[:limit]
            if part.strip()]


def corroborated(phrase: str, others: list[str]) -> bool:
    """The phrase (articles and "to" aside) occurs word-for-word in another
    dictionary's entry for the same headword."""
    key = _phrase_key(phrase)
    if phrase.strip(" .,;:!") in ("I", "O"):
        # One-letter meanings (ἐγώ "I", ὦ "O") cannot be searched for as text
        # without matching numerals and letters; they stand as printed.
        return True
    if len(key) < 2 or not meaningful(key) or metalanguage_only(key):
        return False
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])")
    return any(pattern.search(" ".join(str(text or "").lower().split())) for text in others)


def corroborated_choice(groups):
    """Pick the gloss sense and head phrase that another dictionary confirms.

    ``groups`` is an ordered list of (source, senses, other_entry_texts), one
    per dictionary in DICTIONARY_ORDER, where ``other_entry_texts`` are the
    full texts of the *other* dictionaries' entries for the same headword.
    The first sense of each dictionary is examined in order; the first of its
    leading phrases that another dictionary prints word-for-word wins
    ("alius, another" -> "another": the Latin equivalent is in no English
    dictionary; Middle Liddell's δή "exactness" is in no other entry, so
    Autenrieth's "now" is used). Returns (sense, phrase) or None, in which case
    the caller keeps the plain first sense. Nothing is reworded.
    """
    groups = [group for group in groups if group[1] and group[2]]
    # Lower-case head phrases printed by any dictionary's first sense: a capitalised
    # "God" yields to another dictionary's "god" for a common word; a proper name is
    # capitalised everywhere and is unaffected.
    lowered = {_phrase_key(phrase) for _, senses, _ in groups for phrase in _phrases(senses[0].get("text"))
               if phrase[:1].islower()}
    for source, senses, others in groups:
        sense = senses[0]
        best, best_count = None, 0
        for phrase in _phrases(sense.get("text")):
            if phrase[:1].isupper() and phrase not in ("I", "O") and _phrase_key(phrase) in lowered:
                continue
            if not corroborated(phrase, others):
                continue
            # The phrase confirmed by the most other dictionaries wins; ties keep
            # the earlier phrase ("otherwise, but": "but" is in three, "otherwise" in one).
            count = sum(corroborated(phrase, [text]) for text in others)
            if count > best_count:
                best, best_count = phrase, count
        if best is not None:
            return sense, best
    return None


def normalise_gloss_case(gloss, lemma):
    """Lower-case the first letter of a short gloss for a common (lower-case) Greek headword.

    "To be" (πάρειμι) -> "to be". A capitalised headword (Ζεύς "Zeus"), "I" and "O",
    and an all-capitals first word are left as printed. Only `short_text` changes;
    the dictionary's full text stays verbatim.
    """
    if not isinstance(gloss, dict) or not isinstance(gloss.get("short_text"), str) or not gloss["short_text"]:
        return gloss
    letters = [ch for ch in unicodedata.normalize("NFD", str(lemma or "")) if unicodedata.category(ch).startswith("L")]
    if not letters or letters[0].isupper():
        return gloss
    text = gloss["short_text"]
    first = text.split()[0]
    if first in ("I", "O") or first.isupper() or not first[:1].isupper():
        return gloss
    gloss["short_text"] = text[0].lower() + text[1:]
    gloss["short_text_case"] = "first_letter_lowercased_for_common_headword"
    return gloss


_NAMED_IN_TEXT = re.compile(r"(?<=[a-z,;] )[A-Z][a-z]{3,}(?![a-z.])")


def entry_names_a_being(entry):
    """A lower-case dictionary entry that also names a person, god or being in its English
    (\"II. a Nymph\", \"Eros, the god of love\"): a capitalised word inside a sentence that is not an
    abbreviation. A capitalised headword may use such an entry; ἀνακτορία \"the management\" has none."""
    text = " ".join(str(sense.get("text") or "") for sense in (entry or {}).get("dictionary_senses") or [] if isinstance(sense, dict))
    text += " " + str((entry or {}).get("rendered_entry_text") or (entry or {}).get("entry_text") or "")
    return bool(_NAMED_IN_TEXT.search(text))


__all__ = ["DICTIONARY_ORDER", "normalise_gloss_case", "entry_names_a_being", "corroborated", "corroborated_choice", "DICTIONARY_LABELS", "dictionary_rank", "letter_or_numeral_entry",
           "meaningful", "metalanguage_only", "short_head", "NON_NUMERAL_POS"]
