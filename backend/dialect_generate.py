"""Generate-and-test spelling normalisation for forms the parser does not know.

When local Morpheus has no analysis of a printed form, this module generates a
bounded set of standard (Attic/epic) spellings by general dialect rules, asks the
parser about each, and keeps only spellings it analyses. Nothing is looked up by
word: every rule is orthographic and applies to any form that fits it.

Rules (Buck, *Greek Dialects* §§ 8, 25, 41, 57, 77, 86, 104; Hamm, *Grammatik zu
Sappho und Alkaios*; Smyth §§ 70, 124):
  ᾱ for η              Doric/Aeolic ᾱ where Attic-Ionic has η (σελάνα -> σελήνη)
  geminate             Aeolic νν μμ λλ ρρ σσ ππ for a single consonant, with or
                       without the Attic compensatory lengthening (ε->ει, ο->ου, α->η)
  dative plural        Aeolic -αισι(ν), -οισι(ν) for -αις, -οις
  psilosis             smooth breathing where the standard spelling has a rough one
  accent               Lesbian recessive accent: acute moved one syllable later;
                       circumflex written for an acute
  σδ / ζ               Aeolic σδ for ζ (and the reverse)
  οισ for ουσ          Aeolic -οισα, Μοῖσα for -ουσα, Μοῦσα
  ω, ο for ου          Doric ω for ου (gen. sg.), Aeolic ο for ου       (cost 2)
  ου for υ             Aeolic/Boeotian ου for υ; printed spelling only   (cost 2)
  ε for ει             Aeolic ε (short) where Attic has the spurious ει   (cost 2)
Search: breadth-first, at most MAX_RULES rule applications per spelling and
MAX_CANDIDATES spellings per form; spellings needing fewer rules are tested first
and the first depth with any analysis is the only one kept.

Elision (separate, needs no dialect): an elided form is completed with each short
vowel or diphthong (α ε ι ο αι οι), and a final θ φ χ before a word with a rough
breathing is read back as τ π κ (ἀφ’ ἵππων -> ἀπό, οὐχ -> οὐκ).
"""
from __future__ import annotations

import unicodedata

MAX_RULES = 3
MAX_CANDIDATES = 50
ELISION = "’᾽'ʼ"
VOWELS = "αεηιουω"
SMOOTH, ROUGH, ACUTE, GRAVE, CIRC, DIAER, IOTA_SUB = "̓", "̔", "́", "̀", "͂", "̈", "ͅ"
ACCENTS = (ACUTE, GRAVE, CIRC)


def _nfd(text):
    return unicodedata.normalize("NFD", text)


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def _clusters(form):
    """[(base letter, marks)] in NFD."""
    out = []
    for char in _nfd(form):
        if out and unicodedata.category(char).startswith("M"):
            out[-1][1] += char
        else:
            out.append([char, ""])
    return out


def _join(clusters):
    return _nfc("".join(base + marks for base, marks in clusters))


def _base(cluster):
    return cluster[0].lower()


def _swap(cluster, letter):
    return [letter.upper() if cluster[0].isupper() else letter, cluster[1]]


def _diphthong_second(clusters, index):
    """True when clusters[index] is the ι/υ closing a diphthong."""
    return (index > 0 and _base(clusters[index]) in "ιυ" and DIAER not in clusters[index][1]
            and _base(clusters[index - 1]) in "αεου" and not any(m in clusters[index - 1][1] for m in ACCENTS + (SMOOTH, ROUGH)))


def _opens_diphthong(clusters, index):
    return index + 1 < len(clusters) and _diphthong_second(clusters, index + 1)


# --- rules: form -> [variant] -------------------------------------------------

def alpha_for_eta(form):
    c = _clusters(form)
    return [_join(c[:i] + [_swap(c[i], "η")] + c[i + 1:]) for i in range(len(c))
            if _base(c[i]) == "α" and not _opens_diphthong(c, i)]


_LENGTHEN = {"ε": "ει", "ο": "ου", "α": "η"}


def geminate(form):
    c, out = _clusters(form), []
    for i in range(1, len(c) - 1):
        if _base(c[i]) in "νμλρσπ" and _base(c[i + 1]) == _base(c[i]) and not c[i][1] and not c[i + 1][1]:
            simple = c[:i] + c[i + 1:]
            out.append(_join(simple))
            v = c[i - 1]
            if _base(v) in _LENGTHEN and not _diphthong_second(c, i - 1):
                long = _LENGTHEN[_base(v)]
                if len(long) == 2:  # marks move to the second letter of the diphthong
                    head = [long[0].upper() if v[0].isupper() else long[0], ""]
                    out.append(_join(c[:i - 1] + [head, [long[1], v[1]]] + c[i + 1:]))
                else:
                    out.append(_join(c[:i - 1] + [_swap(v, long)] + c[i + 1:]))
    return out


