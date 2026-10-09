"""Letter-level helpers for Greek scansion: decomposition, comparison keys, Beta Code with quantities.

Everything works on NFD code points so a precomposed letter (ᾶ, ᾳ, ᾱ) splits into a base letter and
its marks. Only the base letters and the marks named below matter to scansion.
"""
from __future__ import annotations

import unicodedata

ACUTE, GRAVE, CIRCUMFLEX = "́", "̀", "͂"
SMOOTH, ROUGH = "̓", "̔"
DIAERESIS, IOTA_SUB = "̈", "ͅ"
MACRON, BREVE = "̄", "̆"
UNDERDOT = "̣"
ACCENTS = (ACUTE, GRAVE, CIRCUMFLEX)
QUANTITY_MARKS = (MACRON, BREVE)
VOWELS = frozenset("αεηιουω")
DICHRONA = frozenset("αιυ")
LONG_VOWELS = frozenset("ηω")
SHORT_VOWELS = frozenset("εο")
DOUBLE_CONSONANTS = frozenset("ζξψ")
STOPS = frozenset("πβφτδθκγχ")
LIQUIDS_NASALS = frozenset("λρμν")
CONSONANTS = frozenset("βγδζθκλμνξπρστφχψϝ")
DIPHTHONGS = frozenset({"αι", "ει", "οι", "υι", "αυ", "ευ", "ηυ", "ου", "ωυ"})
# Elision marks used by the corpus (backend/elision.py ELISION_MARKS) plus U+1FBD koronis-as-apostrophe.
ELISION_MARKS = "’'᾽ʼ᾿"
# Lunate/medial/final sigma and the archaic letters are folded to one base letter.
FOLD = {"ς": "σ", "ϲ": "σ", "ϐ": "β", "ϑ": "θ", "ϕ": "φ", "ϰ": "κ", "ϱ": "ρ", "ϖ": "π", "Ϝ": "ϝ", "ϝ": "ϝ"}


def is_greek_letter(ch: str) -> bool:
    if not ch:
        return False
    base = unicodedata.normalize("NFD", ch)[0]
    return "Ͱ" <= base <= "Ͽ" and base.isalpha() or base in "ϝϜ"


def decompose(ch: str) -> tuple[str, str]:
    """(lower-case base letter, string of combining marks) for one precomposed character."""
    nfd = unicodedata.normalize("NFD", ch)
    base = nfd[0].lower()
    return FOLD.get(base, base), nfd[1:]


def letters(word: str) -> list[tuple[str, str]]:
    """Base letters with their marks; combining marks typed separately attach to the previous letter."""
    out: list[list[str]] = []
    for ch in unicodedata.normalize("NFD", word):
        if unicodedata.combining(ch):
            if out:
                out[-1][1] += ch
            continue
        if is_greek_letter(ch):
            base = ch.lower()
            out.append([FOLD.get(base, base), ""])
    return [(b, m) for b, m in out]


def base_letters(word: str) -> str:
    return "".join(b for b, _ in letters(word))


def key(word: str) -> str:
    """Lookup key: NFC, lower case, grave written as acute, quantity marks, underdots and elision dropped."""
    t = unicodedata.normalize("NFD", word or "").lower().replace(GRAVE, ACUTE)
    t = "".join(ch for ch in t if ch not in (MACRON, BREVE, UNDERDOT) and ch not in ELISION_MARKS)
    t = "".join(FOLD.get(ch, ch) for ch in t)
    return unicodedata.normalize("NFC", t)


def accentless_key(word: str) -> str:
    """Key without accents (breathings, diaeresis and iota subscript kept)."""
    t = unicodedata.normalize("NFD", key(word))
    return unicodedata.normalize("NFC", "".join(ch for ch in t if ch not in ACCENTS))


def quantity_marks(word: str) -> str:
    """One code per base letter: L/S for a marked dichronon, u for an unmarked dichronon, '.' otherwise."""
    codes = []
    for base, marks in letters(word):
        if base in DICHRONA:
            codes.append("L" if MACRON in marks else "S" if BREVE in marks else "u")
        else:
            codes.append(".")
    return "".join(codes)


# --- Beta Code (TLG/Perseus) with Morpheus quantity marks: _ long, ^ short --------------------
BETA_LETTERS = dict(zip("abgdezhqiklmncoprstufxywv", "αβγδεζηθικλμνξοπρστυφχψωϝ"))


def beta_letters(beta: str) -> list[tuple[str, str]]:
    """Base letters of a Beta Code string with quantity codes ('L', 'S' or '') per letter.

    Diacritics, capital markers, digits and Morpheus separators (':', '-') are ignored; '_' and '^'
    attach to the preceding letter.
    """
    out: list[list[str]] = []
    for ch in beta.lower():
        if ch in BETA_LETTERS:
            out.append([BETA_LETTERS[ch], ""])
        elif ch == "_" and out:
            out[-1][1] = "L"
        elif ch == "^" and out:
            out[-1][1] = "S"
    return [(b, q) for b, q in out]
