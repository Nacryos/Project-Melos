"""Words, nuclei and syllables of a Latin text, across word boundaries (metre-free).

Same shapes as the Greek module (Letter, Word, Nucleus, Syllable from backend/scansion/syllabify.py). A Latin
letter is classified first: i and u are vowels or consonants by the rules in latin.classify_iu (typed v / j are
certain); qu, ngu and the suād- family carry a glide that is no consonant unit of its own; h is silent; x, z and
an intervocalic i count two. Rule ids: SYL-LA-* (nuclei), IU-* (i/u roles), ELI-* (an editor's elision mark).
"""
from __future__ import annotations

import re
import unicodedata

from .latin import (
    ALWAYS_DIPHTHONG, CONSONANTS, DIAERESIS, DIPHTHONGS, EI_WORDS, ELISION_MARKS, EO_FORMS, EU_WORDS, LIGATURES,
    SPLIT_AE, SPLIT_OE, UI_WORDS, VOWELS, classify_iu, consonant_value, is_latin_letter,
)
from .syllabify import Letter, Nucleus, Syllable, Word, _assign_spans, _is_combining, line_spans

_WORD = re.compile(r"[A-Za-zÀ-ɏ̀-ͯḀ-ỿ\[\]⟨⟩’'ʼ]+")
_PIECE = re.compile(r"[’'ʼ]?[^’'ʼ]+[’'ʼ]?|[’'ʼ]+")
_PUNCT_STRONG = set(".!?;:")
_PUNCT_WEAK = set(",")


def words_of(text: str, start: int = 0, end: int | None = None, spelling: str = "auto") -> list[Word]:
    """`spelling`: "auto" (the text writes v / j if it contains any), "uv" (it does), "u" (it writes u, i only)."""
    out: list[Word] = []
    low = text.lower()
    uses_v, uses_j = ("v" in low, "j" in low) if spelling == "auto" else (spelling == "uv", spelling == "uv")
    for m in _pieces(text, start, len(text) if end is None else end):
        raw = m.group(0)
        letters: list[Letter] = []
        typed: list[str] = []
        for i, ch in enumerate(raw):
            if ch in ELISION_MARKS or ch in "[]⟨⟩":
                continue
            if ch in LIGATURES:
                for k, c in enumerate(LIGATURES[ch]):
                    letters.append(Letter(c, "", m.start() + i, m.start() + i + 1))
                    typed.append(c)
                continue
            nfd = unicodedata.normalize("NFD", ch)
            base, marks = nfd[0].lower(), nfd[1:]
            if is_latin_letter(ch):
                letters.append(Letter(base, marks, m.start() + i, m.start() + i + 1))
                typed.append(base)
            elif marks == "" and letters and _is_combining(ch):
                letters[-1].marks += ch
                letters[-1].end = m.start() + i + 1
        if not letters:
            continue
        bases = [l.base for l in letters]
        rules = classify_iu(bases, typed, uses_v, uses_j)
        for l, b, r in zip(letters, bases, rules):
            l.base = b
            if r:
                l.marks += "\u0000" + r          # the i/u rule travels with the letter (private tag, see iu_rule)
        stripped = raw.rstrip("[]⟨⟩")
        elided = stripped[-1:] in ELISION_MARKS
        prodelided = raw[:1] in ELISION_MARKS
        out.append(Word(len(out), raw, m.start(), m.end(), letters, bool(elided), prodelided))
    return out


def iu_rule(letter: Letter) -> str:
    return letter.marks.split("\u0000", 1)[1] if "\u0000" in letter.marks else ""


def marks_of(letter: Letter) -> str:
    return letter.marks.split("\u0000", 1)[0]


def _pieces(text: str, start: int, end: int):
    for m in _WORD.finditer(text, start, end):
        for p in _PIECE.finditer(text, m.start(), m.end()):
            yield p


def punct_between(text: str, a: Word, b: Word) -> str:
    gap = text[a.end:b.start]
    if any(ch in _PUNCT_STRONG for ch in gap):
        return "strong"
    if any(ch in _PUNCT_WEAK for ch in gap):
        return "weak"
    return "none"


