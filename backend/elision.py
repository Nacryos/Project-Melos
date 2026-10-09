"""Elided words in the corpus headword index (release Q).

Elision removes only a word's final short vowel or diphthong before a following vowel; before a
rough breathing a final τ π κ of the remaining stem is written θ φ χ. So the readings of an elided
spelling are the spellings with a vowel added back (and, before a rough breathing, the plain stop
restored). Nothing else is ever added or changed.

Readings are ranked by three general sources of evidence, combined as a naive Bayes score:

1. a prior P(headword | elided spelling): treebank gold lemmas of that spelling (train split only),
   smoothed toward a base distribution = the corpus frequency of the restored spellings' headwords in
   the index (accent-compatible restorations only) mixed with the parser-based ranking;
2. context features of the token: its own part of speech and its neighbours' (contextual model) and
   its clause position (after strong punctuation, after a comma, verse-line start, medial);
3. a hard phonological rule: a reading that needs θ φ χ to stand for τ π κ is possible only before
   a rough breathing.

Feature likelihoods are learnt per headword from the treebank train split (neighbours and position
from every token of the headword, its own tag from elided tokens), backed off to the headword's part
of speech. The model file is built by scripts/train_elision_model.py.
Readings within TIE_RATIO of the best are kept as genuine alternatives (both shown).
"""
from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter

ELISION_MARKS = "’'᾽ʼ᾿"
ACUTE, GRAVE, CIRCUMFLEX = "́", "̀", "͂"
SMOOTH, ROUGH = "̓", "̔"
ACCENTS = (ACUTE, GRAVE, CIRCUMFLEX)
VOWELS = "αεηιουω"
RESTORED_ENDINGS = ("α", "ε", "ι", "ο", "αι", "οι")
DEASPIRATE = {"θ": "τ", "φ": "π", "χ": "κ"}
STRONG_PUNCT = ".;·:!?;·"
# Naive Bayes features. own_pos is learnt from elided tokens only (the contextual model tags an elided
# token less reliably than a whole word); the neighbours' parts of speech and the clause position are
# learnt from every treebank token of the headword. The next word's initial is used only by the
# hard aspiration rule.
FEATURES = ("own_pos", "next_pos", "prev_pos", "position")
ELIDED_ONLY_FEATURES = ("own_pos",)
TIE_RATIO = 0.5


def is_elided(form: str) -> bool:
    return bool(form) and form[-1] in ELISION_MARKS and len(form) > 1


def key(text: str) -> str:
    """Comparison key for spellings: NFC, lower case, grave written as acute, elision mark ’."""
    t = unicodedata.normalize("NFD", str(text or "")).replace(GRAVE, ACUTE).lower()
    t = unicodedata.normalize("NFC", t)
    if t and t[-1] in ELISION_MARKS:
        t = t[:-1] + "’"
    return t


def _accented(nfd: str) -> bool:
    return any(a in nfd for a in ACCENTS)


def _acute_on(ending: str) -> str:
    """The ending with an acute on its first vowel (diphthongs: on the second letter)."""
    if len(ending) == 2:
        return ending[0] + ending[1] + ACUTE
    return ending + ACUTE


def _strip_accents(nfd: str) -> str:
    return "".join(c for c in nfd if c not in ACCENTS)


def _accent_on_last_vowel(nfd: str) -> bool:
    """The stem's accent stands on its last vowel (so an oxytone could have retracted onto it)."""
    pos = max(nfd.rfind(a) for a in ACCENTS)
    return pos >= 0 and not any(c in VOWELS for c in nfd[pos + 1:].lower())


def restorations(form: str):
    """[(restored spelling key, needs_rough_breathing)] for an elided spelling.

    Unaccented stem: the lost vowel carried the accent (oxytone) or the word was atonic, so the
    ending is restored with an acute or without accent. Accented stem: the ending is restored
    unaccented; when the accent is on the stem's last vowel, an oxytone that retracted its accent
    (πόλλ’ from πολλά) is also allowed. A final θ φ χ may stand for τ π κ (needs a rough breathing
    on the next word)."""
    if not is_elided(form):
        return []
    stem = unicodedata.normalize("NFD", key(form)[:-1])
    if not stem:
        return []
    stems = [(stem, False)]
    last = stem[-1]
    if last in DEASPIRATE:
        stems.append((stem[:-1] + DEASPIRATE[last], True))
    out = []
    for s, rough in stems:
        accented = _accented(s)
        for e in RESTORED_ENDINGS:
            variants = []
            if not accented:
                variants += [s + e, s + _acute_on(e)]
            else:
                variants.append(s + e)
                if ACUTE in s and _accent_on_last_vowel(s):
                    variants.append(_strip_accents(s) + _acute_on(e))
            for v in variants:
                out.append((unicodedata.normalize("NFC", v), rough))
    seen, unique = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def next_initial(text: str, end: int) -> str:
    """The next word's initial: rough / smooth (vowel with smooth breathing) / rho / consonant / none."""
    i = end
    n = len(text or "")
    while i < n and not text[i].isalpha():
        i += 1
    if i >= n:
        return "none"
    letters = unicodedata.normalize("NFD", text[i:i + 6])
    first = letters[:1].lower()
    marks, k = "", 1
    while k < len(letters) and unicodedata.combining(letters[k]):
        marks += letters[k]
        k += 1
    if first in VOWELS and k < len(letters) and letters[k].lower() in "ιυ":
        # diphthong: the breathing stands on the second letter (αἱ, οὑ, εὑ)
        k += 1
        while k < len(letters) and unicodedata.combining(letters[k]):
            marks += letters[k]
            k += 1
    if first == "ρ":
        return "rho"
    if ROUGH in marks:
        return "rough"
    if first in VOWELS:
        return "smooth"
    return "consonant"


