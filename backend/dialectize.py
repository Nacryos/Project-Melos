"""Release U: Attic/standard spelling -> Lesbian, Doric or Ionic candidate spellings.

The reverse of ``dialect_generate`` (which reads a printed dialect form back to the standard spelling for the
parser). Every rule is orthographic and general (Buck, *Greek Dialects* §§ 8, 41, 54, 57, 68, 77, 86, 104;
Hamm, *Grammatik zu Sappho und Alkaios*; Smyth §§ 30-31, 70); the only lexical table is the Lesbian function-word
table of ``aeolic_variants.LEXICAL`` read in reverse. Rules may combine (at most ``MAX_RULES`` applications).

A generated spelling is never offered on the rules' word alone. It is accepted only when
  (a) the exact spelling is printed in the corpus (lemma index ``form`` table) under a headword that is the input's
      headword, one of its dictionary variants, or the same headword in a dialect spelling; and/or
  (b) local Morpheus analyses it with a lemma that maps back to the input's headword in the same way.
Each accepted candidate names its rules, the dialect, and the evidence (attesting authors, an example citation,
the parses with Morpheus' dialect label).
"""
from __future__ import annotations

import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from .dialect_generate import ACUTE, CIRC, GRAVE, ROUGH, SMOOTH, _base, _clusters, _diphthong_second, _join, _nfc, \
    _opens_diphthong, _swap, _vowel_slots

LESBIAN, DORIC, IONIC = "lesbian", "doric", "ionic"
DIALECTS = (LESBIAN, DORIC, IONIC)
MAX_RULES = 3
MAX_SPELLINGS = 160          # generated spellings per form and dialect (all looked up in one batch)
MAX_PARSES = 6               # unattested spellings sent to the parser per form and dialect (cheapest first)
MAX_FORMS = 50
CONSONANTS_TO_DOUBLE = "νμλρσ"
LONG_LETTERS = "ηω"
DICHRONA = "αιυ"


def key(text):
    """Letters only, lower case, final sigma folded: the comparison key for spellings and headwords."""
    nfd = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in nfd if unicodedata.category(c).startswith("L")).lower().replace("ς", "σ")


def _grave_to_acute(form):
    return _nfc(unicodedata.normalize("NFD", form).replace(GRAVE, ACUTE))


def _final_sigma(form):
    return form[:-1] + "ς" if form.endswith("σ") else form


def _mark_move(c, src, dst, mark):
    out = [list(x) for x in c]
    out[src][1] = out[src][1].replace(mark, "")
    out[dst][1] += mark
    return out


# --- rules: form -> [variant] -------------------------------------------------------------------------------

def eta_to_alpha(form):
    """ᾱ for η (Doric, Lesbian): each η separately and all of them at once (σελήνη -> σελάνα)."""
    c = _clusters(form)
    idx = [i for i in range(len(c)) if _base(c[i]) == "η" and not _opens_diphthong(c, i)]
    out = [_join(c[:i] + [_swap(c[i], "α")] + c[i + 1:]) for i in idx]
    if len(idx) > 1:
        out.append(_join([_swap(x, "α") if i in idx else x for i, x in enumerate(c)]))
    return out


def alpha_to_eta(form):
    """Ionic η for the ᾱ Attic keeps after ε, ι, ρ (χώρα -> χώρη, νεηνίης)."""
    c = _clusters(form)
    return [_join(c[:i] + [_swap(c[i], "η")] + c[i + 1:]) for i in range(1, len(c))
            if _base(c[i]) == "α" and _base(c[i - 1]) in "ειρ" and not _opens_diphthong(c, i)
            and not _diphthong_second(c, i)]


def geminate(form):
    """Lesbian double consonant where Attic lengthened the vowel before a single one (Buck § 77):
    ει -> ε, ου -> ο, η -> α + doubled ν μ λ ρ σ (εἰμί -> ἐμμί, σελάνα -> σελάννα, φθείρω -> φθέρρω)."""
    c, out = _clusters(form), []
    for i in range(1, len(c) - 1):
        if _base(c[i]) not in CONSONANTS_TO_DOUBLE or c[i][1] or _base(c[i + 1]) not in "αεηιουωᾳῃῳ":
            continue
        if _base(c[i - 1]) == _base(c[i]) or (i + 1 < len(c) and _base(c[i + 1]) == _base(c[i])):
            continue
        double = [[c[i][0], ""], [c[i][0], ""]]
        prev = _base(c[i - 1])
        if _diphthong_second(c, i - 1) and prev in "ιυ" and _base(c[i - 2]) in "εο":
            # ει / ου: the marks of the diphthong's second letter move to the short vowel
            head = [c[i - 2][0], c[i - 2][1] + c[i - 1][1]]
            out.append(_join(c[:i - 2] + [head] + double + c[i + 1:]))
        elif prev == "η":
            out.append(_join(c[:i - 1] + [_swap(c[i - 1], "α")] + double + c[i + 1:]))
        elif prev in "αειουω":
            out.append(_join(c[:i] + double + c[i + 1:]))
    return out


