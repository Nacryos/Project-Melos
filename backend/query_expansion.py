"""Conservative Latin-script Greek retrieval keys backed by indexed tokens.

The caller supplies the existing transliteration converter's normalized query
variants and the accepted corpus vocabulary. These are spelling candidates,
not morphological or semantic analyses.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
import re
import unicodedata
from .textutils import tokenize, normalize as text_normalize, search_text
from .morphology import _from_beta, _from_roman, normalize


_VOWEL_ALTERNATES = {"ο": "ω", "ω": "ο", "ε": "η", "η": "ε"}
MAX_QUERY_WORDS = 8
MAX_OUTPUT_TOKENS = 16
MIN_COVERAGE = .8  # Retrieval gate, not a calibrated language probability.
MAX_PHRASE_KEYS = 32
MAX_PHRASE_PASSAGES = 2000


def phrase_token_options(query: str) -> list[list[tuple[str, int]]]:
    """Bounded romanization ambiguities, not linguistic or corpus assertions.

    Plain e/o may stand for either Greek vowel identity; explicit ē/ō have
    already been preserved by the converter and are never changed here. All
    original words, including short function words and elision marks, remain.
    Returned options still require vocabulary AND whole-source-phrase checks.
    """
    words = tokenize(query)
    if (not 2 <= len(words) <= MAX_QUERY_WORDS or len(query) > 200
            or any(_greek_letter(char) for char in query)
            or any(not (char.isspace() or char in "'’ʼ᾽᾿" or unicodedata.category(char).startswith('M')
                        or (char.isalpha() and 'LATIN' in unicodedata.name(char, '')))
                   for char in query)
            or not any(sum(char.isalpha() for char in word) >= 4 for word in words)):
        return []
    groups = []
    for word in words:
        converted = tokenize(normalize(_from_roman(word)))
        if len(converted) != 1:
            return []
        key = converted[0]
        alternates = {key[:i] + {'ε': 'η', 'ο': 'ω'}[char] + key[i + 1:]
                      for i, char in enumerate(key) if char in 'εο'}
        groups.append([(key, 0), *((value, 1) for value in sorted(alternates))])
    return groups


def indexed_phrase_plan(options: list[list[tuple[str, int]]],
                        vocabulary_counts: dict[str, int]) -> dict:
    """Keep only indexed tokens; ≤2 substitutions and ≤32 phrase keys.

    This is intentionally separate from the conservative English/FTS OR gate.
    It cannot activate retrieval until a complete phrase is confirmed in text.
    """
    groups = [[(word, cost) for word, cost in group if word in vocabulary_counts]
              for group in options]
    if not groups or any(not group for group in groups):
        return {}
    phrases = []

    def combinations(index, remaining, prefix):
        if index == len(groups):
            if remaining == 0:
                yield ' '.join(prefix)
            return
        for word, cost in groups[index]:
            if cost <= remaining:
                yield from combinations(index + 1, remaining - cost, [*prefix, word])

    for budget in range(3):
        for phrase in combinations(0, budget, []):
            if phrase not in phrases:
                phrases.append(phrase)
            if len(phrases) > MAX_PHRASE_KEYS:
                break
        if len(phrases) > MAX_PHRASE_KEYS:
            break
    if not phrases:
        return {}
    anchor = min(groups, key=lambda group: (sum(vocabulary_counts[word] for word, _ in group),
                                            tuple(word for word, _ in group)))
    return {'phrases': phrases[:MAX_PHRASE_KEYS], 'phrases_truncated': len(phrases) > MAX_PHRASE_KEYS,
            'anchor_tokens': list(dict.fromkeys(word for word, _ in anchor)),
            'phrase_limit': MAX_PHRASE_KEYS, 'max_vowel_ambiguities': 2}


def confirm_source_phrases(text: str, phrases: Iterable[str]) -> list[str]:
    """Whole printed phrases, never bridges across editorial gaps/supplies.

    Only whitespace (including line breaks) may separate phrase words. The
    existing explicit Greek line-end hyphen join remains a search-copy rule.
    Bracketed supplies, ellipses and underdotted words are opaque boundaries;
    their removal must never manufacture an uninterrupted source phrase.
    """
    depth, safe = 0, []
    for char in str(text):
        if char in '[⟨⟦<{〈⸢⸤⌈⌊‹':
            depth += 1
            safe.append('\0')
        elif char in ']⟩⟧>}〉⸣⸥⌉⌋›':
            depth = max(0, depth - 1)
            safe.append('\0')
        else:
            safe.append('\0' if depth else char)
    value = ''.join(safe)
    value = re.sub(r'\S*\u0323\S*', '\0', value)
    value = re.sub(r'…|(?:\.\s*){2,}', '\0', value)
    value = text_normalize(search_text(value))
    found = []
    for phrase in phrases:
        ending = r'(?!\w)' if phrase.endswith(("'", '᾿')) else r"(?![\w'᾿])"
        pattern = r"(?<!\w)(?<!\w['᾿])" + r'\s+'.join(re.escape(word) for word in phrase.split()) + ending
        if re.search(pattern, value):
            found.append(phrase)
    return found


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
