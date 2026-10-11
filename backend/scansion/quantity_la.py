"""Layer 1 for Latin: metre-free scansion units with a longness probability each (sibling of quantity.py).

A unit is a vowel nucleus plus the consonants after it up to the next nucleus on the line
(backend/scansion/syllabify_la.py). For every unit the features listed in FEATURES_LA are computed here and the
Latin meta-grammar (rules_la.yaml) is evaluated on them: the `vowel` tree gives p_vowel, the `unit` tree gives
p_long, `flags` add annotations. Two flags drive the metre layer: ELI-* (the unit may be elided: its `p` becomes
the unit's `elision`) and PROD-* (prodelision of est / es: `prodelision = {p, p_long}` on the unit before it).
Lexical vowel lengths are an optional hook (lexicon=...); without it `lex` is "none".
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import engine
from .latin import CONSONANTS, DOUBLE_CONSONANTS, INTERJECTIONS, LIQUIDS, MCL_FIRST, SILENT, STOPS, VOWELS, key as la_key
from .latin import BREVE, MACRON
from .quantity import SyllableResult
from .syllabify import Nucleus, Syllable, Word, line_spans, nuclei_of as _unused  # noqa: F401 (shared dataclasses)
from .syllabify_la import consonant_units, iu_rule, marks_of, nuclei_of, punct_between, syllabify_line, words_of

DEFAULT_RULES = Path(__file__).resolve().parent / "rules_la.yaml"

FEATURES_LA: dict[str, str] = {
    "nucleus": 'kind of nucleus: "diphthong" or "vowel"',
    "vowel": "base letter of a single-vowel nucleus (a e i o u y; empty for a diphthong)",
    "diphthong": 'the diphthong\'s letters ("ae", "au", "oe", "eu", "ui", "ei"; empty otherwise)',
    "typed": 'a quantity mark typed on the vowel: "L" (macron), "S" (breve), "" (none)',
    "consonants": "consonant units in the interval after the nucleus (x z and intervocalic i count two, h and the glide of qu none)",
    "double": "the interval contains x, z or an intervocalic i (maior)",
    "mcl": "the interval is exactly a stop (or f) + l/r inside the word, after this nucleus",
    "mcl_prefix": "that cluster stands at a prefix boundary (ab-rumpo, ob-ruo, sub-latus): it makes position",
    "boundary_inside_interval": "a word boundary falls between the interval's consonants",
    "interval_opens_next_word": "all the interval's consonants belong to the next word",
    "next_cluster": 'the next word\'s initial cluster when it opens the interval: "s_stop", "mcl", "double", "other", ""',
    "final_consonant_before_vowel": "one consonant ends this word and the next word begins with a vowel (or h)",
    "final_s_short": "the word ends in -s right after this nucleus and the next word begins with a consonant",
    "elidable": "word-final vowel, or vowel + m, before a word beginning with a vowel or h (elision environment)",
    "final_m": "the word ends in -m right after this nucleus",
    "next_est": 'the next word is "est" or "es" (prodelision)',
    "next_interjection": "the next word is an interjection (o, heu, a, ah, io, ...)",
    "interjection": "this word is an interjection",
    "punct_between": 'punctuation before the next word: "strong" (. ! ? ; :), "weak" (,), "none"',
    "hiatus": '"external" (vowel before the next word\'s vowel), "internal" (vowel before vowel in the word), "none"',
    "next_initial": "first base letter of the next word on the line (empty at line end)",
    "word_final": "the nucleus is the last one of its word",
    "word_initial": "the nucleus is the first one of its word",
    "line_final": "the last unit of the line",
    "elided": "the word ends in an editor's elision mark",
    "is_ultima": "the nucleus is the word's last vowel",
    "is_penult": "the nucleus is the word's second-last vowel",
    "monosyllable": "the word has one nucleus",
    "nsyl": "number of nuclei in the word",
    "enclitic": "the word ends in -que (or -ue, -ne after a consonant) written with it: that final e is the enclitic's",
    "ending": 'the word\'s last vowel letter and the letters after it (e.g. "a", "am", "as", "o", "us", "que")',
    "word": "the word, lower case, u for v, i for j, no marks (for word lists)",
    "stem": "the word without its enclitic -que / -ue / -ne (for word lists)",
    "capitalised": "the word is written with a capital (a name, often Greek)",
    "iambic_word": "a disyllable whose first syllable is an open short-vowel candidate (iambic shortening environment)",
    "lex": 'lexical evidence for this vowel: "L", "S", "conflict", "unmarked", "unknown_word", "none" (no lexicon)',
    "lex_sources": "which sources marked it",
    "p_vowel": "probability the nucleus is long (set by the vowel tree)",
}

ENCLITICS = ("que", "ue", "ne")


class LatinScanner:
    """scan(text) -> list of units.  `lexicon=None` runs the core grammar only."""

    language = "la"

    def __init__(self, lexicon=None, grammar: engine.Grammar | None = None, rules_path: str | Path | None = None,
                 params: dict | None = None, spelling: str = "auto"):
        if grammar is None:
            grammar, errors = engine.load(rules_path or DEFAULT_RULES, param_overrides=params, features=FEATURES_LA)
            if errors:
                raise engine.RuleError("; ".join(errors))
        self.grammar = grammar
        self.lexicon = lexicon
        self.dialect = "none"
        self.spelling = spelling      # "auto" | "uv" (the text writes v and j) | "u" (u and i only)

    def scan(self, text: str) -> list[SyllableResult]:
        out: list[SyllableResult] = []
        for line_no, (a, b) in enumerate(line_spans(text)):
            words = words_of(text, a, b, spelling=self.spelling)
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
    def __init__(self, scanner: LatinScanner, text: str, words: list[Word], units: list[Syllable]):
        self.sc = scanner
        self.text = text
        self.words = words
        self.units = units
        self._nuclei = {w.index: nuclei_of(w) for w in words}
        self._keys = {w.index: la_key("".join(_typed(l) for l in w.letters)) for w in words}

    def result(self, k: int) -> SyllableResult:
        u = self.units[k]
        g = self.sc.grammar
        env = g.env()
        env.update(self.features(u))
        p_vowel, vpath = g.decide(g.vowel, env)
        env["p_vowel"] = p_vowel
        p, upath = g.decide(g.unit, env)
        flags, elision, prodelision = [], None, None
        for f in g.flags:
            if f.when(env):
                d = {"id": f.id, "text": f.reason, "cite": f.cite}
                if f.p is not None:
                    d["p"] = round(float(f.p(env)), 3)
                    # ELI-* and PROD-* flags: the first that matches decides (file order), as in the trees
                    if f.id.startswith("ELI-") and f.id != "ELI-1":
                        if elision is not None:
                            continue
                        elision = min(max(float(f.p(env)), 0.0), 1.0)
                    elif f.id.startswith("PROD"):
                        if prodelision is not None:
                            continue
                        prodelision = {"p": round(min(max(float(f.p(env)), 0.0), 1.0), 3), "p_long": 1.0}
                flags.append(d)
        elision = elision or 0.0
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
            elision=elision, prodelision=prodelision,
        )

    def _interval_end(self, k: int) -> int:
        end = self._letters(self.units[k].nucleus)[-1].end
        stop = self._letters(self.units[k + 1].nucleus)[0].start if k + 1 < len(self.units) else None
        last = end
        for w in self.words:
            for l in w.letters:
                if l.start >= end and (stop is None or l.start < stop) and l.base in CONSONANTS:
                    last = max(last, l.end)
        return last

    def _detail(self, u: Syllable, rule: str) -> str:
        if rule.startswith(("POS", "MCL", "S-IMP", "INIT")):
            return " ".join(("| " if b else "") + c.replace("w", "u").replace("J", "i").replace("j", "i") for c, b in u.coda)
        if rule.startswith(("ELID", "CONS-VOW", "SEMI")):
            nw = u.word + 1
            return "before " + self.words[nw].text if nw < len(self.words) else ""
        return ""

    def _letters(self, n: Nucleus):
        w = self.words[n.word]
        return [w.letters[i] for i in n.letters]

    def features(self, u: Syllable) -> dict:
        w = self.words[u.word]
        n = u.nucleus
        ls = self._letters(n)
        marks = "".join(marks_of(l) for l in ls)
        real = [c for c, _ in u.coda if c in CONSONANTS and c not in SILENT]
        bounds = [b for c, b in u.coda if c in CONSONANTS and c not in SILENT]
        opens_next = bool(real) and bounds[0]
        mcl = (len(real) == 2 and real[0] in MCL_FIRST and real[1] in LIQUIDS and not bounds[1] and not opens_next)
        nw = u.word + 1 if u.word + 1 < len(self.words) else None
        nuc = self._nuclei[w.index]
        idx = next(i for i, x in enumerate(nuc) if x.letters == n.letters)
        last = len(nuc) - 1
        word = self._keys[w.index]
        stem, enclitic = _split_enclitic(word, len(nuc))
        next_word = self._keys[nw] if nw is not None else ""
        next_first = self.words[nw].letters[0].base if nw is not None else ""
        next_begins_vowel = next_first in VOWELS or next_first == "h"
        ending = _ending(w, n)
        final_m = u.word_final and ending.endswith("m") and len(ending) == 2
        elidable = u.word_final and nw is not None and next_begins_vowel and (not real or (final_m and len(real) == 1))
        f = {
            "nucleus": n.kind,
            "vowel": ls[0].base if len(ls) == 1 else "",
            "diphthong": "".join(l.base for l in ls) if len(ls) == 2 else "",
            "typed": "L" if MACRON in marks else "S" if BREVE in marks else "",
            "consonants": consonant_units(u.coda),
            "double": any(c in DOUBLE_CONSONANTS for c in real),
            "mcl": mcl,
            "mcl_prefix": mcl and _prefix_cluster(word, idx, nuc, w),
            "boundary_inside_interval": any(bounds[1:]),
            "interval_opens_next_word": opens_next,
            "next_cluster": _next_cluster(real, bounds) if opens_next else "",
            "final_consonant_before_vowel": (len(real) == 1 and not bounds[0] and u.word_final and not u.line_final
                                             and next_begins_vowel),
            "final_s_short": (u.word_final and ending.endswith("s") and len(ending) == 2 and nw is not None
                              and not next_begins_vowel),
            "elidable": elidable,
            "final_m": final_m,
            "next_est": next_word in ("est", "es"),
            "next_interjection": next_word in INTERJECTIONS,
            "interjection": word in INTERJECTIONS,
            "punct_between": punct_between(self.text, w, self.words[nw]) if nw is not None else "none",
            "hiatus": "external" if (not real and u.next_vowel_word_initial) else
                      "internal" if (not real and u.next_nucleus_same_word) else "none",
            "next_initial": next_first,
            "word_final": u.word_final,
            "word_initial": u.word_initial,
            "line_final": u.line_final,
            "elided": w.elided,
            "is_ultima": idx == last and not w.elided,
            "is_penult": idx == last - 1 and not w.elided,
            "monosyllable": len(nuc) == 1,
            "nsyl": len(nuc),
            "enclitic": bool(enclitic),
            "ending": ending,
            "word": word,
            "stem": stem,
            "capitalised": w.text.lstrip("’'ʼ[⟨")[:1].isupper(),
            "iambic_word": _iambic_word(w, nuc),
            "lex": "none",
            "lex_sources": "",
        }
        if self.sc.lexicon is not None and n.kind == "vowel":
            f["lex"], f["lex_sources"] = self.sc.lexicon.vowel_evidence(word, n.letters[0], w)
        return f


def _typed(letter) -> str:
    """The letter as the owner typed it (u/v, i/j kept), for the word key."""
    r = iu_rule(letter)
    b = letter.base
    if b in ("w",):
        return "u"
    if b in ("j", "J"):
        return "j" if r == "IU-TYPED" else "i"
    if b == "v":
        return "v" if r == "IU-TYPED" else "u"
    return b


def _ending(w: Word, n: Nucleus) -> str:
    """The word's last vowel letter(s) and what follows, when this nucleus is the last one; else ''."""
    nuc = nuclei_of(w)
    if not nuc or nuc[-1].letters != n.letters:
        return ""
    tail = "".join(_typed(l) for l in w.letters[n.letters[0]:])
    return tail.replace("j", "i").replace("v", "u")