def oi_before_sigma(form):
    """Lesbian οι for ου before σ (-ουσα -> -οισα, Μοῦσα -> Μοῖσα, 3rd pl. -ουσι -> -οισι)."""
    c = _clusters(form)
    return [_join(c[:i] + [["ι", c[i][1]]] + c[i + 1:]) for i in range(1, len(c) - 1)
            if _base(c[i]) == "υ" and _base(c[i - 1]) == "ο" and _diphthong_second(c, i) and _base(c[i + 1]) == "σ"]


def ai_before_sigma(form):
    """Lesbian αι for a long α before σ from -νσ- (πᾶσα -> παῖσα, πᾶς -> παῖς, τάλας -> τάλαις,
    aor. participle -ασα -> -αισα)."""
    c = _clusters(form)
    out = []
    for i in range(len(c) - 1):
        if _base(c[i]) == "α" and not _opens_diphthong(c, i) and not _diphthong_second(c, i) \
                and _base(c[i + 1]) in "σς" and (i + 2 == len(c) or _base(c[i + 2]) in "αεηιουω"):
            marks = c[i][1].replace(CIRC, ACUTE) if CIRC in c[i][1] else c[i][1]
            breath = "".join(m for m in marks if m in (SMOOTH, ROUGH))
            accent = "".join(m for m in marks if m not in (SMOOTH, ROUGH))
            accent = CIRC if CIRC in c[i][1] else accent
            out.append(_join(c[:i] + [[c[i][0], breath], ["ι", accent]] + c[i + 1:]))
    return out


def infinitive_ein(form):
    """Lesbian -ην for the infinitive -ειν (ἄγειν -> ἄγην, ἰδεῖν -> ἴδην after the accent rule)."""
    nfd = unicodedata.normalize("NFD", form)
    for ending, new in (("ει" + CIRC + "ν", "η" + CIRC + "ν"), ("ειν", "ην")):
        if nfd.endswith(ending):
            return [_nfc(nfd[: -len(ending)] + new)]
    return []


def infinitive_ein_doric(form):
    """Doric (severior) -εν / -ην for the infinitive -ειν (ἄγειν -> ἄγεν)."""
    nfd = unicodedata.normalize("NFD", form)
    if nfd.endswith("ει" + CIRC + "ν"):
        return [_nfc(nfd[:-4] + "ε" + ACUTE + "ν"), _nfc(nfd[:-4] + "η" + CIRC + "ν")]
    if nfd.endswith("ειν"):
        return [_nfc(nfd[:-3] + "εν"), _nfc(nfd[:-3] + "ην")]
    return []


def psilosis(form):
    """Smooth breathing for rough (Lesbian, East Ionic): ἥλιος -> ἤλιος, ὑμεῖς -> ὐμεῖς."""
    c = _clusters(form)
    for i in range(min(2, len(c))):
        if ROUGH in c[i][1] and _base(c[i]) in "αεηιουω":
            c = [list(x) for x in c]
            c[i][1] = c[i][1].replace(ROUGH, SMOOTH)
            return [_join(c)]
    return []


def recessive_accent(form):
    """Lesbian recessive accent: the accent moves one syllable towards the beginning (θυμός -> θῦμος / θύμος,
    εἰμί -> εἶμι). Circumflex and acute are both offered on a vowel that can be long; the parser and the corpus
    decide."""
    c = _clusters(_grave_to_acute(form))
    slots = _vowel_slots(c)
    out = []
    for k, i in enumerate(slots):
        marks = c[i][1]
        mark = ACUTE if ACUTE in marks else CIRC if CIRC in marks else None
        if not mark:
            continue
        if k == 0:
            if CIRC in marks:  # circumflex written as acute (Lesbian barytone: κᾶρυξ -> κάρυξ)
                swapped = [list(x) for x in c]
                swapped[i][1] = marks.replace(CIRC, ACUTE)
                out.append(_join(swapped))
            break
        j = slots[k - 1]
        moved = _mark_move(c, i, j, mark)
        acute = [list(x) for x in moved]
        acute[j][1] = acute[j][1].replace(CIRC, ACUTE)
        out.append(_join(acute))
        letter = _base(c[j])
        if (letter in LONG_LETTERS or letter in DICHRONA or _diphthong_second(c, j)) and k == len(slots) - 1:
            circ = [list(x) for x in moved]
            circ[j][1] = circ[j][1].replace(ACUTE, CIRC).replace(CIRC + CIRC, CIRC)
            if CIRC not in circ[j][1]:
                circ[j][1] += CIRC
            out.append(_join(circ))
        if CIRC in marks:  # circumflex written as acute in place (Lesbian barytone of a long syllable)
            swapped = [list(x) for x in c]
            swapped[i][1] = marks.replace(CIRC, ACUTE)
            out.append(_join(swapped))
        break
    return out


def uncontracted_eta(form):
    """Aeolic/epic αε where Attic contracted it to η (ἥλιος -> ἀέλιος with psilosis, epic ἠέλιος):
    the breathing stays on the first vowel, the accent goes to the second."""
    c = _clusters(_grave_to_acute(form))
    out = []
    for i in range(len(c)):
        if _base(c[i]) != "η" or _opens_diphthong(c, i):
            continue
        marks = c[i][1]
        breath = "".join(m for m in marks if m in (SMOOTH, ROUGH))
        acc = ACUTE if (ACUTE in marks or CIRC in marks) else ""
        first = ["Α" if c[i][0].isupper() else "α", breath]
        out.append(_join(c[:i] + [first, ["ε", acc]] + c[i + 1:]))
    return out


