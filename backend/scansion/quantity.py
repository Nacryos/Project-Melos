"""Layer 1: metre-free syllable quantities with a longness probability per syllable.

The decision tree (docs/scansion.md, "Decision tree") is applied to every syllable in order:

1. the nucleus's nature (NAT-*), and for a bare α ι υ the dichronon branch (ACC-*, LEX-*, DIA-ETA,
   DICH-UNK);
2. what follows the nucleus up to the next vowel on the same line: two consonants or a double
   consonant (POS-*), stop + liquid/nasal (MCL-*), a vowel of the next word (COR-EXT, HIA-SHORT), a
   vowel inside the word (COR-INT), or at most one consonant (nature decides; EPL-INIT, DIG-LEN,
   CONS-VOW refine a short syllable);
3. flags that do not change the syllable count unless a metre is chosen: synizesis (SYN-CAND),
   digamma (DIG-HIA), line end (FIN-ANC).

The leaf reached gives the probability that the syllable is long: the share of long syllables at
that leaf in the training half of the Hypotactic Iliad (books 1-12; backend/scansion/data/
leaf_rates.json, scripts/scansion_calibrate.py). Grammar rules that admit no exception are given
1.0 / 0.0 when the measured share is at least 0.98 / at most 0.02.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .. import elision as project_elision
from .greek import (
    ACCENTS, ACUTE, CIRCUMFLEX, CONSONANTS, DICHRONA, DOUBLE_CONSONANTS, GRAVE, IOTA_SUB,
    LIQUIDS_NASALS, ROUGH, SMOOTH, STOPS, accentless_key, key,
)
from .lexicon import DICTIONARY_SOURCES, Evidence, QuantityLexicon, lemma_keys
from .rules import RULES
from .syllabify import Nucleus, Syllable, Word, consonant_units, line_spans, syllabify_line, words_of

DATA = Path(__file__).resolve().parent / "data"
CERTAIN = {"NAT-ETA", "NAT-DIPH", "NAT-CIRC", "NAT-ISUB", "NAT-EO", "CRA-1", "POS-WORD", "POS-DOUBLE",
           "POS-ACROSS", "ACC-PROPAROX", "ACC-PROPERISP", "ACC-PAROX-LONG", "ACC-PAROX-SHORT"}
# Grammar values used only when a leaf has no measurement (documented in docs/scansion.md).
GRAMMAR_DEFAULT = {"L": 1.0, "S": 0.0, "A": 0.5}
VOICELESS, ASPIRATE, VOICED = set("πτκ"), set("φθχ"), set("βδγ")
EPIC_LENGTHENING_INITIALS = set("ρλμνσδ")  # Monro §371


@dataclass
class SyllableResult:
    index: int
    line: int
    word: int
    start: int
    end: int
    text: str
    p_long: float
    leaf: str
    rule: str
    vowel: dict
    reasons: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    certain: bool = False
    nstart: int = 0               # offset of the nucleus's first letter

    @property
    def label(self) -> str:
        return "L" if self.p_long >= 0.9 else "S" if self.p_long <= 0.1 else "A"

    def as_dict(self) -> dict:
        return {"i": self.index, "line": self.line, "word": self.word, "start": self.start, "end": self.end,
                "text": self.text, "p_long": round(self.p_long, 3), "label": self.label, "rule": self.rule,
                "leaf": self.leaf, "certain": self.certain, "vowel": self.vowel, "reasons": self.reasons,
                "flags": self.flags}


@lru_cache(maxsize=4)
def load_rates(path: str | None = None) -> dict:
    p = Path(path) if path else DATA / "leaf_rates.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("leaves", {})


@lru_cache(maxsize=1)
def digamma_keys() -> frozenset[str]:
    doc = json.loads((DATA / "digamma_monro.json").read_text(encoding="utf-8"))
    return frozenset(accentless_key(r["word"]) for r in doc["rows"] if r.get("match", True))


class Scanner:
    def __init__(self, lexicon: QuantityLexicon | None = None, rates: dict | None = None):
        self.lexicon = lexicon or QuantityLexicon()
        self.rates = load_rates() if rates is None else rates

    # ----------------------------------------------------------------------------- public
    def scan(self, text: str) -> list[SyllableResult]:
        out: list[SyllableResult] = []
        for line_no, (a, b) in enumerate(line_spans(text)):
            words = words_of(text, a, b)
            if not words:
                continue
            for w in words:
                w.index = w.index  # indices are per line
            sylls = syllabify_line(words, line_no, first_index=len(out))
            ctx = _LineContext(self, text, words)
            for s in sylls:
                out.append(self._syllable(ctx, s, sylls))
        return out

    # ----------------------------------------------------------------------------- tree
    def rate(self, leaf: str, fallback: str) -> tuple[float, str]:
        """Measured share long at the most specific measured leaf key; grammar default otherwise."""
        parts = leaf.split(":")
        for n in range(len(parts), 0, -1):
            k = ":".join(parts[:n])
            if k in self.rates and self.rates[k]["n"] >= 20:
                p = self.rates[k]["p"]
                base = parts[0]
                if base in CERTAIN and (p >= 0.98 or p <= 0.02):
                    return (1.0 if p >= 0.5 else 0.0), k
                return p, k
        return GRAMMAR_DEFAULT[fallback], "grammar"

    def _syllable(self, ctx: "_LineContext", s: Syllable, sylls: list[Syllable]) -> SyllableResult:
        word = ctx.words[s.word]
        vq, vrule, p_v, vreasons = ctx.nature(s.nucleus)
        reasons = list(vreasons)
        flags: list[dict] = []
        units = consonant_units(s.coda)
        cons = [c for c, _ in s.coda if c in CONSONANTS]
        boundary_at = [i for i, (_, b) in enumerate(s.coda) if b]
        next_word = ctx.next_word(s)
        nature_leaf = vrule

        if units >= 2:
            mcl = (len(cons) == 2 and cons[0] in STOPS and cons[1] in LIQUIDS_NASALS
                   and not any(b for _, b in s.coda[1:]))
            if mcl and vq != "L":
                where = "INIT" if s.coda[0][1] else "WORD"
                leaf = f"MCL-{where}:{_stop_class(cons[0])}{'N' if cons[1] in 'μν' else 'L'}"
                p_pos, used = self.rate(leaf, "A")
                p = p_pos if vq == "S" else p_v + (1 - p_v) * p_pos
                reasons.append(_reason(leaf.split(":")[0], f"{cons[0]} + {cons[1]}" + (" opening the next word" if where == "INIT" else "")))
                return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)
            if any(c in DOUBLE_CONSONANTS for c in cons):
                leaf = "POS-DOUBLE"
            elif s.coda and s.coda[0][1]:
                leaf = "POS-INIT"
            elif boundary_at:
                leaf = "POS-ACROSS"
            else:
                leaf = "POS-WORD"
            p, used = self.rate(leaf, "L")
            reasons.append(_reason(leaf, _cluster_note(s.coda)))
            return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)

        if not s.coda and s.next_vowel_word_initial and not s.line_final:
            dig = ctx.is_digamma(next_word)
            if dig:
                flags.append(_flag("DIG-HIA", f"{ctx.words[next_word].text} once began with ϝ"))
            if vq == "L":
                leaf = f"COR-EXT:{_nucleus_class(ctx, s.nucleus)}" + (":dig" if dig else "")
                p, used = self.rate(leaf, "A")
                reasons.append(_reason("COR-EXT", "before " + ctx.words[next_word].text))
                return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)
            if vq == "S":
                leaf = "HIA-SHORT" + (":dig" if dig else "")
                p, used = self.rate(leaf, "S")
                reasons.append(_reason("HIA-SHORT", "before " + ctx.words[next_word].text))
                return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)
            p_cor, _ = self.rate("COR-EXT:long", "A")
            p_hia, _ = self.rate("HIA-SHORT", "S")
            p = p_v * p_cor + (1 - p_v) * p_hia
            reasons.append(_reason("COR-EXT", "a long vowel here could be shortened before " + ctx.words[next_word].text))
            return self._result(ctx, s, p, vrule, vrule, vq, vrule, p_v, reasons, flags)

        if not s.coda and s.next_nucleus_same_word and vq == "L" and s.nucleus.kind == "diphthong" or (
                not s.coda and s.next_nucleus_same_word and vq == "L" and ctx.letters(s.nucleus)[0].base in "ηω"
                and IOTA_SUB not in ctx.letters(s.nucleus)[0].marks):
            leaf = f"COR-INT:{_nucleus_class(ctx, s.nucleus)}"
            p, used = self.rate(leaf, "A")
            reasons.append(_reason("COR-INT", "before " + ctx.next_letters(s)))
            self._synizesis_flag(ctx, s, flags)
            return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)

        self._synizesis_flag(ctx, s, flags)
        if vq == "L":
            p, used = self.rate(nature_leaf, "L")
            return self._result(ctx, s, p, nature_leaf, used, vq, vrule, p_v, reasons, flags)
        if vq == "S":
            leaf = vrule
            if s.word_final and not s.line_final and next_word is not None:
                nxt = ctx.words[next_word]
                first = nxt.letters[0].base
                if ctx.is_digamma(next_word) and (cons or first in CONSONANTS):
                    leaf = "DIG-LEN"
                    reasons.append(_reason("DIG-LEN", f"{nxt.text} once began with ϝ"))
                elif not cons and first in EPIC_LENGTHENING_INITIALS and len(s.coda) == 1:
                    leaf = f"EPL-INIT:{first}"
                    reasons.append(_reason("EPL-INIT", f"before initial {first}"))
                elif cons and not s.coda[-1][1] and first not in CONSONANTS:
                    leaf = "CONS-VOW"
                    reasons.append(_reason("CONS-VOW", f"final {cons[-1]} before a vowel"))
            p, used = self.rate(leaf, "S")
            return self._result(ctx, s, p, leaf, used, vq, vrule, p_v, reasons, flags)
        # dichronon in an open syllable: the vowel decides
        return self._result(ctx, s, p_v, vrule, vrule, vq, vrule, p_v, reasons, flags)

    def _synizesis_flag(self, ctx, s: Syllable, flags: list) -> None:
        letters = ctx.letters(s.nucleus)
        if (not s.coda and s.next_nucleus_same_word and len(letters) == 1 and letters[0].base in "εη"):
            leaf = f"SYN-CAND:{letters[0].base}{ctx.next_letters(s)[:1]}"
            p, used = self.rate(leaf, "A") if leaf in self.rates or "SYN-CAND" in self.rates else (None, "grammar")
            flags.append(_flag("SYN-CAND", f"{letters[0].base} + {ctx.next_letters(s)} may form one syllable",
                               p_merge=None if p is None else round(p, 3)))

    def _result(self, ctx, s: Syllable, p: float, leaf: str, used: str, vq, vrule, p_v, reasons, flags) -> SyllableResult:
        if s.line_final:
            flags.append(_flag("FIN-ANC", "last syllable of the line"))
        rule = leaf.split(":")[0]
        if not reasons or reasons[-1]["id"] != rule:
            if rule in RULES:
                reasons.append(_reason(rule, ""))
        return SyllableResult(
            index=s.index, line=s.line, word=s.word, start=s.start, end=s.end, text=ctx.text[s.start:s.end],
            p_long=float(p), leaf=leaf, rule=rule,
            vowel={"quantity": vq, "rule": vrule.split(":")[0], "p_long": round(p_v, 3)},
            reasons=reasons, flags=flags, certain=(p in (0.0, 1.0) and rule in CERTAIN and used != "grammar"),
            nstart=ctx.letters(s.nucleus)[0].start,
        )


class _LineContext:
    def __init__(self, scanner: Scanner, text: str, words: list[Word]):
        self.scanner = scanner
        self.text = text
        self.words = words
        self._nuclei_cache: dict[int, list[Nucleus]] = {}
        self._evidence: dict[int, Evidence] = {}

    def letters(self, n: Nucleus):
        w = self.words[n.word]
        return [w.letters[i] for i in n.letters]

    def next_letters(self, s: Syllable) -> str:
        w = self.words[s.word]
        i = s.nucleus.letters[-1] + 1
        return "".join(l.base for l in w.letters[i:i + 2])

    def next_word(self, s: Syllable) -> int | None:
        return s.word + 1 if s.word + 1 < len(self.words) else None

    def evidence(self, wi: int) -> Evidence:
        if wi not in self._evidence:
            w = self.words[wi]
            lex = self.scanner.lexicon
            ev = Evidence(False, "none", [dict() for _ in w.letters])
            if w.elided:
                merged = Evidence(False, "none", [dict() for _ in w.letters])
                for spelling, _rough in project_elision.restorations(w.text):
                    r = lex.lookup(spelling)
                    if not r.found:
                        continue
                    merged.found, merged.via = True, "elision_restored"
                    merged.lemmas |= r.lemmas
                    for i in range(min(len(w.letters), len(r.per_letter))):
                        for src, codes in r.per_letter[i].items():
                            merged.per_letter[i].setdefault(src, set()).update(codes)
                ev = merged
            if not ev.found:
                ev = lex.lookup(w.text)
            self._evidence[wi] = ev
        return self._evidence[wi]

    def is_digamma(self, wi: int | None) -> bool:
        if wi is None:
            return False
        keys = digamma_keys()
        w = self.words[wi]
        if accentless_key(w.text) in keys:
            return True
        return bool(lemma_keys(self.evidence(wi).lemmas) & keys)

    # --------------------------------------------------------------------- nature of a nucleus
    def nature(self, n: Nucleus) -> tuple[str, str, float, list[dict]]:
        """(quantity L/S/?, rule id or leaf key, P(vowel long), reasons)."""
        ls = self.letters(n)
        marks = "".join(l.marks for l in ls)
        w = self.words[n.word]
        if n.letters[0] > 0 and SMOOTH in marks and _crasis(w, n):
            return "L", "CRA-1", 1.0, [_reason("CRA-1", "coronis")]
        if n.kind == "diphthong":
            if "SYL-4" in n.rules:
                return "L", "NAT-ISUB", 1.0, [_reason("NAT-ISUB", "iota adscript")]
            return "L", "NAT-DIPH", 1.0, [_reason("NAT-DIPH", "".join(l.base for l in ls))]
        if IOTA_SUB in marks:
            return "L", "NAT-ISUB", 1.0, [_reason("NAT-ISUB", ls[0].base + "ͅ")]
        if CIRCUMFLEX in marks:
            return "L", "NAT-CIRC", 1.0, [_reason("NAT-CIRC", "")]
        if n.kind == "long":
            return "L", "NAT-ETA", 1.0, [_reason("NAT-ETA", ls[0].base)]
        if n.kind == "short":
            return "S", "NAT-EO", 0.0, [_reason("NAT-EO", ls[0].base)]
        return self._dichronon(n)

    def _dichronon(self, n: Nucleus) -> tuple[str, str, float, list[dict]]:
        sc = self.scanner
        w = self.words[n.word]
        li = n.letters[0]
        vowel = w.letters[li].base
        acc = _accent_rule(self, n)
        if acc:
            rule, q = acc
            p, used = sc.rate(rule, q)
            return q, rule, p, [_reason(rule, "")]
        ev = self.evidence(n.word)
        codes = ev.per_letter[li] if ev.found and li < len(ev.per_letter) else {}
        explicit = {src: {c for c in cs if c in "LS"} for src, cs in codes.items()}
        explicit = {src: cs for src, cs in explicit.items() if cs}
        vals = set().union(*explicit.values()) if explicit else set()
        suffix = "" if ev.via == "exact" else ":" + ev.via
        if len(vals) == 1:
            q = next(iter(vals))
            srcs = sorted(explicit)
            kind = ("both" if any(s in DICTIONARY_SOURCES for s in srcs) and "morpheus" in srcs
                    else "dict" if any(s in DICTIONARY_SOURCES for s in srcs) else "morph")
            leaf = f"LEX-{q}:{kind}{suffix}"
            p, _ = sc.rate(leaf, q)
            return q, leaf, p, [_reason(f"LEX-{q}", ", ".join(srcs))]
        if len(vals) == 2:
            dict_vals = set().union(*(cs for src, cs in explicit.items() if src in DICTIONARY_SOURCES))                 if any(src in DICTIONARY_SOURCES for src in explicit) else set()
            leaf = "LEX-CONFLICT" + (f":dict{next(iter(dict_vals))}" if len(dict_vals) == 1 else "") + suffix
            p, _ = sc.rate(leaf, "A")
            detail = "; ".join(f"{s}: {'/'.join(sorted(c))}" for s, c in sorted(explicit.items()))
            return "?", leaf, p, [_reason("LEX-CONFLICT", detail)]
        if any("e" in cs for cs in codes.values()):
            leaf = "LEX-ENDING" + suffix
            p, _ = sc.rate(leaf, "S")
            return ("S" if p < 0.5 else "?"), leaf, p, [_reason("LEX-ENDING", "")]
        unmarked = sorted({("morph" if src == "morpheus" else "dict") for src, cs in codes.items() if "u" in cs})
        if unmarked:
            leaf = "LEX-UNMARKED:" + ("both" if len(unmarked) == 2 else unmarked[0]) + suffix
            p, _ = sc.rate(leaf, "A")
            return ("S" if p <= 0.1 else "L" if p >= 0.9 else "?"), leaf, p, [_reason("LEX-UNMARKED", f"{vowel} without a length mark")]
        if vowel == "α" and self._alpha_for_eta(w, li):
            p, _ = sc.rate("DIA-ETA", "L")
            return "L", "DIA-ETA", p, [_reason("DIA-ETA", "")]
        pos = "final" if li == _last_vowel_index(w) else "medial"
        leaf = f"DICH-UNK:{vowel}:{pos}"
        p, _ = sc.rate(leaf, "A")
        return "?", leaf, p, [_reason("DICH-UNK", f"{vowel} of unknown length")]

    def _alpha_for_eta(self, w: Word, li: int) -> bool:
        """DIA-ETA: replacing this α by η gives a spelling the lexicon knows (Doric/Aeolic ᾱ = Attic η)."""
        nfd = unicodedata.normalize("NFD", key(w.text))
        bases = [i for i, ch in enumerate(nfd) if not unicodedata.combining(ch)]
        if li >= len(bases):
            return False
        pos = bases[li]
        variant = unicodedata.normalize("NFC", nfd[:pos] + "η" + nfd[pos + 1:])
        return self.scanner.lexicon.lookup(variant).found


def _crasis(w: Word, n: Nucleus) -> bool:
    """A smooth breathing (coronis) on a vowel that is not word-initial marks crasis (κἀγώ)."""
    first = n.letters[0]
    return any(w.letters[i].base in CONSONANTS for i in range(first)) or first > 1


def _last_vowel_index(w: Word) -> int:
    for i in range(len(w.letters) - 1, -1, -1):
        if w.letters[i].base in "αεηιουω":
            return i
    return -1


def _accent_rule(ctx: _LineContext, n: Nucleus) -> tuple[str, str] | None:
    """ACC-*: quantity of a bare α ι υ read from the word's accent (Smyth §§163-170)."""
    w = ctx.words[n.word]
    from .syllabify import nuclei_of
    nuc = nuclei_of(w)
    idx = next(i for i, x in enumerate(nuc) if x.letters == n.letters)
    accented = [i for i, x in enumerate(nuc) if any(m in w.letters[j].marks for j in x.letters for m in ACCENTS)]
    if not accented:
        return None
    acc = accented[0]                       # a second accent comes from a following enclitic (Smyth §183)
    acc_marks = "".join(w.letters[j].marks for j in nuc[acc].letters)
    circ = CIRCUMFLEX in acc_marks
    last = len(nuc) - 1
    if w.elided:
        return None                         # the printed last vowel is not the ultima
    if idx == last and acc == last - 2 and not circ:
        return "ACC-PROPAROX", "S"
    if idx == last and acc == last - 1 and circ:
        return "ACC-PROPERISP", "S"
    if idx == last and acc == last - 1 and not circ and _long_by_nature(w, nuc[acc]):
        return "ACC-PAROX-LONG", "L"
    if idx == last - 1 and acc == idx and not circ:
        ult = nuc[last]
        ult_letters = [w.letters[j] for j in ult.letters]
        tail_consonants = any(l.base in CONSONANTS for l in w.letters[ult.letters[-1] + 1:])
        if len(ult_letters) == 1 and ult_letters[0].base in "εο" and IOTA_SUB not in ult_letters[0].marks:
            return "ACC-PAROX-SHORT", "S"
        if ult.kind == "diphthong" and "".join(l.base for l in ult_letters) in ("αι", "οι") and not tail_consonants:
            return "ACC-PAROX-SHORT-AIOI", "S"
    return None


