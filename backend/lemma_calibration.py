"""Calibrated headword confidence (release P).

The index stores a normalised evidence score per token (0-255). scripts/calibrate_lemma_confidence.py
fits, on treebank gold lemmas with the gold texts' own annotations withheld, a monotone map from that
score to the observed rate of agreement with the gold lemma, separately per evidence class. The map
(data/lemma_calibration.json, env MELOS_LEMMA_CALIBRATION) is applied here; without it the API
reports probability null rather than passing the raw score off as one.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES = {
    "damaged_word": "word printed with brackets or underdots",
    "elision_model": "elided word whose reading the elision model ranked (release Q)",
    "generated_spelling": "only a parse of a generated dialect/elision spelling",
    "context_chose": "the contextual model changed the choice among the parser's lemmas",
    "context_agrees": "the contextual model names the same lemma",
    "context_disagrees": ("the contextual model names another reading of the same spelling, which it could not "
                          "impose (release Q; index table token_flag bit 1)"),
    "recorded_form_no_context": ("no contextual signal, but the spelling is recorded with this lemma in a source "
                                 "annotation (exact dictionary/treebank form match; release Q)"),
    "no_context_signal": ("no contextual signal: the model did not run, or named a lemma that is not a reading of "
                          "the spelling (typical of dialect forms it cannot lemmatise)"),
}
_LOCK = threading.Lock()
_CACHE = {}


CONTEXT_DISAGREES = 1   # token_flag bit: the contextual model named another reading of this spelling


# Coarse parts of speech that one lexeme spans in dictionary practice (ταχέως under ταχύς).
_FAMILY_POS = {frozenset(("adverb", "adjective"))}


def same_lexeme(a, b, pos_a, pos_b, form_lemmas):
    """Release Q: headwords a and b name one lexeme under different lemmatisation conventions when the
    source annotations record one spelling as an inflected form of the other (μάλιστα under μάλα,
    εἶδον under ὁράω, ταχέως under ταχύς) and their parts of speech agree (adverb/adjective counted as
    one family). A different word that happens to share a spelling (ἦ particle, a form of εἰμί; τοι,
    a form of σύ) differs in part of speech and is not the same lexeme. `form_lemmas(spelling)` lists
    the lemmas recorded for an exact spelling (backend.morphology.Morphology.form_lemmas)."""
    from .lemma_tokens import fold
    if not a or not b or fold(a) == fold(b):
        return bool(a) and fold(a) == fold(b)
    pa, pb = (pos_a or "").lower(), (pos_b or "").lower()
    if not pa or not pb or (pa != pb and frozenset((pa, pb)) not in _FAMILY_POS):
        return False
    return (fold(b) in {fold(x) for x in form_lemmas(a)}) or (fold(a) in {fold(x) for x in form_lemmas(b)})


def evidence_class(bits, flags=0):
    """Evidence class of a token from its source bits and (release Q) its token_flag bits."""
    bits = int(bits)
    if bits & 64:
        return "damaged_word"
    if bits & 128:
        return "elision_model"
    if bits & 4 and not bits & 1:
        return "generated_spelling"
    if bits & 32:
        return "context_chose"
    if bits & 16:
        return "context_agrees"
    if int(flags or 0) & CONTEXT_DISAGREES:
        return "context_disagrees"
    if bits & 2:
        return "recorded_form_no_context"
    return "no_context_signal"


def _lookup(table, conf):
    """Step function from isotonic blocks [[lo, hi, value, weight], ...] (raw score 0-255)."""
    if not table:
        return None
    for lo, hi, value, _ in table:
        if conf <= hi:
            return value
    return table[-1][2]


def apply_model(model, conf, bits, flags=0):
    table = model.get(evidence_class(bits, flags)) or model.get("all")
    value = _lookup(table, int(conf))
    return None if value is None else round(float(value), 3)


def path():
    return Path(os.getenv("MELOS_LEMMA_CALIBRATION", str(ROOT / "data/lemma_calibration.json")))


def calibration():
    """The fitted calibration document, or None when not deployed."""
    p = path()
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        return None
    with _LOCK:
        if _CACHE.get("stamp") != stamp:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            _CACHE.update(stamp=stamp, data=data if data and data.get("model") else None)
        return _CACHE["data"]


def probability(conf, bits, flags=0):
    """Calibrated probability that the token's headline headword is right, or None. `flags`: the
    token's token_flag bits (release Q index; 0 for an older index)."""
    data = calibration()
    if not data or not conf:
        return None
    return apply_model(data["model"], conf, bits, flags)


def summary():
    data = calibration()
    if not data:
        return {"calibrated": False, "note": "No calibration deployed; confidence is the raw normalised score."}
    return {"calibrated": True, "version": data.get("version"), "built_at": data.get("built_at"),
            "method": data.get("method"), "gold": data.get("gold"), "classes": data.get("classes"),
            "fit_tokens_by_class": data.get("fit_tokens_by_class")}


__all__ = ["same_lexeme", "evidence_class", "apply_model", "probability", "summary", "CLASSES", "CONTEXT_DISAGREES"]
