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
    "generated_spelling": "only a parse of a generated dialect/elision spelling",
    "context_chose": "the contextual model changed the choice among the parser's lemmas",
    "context_agrees": "the contextual model names the same lemma",
    "no_context_signal": "no contextual agreement (model did not run, or named another lemma it could not impose)",
}
_LOCK = threading.Lock()
_CACHE = {}


def evidence_class(bits):
    bits = int(bits)
    if bits & 64:
        return "damaged_word"
    if bits & 4 and not bits & 1:
        return "generated_spelling"
    if bits & 32:
        return "context_chose"
    if bits & 16:
        return "context_agrees"
    return "no_context_signal"


def _lookup(table, conf):
    """Step function from isotonic blocks [[lo, hi, value, weight], ...] (raw score 0-255)."""
    if not table:
        return None
    for lo, hi, value, _ in table:
        if conf <= hi:
            return value
    return table[-1][2]


def apply_model(model, conf, bits):
    table = model.get(evidence_class(bits)) or model.get("all")
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


def probability(conf, bits):
    """Calibrated probability that the token's headline headword is right, or None."""
    data = calibration()
    if not data or not conf:
        return None
    return apply_model(data["model"], conf, bits)


def summary():
    data = calibration()
    if not data:
        return {"calibrated": False, "note": "No calibration deployed; confidence is the raw normalised score."}
    return {"calibrated": True, "version": data.get("version"), "built_at": data.get("built_at"),
            "method": data.get("method"), "gold": data.get("gold"), "classes": data.get("classes"),
            "fit_tokens_by_class": data.get("fit_tokens_by_class")}


__all__ = ["evidence_class", "apply_model", "probability", "summary", "CLASSES"]
