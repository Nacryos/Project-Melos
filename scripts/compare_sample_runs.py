"""Row-by-row comparison of two sample_glp_quality.py result files (same seed).

Rows are aligned by span and position within the span; prints per-metric rates for both,
every row that lost a metric (regressions) and how many gained one.

  python scripts/compare_sample_runs.py before.jsonl after.jsonl [--json out.json]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.sample_glp_quality import METRICS, score_row  # noqa: E402


def load(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_span, keyed = defaultdict(int), {}
    for row in rows:
        if row.get("kind") != "word":
            continue
        row.update(score_row(row, row["poet"]))
        keyed[(row["span"], by_span[row["span"]])] = row
        by_span[row["span"]] += 1
    return keyed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--json")
    args = ap.parse_args()
    a, b = load(args.before), load(args.after)
    common = sorted(set(a) & set(b))
    lost, gained = [], 0
    for key in common:
        x, y = a[key], b[key]
        if x["text"] != y["text"]:
            lost.append({"key": key, "problem": "row text differs", "before": x["text"], "after": y["text"]})
            continue
        down = [m for m in METRICS if x["metrics"][m] and not y["metrics"][m]]
        gained += any(not x["metrics"][m] and y["metrics"][m] for m in METRICS)
        if down:
            lost.append({"key": key, "text": x["text"], "pid": x["pid"], "lost": down,
                         "before": [x.get("lemma"), x.get("parse_short"), x.get("short")],
                         "after": [y.get("lemma"), y.get("parse_short"), y.get("short")]})
    rate = lambda rows: {m: round(sum(r["metrics"][m] for r in rows) / max(1, len(rows)), 4) for m in METRICS}
    out = {"rows_before": len(a), "rows_after": len(b), "aligned": len(common),
           "before": {**rate(list(a.values())), "all_ok": round(sum(not r["failed"] for r in a.values()) / max(1, len(a)), 4)},
           "after": {**rate(list(b.values())), "all_ok": round(sum(not r["failed"] for r in b.values()) / max(1, len(b)), 4)},
           "rows_gaining": gained, "rows_losing": len(lost), "losses": lost}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
