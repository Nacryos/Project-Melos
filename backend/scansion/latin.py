"""Letter-level helpers for Latin scansion: decomposition, i/u roles, digraphs, lookup keys.

Everything works on NFD code points so a letter with a macron or breve (ā, ă) splits into the base letter
and its mark; the mark is kept as typed evidence. Only the base letters and the marks named here matter.
"""
from __future__ import annotations

import unicodedata

MACRON, BREVE, DIAERESIS = "̄", "̆", "̈"
UNDERDOT = "̣"
QUANTITY_MARKS = (MACRON, BREVE)
VOWELS = frozenset("aeiouy")
# Consonant bases after classification: j = consonantal i (one unit), J = intervocalic i (two units),
# v = consonantal u, w = the glide of qu / ngu / su (no unit of its own: it belongs to the letter before it).
CONSONANTS = frozenset("bcdfghjJklmnpqrstvwxz")
DOUBLE_CONSONANTS = frozenset("xzJ")
SILENT = frozenset("hw")
STOPS = frozenset("bcdgkpqt")
MCL_FIRST = STOPS | {"f"}          # f + l/r behaves as muta cum liquida (Allen & Greenough §11b)
LIQUIDS = frozenset("lr")
NASALS = frozenset("mn")
DIPHTHONGS = frozenset({"ae", "au", "oe", "eu", "ui", "ei"})
ALWAYS_DIPHTHONG = frozenset({"ae", "au", "oe"})
# Elision written by an editor (rare in Latin editions: dict' est); U+2019 and friends.
ELISION_MARKS = "’'ʼ"
LIGATURES = {"æ": "ae", "œ": "oe", "Æ": "ae", "Œ": "oe"}
FOLD = {"v": "u", "j": "i", "V": "u", "J": "i"}

# eu is a diphthong in these words and in word-initial position (Europa, Eurus) except the forms of eo
EU_WORDS = frozenset({"heu", "seu", "neu", "ceu", "heus", "eheu", "neuter", "neutra", "neutrum", "neutiquam"})
EO_FORMS = frozenset({"eum", "eunt", "euntem", "euntis", "eunti", "euntes", "euntibus", "euntium", "eundo", "eundum",
                      "eundi", "eunto"})
UI_WORDS = frozenset({"cui", "huic", "hui"})
EI_WORDS = frozenset({"hei", "ei", "dein", "deinde", "deinceps", "deinde"})
# oe / ae / au split (two syllables) in these stems: poeta, poema, coego, coerceo, aer, Danae …
SPLIT_OE = ("poet", "poem", "poes", "coeg", "coer", "coet", "coeo", "coeu", "coea", "coiu", "oen")  # oen-: Oenone? no: oe
SPLIT_AE = ("aer", "aeri", "aere", "dana", "israe")
INTERJECTIONS = frozenset({"o", "heu", "a", "ah", "eheu", "io", "pro", "hem", "ei", "uae", "uah", "en", "ecce", "hei"})
GREEK_INITIAL_I = ("iason", "iasi", "io", "ion", "iola", "iolc", "iul")   # Iāsōn, Iō, Iōnes, Iolāus (vocalic initial i)
SU_GLIDE = ("suad", "suau", "suaui", "suas", "suesc", "suet", "sueu", "suev", "sueb")  # suādeō, suāvis, suēscō, Suēbī


def is_latin_letter(ch: str) -> bool:
    base = unicodedata.normalize("NFD", ch)[:1]
    return bool(base) and base.isascii() and base.isalpha()


def decompose(ch: str) -> tuple[str, str]:
    """(lower-case base letter, string of combining marks) for one character."""
    nfd = unicodedata.normalize("NFD", ch)
    return nfd[0].lower(), nfd[1:]


def letters(word: str) -> list[tuple[str, str]]:
    out: list[list[str]] = []
    for ch in unicodedata.normalize("NFD", word):
        if unicodedata.combining(ch):
            if out:
                out[-1][1] += ch
            continue
        if ch in LIGATURES:
            for c in LIGATURES[ch]:
                out.append([c, ""])
            continue
        if is_latin_letter(ch):
            out.append([ch.lower(), ""])
    return [(b, m) for b, m in out]


def base_letters(word: str) -> str:
    return "".join(b for b, _ in letters(word))