def _long_by_nature(w: Word, n: Nucleus) -> bool:
    ls = [w.letters[j] for j in n.letters]
    marks = "".join(l.marks for l in ls)
    return n.kind in ("diphthong", "long") or IOTA_SUB in marks or CIRCUMFLEX in marks


def _nucleus_class(ctx: _LineContext, n: Nucleus) -> str:
    ls = ctx.letters(n)
    if IOTA_SUB in "".join(l.marks for l in ls):
        return "isub"
    if n.kind == "diphthong":
        d = "".join(l.base for l in ls)
        return d if d in ("αι", "οι", "ει", "ου") else "diph"
    if n.kind == "long":
        return "eta"
    return "long"


def _stop_class(c: str) -> str:
    return "voiceless" if c in VOICELESS else "aspirate" if c in ASPIRATE else "voiced"


def _cluster_note(coda) -> str:
    out = []
    for c, b in coda:
        out.append(("| " if b else "") + c)
    return " ".join(out)


def _reason(rule_id: str, detail: str) -> dict:
    text, cite = RULES.get(rule_id, ("", ""))
    return {"id": rule_id, "text": text, "detail": detail, "cite": cite}


def _flag(rule_id: str, detail: str, **extra) -> dict:
    d = _reason(rule_id, detail)
    d.update({k: v for k, v in extra.items() if v is not None})
    return d
