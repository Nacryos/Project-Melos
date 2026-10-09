"""Words, nuclei and syllables of a Greek text, across word boundaries (metre-free).

Rule ids (SYL-*, ELI-*, CRA-*) are listed in backend/scansion/rules.py with their citations.
Offsets are code points in the caller's string; a newline ends a line (consonants never carry
across it), any other punctuation does not interrupt the flow of sound.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .greek import (
    ACCENTS, CIRCUMFLEX, CONSONANTS, DIAERESIS, DIPHTHONGS, DOUBLE_CONSONANTS, ELISION_MARKS,
    ROUGH, SMOOTH, VOWELS, decompose, is_greek_letter,
)

_WORD = re.compile(r"[Ͱ-Ͽἀ-῿̀-ͯ\[\]⟨⟩’'ʼϝϜ]+")


@dataclass
class Letter:
    base: str
    marks: str
    start: int
    end: int


@dataclass
class Word:
    index: int
    text: str
    start: int
    end: int
    letters: list[Letter]
    elided: bool = False          # ends in an elision mark (ELI-1)
    prodelided: bool = False      # begins with an elision mark (ELI-2)


@dataclass
class Nucleus:
    word: int
    letters: list[int]            # indices into the word's letters
    kind: str                     # diphthong | long | short | dichronon
    rules: list[str] = field(default_factory=list)


@dataclass
class Syllable:
    index: int
    line: int
    word: int                     # word holding the nucleus
    start: int
    end: int
    nucleus: Nucleus
    coda: list[tuple[str, bool]]  # consonants up to the next nucleus: (letter, word boundary before it)
    next_vowel_word_initial: bool  # zero consonants and the next nucleus opens the next word (hiatus)
    next_nucleus_same_word: bool
    line_final: bool
    word_final: bool
    word_initial: bool

    @property
    def text(self) -> str:  # filled by Scanner (needs the source string)
        return ""


def words_of(text: str, start: int = 0, end: int | None = None) -> list[Word]:
    out: list[Word] = []
    for m in _WORD.finditer(text, start, len(text) if end is None else end):
        raw = m.group(0)
        letters = []
        for i, ch in enumerate(raw):
            if ch in ELISION_MARKS or ch in "[]⟨⟩":
                continue
            base, marks = decompose(ch)
            if is_greek_letter(ch):
                letters.append(Letter(base, marks, m.start() + i, m.start() + i + 1))
            elif marks == "" and letters and _is_combining(ch):
                letters[-1].marks += ch
                letters[-1].end = m.start() + i + 1
        if not letters:
            continue
        stripped = raw.rstrip("[]⟨⟩")
        elided = stripped[-1:] in ELISION_MARKS
        prodelided = raw[:1] in ELISION_MARKS
        out.append(Word(len(out), raw, m.start(), m.end(), letters, bool(elided), prodelided))
    return out


def _is_combining(ch: str) -> bool:
    import unicodedata
    return unicodedata.combining(ch) > 0


def nuclei_of(word: Word) -> list[Nucleus]:
    """SYL-1..SYL-5: one nucleus per vowel, two vowels joined when they form a diphthong."""
    out: list[Nucleus] = []
    L = word.letters
    i = 0
    while i < len(L):
        if L[i].base not in VOWELS:
            i += 1
            continue
        if i + 1 < len(L) and L[i + 1].base in VOWELS:
            joined, rule = _diphthong(L[i], L[i + 1])
            if joined:
                out.append(Nucleus(word.index, [i, i + 1], "diphthong", [rule]))
                i += 2
                continue
            if rule:
                out.append(Nucleus(word.index, [i], _kind(L[i]), [rule]))
                i += 1
                continue
        out.append(Nucleus(word.index, [i], _kind(L[i]), []))
        i += 1
    return out


def _kind(letter: Letter) -> str:
    if letter.base in "ηω":
        return "long"
    if letter.base in "εο":
        return "short"
    return "dichronon"


def _diphthong(a: Letter, b: Letter) -> tuple[bool, str | None]:
    pair = a.base + b.base
    if DIAERESIS in b.marks:
        return False, "SYL-2"                       # diaeresis: two vowels
    if pair in ("ηι", "ωι") or (pair == "αι" and CIRCUMFLEX in a.marks):
        # iota adscript (τῶι, τᾶι): the ι is written beside a long vowel; the ι itself is bare
        if not any(m in b.marks for m in ACCENTS + (SMOOTH, ROUGH)):
            return True, "SYL-4"
        return False, None
    if pair in DIPHTHONGS:
        if any(m in a.marks for m in ACCENTS + (SMOOTH, ROUGH)):
            return False, "SYL-3"                   # breathing/accent on the first vowel: hiatus (ἀίω)
        return True, "SYL-1"
    return False, None


def line_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for part in text.split("\n"):
        spans.append((pos, pos + len(part)))
        pos += len(part) + 1
    return spans


def syllabify_line(words: list[Word], line: int, first_index: int = 0) -> list[Syllable]:
    """Syllables of one verse line (or prose line): position counts consonants across words."""
    seq: list[tuple[str, int, int, int]] = []    # (kind 'C'/'N', word index, letter or nucleus index, ...)
    nuclei_by_word = {w.index: nuclei_of(w) for w in words}
    for w in words:
        nuc = nuclei_by_word[w.index]
        starts = {n.letters[0]: k for k, n in enumerate(nuc)}
        covered = {i for n in nuc for i in n.letters}
        for i, letter in enumerate(w.letters):
            if i in starts:
                seq.append(("N", w.index, starts[i], i))
            elif i not in covered:
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
            letter = word_by_index[item[1]].letters[item[2]]
            coda.append((letter.base, item[1] != prev_word))
            prev_word = item[1]
        next_word = seq[nxt][1] if nxt < len(seq) else None
        sylls.append(Syllable(
            index=first_index + s, line=line, word=wi, start=0, end=0, nucleus=nucleus, coda=coda,
            next_vowel_word_initial=(not coda and next_word is not None and next_word != wi),
            next_nucleus_same_word=(next_word == wi),
            line_final=(nxt >= len(seq)),
            word_final=(next_word != wi),
            word_initial=(s == 0 or seq[npos[s - 1]][1] != wi),
        ))
    _assign_spans(sylls, words, nuclei_by_word)
    return sylls


def _assign_spans(sylls: list[Syllable], words: list[Word], nuclei_by_word) -> None:
    """Display spans inside words: VC.CV splits a cluster after its first consonant; a single consonant
    goes with the following vowel; an elided word without a vowel (δ’) joins the next syllable."""
    by_word: dict[int, list[Syllable]] = {}
    for s in sylls:
        by_word.setdefault(s.word, []).append(s)
    for w in words:
        ss = by_word.get(w.index, [])
        if not ss:
            continue
        L = w.letters
        bounds = []
        for a, b in zip(ss, ss[1:]):
            end_a = a.nucleus.letters[-1]
            start_b = b.nucleus.letters[0]
            n_cons = start_b - end_a - 1
            split = end_a + 1 + (1 if n_cons >= 2 else 0)
            bounds.append(split)
        cuts = [0] + bounds + [len(L)]
        for s, lo, hi in zip(ss, cuts, cuts[1:]):
            s.start = L[lo].start
            s.end = L[hi - 1].end
        # elision mark stays with its syllable
        if w.elided:
            ss[-1].end = w.end
    # vowel-less words (an elided δ’, τ’, or a lone consonant) join the next syllable on the line
    for w in words:
        if w.index in by_word:
            continue
        nxt = next((s for s in sylls if s.word > w.index), None)
        prv = next((s for s in reversed(sylls) if s.word < w.index), None)
        if nxt is not None:
            nxt.start = min(nxt.start, w.start)
        elif prv is not None:
            prv.end = max(prv.end, w.end)


def consonant_units(coda: list[tuple[str, bool]]) -> int:
    return sum(2 if c in DOUBLE_CONSONANTS else 1 for c, _ in coda if c in CONSONANTS)