def dative_plural(form):
    nfd = _nfd(form)
    plain = "".join(ch for ch in nfd if ch not in ACCENTS)
    for ending in ("αισιν", "οισιν", "αισι", "οισι"):
        if plain.endswith(ending):
            # keep everything before the ending, then -αις/-οις with a circumflex
            # when the ending carried the accent (σκιεροίσιν -> σκιεροῖς)
            cut = len(nfd)
            letters = 0
            while letters < len(ending):
                cut -= 1
                if not unicodedata.category(nfd[cut]).startswith("M"):
                    letters += 1
            tail = nfd[cut:]
            accented = any(m in tail for m in ACCENTS)
            stem = ending[:2] + "ς"
            if accented:
                stem = ending[0] + ending[1] + CIRC + "ς"
            return [_nfc(nfd[:cut] + stem)]
    return []


def psilosis(form):
    c = _clusters(form)
    if not c or SMOOTH not in "".join(m for _, m in c[:2]):
        return []
    i = 0 if SMOOTH in c[0][1] else 1
    c[i] = [c[i][0], c[i][1].replace(SMOOTH, ROUGH)]
    return [_join(c)]


def _vowel_slots(c):
    """Indices of the cluster that carries a syllable's accent (2nd of a diphthong)."""
    slots = []
    for i, (base, _) in enumerate(c):
        if base.lower() in VOWELS:
            if _diphthong_second(c, i):
                slots[-1] = i
            else:
                slots.append(i)
    return slots


def accent(form):
    c = _clusters(form)
    slots = _vowel_slots(c)
    out = []
    for k, i in enumerate(slots):
        marks = c[i][1]
        if ACUTE in marks and k + 1 < len(slots):
            moved = [list(x) for x in c]
            moved[i][1] = marks.replace(ACUTE, "")
            moved[slots[k + 1]][1] += ACUTE
            out.append(_join(moved))
        if CIRC in marks:
            swapped = [list(x) for x in c]
            swapped[i][1] = marks.replace(CIRC, ACUTE)
            out.append(_join(swapped))
    return out


def sigma_delta(form):
    nfd, out = _nfd(form), []
    if "σδ" in nfd:
        out.append(_nfc(nfd.replace("σδ", "ζ", 1)))
    if "ζ" in nfd[1:]:
        out.append(_nfc(nfd[0] + nfd[1:].replace("ζ", "σδ", 1)))
    return out


def oi_for_ou(form):
    c = _clusters(form)
    return [_join(c[:i] + [["υ" if c[i][0].islower() else "Υ", c[i][1]]] + c[i + 1:])
            for i in range(1, len(c) - 1)
            if _base(c[i]) == "ι" and _base(c[i - 1]) == "ο" and _diphthong_second(c, i) and _base(c[i + 1]) == "σ"]


def o_vowels(form):
    """Doric ω / Aeolic ο where the standard spelling has ου; the marks move to the υ."""
    c = _clusters(form)
    return [_join(c[:i] + [[_swap(c[i], "ο")[0], ""], ["υ", c[i][1]]] + c[i + 1:]) for i in range(len(c))
            if _base(c[i]) == "ω" or (_base(c[i]) == "ο" and not _opens_diphthong(c, i))]


def ou_for_u(form):
    """Aeolic/Boeotian ου for υ (Κούπρις for Κύπρις)."""
    c = _clusters(form)
    return [_join(c[:i - 1] + [[_swap(c[i - 1], "υ")[0], c[i][1]]] + c[i + 1:]) for i in range(1, len(c))
            if _base(c[i]) == "υ" and _diphthong_second(c, i) and _base(c[i - 1]) == "ο"]


def e_for_ei(form):
    c = _clusters(form)
    return [_join(c[:i] + [[c[i][0], ""], ["ι", c[i][1]]] + c[i + 1:]) for i in range(len(c))
            if _base(c[i]) == "ε" and not _opens_diphthong(c, i)]


RULES = (
    ("alpha_for_eta", "Doric/Aeolic", "ᾱ for η", alpha_for_eta),
    ("geminate", "Aeolic", "double consonant for a single one (with or without lengthening)", geminate),
    ("dative_plural", "Aeolic", "-αισι(ν)/-οισι(ν) for -αις/-οις", dative_plural),
    ("psilosis", "Aeolic", "smooth breathing for rough", psilosis),
    ("oi_for_ou", "Aeolic", "οι for ου before σ (-οισα, Μοῖσα)", oi_for_ou),
    ("sigma_delta", "Aeolic", "σδ for ζ", sigma_delta),
    ("accent", "Aeolic", "recessive accent", accent),
    ("e_for_ei", "Aeolic", "ε for ει", e_for_ei),
    ("o_vowels", "Doric/Aeolic", "ω or ο where the standard spelling has ου", o_vowels),
    ("ou_for_u", "Aeolic", "ου for υ", ou_for_u),
)
# Weaker correspondences cost two: a spelling explained by cheaper rules wins.
COST = {"e_for_ei": 2, "o_vowels": 2, "ou_for_u": 2}
# Applied to the printed spelling only, never to a generated one.
FIRST_ONLY = {"ou_for_u"}
_RULE = {name: (dialect, note) for name, dialect, note, _ in RULES}