NOT_ENCLITIC_QUE = frozenset({"atque", "neque", "quoque", "itaque", "denique", "undique", "utique", "ubique", "usque",
                              "absque", "plerumque", "utroque", "quisque", "quaeque", "quodque", "quemque", "quamque",
                              "cumque", "quandoque", "quicumque", "quaecumque", "quodcumque"})


def _split_enclitic(word: str, nsyl: int) -> tuple[str, str]:
    """-que (and -ue / -ne after a consonant) written with the word: (stem, enclitic) or (word, '')."""
    if nsyl < 2:
        return word, ""
    if word.endswith("que") and len(word) > 4 and word not in NOT_ENCLITIC_QUE:
        return word[:-3], "que"
    return word, ""


def _prefix_cluster(word: str, idx: int, nuc: list[Nucleus], w: Word) -> bool:
    """ab-rumpo, ob-ruo, sub-latus: the stop ends a prefix, so the cluster makes position (A&G §603f)."""
    first = nuc[idx].letters[0]
    after = "".join(l.base for l in w.letters[first + 1:first + 3])
    return bool(after) and ((word.startswith(("ab", "ob")) and first == 0 and after[:1] == "b")
                            or (word.startswith("sub") and first == 1 and after[:1] == "b"))


def _next_cluster(real: list[str], bounds: list[bool]) -> str:
    """Class of the next word's initial cluster when the whole interval belongs to it."""
    nxt = real
    if len(nxt) < 2:
        return "other"
    if any(c in DOUBLE_CONSONANTS for c in nxt):
        return "double"
    if nxt[0] == "s" and nxt[1] in STOPS:
        return "s_stop"
    if nxt[0] in MCL_FIRST and nxt[1] in LIQUIDS:
        return "mcl"
    return "other"


def _iambic_word(w: Word, nuc: list[Nucleus]) -> bool:
    if len(nuc) != 2 or nuc[0].kind != "vowel":
        return False
    a, b = nuc[0].letters[-1], nuc[1].letters[0]
    between = [l.base for l in w.letters[a + 1:b] if l.base in CONSONANTS and l.base not in SILENT]
    return len(between) <= 1 and not any(c in DOUBLE_CONSONANTS for c in between)


@lru_cache(maxsize=1)
def default_scanner() -> LatinScanner:
    return LatinScanner()
