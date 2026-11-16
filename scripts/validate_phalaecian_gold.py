#!/usr/bin/env python3
"""Run the Latin scanner over EVERY Catullan hendecasyllable in the Hypotactic gold (dev and held-out together) and
write one record per line: accepted or not, best pattern against the hand scansion, and the cause of each miss.

Setting: core rules + quantity lexicon, text as Hypotactic prints it (v and j written), the same as the `lexicon`
rows of docs/latin/eval-log.md. Poems 55 and 58b may take the decasyllabic template (scripts/scansion_eval_la.py).

Usage: python scripts/validate_phalaecian_gold.py [--out docs/latin/eval/NAME.json] [--fold-v]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.scansion import gold_la  # noqa: E402
from backend.scansion.lexicon_la import LatinQuantityLexicon  # noqa: E402
from backend.scansion.quantity_la import LatinScanner  # noqa: E402
from scansion_eval_la import best_fit, fold_v  # noqa: E402


def cause_of(g, units, fit) -> tuple[str, list[dict]]:
    """Why the line is rejected or mis-scanned, read off the gold: the units that disagree with the hand scansion."""
    if len(units) != len(g.lengths):
        return "syllable count differs from the gold (synizesis, diaeresis or a Greek name the lists do not know)", []
    diffs = []
    elided = {s for a in fit.assignment if a.get("elided") for s in a["syllables"]}
    first = units[0].index if units else 0
    for k, (u, q) in enumerate(zip(units, g.lengths)):
        if k == len(units) - 1:
            break
        took = "E" if (first + k) in elided else None
        if took is None:
            took = next((a["weight"] for a in fit.assignment if not a.get("elided") and (first + k) in a["syllables"]), "?")
        if took != q:
            diffs.append({"unit": u.text, "gold": q, "scanner": took, "p_long": round(u.p_long, 3), "rule": u.rule,
                          "vowel_rule": u.vowel["rule"], "gold_flags": g.flags[k]})
    if not diffs:
        return ("rejected although every unit agrees: " + fit.message) if not fit.ok else "", diffs
    kinds = Counter()
    for d in diffs:
        if "E" in (d["gold"], d["scanner"]):
            kinds["elision / hiatus decided differently"] += 1
        elif d["vowel_rule"].startswith("LEX"):
            kinds["lexicon quantity (" + d["vowel_rule"] + ")"] += 1
        elif d["rule"].startswith(("POS", "MCL", "INIT", "S-IMP")):
            kinds["position rule (" + d["rule"] + ")"] += 1
        else:
            kinds["rule " + d["rule"] + " / " + d["vowel_rule"]] += 1
    return "; ".join(f"{k} x{v}" for k, v in kinds.items()), diffs


def run(fold: bool = False) -> dict:
    lines = gold_la.load(work="catullus", metre="hendecasyllables")
    sc = LatinScanner(lexicon=LatinQuantityLexicon(), spelling="u" if fold else "uv")
    rows = []
    tot = Counter()
    for g in lines:
        units = sc.scan(fold_v(g.plain) if fold else g.plain)
        fit = best_fit(units, "phalaecian", g)
        aligned = len(units) == len(g.lengths)
        same = bool(fit.pattern) and fit.pattern[:-1] == g.pattern[:-1]       # the line-final anceps is not compared
        cause, diffs = ("", []) if (fit.ok and same) else cause_of(g, units, fit)
        rows.append({"id": g.id, "poem": g.poem, "line": g.line_no, "split": g.split, "text": g.plain,
                     "gold_pattern": g.pattern, "gold_q": "".join(g.lengths), "aligned": aligned, "accepted": bool(fit.ok),
                     "template": fit.metre, "pattern": fit.pattern, "equals_gold": same, "message": fit.message,
                     "cause": cause, "diffs": diffs,
                     "violations": [{k: v.get(k) for k in ("text", "needs", "p_long", "rule")} for v in fit.violations]})
        for scope in ("all", g.split):
            tot[scope, "lines"] += 1
            tot[scope, "aligned"] += aligned
            tot[scope, "accepted"] += bool(fit.ok)
            tot[scope, "equals_gold"] += same
            tot[scope, "accepted_and_equal"] += bool(fit.ok) and same
    summary = {s: {k: tot[s, k] for k in ("lines", "aligned", "accepted", "equals_gold", "accepted_and_equal")}
               for s in ("all", "dev", "held_out")}
    return {"setting": {"work": "catullus", "metre": "hendecasyllables", "lexicon": True, "fold_v": fold,
                        "decasyllable_poems": ["55", "58b"], "poems": sorted({r["poem"] for r in rows}, key=lambda p: (int("".join(c for c in p if c.isdigit()) or 0), p))},
            "summary": summary, "problems": [r for r in rows if not (r["accepted"] and r["equals_gold"])], "lines": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--fold-v", action="store_true")
    args = ap.parse_args()
    res = run(args.fold_v)
    print(json.dumps(res["summary"], indent=1))
    for r in res["problems"]:
        print(("REJECTED " if not r["accepted"] else "MIS-SCANNED "), r["poem"] + "." + str(r["line"]), "|", r["text"], "|", r["pattern"],
              "vs", r["gold_pattern"], "|", r["cause"], "|",
              "; ".join(f"{d['unit']}:{d['scanner']}!={d['gold']} p={d['p_long']} {d['rule']}/{d['vowel_rule']}" for d in r["diffs"]),
              "|", r["message"] if not r["accepted"] else "")
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
