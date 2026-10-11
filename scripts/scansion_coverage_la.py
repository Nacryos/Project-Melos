#!/usr/bin/env python3
"""The coverage report of docs/prd/latin-composer.md §4.3 from the evaluation JSONs in docs/latin/eval/:
what share of syllables each layer decides, and how right it is, core versus lexicon, on one split.
Usage: python scripts/scansion_coverage_la.py [--split held_out] [--prefix catullus-hendeca]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="held_out")
    ap.add_argument("--prefix", default="catullus-hendeca")
    ap.add_argument("--folded", action="store_true")
    args = ap.parse_args()
    suffix = "-folded" if args.folded else ""
    rows = []
    for setting in ("core", "lexicon"):
        path = ROOT / "docs" / "latin" / "eval" / f"{args.prefix}-{args.split}-{setting}{suffix}.json"
        if not path.exists():
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        by = r.get("decided_by", {})
        f, n, e = r["fit"], r["negative_control"], r["elision"]
        rows.append((setting, r, by, f, n, e))
    print(f"Split: {args.split}{' (u/i only)' if args.folded else ' (as typed)'}; units scored exclude the line-final unit.\n")
    print("| Setting | Decided | by position | by diphthong / monosyllable | by finals and lists | by lexicon | Accuracy on decided | Brier | Elision right | Lines fitting | Best pattern = gold | Perturbed lines rejected (swap / replace) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for setting, r, by, f, n, e in rows:
        def share(k):
            v = by.get(k, {}).get("share_of_scored", 0.0)
            return f"{v*100:.1f} %"
        print(f"| {setting} | {r['decided_share']*100:.1f} % | {share('position')} | {share('diphthong_or_monosyllable')} | "
              f"{share('finals_and_lists')} | {share('lexicon')} | {r['accuracy_on_decided']*100:.2f} % | {r['brier']:.3f} | "
              f"{e['accuracy']*100:.1f} % | {f['ok']}/{f['lines']} | {f['pattern_match']}/{f['lines']} | "
              f"{(1 - n['swap_accepted']/n['swap_total'])*100:.0f} % / {(1 - n['replace_accepted']/n['replace_total'])*100:.0f} % |")
    for setting, r, by, f, n, e in rows:
        amb = r.get("ambiguous_by_rule", [])[:6]
        print(f"\nStill open ({setting}): " + "; ".join(f"{k} ({v})" for k, v in amb))


if __name__ == "__main__":
    main()