def nuclei_of(word: Word) -> list[Nucleus]:
    """SYL-LA-1..4: one nucleus per vowel letter; two vowels joined when they form a diphthong."""
    out: list[Nucleus] = []
    L = word.letters
    key = "".join(l.base for l in L).replace("j", "i").replace("J", "i").replace("v", "u").replace("w", "u")
    i = 0
    while i < len(L):
        if L[i].base not in VOWELS:
            i += 1
            continue
        if i + 1 < len(L) and L[i + 1].base in VOWELS:
            joined, rule = _diphthong(L[i], L[i + 1], key, i, word.text.lstrip("’'ʼ[⟨")[:1].isupper())
            if joined:
                out.append(Nucleus(word.index, [i, i + 1], "diphthong", [rule]))
                i += 2
                continue
            if rule:
                out.append(Nucleus(word.index, [i], "vowel", [rule]))
                i += 1
                continue
        out.append(Nucleus(word.index, [i], "vowel", []))
        i += 1
    return out


def _diphthong(a: Letter, b: Letter, key: str, i: int, capitalised: bool = False) -> tuple[bool, str | None]:
    pair = a.base + b.base
    if DIAERESIS in marks_of(b) or DIAERESIS in marks_of(a):
        return False, "SYL-LA-2"                                   # written diaeresis: aër, poëta
    if pair not in DIPHTHONGS:
        return False, None
    if pair in ALWAYS_DIPHTHONG:
        if pair == "oe" and key.startswith(SPLIT_OE):
            return False, "SYL-LA-3"                               # poēta, coēgī, coerceō
        if pair == "ae" and key.startswith(SPLIT_AE):
            return False, "SYL-LA-3"                               # āēr, Danaē
        return True, "SYL-LA-1"
    if pair == "eu":
        if key in EU_WORDS or key in {w + "que" for w in EU_WORDS}:
            return True, "SYL-LA-4"
        if i == 0 and key not in EO_FORMS and not key.startswith("eo"):
            return True, "SYL-LA-4"                                # Eurōpa, Eurus, Eumenides
        if key.endswith("eus") and i == len(key) - 3 and i > 0 and key[i - 1] not in VOWELS and capitalised and key not in ("deus", "meus", "reus"):
            return True, "SYL-LA-4"                                # Orpheus, Pēleus, Tȳdeus (Greek names)
        return False, None
    if pair == "ui":
        return (True, "SYL-LA-4") if key in UI_WORDS else (False, None)
    if pair == "ei":
        return (True, "SYL-LA-4") if key in EI_WORDS else (False, None)
    return False, None


def syllabify_line(words: list[Word], line: int, first_index: int = 0) -> list[Syllable]:
    """Syllables of one line: the coda of a unit is every consonant up to the next nucleus, with word boundaries."""
    seq: list[tuple[str, int, int, int]] = []
    nuclei_by_word = {w.index: nuclei_of(w) for w in words}
    for w in words:
        nuc = nuclei_by_word[w.index]
        starts = {n.letters[0]: k for k, n in enumerate(nuc)}
        covered = {i for n in nuc for i in n.letters}
        for i, letter in enumerate(w.letters):
            if i in starts:
                if iu_rule(letter) == "IU-COMPOUND":
                    seq.append(("C", w.index, -1, i))      # the glide of ab-icio / prō-icio: a double consonant (J)
                seq.append(("N", w.index, starts[i], i))
            elif i not in covered and letter.base in CONSONANTS:
                seq.append(("C", w.index, i, i))
    word_by_index = {w.index: w for w in words}
    sylls: list[Syllable] = []
    npos = [k for k, item in enumerate(seq) if item[0] == "N"]
    for s, k in enumerate(npos):
        _, wi, ni, li = seq[k]
        nucleus = nuclei_by_word[wi][ni]
        nxt = npos[s + 1] if s + 1 < len(npos) else len(seq)
        coda = []
        prev_word = wi
        for item in seq[k + 1:nxt]:
            base = "J" if item[2] == -1 else word_by_index[item[1]].letters[item[2]].base
            coda.append((base, item[1] != prev_word))
            prev_word = item[1]
        next_word = seq[nxt][1] if nxt < len(seq) else None
        real = [c for c, _ in coda if consonant_value(c) > 0]
        sylls.append(Syllable(
            index=first_index + s, line=line, word=wi, start=0, end=0, nucleus=nucleus, coda=coda,
            next_vowel_word_initial=(not real and next_word is not None and next_word != wi),
            next_nucleus_same_word=(next_word == wi),
            line_final=(nxt >= len(seq)),
            word_final=(next_word != wi),
            word_initial=(s == 0 or seq[npos[s - 1]][1] != wi),
        ))
    _assign_spans(sylls, words, nuclei_by_word)
    return sylls


def consonant_units(coda: list[tuple[str, bool]]) -> int:
    return sum(consonant_value(c) for c, _ in coda if c in CONSONANTS)