def labiovelar_p(form):
    """Aeolic π where Attic has τ before a front vowel from a labiovelar (τηλόθεν -> πήλοθεν, τέσσαρες -> πέσσυρες)."""
    c = _clusters(form)
    if len(c) > 1 and _base(c[0]) == "τ" and _base(c[1]) in "εη":
        return [_join([_swap(c[0], "π")] + c[1:])]
    return []


def zeta_sd(form):
    """Lesbian σδ for ζ (ζυγόν -> σδυγόν, ὄζος -> ὄσδος)."""
    nfd = unicodedata.normalize("NFD", form)
    return [_nfc(nfd.replace("ζ", "σδ", 1))] if "ζ" in nfd else []


def dative_plural(form):
    """Lesbian/Ionic -αισι(ν), -οισι(ν) (Ionic -ῃσι) for the dative plural -αις, -οις."""
    nfd = unicodedata.normalize("NFD", form)
    out = []
    for stem, accented in (("αι", "αι" + CIRC), ("οι", "οι" + CIRC)):
        if nfd.endswith(accented + "ς"):
            base = nfd[: -len(accented) - 1]
            out += [_nfc(base + stem[0] + stem[1] + ACUTE + "σι"), _nfc(base + stem[0] + stem[1] + ACUTE + "σιν")]
        elif nfd.endswith(stem + "ς"):
            base = nfd[:-3]
            out += [_nfc(base + stem + "σι"), _nfc(base + stem + "σιν")]
    return out


def dative_plural_ionic(form):
    nfd = unicodedata.normalize("NFD", form)
    if nfd.endswith("αι" + CIRC + "ς"):
        return [_nfc(nfd[:-4] + "η" + "ͅ" + "σι")]
    if nfd.endswith("αις"):
        return [_nfc(nfd[:-3] + "η" + "ͅ" + "σι")]
    return dative_plural(form) if nfd.replace(ACUTE, "").replace(CIRC, "").endswith("οις") else []


def genitive_plural_an(form):
    """Doric/Aeolic -ᾶν for the first-declension genitive plural -ῶν (Μουσῶν -> Μοισᾶν)."""
    nfd = unicodedata.normalize("NFD", form)
    return [_nfc(nfd[:-3] + "α" + CIRC + "ν")] if nfd.endswith("ω" + CIRC + "ν") else []


def genitive_o(form):
    """Doric/Lesbian -ω for the second-declension genitive singular -ου (τοῦ -> τῶ, θεοῦ -> θεῶ)."""
    nfd = unicodedata.normalize("NFD", form)
    if nfd.endswith("ου" + CIRC):
        return [_nfc(nfd[:-3] + "ω" + CIRC)]
    if nfd.endswith("ου"):
        return [_nfc(nfd[:-2] + "ω")]
    return []


def ionic_lengthening(form):
    """Ionic ου, ει where Attic has ο, ε before ν, ρ, λ after a lost digamma (μόνος -> μοῦνος, ξένος -> ξεῖνος)."""
    c, out = _clusters(_grave_to_acute(form)), []
    for i in range(len(c) - 1):
        if _base(c[i]) in "εο" and not _opens_diphthong(c, i) and _base(c[i + 1]) in "νρλ":
            second = "υ" if _base(c[i]) == "ο" else "ι"
            marks = c[i][1]
            breath = "".join(m for m in marks if m in (SMOOTH, ROUGH))
            if ACUTE in marks:
                out.append(_join(c[:i] + [[c[i][0], ""], [second, breath + CIRC]] + c[i + 1:]))
                out.append(_join(c[:i] + [[c[i][0], ""], [second, breath + ACUTE]] + c[i + 1:]))
            else:
                out.append(_join(c[:i] + [[c[i][0], ""], [second, breath]] + c[i + 1:]))
    return out


def pi_to_kappa(form):
    """Ionic κ for π in interrogatives and indefinites (πῶς -> κῶς, ὅπου -> ὅκου, πότε -> κότε)."""
    c = _clusters(form)
    return [_join(c[:i] + [_swap(c[i], "κ")] + c[i + 1:]) for i in range(len(c) - 1)
            if _base(c[i]) == "π" and _base(c[i + 1]) in "οω" and (i == 0 or (i == 1 and _base(c[0]) == "ο"))]


def temporal_ka(form):
    """Doric -κα, Lesbian -τα for -τε in temporal adverbs (ὅτε -> ὅκα / ὄτα, πότε -> πόκα / πότα)."""
    nfd = unicodedata.normalize("NFD", form)
    plain = key(form)
    if not plain.endswith("τε") or len(plain) > 6:
        return []
    return [_nfc(nfd[: nfd.rfind("τ")] + "κα" + nfd[nfd.rfind("τ") + 2:])]


def temporal_ta(form):
    nfd = unicodedata.normalize("NFD", form)
    plain = key(form)
    if not plain.endswith("τε") or len(plain) > 6:
        return []
    return [_nfc(nfd[: nfd.rfind("ε")] + "α" + nfd[nfd.rfind("ε") + 1:])]