def key(word: str) -> str:
    """Lookup key: lower case, u for v, i for j, ligatures expanded, quantity marks, underdots and elision dropped."""
    t = unicodedata.normalize("NFD", word or "")
    t = "".join(LIGATURES.get(ch, ch) for ch in t).lower()
    t = "".join(ch for ch in t if ch not in (MACRON, BREVE, UNDERDOT, DIAERESIS) and ch not in ELISION_MARKS)
    t = "".join(FOLD.get(ch, ch) for ch in t)
    return unicodedata.normalize("NFC", t)


def quantity_marks(word: str) -> str:
    """One code per base letter: L/S for a marked vowel, u for an unmarked vowel, '.' for a consonant."""
    codes = []
    for base, marks in letters(word):
        if base in VOWELS:
            codes.append("L" if MACRON in marks else "S" if BREVE in marks else "u")
        else:
            codes.append(".")
    return "".join(codes)


def classify_iu(bases: list[str], typed: list[str]) -> list[str]:
    """Role of every letter: 'V' vowel, 'C' consonant (bases get j/J/v/w), with the i/u rules.

    `typed` holds the letter as written (so a typed v or j is kept as a consonant). Returns the list of
    rule ids that fired, one per letter ('' when none). Modifies `bases` in place."""
    n = len(bases)
    rules = [""] * n
    word = "".join(bases)
    for i, b in enumerate(bases):
        nxt = bases[i + 1] if i + 1 < n else ""
        prv = bases[i - 1] if i > 0 else ""
        if typed[i] in ("v", "j"):
            bases[i] = "v" if typed[i] == "v" else ("J" if (prv in VOWELS and nxt in VOWELS) else "j")
            rules[i] = "IU-TYPED"
            continue
        if b == "u":
            if prv == "q":
                bases[i], rules[i] = "w", "IU-QU"                     # qu: one consonant (A&G §6c, §11c)
            elif prv == "g" and i >= 2 and bases[i - 2] == "n" and nxt in VOWELS:
                bases[i], rules[i] = "w", "IU-NGU"                    # lingua, sanguis
            elif prv == "s" and nxt in VOWELS and (word.startswith(SU_GLIDE) or (i >= 2 and bases[i - 2] == "n" and word[i - 2:].startswith("nsue"))):
                bases[i], rules[i] = "w", "IU-SU"                     # suādeō, suāvis, cōnsuētūdō
            elif i == 0 and nxt in VOWELS and not (nxt == "u" and n > 2 and bases[2] in VOWELS):
                bases[i], rules[i] = "v", "IU-INIT"                   # uideō, uolō, uulgus (but uua = ū-va)
            elif i == 1 and bases[0] == "u" and nxt in VOWELS:
                bases[i], rules[i] = "v", "IU-INIT"                   # uua: the second u is the consonant
            elif prv in VOWELS and nxt in VOWELS:
                bases[i], rules[i] = "v", "IU-INTERVOC"               # ōvum, avis, novus, iuvat, fluvius
            elif prv in LIQUIDS and nxt in VOWELS and nxt != "u":
                bases[i], rules[i] = "v", "IU-LIQ"                    # silua, seruus, aruum, paruus
            elif prv in LIQUIDS and nxt == "u" and i + 2 < n and bases[i + 2] in VOWELS:
                pass                                                   # fluuius: this u is the vowel
        elif b == "i":
            if i == 0 and nxt in VOWELS and not word.startswith(GREEK_INITIAL_I):
                bases[i], rules[i] = "j", "IU-INIT"                   # iam, iaceō, Iuppiter
            elif prv in VOWELS and nxt in VOWELS and not (prv == "e" and i == 1 and word.startswith("ei")):
                bases[i], rules[i] = "J", "IU-INTERVOC"               # maior, eius, Troia: a double consonant
            elif prv in ("b", "d", "n", "r", "s", "x") and nxt in VOWELS and word.startswith(("abi", "adi", "coni", "disi", "ini", "obi", "rei", "subi", "proi", "traj", "trai", "dei")) and i == len(_prefix_of(word)):
                bases[i], rules[i] = "j", "IU-COMPOUND"               # abicio, conicio, subicio, reicio
    return rules


def _prefix_of(word: str) -> str:
    for p in ("ab", "ad", "con", "dis", "in", "ob", "re", "sub", "pro", "tra", "de"):
        if word.startswith(p):
            return p
    return ""


def consonant_value(base: str) -> int:
    """How many consonants a classified base letter counts for position."""
    if base in SILENT:
        return 0
    if base in DOUBLE_CONSONANTS:
        return 2
    return 1