def generate(form, max_rules=MAX_RULES, limit=MAX_CANDIDATES):
    """[(spelling, (rule, ...))] breadth-first; each spelling once, original excluded."""
    form = _nfc(form)
    seen, frontier, out = {form}, [(form, ())], []
    for _ in range(max_rules):
        nxt = []
        for spelling, applied in frontier:
            for name, _, _, rule in RULES:
                if name in FIRST_ONLY and applied:
                    continue
                for variant in rule(spelling):
                    if variant and variant not in seen:
                        seen.add(variant)
                        out.append((variant, applied + (name,)))
                        nxt.append((variant, applied + (name,)))
                        if len(out) >= limit:
                            return out
        frontier = nxt
    return out


def elision_completions(form, next_form=None):
    """[(spelling, (rule, ...))] for an elided form, or a final θ/φ/χ before a rough breathing."""
    form = _nfc(form)
    elided = form[-1:] in ELISION
    stem = form[:-1] if elided else form
    if not stem or (elided and not any(ch.lower() in VOWELS for ch in _nfd(stem))):
        return []  # a lone consonant with a mark (δ’, μ’) is left to the parser
    stems = [(stem, ())]
    nxt = _nfd(next_form or "")
    if stem[-1] in "θφχ" and (ROUGH in nxt[:3] or nxt[:1].lower() == "ῥ"):
        stems.append((stem[:-1] + {"θ": "τ", "φ": "π", "χ": "κ"}[stem[-1]], ("aspirate_reversed",)))
    out = []
    accented = any(m in _nfd(stem) for m in ACCENTS)
    for base, applied in stems:
        if not elided:
            out.append((base, applied))
            continue
        for vowel in ("α", "ε", "ι", "ο", "αι", "οι"):
            out.append((base + vowel, applied + ("elision_completed",)))
            if not accented:  # the restored vowel may carry the word's accent (οὐδ’ -> οὐδέ)
                out.append((_nfc(base + vowel[0] + ACUTE + vowel[1:] if len(vowel) == 1
                                 else base + vowel[0] + vowel[1] + ACUTE), applied + ("elision_completed",)))
            elif GRAVE in _nfd(base):
                out.append((_nfc(_nfd(base).replace(GRAVE, ACUTE) + vowel), applied + ("elision_completed",)))
    seen, unique = {form}, []
    for spelling, applied in out:
        spelling = _nfc(spelling)
        if spelling not in seen:
            seen.add(spelling)
            unique.append((spelling, applied))
    return unique


def describe(rules):
    if "elision_completed" in rules or "aspirate_reversed" in rules:
        parts = (["elided vowel restored"] if "elision_completed" in rules else []) + \
                (["θ/φ/χ before a rough breathing read as τ/π/κ"] if "aspirate_reversed" in rules else [])
        return "Projection: " + "; ".join(parts)
    dialects = sorted({_RULE[r][0] for r in rules})
    return "Normalised from " + " and ".join(dialects) + " via " + "; ".join(_RULE[r][1] for r in rules)


def generate_and_test(form, analyze, next_form=None):
    """Ask `analyze(spelling)` (a machine-morphology result) about generated spellings.

    Returns (accepted, tried): accepted = [(spelling, rules, result)] from the first
    cost (fewest rule applications, weak rules counting two) at which anything parses.
    """
    candidates = elision_completions(form, next_form)
    if _nfc(form)[-1:] not in ELISION:
        candidates += generate(form)
    tried, by_depth = [], {}
    for spelling, rules in candidates:
        # θ/φ/χ before a rough breathing is assimilation, the primary reading: no extra depth.
        cost = sum(COST.get(r, 1) for r in rules if r != "aspirate_reversed")
        by_depth.setdefault(cost, []).append((spelling, rules))
    for depth in sorted(by_depth):
        accepted = []
        for spelling, rules in by_depth[depth]:
            result = analyze(spelling)
            status = result.get("status")
            tried.append({"form": spelling, "rules": list(rules), "status": status})
            if status == "ok" and result.get("machine_candidates"):
                accepted.append((spelling, rules, result))
        if accepted:
            return accepted, tried
    return [], tried