def first_plural_mes(form):
    """Doric -μες for the first person plural -μεν (λέγομεν -> λέγομες)."""
    return [form[:-1] + "ς"] if form.endswith("μεν") and len(form) > 4 else []


def _lexical_table():
    from .aeolic_variants import LEXICAL
    table = {}
    for printed, (standard, note) in LEXICAL.items():
        table.setdefault(_nfc(standard), []).append((_nfc(printed), note))
    return table


_LEXICAL = None


def lesbian_lexical(form):
    """Lesbian function words read in reverse from aeolic_variants.LEXICAL (ἐκεῖνος -> κῆνος, ὅτι -> ὄττι)."""
    global _LEXICAL
    if _LEXICAL is None:
        _LEXICAL = _lexical_table()
    return [p for p, _ in _LEXICAL.get(_nfc(_grave_to_acute(form)), [])]


def feminine(form):
    """Not a dialect rule: the feminine of an adjective headword in -ος (μόνος -> μόνη / μόνα), so a feminine
    dialect form can be asked for by the masculine headword."""
    nfd = unicodedata.normalize("NFD", form)
    if not nfd.endswith("ος") or len(key(form)) < 4:
        return []
    stem = nfd[:-2]
    letters = key(stem)
    return [_nfc(stem + ("α" if letters[-1:] in ("ε", "ι", "ρ") else "η"))]


# id -> (dialects, description, function, cost)
RULES = {
    "eta_to_alpha": ((LESBIAN, DORIC), "ᾱ for Attic-Ionic η", eta_to_alpha, 1),
    "geminate": ((LESBIAN,), "double ν μ λ ρ σ for a single consonant after a lengthened vowel (ει, ου, η -> ε, ο, α)", geminate, 1),
    "oi_before_sigma": ((LESBIAN,), "οι for ου before σ (-οισα, Μοῖσα, 3rd pl. -οισι)", oi_before_sigma, 1),
    "ai_before_sigma": ((LESBIAN,), "αι for long α before σ (παῖσα, -αισα)", ai_before_sigma, 2),
    "infinitive_ein": ((LESBIAN,), "infinitive -ην for -ειν", infinitive_ein, 1),
    "infinitive_ein_doric": ((DORIC,), "infinitive -εν / -ην for -ειν", infinitive_ein_doric, 1),
    "psilosis": ((LESBIAN, IONIC), "smooth breathing for rough (psilosis)", psilosis, 1),
    "recessive_accent": ((LESBIAN,), "recessive accent (barytonesis)", recessive_accent, 1),
    "uncontracted_eta": ((LESBIAN,), "αε where Attic contracted to η (ἀέλιος)", uncontracted_eta, 2),
    "labiovelar_p": ((LESBIAN,), "π for τ before a front vowel from a labiovelar (πήλοθεν)", labiovelar_p, 2),
    "zeta_sd": ((LESBIAN,), "σδ for ζ", zeta_sd, 1),
    "dative_plural": ((LESBIAN,), "dative plural -αισι(ν), -οισι(ν)", dative_plural, 1),
    "dative_plural_ionic": ((IONIC,), "dative plural -ῃσι, -οισι", dative_plural_ionic, 1),
    "genitive_plural_an": ((LESBIAN, DORIC), "first-declension genitive plural -ᾶν for -ῶν", genitive_plural_an, 1),
    "genitive_o": ((DORIC, LESBIAN), "second-declension genitive singular -ω for -ου", genitive_o, 2),
    "ionic_lengthening": ((IONIC,), "ου, ει for ο, ε before ν ρ λ (μοῦνος, ξεῖνος)", ionic_lengthening, 2),
    "alpha_to_eta": ((IONIC,), "η for the ᾱ Attic keeps after ε, ι, ρ", alpha_to_eta, 1),
    "pi_to_kappa": ((IONIC,), "κ for π in interrogatives and indefinites (κῶς, ὅκου)", pi_to_kappa, 2),
    "temporal_ka": ((DORIC,), "-κα for -τε in temporal adverbs (ὅκα)", temporal_ka, 1),
    "temporal_ta": ((LESBIAN,), "-τα for -τε in temporal adverbs (ὄτα)", temporal_ta, 1),
    "first_plural_mes": ((DORIC,), "first person plural -μες for -μεν", first_plural_mes, 2),
    "lesbian_lexical": ((LESBIAN,), "Lesbian function word (aeolic_variants.LEXICAL, reversed)", lesbian_lexical, 1),
    "feminine": ((LESBIAN, DORIC, IONIC), "feminine of an adjective in -ος (not a dialect rule)", feminine, 1),
}
FIRST_ONLY = {"feminine", "lesbian_lexical"}
NOT_DIALECT = {"feminine"}


def describe(rule_id):
    dialects, text, _, _ = RULES[rule_id]
    return {"id": rule_id, "description": text, "dialects": list(dialects)}


