"""Layer 1: metre-free scansion units with a longness probability each.

A unit is a vowel nucleus plus the consonants after it up to the next nucleus on the line
(backend/scansion/syllabify.py). For every unit the features listed in engine.FEATURES are
computed here, and the meta-grammar (rules.yaml) is evaluated on them: the `vowel` tree gives
p_vowel, the `unit` tree gives p_long, `flags` add annotations. Lexical vowel lengths are an
optional hook (lexicon=...): without it the `lex` feature is "none" and the grammar falls back to
its dichronon default.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .. import elision as project_elision
from . import engine
from .greek import ACCENTS, CIRCUMFLEX, CONSONANTS, DOUBLE_CONSONANTS, IOTA_SUB, LIQUIDS_NASALS, SMOOTH, STOPS, accentless_key
from .lexicon import DICTIONARY_SOURCES, Evidence, QuantityLexicon, lemma_keys
from .syllabify import Nucleus, Syllable, Word, consonant_units, line_spans, nuclei_of, syllabify_line, words_of

DATA = Path(__file__).resolve().parent / "data"


@dataclass
class SyllableResult:
    """One scansion unit (the metre layer treats it as a syllable)."""
    index: int
    line: int
    word: int
    start: int
    end: int
    text: str
    p_long: float
    rule: str                     # deciding unit-tree node
    path: list[str]               # unit-tree path
    vowel: dict                   # {"rule", "path", "p_long"}
    reasons: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    nstart: int = 0               # offsets of the nucleus
    nend: int = 0
    certain: bool = False

    @property
    def leaf(self) -> str:
        return self.rule

    @property
    def label(self) -> str:
        return "L" if self.p_long >= 0.9 else "S" if self.p_long <= 0.1 else "A"

    def as_dict(self) -> dict:
        return {"i": self.index, "line": self.line, "word": self.word, "start": self.start, "end": self.end,
                "nucleus": [self.nstart, self.nend], "text": self.text, "p_long": round(self.p_long, 3),
                "label": self.label, "certain": self.certain, "rule": self.rule, "path": self.path,
                "vowel": self.vowel, "reasons": self.reasons, "flags": self.flags}


@lru_cache(maxsize=1)
def digamma_keys() -> frozenset[str]:
    doc = json.loads((DATA / "digamma_monro.json").read_text(encoding="utf-8"))
    return frozenset(accentless_key(r["word"]) for r in doc["rows"] if r.get("match", True))


class Scanner:
    """scan(text) -> list of units.  `lexicon=None` runs the core grammar only."""

    def __init__(self, lexicon: QuantityLexicon | None = None, grammar: engine.Grammar | None = None,
                 rules_path: str | Path | None = None, params: dict | None = None, dialect: str = "none"):
        if grammar is None:
            grammar, errors = engine.load(rules_path, param_overrides=params)
            if errors:
                raise engine.RuleError("; ".join(errors))
        self.grammar = grammar
        self.lexicon = lexicon
        self.dialect = dialect          # "none" | "aeolic" | "doric" | "ionic" | "attic" (caller's statement)

    def scan(self, text: str) -> list[SyllableResult]:
        out: list[SyllableResult] = []
        for line_no, (a, b) in enumerate(line_spans(text)):
            words = words_of(text, a, b)
            if not words:
                continue
            units = syllabify_line(words, line_no, first_index=len(out))
            ctx = _Line(self, text, words, units)
            for k in range(len(units)):
                out.append(ctx.result(k))
        return out

    def scan_lines(self, text: str) -> list[list[SyllableResult]]:
        lines: dict[int, list[SyllableResult]] = {}
        for r in self.scan(text):
            lines.setdefault(r.line, []).append(r)
        return [lines[k] for k in sorted(lines)]


class _Line:
    def __init__(self, scanner: Scanner, text: str, words: list[Word], units: list[Syllable]):
        self.sc = scanner
        self.text = text
        self.words = words
        self.units = units
        self._nuclei = {w.index: nuclei_of(w) for w in words}
        self._ev: dict[int, Evidence] = {}
        self._dig: dict[int, bool] = {}

    # ------------------------------------------------------------------ output
    def result(self, k: int) -> SyllableResult:
        u = self.units[k]
        g = self.sc.grammar
        env = dict(g.params)
        env.update(self.features(u))
        p_vowel, vpath = g.decide(g.vowel, env)
        env["p_vowel"] = p_vowel
        p, upath = g.decide(g.unit, env)
        flags = []
        for f in g.flags:
            if f.when(env):
                d = {"id": f.id, "text": f.reason, "cite": f.cite}
                if f.p is not None:
                    d["p"] = round(float(f.p(env)), 3)
                flags.append(d)
        reasons = [{"id": vpath[-1].id, "text": vpath[-1].reason, "cite": vpath[-1].cite, "tree": "vowel"}]
        if upath[-1].id != "NATURE":
            reasons.append({"id": upath[-1].id, "text": upath[-1].reason, "cite": upath[-1].cite, "tree": "unit",
                            "detail": self._detail(u, upath[-1].id)})
        letters = self._letters(u.nucleus)
        nstart, nend = letters[0].start, letters[-1].end
        start = nstart if k > 0 else min(nstart, self.words[0].start)
        end = self._interval_end(k)
        return SyllableResult(
            index=u.index, line=u.line, word=u.word, start=start, end=end, text=self.text[start:end],
            p_long=p, rule=upath[-1].id, path=[n.id for n in upath],
            vowel={"rule": vpath[-1].id, "path": [n.id for n in vpath], "p_long": round(p_vowel, 3)},
            reasons=reasons, flags=flags, nstart=nstart, nend=nend, certain=p in (0.0, 1.0),
        )

    def _interval_end(self, k: int) -> int:
        """End of the unit: its nucleus plus the consonants after it (with an elision mark that follows one)."""
        end = self._letters(self.units[k].nucleus)[-1].end
        stop = self._letters(self.units[k + 1].nucleus)[0].start if k + 1 < len(self.units) else None
        last = end
        for w in self.words:
            for l in w.letters:
                if l.start >= end and (stop is None or l.start < stop) and l.base in CONSONANTS:
                    last = max(last, l.end)
                    if w.elided and l is w.letters[-1]:
                        last = max(last, w.end)
        if stop is None or k + 1 == len(self.units):
            w = self.words[self.units[k].word]
            if w.elided and w.letters[-1].end <= end:
                last = max(last, w.end)
        return last

    def _detail(self, u: Syllable, rule: str) -> str:
        if rule.startswith(("POS", "MCL")):
            return " ".join(("| " if b else "") + c for c, b in u.coda)
        if rule in ("COR-EXT", "DIG-HIA", "HIA-SHORT", "DIG-LEN", "EPL-INIT", "CONS-VOW"):
            nw = u.word + 1
            return "before " + self.words[nw].text if nw < len(self.words) else ""
        return ""

    # ------------------------------------------------------------------ features
    def _letters(self, n: Nucleus):
        w = self.words[n.word]
        return [w.letters[i] for i in n.letters]

    def features(self, u: Syllable) -> dict:
        w = self.words[u.word]
        n = u.nucleus
        ls = self._letters(n)
        marks = "".join(l.marks for l in ls)
        cons = [c for c, _ in u.coda if c in CONSONANTS]
        mcl = len(cons) == 2 and cons[0] in STOPS and cons[1] in LIQUIDS_NASALS and not u.coda[1][1]
        nw = u.word + 1 if u.word + 1 < len(self.words) else None
        nuc = self._nuclei[w.index]
        idx = next(i for i, x in enumerate(nuc) if x.letters == n.letters)
        last = len(nuc) - 1
        f = {
            "nucleus": n.kind,
            "vowel": ls[0].base if len(ls) == 1 else "",
            "adscript": "SYL-4" in n.rules,
            "iota_sub": IOTA_SUB in marks,
            "circumflex": CIRCUMFLEX in marks,
            "crasis": "CRA-1" in n.rules or (n.letters[0] > 0 and SMOOTH in marks and _crasis(w, n)),
            "consonants": consonant_units(u.coda),
            "double": any(c in DOUBLE_CONSONANTS for c in cons),
            "mcl": mcl,
            "stop": _stop_class(cons[0]) if mcl else "",
            "liquid": ("nasal" if cons[1] in "μν" else "liquid") if mcl else "",
            "boundary_inside_interval": any(b for _, b in u.coda[1:]),
            "interval_opens_next_word": bool(u.coda) and u.coda[0][1],
            "final_consonant_before_vowel": (len(cons) == 1 and not u.coda[0][1] and u.word_final
                                             and not u.line_final),
            "hiatus": "external" if (not u.coda and u.next_vowel_word_initial) else
                      "internal" if (not u.coda and u.next_nucleus_same_word) else "none",
            "next_initial": self.words[nw].letters[0].base if nw is not None else "",
            "next_digamma": self.is_digamma(nw),
            "word_final": u.word_final,
            "word_initial": u.word_initial,
            "line_final": u.line_final,
            "elided": w.elided,
            "is_ultima": idx == last and not w.elided,
            "is_penult": idx == last - 1 and not w.elided,
            "accent": "none" if w.elided else _accent(w, nuc),
            "penult_long_by_nature": last >= 1 and _long_by_nature(w, nuc[last - 1]),
            "ultima_short_by_nature": _ultima_short(w, nuc[last]),
            "ultima_ai_oi": _ultima_ai_oi(w, nuc[last]),
            "enclitic_compound": _enclitic_compound(w, nuc),
            "dialect": self.sc.dialect,
            "lex": "none",
            "lex_sources": "",
        }
        f["alpha_for_eta"] = False
        if self.sc.lexicon is not None and n.kind == "dichronon" and not f["circumflex"] and not f["iota_sub"]:
            f["lex"], f["lex_sources"] = self.lex(u.word, n.letters[0])
            if f["vowel"] == "α":
                f["alpha_for_eta"] = n.letters[0] in self.eta_alphas(u.word)
        return f

    def eta_alphas(self, wi: int) -> frozenset[int]:
        """Letter indices of α that stand where the attested Attic-Ionic spelling has η (lexical hook).

        Candidates come from the project's dialect correspondence rules (backend/dialect_generate.py:
        ᾱ for η, Aeolic gemination, psilosis, recessive accent, ...); a candidate counts when the
        quantity lexicon knows that exact spelling and, if the printed form is itself known, the two
        share a lemma (so an Ionic α never borrows length from an unrelated η-word)."""
        if not hasattr(self, "_eta"):
            self._eta = {}
        if wi not in self._eta:
            self._eta[wi] = _eta_alphas(self.sc.lexicon, self.words[wi].text)
        return self._eta[wi]

    def evidence(self, wi: int) -> Evidence:
        if wi not in self._ev:
            w = self.words[wi]
            lex = self.sc.lexicon
            ev = Evidence(False, "none", [dict() for _ in w.letters])
            if w.elided:
                for spelling, _rough in project_elision.restorations(w.text):
                    r = lex.lookup(spelling)
                    if not r.found:
                        continue
                    ev.found, ev.via = True, "elision_restored"
                    ev.lemmas |= r.lemmas
                    for i in range(min(len(w.letters), len(r.per_letter))):
                        for src, codes in r.per_letter[i].items():
                            ev.per_letter[i].setdefault(src, set()).update(codes)
            if not ev.found:
                ev = lex.lookup(w.text)
            self._ev[wi] = ev
        return self._ev[wi]

    def lex(self, wi: int, li: int) -> tuple[str, str]:
        ev = self.evidence(wi)
        if not ev.found or li >= len(ev.per_letter) or ev.via == "accentless":
            return "unknown_word", ""
        codes = ev.per_letter[li]
        explicit = {src: {c for c in cs if c in "LS"} for src, cs in codes.items()}
        explicit = {src: cs for src, cs in explicit.items() if cs}
        vals = set().union(*explicit.values()) if explicit else set()
        srcs = sorted(explicit)
        kind = ("both" if any(s in DICTIONARY_SOURCES for s in srcs) and "morpheus" in srcs
                else "dict" if any(s in DICTIONARY_SOURCES for s in srcs) else "morph" if srcs else "")
        if len(vals) == 1:
            return next(iter(vals)), kind
        if len(vals) == 2:
            return "conflict", kind
        if any("e" in cs for cs in codes.values()):
            return "ending", "morph"
        if any("u" in cs for cs in codes.values()):
            return "unmarked", ""
        return "none", ""

    def is_digamma(self, wi: int | None) -> bool:
        if wi is None:
            return False
        if wi not in self._dig:
            keys = digamma_keys()
            hit = accentless_key(self.words[wi].text) in keys
            if not hit and self.sc.lexicon is not None:
                hit = bool(lemma_keys(self.evidence(wi).lemmas) & keys)
            self._dig[wi] = hit
        return self._dig[wi]


# Enclitics that join a preceding word into one written word (Smyth §181, §186: such compounds keep
# the accent of the first word, as if the enclitic were separate: οὔτις, ὥστε, ὅδε).
ENCLITIC_ENDINGS = ("τε", "τισ", "τι", "τινα", "τινοσ", "τινι", "περ", "γε", "δε")  # σ: letters are folded (FOLD)


def _enclitic_compound(w: Word, nuc: list[Nucleus]) -> bool:
    if len(nuc) < 2:
        return False
    bases = "".join(l.base for l in w.letters)
    for e in ENCLITIC_ENDINGS:
        if bases.endswith(e) and len(bases) > len(e):
            tail_start = len(w.letters) - len(e)
            # the accent stands just before the enclitic and the enclitic part itself is unaccented
            tail_marks = "".join(l.marks for l in w.letters[tail_start:])
            head_marks = "".join(l.marks for l in w.letters[:tail_start])
            if not any(a in tail_marks for a in ACCENTS) and any(a in head_marks for a in ACCENTS):
                return True
    return False


@lru_cache(maxsize=50_000)
def _eta_alphas_cached(lexicon: QuantityLexicon, form: str) -> frozenset[int]:
    import difflib
    from .. import dialect_generate
    from .greek import base_letters
    if "α" not in base_letters(form):
        return frozenset()
    own = lexicon.lookup(form)
    own_lemmas = lemma_keys(own.lemmas) if own.found and own.via == "exact" else set()
    src = base_letters(form)
    hits: set[int] = set()
    for spelling, rules in dialect_generate.generate(form):
        if "alpha_for_eta" not in rules:
            continue
        ev = lexicon.lookup(spelling)
        if not ev.found or ev.via != "exact":
            continue
        if own_lemmas and not (own_lemmas & lemma_keys(ev.lemmas)):
            continue
        dst = base_letters(spelling)
        sm = difflib.SequenceMatcher(None, src, dst, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "replace":
                continue
            m = min(i2 - i1, j2 - j1)
            pairs = [(i1 + k, j1 + k) for k in range(m)] + [(i2 - 1 - k, j2 - 1 - k) for k in range(m)]
            for i, j in pairs:
                if src[i] == "α" and dst[j] == "η":
                    # an α before an Aeolic double consonant answers Attic η by compensatory
                    # lengthening (σελάννα / σελήνη): the Aeolic α itself is short
                    if "geminate" in rules and i + 2 < len(src) and src[i + 1] == src[i + 2]:
                        continue
                    hits.add(i)
    return frozenset(hits)


def _eta_alphas(lexicon: QuantityLexicon, form: str) -> frozenset[int]:
    from .greek import ELISION_MARKS
    if form[-1:] in ELISION_MARKS:
        return frozenset()
    return _eta_alphas_cached(lexicon, form)


def _crasis(w: Word, n: Nucleus) -> bool:
    first = n.letters[0]
    return any(w.letters[i].base in CONSONANTS for i in range(first)) or first > 1


def _accent(w: Word, nuc: list[Nucleus]) -> str:
    """Position of the word's first accent (a second one comes from an enclitic, Smyth §183)."""
    last = len(nuc) - 1
    for i, x in enumerate(nuc):
        marks = "".join(w.letters[j].marks for j in x.letters)
        if any(a in marks for a in ACCENTS):
            kind = "circumflex" if CIRCUMFLEX in marks else "acute"
            pos = {last: "ultima", last - 1: "penult", last - 2: "antepenult"}.get(i)
            return f"{pos}_{kind}" if pos else "none"
    return "none"


def _long_by_nature(w: Word, n: Nucleus) -> bool:
    marks = "".join(w.letters[j].marks for j in n.letters)
    return n.kind in ("diphthong", "long") or IOTA_SUB in marks or CIRCUMFLEX in marks


def _ultima_short(w: Word, n: Nucleus) -> bool:
    ls = [w.letters[j] for j in n.letters]
    return len(ls) == 1 and ls[0].base in "εο" and IOTA_SUB not in ls[0].marks


def _ultima_ai_oi(w: Word, n: Nucleus) -> bool:
    d = "".join(w.letters[j].base for j in n.letters)
    return n.kind == "diphthong" and d in ("αι", "οι") and not w.letters[n.letters[-1] + 1:]


def _stop_class(c: str) -> str:
    return "voiceless" if c in "πτκ" else "aspirate" if c in "φθχ" else "voiced"
