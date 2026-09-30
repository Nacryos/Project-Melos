"""Conservative Latin-script Greek retrieval keys backed by indexed tokens.

The caller supplies the existing transliteration converter's normalized query
variants and the accepted corpus vocabulary. These are spelling candidates,
not morphological or semantic analyses.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from .textutils import tokenize
from .morphology import _from_beta, _from_roman, normalize


_VOWEL_ALTERNATES = {"ο": "ω", "ω": "ο", "ε": "η", "η": "ε"}
MAX_QUERY_WORDS = 8
MAX_OUTPUT_TOKENS = 16
MIN_COVERAGE = .8  # Retrieval gate, not a calibrated language probability.


def _greek_letter(char: str) -> bool:
    return char.isalpha() and ("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff")


def _indexed_tokens(variant: str, vocabulary: Collection[str]) -> tuple[list[str], int]:
    # The shared lexer preserves attached apostrophes and spacing psili. A
    # terminal sign is not silently removed to claim an attested whole word.
    words = [word for word in tokenize(variant) if sum(_greek_letter(c) for c in word) >= 3]
    exact = [word for word in words if word in vocabulary]
    output = list(exact)
    # When every substantial word already has an attested exact key, widening
    # an FTS OR query can only add noise.
    if len(exact) == len(words):
        return list(dict.fromkeys(output)), len(set(exact))
    for word in words:
        if sum(_greek_letter(c) for c in word) < 4:
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
    return list(dict.fromkeys(output)), len(set(exact))


def fallback_plan(query: str, normalized_variants: Iterable[str],
                  vocabulary: Collection[str] | Iterable[str]) -> dict:
    """Return at most 16 attested Greek FTS terms for likely transliteration.

    Require two long Latin query words, two distinct exact indexed Greek anchors, and
    indexed spelling support for at least 80% of substantial ORIGINAL query
    words. This is a conservative retrieval gate, not language identification.
    Unconverted words remain in the denominator. A converter that drops or
    splits words is rejected rather than inflating coverage. Highest coverage
    wins, then exact anchors; ties retain caller order. Every returned term
    exists in the supplied vocabulary. No inflection or sense is proposed.
    """
    words = tokenize(query)
    if (len(words) < 2 or len(words) > MAX_QUERY_WORDS
            or sum(sum(c.isascii() and c.isalpha() for c in word) >= 4 for word in words) < 2
            or any(_greek_letter(char) for char in query)):
        return {}
    substantial = [i for i, word in enumerate(words) if sum(c.isalpha() for c in word) >= 3]
    lexicon = vocabulary if isinstance(vocabulary, (set, frozenset)) else set(vocabulary)
    best: dict = {}
    best_rank = (0, 0)
    for variant in list(normalized_variants)[:3]:
        # Aggregate token counts can conceal one dropped word plus another
        # split word. Prove alignment for EACH source token with the same
        # converter that produced this whole-query variant.
        converter = next((fn for fn in (_from_roman, _from_beta)
                          if normalize(fn(query)) == variant), None)
        if converter is None:
            continue
        aligned = [tokenize(normalize(converter(word))) for word in words]
        if any(len(tokens) != 1 for tokens in aligned):
            continue
        converted = [tokens[0] for tokens in aligned]
        covered = sum(bool(_indexed_tokens(converted[i], lexicon)[0]) for i in substantial)
        tokens, count = _indexed_tokens(variant, lexicon)
        if count < 2 or covered < MIN_COVERAGE * len(substantial):
            continue
        if (covered, count) > best_rank:
            allowed = set(tokens[:MAX_OUTPUT_TOKENS])
            groups = []
            for i in substantial:
                word = converted[i]
                # Alternatives count with their source word, never as extra
                # query votes. Reuse the same bounded spelling policy.
                possible = {word} | {word[:j] + _VOWEL_ALTERNATES[c] + word[j + 1:]
                                     for j, c in enumerate(word)
                                     if j >= len(word) - 3 and c in _VOWEL_ALTERNATES}
                groups.append({'original': normalize(words[i]),
                               'transliterated': [token for token in tokens[:MAX_OUTPUT_TOKENS]
                                                  if token in allowed & possible]})
            best = {'tokens': tokens[:MAX_OUTPUT_TOKENS], 'groups': groups,
                    'covered_words': covered, 'substantial_words': len(substantial),
                    'exact_anchors': count}
            best_rank = (covered, count)
    return best


def fallback_tokens(query: str, normalized_variants: Iterable[str],
                    vocabulary: Collection[str] | Iterable[str]) -> list[str]:
    """Compatibility helper returning only the accepted indexed Greek terms."""
    return fallback_plan(query, normalized_variants, vocabulary).get('tokens', [])