def generate(form, dialect, max_rules=MAX_RULES, limit=MAX_SPELLINGS, adjective=True):
    """[(spelling, (rule, ...), cost)] breadth-first for one dialect; each spelling once, the input excluded.
    ``adjective=False`` (the headword is known not to be an adjective) leaves out the feminine expansion."""
    form = _nfc(form.strip())
    names = [name for name, (dialects, *_rest) in RULES.items() if dialect in dialects
             and (adjective or name != "feminine")]
    seen, frontier, out = {form}, [(form, ())], []
    for _ in range(max_rules):
        nxt = []
        for spelling, applied in frontier:
            for name in names:
                if name in applied or (name in FIRST_ONLY and applied):
                    continue
                for variant in RULES[name][2](spelling):
                    variant = _final_sigma(_nfc(variant))
                    if variant and variant not in seen:
                        seen.add(variant)
                        rules = applied + (name,)
                        nxt.append((variant, rules))
                        if set(rules) <= NOT_DIALECT:
                            continue  # the Attic feminine itself (μόνη) is no dialect spelling
                        out.append((variant, rules, sum(RULES[r][3] for r in rules)))
                        if len(out) >= limit:
                            return sorted(out, key=lambda x: x[2])
        frontier = nxt
    return sorted(out, key=lambda x: x[2])


# --- evidence backends ----------------------------------------------------------------------------------------

class IndexEvidence:
    """Corpus attestation from the lemma index (exact printed spelling)."""

    def __init__(self, index=None):
        self._index = index
        self._dialect_of = None
        self._lock = threading.Lock()

    @property
    def index(self):
        if self._index is None:
            from .lemma_index import get_index
            self._index = get_index()
        return self._index

    CODES = (None, LESBIAN, DORIC, "boeotian")

    def dialect_of_pid(self):
        """numpy int8 per passage: index into CODES (passage_dialect by author label, else by the poet named in the
        passage id), computed once."""
        with self._lock:
            if self._dialect_of is None:
                import numpy as np
                from .passage_dialect import _ID_POETS, _LOOKUP, _key, passage_dialect
                ix = self.index
                by_author = {}
                out = np.zeros(len(ix.pid_id), dtype=np.int8)
                for pid, label in enumerate(ix.author_of):
                    pid_text = ix.pid_id[pid]
                    if pid_text is None:
                        continue
                    if label not in by_author:
                        by_author[label] = passage_dialect({"author": label})
                    found = by_author[label]
                    if not found:
                        part = pid_text.split(":")[1:2]
                        found = _LOOKUP[_key(part[0])] if part and _key(part[0]) in _ID_POETS else None
                    if found in self.CODES:
                        out[pid] = self.CODES.index(found)
                self._dialect_of = out
            return self._dialect_of

    def forms(self, spellings):
        """{spelling: {"form_ids": [...], "tokens": n, "lemmas": [(lemma_id, lemma)]}} for spellings printed in the corpus."""
        spellings = list(dict.fromkeys(spellings))
        out = {}
        con = self.index.con()
        for start in range(0, len(spellings), 400):
            chunk = spellings[start:start + 400]
            rows = con.execute(
                f"SELECT f.id, f.form, f.tokens, l.id, l.lemma FROM form f LEFT JOIN form_lemma fl ON fl.form_id=f.id "
                f"LEFT JOIN lemma l ON l.id=fl.lemma_id WHERE f.form IN ({','.join('?' * len(chunk))}) ORDER BY fl.rank",
                chunk).fetchall()
            for fid, form, tokens, lid, lemma in rows:
                item = out.setdefault(form, {"form_ids": [], "tokens": 0, "lemmas": []})
                if fid not in item["form_ids"]:
                    item["form_ids"].append(fid)
                    item["tokens"] += int(tokens or 0)
                if lid is not None and (lid, lemma) not in item["lemmas"]:
                    item["lemmas"].append((lid, lemma))
        return out

    def related_keys(self, lemma_ids):
        """Keys of the headwords linked to these (variant groups, capitalisation)."""
        keys = set()
        ix = self.index
        for lid in lemma_ids:
            try:
                for other in ix.expand_variants([int(lid)]):
                    keys.add(key((ix.lemma_row(other) or {}).get("lemma")))
            except Exception:  # noqa: BLE001 - an older index without variant tables
                pass
        return keys

    def headwords(self, form):
        hit = self.forms([_nfc(form)]).get(_nfc(form))
        return [(lid, lemma) for lid, lemma in (hit or {}).get("lemmas", [])[:3]]

    def is_adjective(self, lemma_id):
        """True / False from the headword's part of speech; None when unknown."""
        if lemma_id is None:
            return None
        pos = ((self.index.lemma_row(lemma_id) or {}).get("pos") or "").lower()
        return pos.startswith("adj") if pos else None

    def dialect_forms(self, code):
        """{form id: [tokens, {author: tokens}, first pid]} over every passage of one dialect code (edited text
        first, so the first pid is an edited passage when there is one). Built once per dialect on first use."""
        with self._lock:
            table = self.__dict__.setdefault("_dialect_forms", {}).get(code)
        if table is not None:
            return table
        import numpy as np
        ix = self.index
        codes = self.dialect_of_pid()
        pids = np.flatnonzero(codes == code)
        pids = np.concatenate([pids[ix.edited[pids]], pids[~ix.edited[pids]]])
        table = {}
        for pid in pids.tolist():
            toks = ix.tokens(pid)
            if toks is None:
                continue
            info = ix.authors.get(ix.author_of[pid]) or {}
            name = info.get("author") or ix.author_of[pid]
            values, counts = np.unique(toks[1], return_counts=True)
            for fid, n in zip(values.tolist(), counts.tolist()):
                row = table.get(fid)
                if row is None:
                    table[fid] = row = [0, {}, pid]
                row[0] += n
                row[1][name] = row[1].get(name, 0) + n
        with self._lock:
            self._dialect_forms[code] = table
        return table

    def attestation(self, spelling, form_ids, lemma_ids, dialect, author="", other_scan=20):
        """Tokens of this exact spelling in every passage of the dialect's authors, per author, with one citation
        (a dialect passage when there is one, else one of up to ``other_scan`` passages holding the headword)."""
        import numpy as np
        ck = (spelling, tuple(form_ids), dialect, author)
        with self._lock:
            cached = getattr(self, "_att_cache", {}).get(ck)
        if cached is not None:
            return cached
        ix = self.index
        code = self.CODES.index(dialect) if dialect in self.CODES and dialect else -1
        wanted_author = key(author) if author else ""
        authors, tokens, first = {}, 0, None
        if code > 0:
            table = self.dialect_forms(code)
            for fid in form_ids:
                row = table.get(int(fid))
                if row:
                    tokens += row[0]
                    for name, n in row[1].items():
                        authors[name] = authors.get(name, 0) + n
                    first = row[2] if first is None or (not ix.edited[first] and ix.edited[row[2]]) else first
        example = None
        if first is not None:
            rec = ix.record(int(first))
            example = {"passage_id": rec["id"], "author": rec["author"], "citation": rec.get("citation"),
                       "work": rec.get("display_work") or rec.get("work"), "dialect": dialect}
        else:
            fids = np.asarray(sorted(int(f) for f in form_ids), dtype=np.uint32)
            for lid in lemma_ids[:2]:
                rows = ix.con().execute("SELECT pid FROM posting WHERE lemma_id=? LIMIT 400", (int(lid),)).fetchall()
                pids = np.asarray([r[0] for r in rows], dtype=np.int64)
                pids = np.concatenate([pids[ix.edited[pids]], pids[~ix.edited[pids]]]) if len(pids) else pids
                for pid in pids[:other_scan].tolist():
                    toks = ix.tokens(pid)
                    if toks is not None and np.isin(toks[1], fids).any():
                        rec = ix.record(pid)
                        example = {"passage_id": rec["id"], "author": rec["author"], "citation": rec.get("citation"),
                                   "work": rec.get("display_work") or rec.get("work"), "dialect": None}
                        break
                if example:
                    break
        author_tokens = None
        if wanted_author:
            author_tokens = sum(n for name, n in authors.items() if key(name) == wanted_author)
        value = {"dialect_tokens": tokens, "dialect_tokens_capped": False,
                 "dialect_authors": [{"author": a, "tokens": n} for a, n in sorted(authors.items(), key=lambda kv: -kv[1])],
                 "author_tokens": author_tokens, "example": example}
        with self._lock:
            cache = self.__dict__.setdefault("_att_cache", {})
            if len(cache) > 20000:
                cache.clear()
            cache[ck] = value
        return value