def position(text: str, start: int) -> str:
    """Clause position of a word: start (text start or after . ; · : ! ?), comma, line, medial."""
    i = start - 1
    newline = False
    while i >= 0 and not (text[i].isalpha() or text[i] in STRONG_PUNCT or text[i] == ","):
        if text[i] == "\n":
            newline = True
        i -= 1
    if i < 0 or text[i] in STRONG_PUNCT:
        return "start"
    if text[i] == ",":
        return "comma"
    return "line" if newline else "medial"


def token_features(text, tokens, i, pred_at):
    """Feature values of token i ([(start, end, printed, form, damaged)], preds keyed by start)."""
    s, e = tokens[i][0], tokens[i][1]

    def pos_at(j):
        if j < 0 or j >= len(tokens):
            return "NONE"
        p = pred_at.get(tokens[j][0])
        return (p[3] if p and len(p) > 3 and p[3] else "UNK")
    return {"own_pos": pos_at(i), "next_pos": pos_at(i + 1), "prev_pos": pos_at(i - 1),
            "position": position(text, s), "next_initial": next_initial(text, e)}


def base_distribution(form, candidates, freq_lookup, rough_next, mix=0.8):
    """Base distribution over candidate headwords of an elided spelling.

    candidates: {headword: parser-based probability}; freq_lookup(restored_key) -> {headword: tokens}
    for spellings of the index. The restorations' corpus frequency (only accent-compatible
    restorations; θ φ χ read as τ π κ only before a rough breathing) is mixed with the parser-based
    ranking. Headwords that no restoration supports keep only their parser share."""
    freq = Counter()
    for restored, needs_rough in restorations(form):
        if needs_rough and not rough_next:
            continue
        for head, n in (freq_lookup(restored) or {}).items():
            if head in candidates:
                freq[head] += n
    total_f = sum(freq.values())
    total_c = sum(candidates.values()) or 1.0
    out = {}
    for head, p in candidates.items():
        f = freq[head] / total_f if total_f else 0.0
        out[head] = (mix * f + (1 - mix) * p / total_c) if total_f else p / total_c
    z = sum(out.values()) or 1.0
    return {h: v / z for h, v in out.items()}


class ElisionModel:
    """Naive Bayes ranking of an elided spelling's readings (see module docstring)."""

    def __init__(self, data):
        self.data = data
        self.prior = data.get("prior", {})
        self.feat = data.get("features", {})
        self.cls_feat = data.get("class_features", {})
        self.values = {k: data.get("values", {}).get(k, []) for k in FEATURES}
        p = data.get("params", {})
        self.alpha = float(p.get("alpha", 3.0))
        self.beta = float(p.get("beta", 10.0))
        self.tau = float(p.get("tau", 1.0))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def _p_feat(self, name, head_key, cls_name, value):
        nv = max(2, len(self.values.get(name) or []))
        cc = (self.cls_feat.get(name, {}).get(cls_name or "unknown") or {})
        p_cls = (cc.get(value, 0) + 1.0) / (sum(cc.values()) + nv)
        hc = self.feat.get(name, {}).get(head_key) or {}
        return (hc.get(value, 0) + self.beta * p_cls) / (sum(hc.values()) + self.beta)

    def rank(self, form, base, classes, features, fold_key):
        """[(headword, probability)] best first. base: {headword: p}; classes: {headword: pos};
        features: token_features(); fold_key: headword -> lemma key used in the model."""
        counts = self.prior.get(key(form)) or {}
        n = sum(counts.values())
        scores = {}
        for head, b in base.items():
            hk = fold_key(head)
            prior = (counts.get(hk, 0) + self.alpha * b) / (n + self.alpha)
            if prior <= 0:
                continue
            s = math.log(prior)
            for name in FEATURES:
                v = features.get(name)
                if v is None:
                    continue
                s += self.tau * math.log(self._p_feat(name, hk, classes.get(head), v))
            scores[head] = s
        if not scores:
            return sorted(base.items(), key=lambda kv: (-kv[1], kv[0]))
        top = max(scores.values())
        exp = {h: math.exp(s - top) for h, s in scores.items()}
        z = sum(exp.values())
        return sorted(((h, v / z) for h, v in exp.items()), key=lambda kv: (-kv[1], kv[0]))


def is_tie(ranked, ratio=TIE_RATIO, same=key):
    """The genuine alternative (headword, probability) when one is within ratio of the best, else None.
    Headwords that differ only in case (Τηλέμαχος / τηλέμαχος) are one reading, not a tie."""
    if not ranked:
        return None
    top_head, top_p = ranked[0]
    for head, p in ranked[1:]:
        if same(head) == same(top_head):
            continue
        return (head, p) if p >= ratio * top_p else None
    return None


__all__ = ["is_elided", "key", "restorations", "next_initial", "position", "token_features",
           "base_distribution", "ElisionModel", "is_tie", "FEATURES", "ELIDED_ONLY_FEATURES", "TIE_RATIO"]
