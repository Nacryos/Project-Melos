"""Calibrate and evaluate the metre-free scanner against the Hypotactic Iliad (CC BY 4.0).

    python scripts/scansion_eval.py calibrate   # books 1-12 -> backend/scansion/data/leaf_rates.json
    python scripts/scansion_eval.py evaluate    # books 13-24 -> report (JSON on stdout / --out)

Alignment: the line text is rebuilt from the gold syllables, so the Greek letters of the scanner's
input and of the gold syllables are the same sequence. Each scanner syllable is matched to the gold
syllable that contains its nucleus's first letter. Two scanner syllables in one gold syllable are a
merger (synizesis / crasis not written as such); they are counted for the synizesis rate and left
out of the per-syllable figures. The last syllable of every line (brevis in longo) is left out.
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
from backend.scansion.quantity import Scanner  # noqa: E402

TRAIN, TEST = range(1, 13), range(13, 25)


def align(line, results):
    """[(result, gold 'L'/'S'/None, merged_with_next: bool)] for one gold line."""
    bounds, n = [], 0
    for syl in line.syllables:
        n += len(letters(syl))
        bounds.append(n)
    text = line.text
    ordinal = []
    for r in results:
        ordinal.append(len(letters(text[: r.nstart])))
    gold_idx = []
    for o in ordinal:
        g = next((i for i, b in enumerate(bounds) if o < b), None)
        gold_idx.append(g)
    out = []
    for k, r in enumerate(results):
        g = gold_idx[k]
        merged_next = k + 1 < len(results) and gold_idx[k + 1] == g
        merged_prev = k > 0 and gold_idx[k - 1] == g
        label = line.lengths[g] if g is not None else None
        out.append((r, label, merged_next, merged_prev, g == len(line.syllables) - 1))
    return out


def prefixes(leaf: str):
    parts = leaf.split(":")
    return [":".join(parts[:i]) for i in range(1, len(parts) + 1)]


def calibrate(args):
    sc = Scanner(rates={})
    counts = defaultdict(lambda: [0, 0])
    syn = defaultdict(lambda: [0, 0])
    lines = load_iliad(books=TRAIN)
    for line in lines:
        res = sc.scan(line.text)
        for r, label, mnext, mprev, final in align(line, res):
            cand = [f for f in r.flags if f["id"] == "SYN-CAND"]
            if cand:
                pair = cand[0]["detail"].split(" may")[0].replace(" + ", "")[:2]
                for key in ("SYN-CAND", f"SYN-CAND:{pair}"):
                    syn[key][0] += 1
                    syn[key][1] += int(mnext)
            if label is None or final or mnext or mprev:
                continue
            for key in prefixes(r.leaf):
                counts[key][0] += 1
                counts[key][1] += int(label == "L")
    leaves = {k: {"n": n, "long": l, "p": round((l + 0.5) / (n + 1), 4)} for k, (n, l) in sorted(counts.items())}
    for k, (n, m) in sorted(syn.items()):
        leaves[k] = {"n": n, "long": m, "p": round((m + 0.5) / (n + 1), 4), "kind": "merge_rate"}
    doc = {
        "source": "Hypotactic Iliad scansion (David Chamberlain, CC BY 4.0), books 1-12",
        "method": "share of gold-long syllables per decision-tree leaf (Jeffreys-smoothed: (long+0.5)/(n+1)); "
                  "SYN-CAND entries are the share of candidates merged into one gold syllable",
        "lines": len(lines),
        "built": time.strftime("%Y-%m-%d"),
        "leaves": leaves,
    }
    out = ROOT / "backend/scansion/data/leaf_rates.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(leaves)} leaves from {len(lines)} lines -> {out}")


def evaluate(args):
    sc = Scanner()
    books = TEST if not args.books else [int(b) for b in args.books.split(",")]
    lines = load_iliad(books=books)
    tot = defaultdict(int)
    by_rule = defaultdict(lambda: defaultdict(int))
    bins = defaultdict(lambda: [0, 0])
    amb_reasons = defaultdict(int)
    times = []
    brier = 0.0
    syn_flagged = syn_merged = merges = merges_flagged = 0
    for line in lines:
        t0 = time.perf_counter()
        res = sc.scan(line.text)
        times.append(time.perf_counter() - t0)
        tot["lines"] += 1
        if len(res) != len(line.syllables):
            tot["lines_count_mismatch"] += 1
        for r, label, mnext, mprev, final in align(line, res):
            if mnext:
                merges += 1
                merges_flagged += any(f["id"] == "SYN-CAND" for f in r.flags)
            if label is None or final or mnext or mprev:
                continue
            tot["syll"] += 1
            p = r.p_long
            y = 1 if label == "L" else 0
            brier += (p - y) ** 2
            b = min(int(p * 10), 9)
            bins[b][0] += 1
            bins[b][1] += y
            lab = r.label
            by_rule[r.rule]["n"] += 1
            if lab == "A":
                tot["ambiguous"] += 1
                amb_reasons[r.leaf.split(":")[0]] += 1
                by_rule[r.rule]["A"] += 1
            else:
                tot["decided"] += 1
                ok = (lab == label)
                tot["decided_correct"] += ok
                by_rule[r.rule]["correct" if ok else "wrong"] += 1
            tot["hard_correct"] += int((p >= 0.5) == bool(y))
    times.sort()
    report = {
        "books": list(books),
        "lines": tot["lines"],
        "lines_syllable_count_differs": tot["lines_count_mismatch"],
        "syllables_scored": tot["syll"],
        "decided_share": round(tot["decided"] / tot["syll"], 4),
        "decided_accuracy": round(tot["decided_correct"] / max(tot["decided"], 1), 4),
        "ambiguous_share": round(tot["ambiguous"] / tot["syll"], 4),
        "hard_decision_accuracy_p>=0.5": round(tot["hard_correct"] / tot["syll"], 4),
        "brier": round(brier / tot["syll"], 4),
        "calibration_bins": {f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": n, "observed_long": round(l / n, 3)}
                             for b, (n, l) in sorted(bins.items()) if n},
        "ambiguous_by_rule": dict(sorted(amb_reasons.items(), key=lambda kv: -kv[1])),
        "by_rule": {k: dict(v) for k, v in sorted(by_rule.items())},
        "synizesis_mergers_in_gold": merges,
        "mergers_flagged_as_candidates": merges_flagged,
        "ms_per_line": {"median": round(1000 * times[len(times) // 2], 3),
                        "p95": round(1000 * times[int(len(times) * 0.95)], 3),
                        "max": round(1000 * times[-1], 3)},
    }
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