class ParserEvidence:
    """Local Morpheus (no courtesy quota for the local engine); results cached per spelling."""

    def __init__(self, analyze=None, cache_size=20000):
        self._analyze = analyze
        self._service = None
        self._cache = {}
        self._lock = threading.Lock()
        self.cache_size = cache_size

    def available(self):
        if self._analyze is not None:
            return True
        try:
            from .machine_morphology import local_endpoint
            return bool(local_endpoint())
        except (ImportError, ValueError):
            return False

    def _call(self, spelling):
        if self._analyze is not None:
            return self._analyze(spelling)
        if self._service is None:
            from .machine_morphology import get_service
            self._service = get_service()
        result = self._service.analyze(spelling, "dialectize-internal", fetch=True) or {}
        if result.get("status") != "ok":
            return []
        parses = []
        for cand in result.get("machine_candidates") or []:
            feats = cand.get("features") or {}
            parse = " ".join(str(feats[k]) for k in ("pofs", "case", "gend", "num", "pers", "tense", "mood", "voice")
                             if feats.get(k))
            parses.append({"lemma": cand.get("lemma"), "parse": parse, "dialect_tag": feats.get("dial")})
        return parses

    def parse(self, spelling):
        with self._lock:
            if spelling in self._cache:
                return self._cache[spelling]
        value = self._call(spelling)
        with self._lock:
            if len(self._cache) > self.cache_size:
                self._cache.clear()
            self._cache[spelling] = value
        return value


# --- service --------------------------------------------------------------------------------------------------

def _strip_digits(lemma):
    return key("".join(ch for ch in str(lemma or "") if not ch.isdigit()))


