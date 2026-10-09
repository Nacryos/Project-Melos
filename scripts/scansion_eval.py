"""Calibrate and evaluate the metre-free scanner against the Hypotactic Iliad (CC BY 4.0).

    python scripts/scansion_eval.py calibrate   # books 1-12: share long per rule, both lexicon modes
                                                #   -> backend/scansion/data/rule_calibration.json
    python scripts/scansion_eval.py evaluate    # books 13-24: accuracy, calibration, speed
                                                #   (rules as written, with and without the lexicon,
                                                #    and with parameters set to the measured shares)

Alignment: the line text is rebuilt from the gold syllables, so both share one sequence of Greek
letters. Each unit is matched to the gold syllable containing its nucleus's first letter; a gold
syllable holding two nuclei is a merger (synizesis) and both units are left out of the per-unit
figures (and counted for the synizesis rate). The last unit of a line (brevis in longo) is left out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scansion.gold import load_iliad  # noqa: E402
from backend.scansion.greek import letters  # noqa: E402
from backend.scansion.lexicon import QuantityLexicon  # noqa: E402
from backend.scansion.quantity import Scanner  # noqa: E402

TRAIN, TEST = range(1, 13), range(13, 25)
CAL_PATH = ROOT / "backend/scansion/data/rule_calibration.json"


def align(line, results):
    bounds, n = [], 0
    for syl in line.syllables:
        n += len(letters(syl))
        bounds.append(n)
    gold_idx = []
    for r in results:
        o = len(letters(line.text[: r.nstart]))
        gold_idx.append(next((i for i, b in enumerate(bounds) if o < b), None))
    out = []
    for k, r in enumerate(results):
        g = gold_idx[k]
        mnext = k + 1 < len(results) and gold_idx[k + 1] == g
        mprev = k > 0 and gold_idx[k - 1] == g
        out.append((r, line.lengths[g] if g is not None else None, mnext, mprev, r.rule == "FIN-ANC"))
    return out


def scored(scanner, lines):
    for line in lines:
        res = scanner.scan(line.text)
        for r, label, mnext, mprev, final in align(line, res):
            yield line, r, label, mnext, mprev, final


def measure(scanner, lines) -> dict:
    """Share long per unit rule, per vowel rule (where the vowel decides), and per flag."""
    unit = defaultdict(lambda: [0, 0])
    vowel = defaultdict(lambda: [0, 0])
    flag = defaultdict(lambda: [0, 0])
    param = defaultdict(lambda: [0, 0])
    for line, r, label, mnext, mprev, final in scored(scanner, lines):
        for f in r.flags:
            if f["id"] == "SYN-CAND":
                flag["SYN-CAND"][0] += 1
                flag["SYN-CAND"][1] += int(mnext)
        if label is None or final or mnext or mprev:
            continue
        y = int(label == "L")
        for node in r.path:
            unit[node][0] += 1
            unit[node][1] += y
        pv = r.vowel["p_long"]
        if r.rule in ("NATURE", "CONS-VOW"):
            for node in r.vowel["path"]:
                vowel[node][0] += 1
                vowel[node][1] += y
        # inputs for the measured parameters
        if r.rule == "COR-EXT" and pv >= 0.99:
            param["correption"][0] += 1; param["correption"][1] += y
        if r.rule == "DIG-HIA" and pv >= 0.99:
            param["digamma_keep"][0] += 1; param["digamma_keep"][1] += y
        if r.rule == "COR-INT":
            param["internal_keep"][0] += 1; param["internal_keep"][1] += y
        if r.rule == "MCL-WORD" and pv <= 0.01:
            param["mcl_word"][0] += 1; param["mcl_word"][1] += y
        if r.rule == "MCL-INIT" and pv <= 0.01:
            param["mcl_boundary"][0] += 1; param["mcl_boundary"][1] += y
        if r.rule in ("NATURE", "CONS-VOW"):
            vr = r.vowel["rule"]
            key = {"DICH-UNK": "dichronon_default", "LEX-L": "lex_long", "LEX-S": "lex_short",
                   "LEX-UNMARKED": "lex_unmarked"}.get(vr)
            if key:
                param[key][0] += 1; param[key][1] += y
        if r.rule == "DIG-LEN" and pv <= 0.01:
            param["digamma_lengthening"][0] += 1; param["digamma_lengthening"][1] += y
        if r.rule == "EPL-RHO" and pv <= 0.01:
            param["epic_lengthening_rho"][0] += 1; param["epic_lengthening_rho"][1] += y
        if r.rule == "EPL-INIT" and pv <= 0.01:
            param["epic_lengthening"][0] += 1; param["epic_lengthening"][1] += y
    param["synizesis"] = flag["SYN-CAND"]

    def fmt(d):
        return {k: {"n": n, "long": l, "share": round(l / n, 4) if n else None} for k, (n, l) in sorted(d.items())}
    return {"unit": fmt(unit), "vowel": fmt(vowel), "flags": fmt(flag), "params": fmt(param)}


def calibrate(args):
    lines = load_iliad(books=TRAIN)
    doc = {"gold": "Hypotactic Iliad scansion (David Chamberlain, CC BY 4.0), books 1-12",
           "lines": len(lines), "built": time.strftime("%Y-%m-%d"),
           "note": "share = gold-long units / units reaching the rule; the line-final unit and synizesis mergers "
                   "are left out. 'params' are the shares the tunable parameters would take if set from Homer.",
           "without_lexicon": measure(Scanner(lexicon=None), lines),
           "with_lexicon": measure(Scanner(lexicon=QuantityLexicon()), lines)}
    CAL_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"calibration from {len(lines)} lines -> {CAL_PATH}")


def evaluate_one(scanner, lines) -> dict:
    tot = defaultdict(int)
    by_rule = defaultdict(lambda: defaultdict(int))
    bins = defaultdict(lambda: [0, 0])
    amb = defaultdict(int)
    brier = 0.0
    merges = merges_flagged = 0
    for line, r, label, mnext, mprev, final in scored(scanner, lines):
        if mnext:
            merges += 1
            merges_flagged += any(f["id"] == "SYN-CAND" for f in r.flags)
        if label is None or final or mnext or mprev:
            continue
        tot["n"] += 1
        y = int(label == "L")
        p = r.p_long
        brier += (p - y) ** 2
        bins[min(int(p * 10), 9)][0] += 1
        bins[min(int(p * 10), 9)][1] += y
        lab = r.label
        key = r.rule if r.rule not in ("NATURE", "CONS-VOW") else f"{r.rule}/{r.vowel['rule']}"
        by_rule[key]["n"] += 1
        if lab == "A":
            tot["A"] += 1
            amb[key] += 1
            by_rule[key]["A"] += 1
        else:
            tot["decided"] += 1
            ok = lab == label
            tot["ok"] += ok
            by_rule[key]["ok" if ok else "wrong"] += 1
        tot["hard"] += int((p >= 0.5) == bool(y)) if p != 0.5 else 0
        tot["half"] += int(p == 0.5)
    n = tot["n"]
    return {
        "units_scored": n,
        "decided_share": round(tot["decided"] / n, 4),
        "decided_accuracy": round(tot["ok"] / max(tot["decided"], 1), 4),
        "ambiguous_share": round(tot["A"] / n, 4),
        "accuracy_if_p>0.5_is_long (p=0.5 counted wrong)": round(tot["hard"] / n, 4),
        "units_at_exactly_0.5": tot["half"],
        "brier": round(brier / n, 4),
        "calibration": {f"{b / 10:.1f}-{(b + 1) / 10:.1f}": {"n": c, "observed_long": round(l / c, 3)}
                        for b, (c, l) in sorted(bins.items()) if c},
        "ambiguous_by_rule": dict(sorted(amb.items(), key=lambda kv: -kv[1])),
        "by_rule": {k: dict(v) for k, v in sorted(by_rule.items())},
        "synizesis_mergers_in_gold": merges,
        "mergers_flagged": merges_flagged,
    }


def measured_params() -> dict:
    cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))["with_lexicon"]["params"]
    return {k: v["share"] for k, v in cal.items() if v["share"] is not None and v["n"] >= 20}


def speed(scanner, lines, cold: bool) -> dict:
    from backend.scansion import lexicon as lexmod
    times = []
    for line in lines:
        if cold:
            lexmod._lookup_cached.cache_clear()
        t0 = time.perf_counter()
        scanner.scan(line.text)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {"lines": len(times), "median_ms": round(times[len(times) // 2], 3),
            "p95_ms": round(times[int(len(times) * 0.95)], 3), "max_ms": round(times[-1], 3)}


def evaluate(args):
    books = TEST if not args.books else [int(b) for b in args.books.split(",")]
    lines = load_iliad(books=books)
    lex = QuantityLexicon()
    report = {"books": list(books), "lines": len(lines),
              "lines_unit_count_differs_from_gold": sum(len(Scanner().scan(l.text)) != len(l.syllables) for l in lines)}
    report["rules_as_written_without_lexicon"] = evaluate_one(Scanner(lexicon=None), lines)
    report["rules_as_written_with_lexicon"] = evaluate_one(Scanner(lexicon=lex), lines)
    mp = measured_params()
    report["measured_params"] = mp
    report["measured_params_without_lexicon"] = evaluate_one(Scanner(lexicon=None, params=mp), lines)
    report["measured_params_with_lexicon"] = evaluate_one(Scanner(lexicon=lex, params=mp), lines)
    sample = lines[:500]
    report["speed_warm_lexicon"] = speed(Scanner(lexicon=lex), sample, cold=False)
    report["speed_cold_lexicon_cache_cleared_per_line"] = speed(Scanner(lexicon=lex), sample, cold=True)
    report["speed_without_lexicon"] = speed(Scanner(lexicon=None), sample, cold=False)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "evaluate"])
    ap.add_argument("--books", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    {"calibrate": calibrate, "evaluate": evaluate}[args.mode](args)


if __name__ == "__main__":
    main()
