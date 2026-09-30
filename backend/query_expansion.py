"""Conservative Latin-script Greek retrieval keys backed by indexed tokens.

The caller supplies the existing transliteration converter's normalized query
variants and the accepted corpus vocabulary. These are spelling candidates,
not morphological or semantic analyses.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
import re


_ASCII_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_GREEK_WORD = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]+")
_VOWEL_ALTERNATES = {"ο": "ω", "ω": "ο", "ε": "η", "η": "ε"}
MAX_QUERY_WORDS = 8
MAX_OUTPUT_TOKENS = 16


def _indexed_tokens(variant: str, vocabulary: Collection[str]) -> tuple[list[str], int]:
    words = [word for word in _GREEK_WORD.findall(variant) if len(word) >= 3]
    exact = [word for word in words if word in vocabulary]
    output = list(exact)
    # When every substantial word already has an attested exact key, widening
    # an FTS OR query can only add noise.
    if len(exact) == len(words):
        return list(dict.fromkeys(output)), len(exact)
    for word in words:
        if len(word) < 3:
            continue
        if len(word) < 4:
            continue
        # The ALA-LC-inspired input converter intentionally accepts plain
        # Latin o/e. It cannot distinguish omicron/omega or epsilon/eta.
        # Consider only one such substitution, and only if actually indexed.
        alternatives = sorted({
            word[:i] + _VOWEL_ALTERNATES[char] + word[i + 1:]
            for i, char in enumerate(word)
            if i >= len(word) - 3 and char in _VOWEL_ALTERNATES
        })
        output.extend(candidate for candidate in alternatives if candidate in vocabulary)
    return list(dict.fromkeys(output)), len(exact)


def fallback_tokens(query: str, normalized_variants: Iterable[str],
                    vocabulary: Collection[str] | Iterable[str]) -> list[str]:
    """Return at most 16 attested Greek FTS terms for likely transliteration.

    At least two long ASCII query words and two exact indexed Greek tokens
    are required to prevent most English descriptions from triggering this
    fallback. The highest-coverage converter variant is chosen; ties retain
    caller order. Every returned term is an indexed source token, including
    spelling alternatives. No unattested inflection or sense is proposed.
    """
    words = _ASCII_WORD.findall(query)
    if (len(words) < 2 or len(words) > MAX_QUERY_WORDS
            or sum(len(word.strip("'’")) >= 4 for word in words) < 2
            or any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff"
                   for char in query)):
        return []
    lexicon = vocabulary if isinstance(vocabulary, (set, frozenset)) else set(vocabulary)
    best: list[str] = []
    best_count = 0
    for variant in list(normalized_variants)[:3]:
        tokens, count = _indexed_tokens(variant, lexicon)
        if count > best_count:
            best, best_count = tokens, count
    if best_count < 2:
        return []
    return best[:MAX_OUTPUT_TOKENS]