class Dialectizer:
    def __init__(self, index_evidence=None, parser_evidence=None, max_parses=MAX_PARSES):
        self.index = index_evidence or IndexEvidence()
        self.parser = parser_evidence or ParserEvidence()
        self.max_parses = max_parses
        self._pool = ThreadPoolExecutor(max_workers=8)

    def _target_keys(self, form, headwords, dialect):
        """Keys a candidate's headword may have to count as the input's word: the input and its headwords and
        their dictionary variant groups. (The index files printed dialect forms under the Attic headword:
        σελάννα under σελήνη, πήλοθεν under τηλόθεν; a headword merely spelled by the same rules, κάλλος for
        καλός, is another word.)"""
        keys = {key(form)} | {_strip_digits(h) for _, h in headwords}
        keys |= self.index.related_keys([lid for lid, _ in headwords if lid is not None])
        return {k for k in keys if k}

    def dialectize_one(self, form, dialect, *, author="", debug=False, parse_attested=False, use_parser=True):
        form = _nfc(str(form or "").strip())
        started = time.perf_counter()
        headwords = self.index.headwords(form)
        if not headwords and use_parser and self.parser.available():
            headwords = [(None, p["lemma"]) for p in self.parser.parse(form) if p.get("lemma")][:3]
        if not headwords:
            headwords = [(None, form)]
        targets = self._target_keys(form, headwords, dialect)
        is_adj = getattr(self.index, "is_adjective", lambda _lid: None)(headwords[0][0])
        generated = generate(form, dialect, adjective=is_adj is not False)
        found = self.index.forms([s for s, _, _ in generated])
        accepted, rejected, other_word = [], [], []
        to_parse = []
        for spelling, rules, cost in generated:
            hit = found.get(spelling)
            if hit:
                # The input's headword must be one of the spelling's two best-ranked readings.
                top = hit["lemmas"][:2]
                lemma_keys = {_strip_digits(l) for _, l in top}
                lemma_keys |= self.index.related_keys([lid for lid, _ in top if lid is not None])
                if lemma_keys & targets:
                    others = [l for _, l in hit["lemmas"][:4] if _strip_digits(l) not in targets]
                    accepted.append({"spelling": spelling, "rules": rules, "cost": cost, "hit": hit,
                                     "ambiguous_with": others})
                    continue
                # Printed under another headword (παῖς "child" for Lesbian παῖς = πᾶς): only the parser can
                # still accept it, flagged with the other reading.
                other_word.append((spelling, rules, cost, hit))
                continue
            to_parse.append((spelling, rules, cost))
        # An attested spelling outranks an unattested one made by the same rules (φάμα, not φάμη; σελάννα, not
        # σελάννη) or differing only in accent (θῦμος, not θύμος): the parser ignores accents and accepts mixed
        # ᾱ/η stems, so it cannot tell those apart. They are not sent to the parser.
        attested_rules = {frozenset(a["rules"]) for a in accepted}
        attested_keys = {key(a["spelling"]) for a in accepted}
        kept = []
        for spelling, rules, cost in to_parse:
            if frozenset(rules) in attested_rules or key(spelling) in attested_keys:
                rejected.append({"form": spelling, "rules": list(rules),
                                 "reason": "an attested spelling made by the same rules or letters is preferred"})
            else:
                kept.append((spelling, rules, cost))
        to_parse = kept
        other_word = [o for o in other_word if frozenset(o[1]) not in attested_rules and key(o[0]) not in attested_keys]
        # Parser budget (the local engine answers one call at a time, ~50-70 ms each): the cheapest unattested
        # spellings, fewer when the corpus already attests a spelling; attested spellings only on request.
        budget = self.max_parses if not accepted else min(2, self.max_parses)
        to_parse_now = to_parse[:budget]
        other_word = other_word[:max(2, budget)]
        parses = {}
        if use_parser and self.parser.available():
            batch = ([s for s, _, _ in to_parse_now] + [o[0] for o in other_word]
                     + ([a["spelling"] for a in accepted] if parse_attested else []))
            for spelling, result in zip(batch, self._pool.map(self.parser.parse, batch)):
                parses[spelling] = result
        out = []
        for item in accepted:
            evidence = self.index.attestation(item["spelling"], item["hit"]["form_ids"],
                                              [lid for lid, _ in item["hit"]["lemmas"]][:3], dialect, author)
            p = [x for x in parses.get(item["spelling"], []) if _strip_digits(x["lemma"]) in targets]
            cand = self._candidate(item["spelling"], dialect, item["rules"], item["cost"], item["hit"], evidence, p)
            if item["ambiguous_with"]:
                # The spelling is also read as another word (ἄγαν "very" beside ἄγω): kept, but flagged.
                cand["also_read_as"] = item["ambiguous_with"]
            out.append(cand)
        for spelling, rules, cost in to_parse_now:
            p = [x for x in parses.get(spelling, []) if _strip_digits(x["lemma"]) in targets]
            if p:
                cand = self._candidate(spelling, dialect, rules, cost, None, None, p)
                cand["accent_checked"] = False  # the parser does not check accents
                out.append(cand)
            else:
                rejected.append({"form": spelling, "rules": list(rules),
                                 "reason": "not printed in the corpus; the parser has no analysis with this headword"
                                 if parses.get(spelling) is not None else "not printed in the corpus; not parsed"})
        for spelling, rules, cost, hit in other_word:
            p = [x for x in parses.get(spelling, []) if _strip_digits(x["lemma"]) in targets]
            if p:
                evidence = self.index.attestation(spelling, hit["form_ids"], [lid for lid, _ in hit["lemmas"]][:3],
                                                  dialect, author)
                cand = self._candidate(spelling, dialect, rules, cost, hit, evidence, p)
                cand["also_read_as"] = [l for _, l in hit["lemmas"][:4] if _strip_digits(l) not in targets]
                cand["evidence"]["attestation_note"] = ("printed tokens are indexed under another headword; the "
                                                        "count is of the spelling, not of this word")
                out.append(cand)
            else:
                rejected.append({"form": spelling, "rules": list(rules), "reason": "printed under another headword: "
                                 + ", ".join(l for _, l in hit["lemmas"][:3])})
        untested = len(to_parse) - len(to_parse_now)
        out.sort(key=lambda c: (bool(c.get("also_read_as")) and not c["evidence"]["parses"],
                                c["verdict"] != "attested_in_dialect", c["verdict"] == "parses_only",
                                -(c["evidence"]["dialect_tokens"] or 0), c["cost"]))
        result = {"form": form, "dialect": dialect, "headwords": [h for _, h in headwords],
                  "candidates": out, "generated": len(generated), "parsed": len(to_parse_now) + len(other_word),
                  "untested_unattested": untested, "ms": round((time.perf_counter() - started) * 1000, 1)}
        if debug:
            result["rejected"] = rejected[:80]
        return result

    @staticmethod
    def _candidate(spelling, dialect, rules, cost, hit, evidence, parses):
        attested_in_dialect = bool(evidence and evidence["dialect_tokens"])
        if attested_in_dialect and parses:
            verdict = "attested_in_dialect"
        elif attested_in_dialect:
            verdict = "attested_in_dialect"
        elif hit and parses:
            verdict = "attested_and_parses"
        elif hit:
            verdict = "attested_elsewhere"
        else:
            verdict = "parses_only"
        ev = {"attested_tokens": int(hit["tokens"]) if hit else 0,
              "dialect_tokens": evidence["dialect_tokens"] if evidence else 0,
              "dialect_tokens_capped": bool(evidence and evidence.get("dialect_tokens_capped")),
              "attested_authors": evidence["dialect_authors"] if evidence else [],
              "author_tokens": evidence["author_tokens"] if evidence else None,
              "example_citation": evidence["example"] if evidence else None,
              "indexed_headwords": [l for _, l in hit["lemmas"][:3]] if hit else [],
              "parses": parses,
              "kind": ("attested+parses" if hit and parses else "attested" if hit else "parses")}
        return {"form": spelling, "dialect": dialect, "rules": [describe(r) for r in rules], "cost": cost,
                "evidence": ev, "verdict": verdict}

    def dialectize(self, forms, dialect="all", *, author="", debug=False, parse_attested=False, use_parser=True):
        if dialect not in DIALECTS + ("all",):
            raise ValueError("dialect must be lesbian, doric, ionic or all")
        if author and dialect == "all":
            from .passage_dialect import passage_dialect
            dialect = passage_dialect({"author": author}) or "all"
            if dialect not in DIALECTS:
                dialect = "all"
        dialects = DIALECTS if dialect == "all" else (dialect,)
        started = time.perf_counter()
        results = []
        for form in forms[:MAX_FORMS]:
            per = [self.dialectize_one(form, d, author=author, debug=debug, parse_attested=parse_attested,
                                       use_parser=use_parser)
                   for d in dialects]
            item = {"form": _nfc(str(form).strip()), "headwords": per[0]["headwords"] if per else [],
                    "candidates": [c for p in per for c in p["candidates"]],
                    "generated": sum(p["generated"] for p in per), "parsed": sum(p["parsed"] for p in per),
                    "untested_unattested": sum(p["untested_unattested"] for p in per)}
            if debug:
                item["rejected"] = [r for p in per for r in p.get("rejected", [])]
            results.append(item)
        return {"dialect": dialect, "author": author or None, "results": results,
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "rules": {name: describe(name) for name in RULES},
                "method": ("Candidate spellings come from general Attic -> dialect rules (at most three per spelling). A "
                           "candidate is kept only when the exact spelling is printed in the corpus under the input's "
                           "headword (or a dictionary variant or dialect spelling of it), or local Morpheus analyses it "
                           "with that headword. attested_in_dialect: printed by an author who writes that dialect; "
                           "attested_elsewhere / attested_and_parses: printed by other authors; parses_only: generated, "
                           "unattested, but the parser reads it. The cheapest unattested spellings are sent to the parser "
                           f"(at most {MAX_PARSES} per form and dialect, 2 when the corpus attests a spelling); "
                           "attested spellings are parsed only with parse_attested=true. The parser ignores accents "
                           "(accent_checked=false on parse-only candidates).")}


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def get_dialectizer():
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = Dialectizer()
        return _SERVICE


def warm():
    """Build the per-passage dialect table and the Lesbian and Doric spelling tables ahead of the first request."""
    service = get_dialectizer()
    if isinstance(service.index, IndexEvidence):
        service.index.dialect_of_pid()
        for code in (1, 2):
            service.index.dialect_forms(code)
        service.index.index.variant_links()


__all__ = ["generate", "Dialectizer", "IndexEvidence", "ParserEvidence", "get_dialectizer", "warm", "RULES",
           "DIALECTS"]
