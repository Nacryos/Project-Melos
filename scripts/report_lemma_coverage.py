"""Coverage of the corpus headword index by author and genre (release O).

  python scripts/report_lemma_coverage.py --index data/lemma_index.sqlite --out coverage.json [--all-records]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.lemma_index import LemmaIndex  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--all-records", action="store_true")
    args = p.parse_args()
    ix = LemmaIndex(args.index)
    mask = ix.scope_mask(args.all_records)
    stats = {"author": defaultdict(lambda: np.zeros(7)), "genre": defaultdict(lambda: np.zeros(7))}
    total = np.zeros(7)
    for pid in np.flatnonzero(mask).tolist():
        toks = ix.tokens(pid)
        if toks is None:
            continue
        lem, _, conf, src = toks[0], toks[1], toks[2], toks[3]
        row = np.array([len(lem), (lem > 0).sum(), ((src & 1) > 0).sum(), ((src & 4) > 0).sum(),
                        ((src & 16) > 0).sum(), ((lem > 0) & (conf >= 0.8 * 255)).sum(), ((src & 64) > 0).sum()],
                       dtype=float)
        info = ix.authors.get(ix.author_of[pid]) or {}
        stats["author"][info.get("author") or ix.author_of[pid]] += row
        stats["genre"][info.get("genre") or "unclassified"] += row
        total += row

    def fmt(v):
        n = v[0] or 1
        return {"tokens": int(v[0]), "with_headword_pct": round(100 * v[1] / n, 2), "parser_exact_pct": round(100 * v[2] / n, 2),
                "generated_spelling_pct": round(100 * v[3] / n, 2), "context_agrees_pct": round(100 * v[4] / n, 2),
                "confidence_ge_0_8_pct": round(100 * v[5] / n, 2), "damaged_word_pct": round(100 * v[6] / n, 2)}

    out = {"scope": "all indexed Greek records" if args.all_records else "searchable edited Greek text",
           "total": fmt(total),
           "by_genre": {k: fmt(v) for k, v in sorted(stats["genre"].items(), key=lambda kv: -kv[1][0])},
           "by_author": {k: fmt(v) for k, v in sorted(stats["author"].items(), key=lambda kv: -kv[1][0])}}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": out["total"], "by_genre": out["by_genre"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
