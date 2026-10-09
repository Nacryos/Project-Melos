"""Score the metre-free scanner on random chunks of the owner's hexameter scansions.

Gold: C:/Users/alvin/homer-bard/data/scansion/<work>_scansion.jsonl (read only; MELOS_OWNER_SCANSION to
override). Iliad = the owner's own Iliad scansion (Homerides training data, from the owner's
"Iliad Parsed Interlinear" conversion); the other works were scanned by homer-bard's rule-based
hexameter scanner (scripts/scan_work.py, 99.3 % feet accuracy on the Iliad), so they are
metre-fitted machine output, not hand scansion.

Chunks of CHUNK consecutive scanned lines are drawn per work with a fixed seed and split into
`dev` (used while editing general rules) and `heldout` (scored once, at the end). The manifest is
written to backend/scansion/data/eval_chunks.json the first time and reused afterwards. Iliad
held-out chunks come from Books 13-24 only (Books 1-12 of the Hypotactic Iliad calibrated the
measured parameters).

A line is scored unit by unit when the scanner finds as many units as the gold has quantities;
otherwise (synizesis, gold slips) it is counted as a unit-count mismatch. The final 'x' is skipped.

    python scripts/scansion_eval_owner.py --split dev [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scansion.lexicon import QuantityLexicon  # noqa: E402
from backend.scansion.quantity import Scanner  # noqa: E402

GOLD = Path(os.environ.get("MELOS_OWNER_SCANSION", "C:/Users/alvin/homer-bard/data/scansion"))
WORKS = ["iliad", "odyssey", "homeric_hymns", "theogony", "works_and_days", "shield", "argonautica",
         "quintus_posthomerica", "nonnus_dionysiaca"]
CHUNK, PER_SPLIT, SEED = 20, 8, 20261009
MANIFEST = ROOT / "backend/scansion/data/eval_chunks.json"


def load(work):
    rows = []
    with open(GOLD / f"{work}_scansion.jsonl", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("quantities") and r["quantities"] != "UNSCANNED":
                rows.append(r)
    return rows


def manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    doc = {"seed": SEED, "chunk_lines": CHUNK, "per_split_per_work": PER_SPLIT, "works": {}}
    for work in WORKS:
        rows = load(work)
        starts = list(range(0, len(rows) - CHUNK, CHUNK))
        if work == "iliad":
            late = [s for s in starts if rows[s].get("book", 0) >= 13]
            early = [s for s in starts if rows[s].get("book", 0) < 13]
            held = rng.sample(late, PER_SPLIT)
            dev = rng.sample(early, PER_SPLIT)
        else:
            pick = rng.sample(starts, 2 * PER_SPLIT)
            dev, held = pick[:PER_SPLIT], pick[PER_SPLIT:]
        doc["works"][work] = {"lines_scanned": len(rows), "dev": sorted(dev), "heldout": sorted(held)}
    MANIFEST.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def score(scanner, lines):
    tot = defaultdict(int)
    by_rule = defaultdict(lambda: defaultdict(int))
    bins = defaultdict(lambda: [0, 0])
    amb = defaultdict(int)
    errors = defaultdict(list)
    brier = 0.0
    times = []
    for r in lines:
        t0 = time.perf_counter()
        units = scanner.scan(r["text"])
        times.append((time.perf_counter() - t0) * 1000)
        q = r["quantities"]
        tot["lines"] += 1
        if len(units) != len(q):
            tot["count_mismatch"] += 1
            continue
        for u, g in zip(units, q):
            if g == "x" or any(f["id"] == "FIN-ANC" for f in u.flags):
                continue
            y = int(g == "-")
            tot["n"] += 1
            brier += (u.p_long - y) ** 2
            bins[min(int(u.p_long * 10), 9)][0] += 1
            bins[min(int(u.p_long * 10), 9)][1] += y
            key = u.rule if u.rule not in ("NATURE", "CONS-VOW") else f"{u.rule}/{u.vowel['rule']}"
            by_rule[key]["n"] += 1
            if u.label == "A":
                tot["A"] += 1
                amb[key] += 1
            else:
                tot["decided"] += 1
                ok = (u.label == "L") == bool(y)
                tot["ok"] += ok
                by_rule[key]["ok" if ok else "wrong"] += 1
                if not ok and len(errors[key]) < 3:
                    errors[key].append(f"{r.get('work', 'iliad')} {r.get('book', '')}.{r.get('line', '')}: "
                                       f"'{u.text}' gold {'long' if y else 'short'}, scanner {u.label} p={u.p_long:.2f}")
    n = max(tot["n"], 1)
    times.sort()
    return {
        "lines": tot["lines"], "lines_unit_count_differs": tot["count_mismatch"], "units_scored": tot["n"],
        "decided_share": round(tot["decided"] / n, 4),
        "decided_accuracy": round(tot["ok"] / max(tot["decided"], 1), 4),
        "ambiguous_share": round(tot["A"] / n, 4), "brier": round(brier / n, 4),
        "reliability": {f"{b / 10:.1f}-{(b + 1) / 10:.1f}": {"n": c, "observed_long": round(l / c, 3)}
                        for b, (c, l) in sorted(bins.items()) if c},
        "ambiguous_by_rule": dict(sorted(amb.items(), key=lambda kv: -kv[1])),
        "errors_by_rule": {k: {"wrong": v.get("wrong", 0), "of_decided": v.get("ok", 0) + v.get("wrong", 0),
                               "examples": errors.get(k, [])}
                           for k, v in sorted(by_rule.items(), key=lambda kv: -kv[1].get("wrong", 0)) if v.get("wrong")},
        "ms_per_line": {"median": round(times[len(times) // 2], 3), "p95": round(times[int(len(times) * .95)], 3)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "heldout"], required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--params", choices=["written", "measured"], default="written")
    args = ap.parse_args()
    man = manifest()
    params = None
    if args.params == "measured":
        cal = json.loads((ROOT / "backend/scansion/data/rule_calibration.json").read_text(encoding="utf-8"))
        params = {k: v["share"] for k, v in cal["with_lexicon"]["params"].items() if v["share"] is not None and v["n"] >= 20}
    lex = QuantityLexicon()
    report = {"split": args.split, "params": args.params, "chunk_lines": man["chunk_lines"], "works": {}}
    all_lines = []
    for work in WORKS:
        rows = load(work)
        lines = [rows[i] for s in man["works"][work][args.split] for i in range(s, s + man["chunk_lines"])]
        all_lines += lines
        report["works"][work] = {
            "without_lexicon": score(Scanner(lexicon=None, params=params), lines),
            "with_lexicon": score(Scanner(lexicon=lex, params=params), lines),
        }
    report["all_works"] = {"without_lexicon": score(Scanner(lexicon=None, params=params), all_lines),
                           "with_lexicon": score(Scanner(lexicon=lex, params=params), all_lines)}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:3000])


if __name__ == "__main__":
    main()
