"""Metre-locked resolution for the READER only (release V; docs/scansion.md §10).

When a stored poem's metre is recorded (recorded_metres.py), the metre settles syllables the scanner left
uncertain: a unit whose p_long is in the uncertain band [0.30, 0.70] at a position whose quantity the metre
fixes (long or short; anceps and the line end do not count) moves 0.50 toward that quantity, clamped to 0..1.
A unit outside the band that contradicts the metre is not moved; it is flagged as a conflict (a textual or
responsion problem). Lines with editorial marks (brackets, lacunae, dotted letters) and lines that do not
parse against any of the metre's line templates are left alone.

The composer never calls this module: its scans exist to catch the writer's errors, not to hide them
(tests/test_compose_routes.py asserts it).
"""
from __future__ import annotations

from . import metre

BAND = (0.30, 0.70)
SHIFT = 0.50
FIXED = {"-": "long", "u": "short", "D": None, "R": None}      # D, R: fixed by the parse's realisation
ANCEPS = {"x", "X", "F"}


def _requirement(symbol: str, weight: str) -> str:
    if symbol in ANCEPS:
        return "anceps"
    if symbol in FIXED and FIXED[symbol]:
        return FIXED[symbol]
    return "long" if weight == "L" else "short"


def lock_line(sylls, metre_name: str) -> dict:
    """Best-fitting template of `metre_name` for one line → {template, ok, units: {unit index: info}}."""
    best = None
    for template in dict.fromkeys(metre.TEMPLATES[metre_name]):
        f = metre.fit_line(sylls, metre_name, template)
        if f.log_likelihood > float("-inf") and (best is None or f.log_likelihood > best.log_likelihood):
            best = f
    if best is None:
        return {"template": None, "ok": False, "units": {}}
    by_index = {s.index: s for s in sylls}
    # Name the line by its own template when one metre is exactly that line (Sapphic hendecasyllable, adonean).
    single = next((n for n, t in metre.TEMPLATES.items() if t == [best.template]), metre_name)
    label = single.replace("_", " ").capitalize() if single.startswith("sapphic") else single.replace("_", " ")
    units = {}
    for entry in best.assignment:
        if entry.get("synizesis") or entry.get("elided"):
            continue
        (idx,) = entry["syllables"]
        s = by_index[idx]
        need = _requirement(entry["symbol"], entry["weight"])
        info = {"position": entry["position"] + 1, "symbol": entry["symbol"], "requires": need,
                "p_before": round(s.p_long, 3), "p_after": round(s.p_long, 3), "adjusted": False, "conflict": False}
        p = s.p_long
        if need in ("long", "short"):
            if BAND[0] <= p <= BAND[1]:
                q = min(1.0, p + SHIFT) if need == "long" else max(0.0, p - SHIFT)
                info.update(p_after=round(q, 3), adjusted=True,
                            reason=f"metre: {label}, position {info['position']} requires {need}; "
                                   f"{round(p * 100)}% → {round(q * 100)}%")
            elif (need == "short" and p > BAND[1]) or (need == "long" and p < BAND[0]):
                info.update(conflict=True,
                            reason=f"metre: {label}, position {info['position']} requires {need}, but the scanner "
                                   f"gives {round(p * 100)}% long; not adjusted (a textual or responsion problem?)")
        else:
            info["reason"] = f"metre: {label}, position {info['position']} is anceps"
        units[idx] = info
    return {"template": best.template, "ok": best.ok, "units": units}
