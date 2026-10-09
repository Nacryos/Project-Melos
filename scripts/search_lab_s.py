"""Release S search lab: collect every retriever's candidates once, then score retrievers alone, fit the
fusion weights on the development queries and report the stack (in process, read-only).

  python scripts/search_lab_s.py collect --out lab/candidates.jsonl [--signals keyword,headword,...]
  python scripts/search_lab_s.py report  --cand lab/candidates.jsonl [--weights backend/search_stack_weights.json]
  python scripts/search_lab_s.py fit     --cand lab/candidates.jsonl --out backend/search_stack_weights.json

``collect`` runs ``server.hybrid_candidates`` with every stack list and fuses with weight 1 for all lists,
keeping each fused passage's rank in every list (``retrieval_ranks``). Any other weighting is then exact
arithmetic on those ranks: score = sum(weight / (60 + rank)), ties by best rank then id, as in
``backend.retrieval.fuse``; editions are folded with ``group_editions`` and the result is scored with
``scripts/search_eval.py``'s rule. Weights are fitted by coordinate ascent on development nDCG@10 (mean of
nDCG@10 and recall@50 breaks ties), separately for Greek-letter and other queries. Held-out queries are
never read by ``fit``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import search_eval  # noqa: E402

EVAL = ROOT / "data/evaluation/search-eval-s.json"
COUNTS = ROOT / "data/evaluation/search-eval-s-counts.json"
KEEP = ("id", "author", "author_canonical", "text", "language", "kind", "quality", "edition", "source", "citation", "work")
BASE = ("lexical", "forms", "semantic", "bm25_bridge", "lemma")
GRID = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)


def is_greek(q):
    return any(c.isalpha() and ("Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿") for c in q)


def collect(args):
    from backend import server
    data = search_eval.load(args.queries)
    signals = [s for s in args.signals.split(",") if s]
    out = open(args.out, "w", encoding="utf-8")
    for q in data["queries"]:
        started = time.time()
        c = server.hybrid_candidates(q["q"], stack=signals)
        t_lists = time.time() - started
        names = ["lexical", "forms", "semantic", *c["extra"]]
        ones = dict.fromkeys(names, 1.0)
        fused, ranked, _ = server.fuse_candidates(q["q"], c, weights=ones, pool=5000)
        rows = [{**{k: r.get(k) for k in KEEP}, "ranks": r["retrieval_ranks"]} for r in fused["results"]]
        out.write(json.dumps({"q": q["q"], "type": q["type"], "split": q["split"], "greek": c["greek"],
                              "base_weights": c["weights"], "signals": names,
                              "list_sizes": {"lexical": len(c["lexical"]["results"]), "forms": len(c["forms"]["results"]),
                                             "semantic": len(c["dense"]), **{k: len(v) for k, v in c["extra"].items()}},
                              "seconds_lists": round(t_lists, 2), "rows": rows}, ensure_ascii=False) + "\n")
        out.flush()
        print(f"{q['split'][:3]} {t_lists:5.1f}s {len(rows):5d} {q['q']}", flush=True)


def load_cand(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def rank(rows, weights, alone=False):
    scored = []
    for r in rows:
        s = sum(weights.get(name, 0.0) / (60 + k) for name, k in r["ranks"].items())
        if alone and s <= 0:
            continue
        scored.append((-s, min(r["ranks"].values()), str(r["id"]), r))
    scored.sort(key=lambda t: t[:3])
    return [t[3] for t in scored]


def evaluate(cands, weights_for, counts, data_by_q, alone=False):
    from backend.retrieval import group_editions
    from backend.server import canonical_key
    out = []
    for c in cands:
        w = weights_for(c)
        ranked = rank(c["rows"], w, alone)
        ranked = [dict(r) for r in ranked[:400]]
        folded, _ = group_editions(ranked, author_key=canonical_key)
        s = search_eval.score(folded, data_by_q[c["q"]]["regex"], counts.get(c["q"], 10))
        out.append({"q": c["q"], "type": c["type"], "split": c["split"], "ndcg10": s["ndcg10"], "recall50": s["recall50"],
                    "first": s["first_relevant"]})
    return out


def summary(rows, old42=None):
    def mean(sel, key):
        return round(sum(r[key] for r in sel) / len(sel), 4) if sel else None
    out = {}
    for split in ("development", "held_out", "all"):
        sel = [r for r in rows if split == "all" or r["split"] == split]
        out[split] = {"n": len(sel), "ndcg10": mean(sel, "ndcg10"), "recall50": mean(sel, "recall50")}
    if old42:
        for split in ("development", "held_out", "all"):
            sel = [r for r in rows if r["q"] in old42 and (split == "all" or r["split"] == split)]
            out["o42_" + split] = {"n": len(sel), "ndcg10": mean(sel, "ndcg10"), "recall50": mean(sel, "recall50")}
    for t in sorted({r["type"] for r in rows}):
        sel = [r for r in rows if r["type"] == t]
        out["type:" + t] = {"n": len(sel), "ndcg10": mean(sel, "ndcg10"), "recall50": mean(sel, "recall50")}
    return out


def context(args):
    data = search_eval.load(args.queries)
    counts = json.loads(Path(args.counts).read_text(encoding="utf-8"))
    o42 = {q["q"] for q in json.loads((ROOT / "data/evaluation/search-eval-o.json").read_text(encoding="utf-8"))["queries"]}
    return {q["q"]: q for q in data["queries"]}, counts, o42


def report(args):
    by_q, counts, o42 = context(args)
    cands = load_cand(args.cand)
    signals = sorted({s for c in cands for s in c["signals"]})
    result = {}

    def base(c):
        w = {"lexical": 1.0, "forms": 1.0, "semantic": 1.0}
        w.update(c["base_weights"] or {})
        return {k: v for k, v in w.items() if k in BASE}
    result["release_R_fusion"] = summary(evaluate(cands, base, counts, by_q), o42)
    for s in signals:
        result["alone:" + s] = summary(evaluate(cands, lambda c, s=s: {s: 1.0}, counts, by_q, alone=True), o42)
    if args.weights:
        cfg = json.loads(Path(args.weights).read_text(encoding="utf-8"))
        rows = evaluate(cands, lambda c: cfg["greek" if c["greek"] else "english"], counts, by_q)
        result["stack"] = summary(rows, o42)
        result["stack_queries"] = rows
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in result.items():
        if k != "stack_queries":
            print(f"{k:34s} dev {v['development']['ndcg10']} held {v['held_out']['ndcg10']} all {v['all']['ndcg10']}"
                  f" | R@50 all {v['all']['recall50']} | O42 all {v['o42_all']['ndcg10']} held {v['o42_held_out']['ndcg10']}")


def fit(args):
    by_q, counts, o42 = context(args)
    cands = [c for c in load_cand(args.cand) if c["split"] == "development"]  # held-out never read
    config = {}
    for cls in ("greek", "english"):
        sel = [c for c in cands if c["greek"] == (cls == "greek")]
        signals = sorted({s for c in sel for s in c["signals"]})
        if args.signals:
            signals = [s for s in signals if s in args.signals.split(",")]
        start = {"lexical": 1.0, "forms": 1.0, "semantic": 1.0}
        start.update(sel[0]["base_weights"] or {})
        w = {s: float(start.get(s, 0.0)) for s in signals}

        def objective(weights):
            rows = evaluate(sel, lambda c: weights, counts, by_q)
            n = sum(r["ndcg10"] for r in rows) / len(rows)
            r50 = sum(r["recall50"] for r in rows) / len(rows)
            return (round(n, 6), round((n + r50) / 2, 6))
        best = objective(w)
        print(cls, len(sel), "start", best, flush=True)
        for sweep in range(args.sweeps):
            changed = False
            for s in signals:
                for value in GRID:
                    if value == w[s]:
                        continue
                    trial = dict(w, **{s: value})
                    score = objective(trial)
                    if score > best:
                        best, w, changed = score, trial, True
                print(f"  sweep {sweep} {s:24s} -> {w[s]}  {best}", flush=True)
            if not changed:
                break
        config[cls] = w
        config[cls + "_dev_objective"] = {"ndcg10": best[0], "ndcg10_recall50_mean": best[1], "queries": len(sel)}
    config["fitted_on"] = {"queries": str(args.queries), "split": "development", "grid": GRID,
                           "method": "coordinate ascent on development nDCG@10 (ties: mean of nDCG@10 and recall@50)",
                           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    Path(args.out).write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(config, indent=1))


def stacked_top(c, cfg, by_q, counts, n=50):
    from backend.retrieval import group_editions
    from backend.server import canonical_key
    w = cfg["greek" if c["greek"] else "english"]
    ranked = [dict(r) for r in rank(c["rows"], w)[:400]]
    folded, _ = group_editions(ranked, author_key=canonical_key)
    return folded[:n], folded


def rerank_scores(args):
    """Cross-encoder scores for the first 50 stacked results of every query (cached to --out)."""
    from backend import server
    from backend.search_rerank import passage_text
    by_q, counts, _ = context(args)
    cfg = json.loads(Path(args.weights).read_text(encoding="utf-8"))
    cands = load_cand(args.cand)
    from sentence_transformers import CrossEncoder
    try:
        model = CrossEncoder(args.model, max_length=512, cache_folder=os.environ.get("MELOS_S_MODEL_CACHE"))
    except TypeError:  # sentence-transformers < 5
        model = CrossEncoder(args.model, max_length=512, cache_dir=os.environ.get("MELOS_S_MODEL_CACHE"))
    out = {}
    with server.connect() as con:
        for c in cands:
            top, _ = stacked_top(c, cfg, by_q, counts)
            texts = [passage_text(con, r) for r in top]
            started = time.time()
            scores = model.predict([(c["q"], t) for t in texts], batch_size=16, show_progress_bar=False)
            out[c["q"]] = {"ids": [r["id"] for r in top], "scores": [float(s) for s in scores],
                           "seconds": round(time.time() - started, 3)}
            print(f"{out[c['q']]['seconds']:.2f}s {c['q']}", flush=True)
    Path(args.out).write_text(json.dumps({"model": args.model, "scores": out}, ensure_ascii=False), encoding="utf-8")


def rerank_eval(args):
    """Blend fused rank with the cross-encoder score in the first 50: fit beta on development queries."""
    by_q, counts, o42 = context(args)
    cfg = json.loads(Path(args.weights).read_text(encoding="utf-8"))
    cands = load_cand(args.cand)
    ce = json.loads(Path(args.scores).read_text(encoding="utf-8"))["scores"]

    def rows_for(beta):
        rows = []
        for c in cands:
            top, folded = stacked_top(c, cfg, by_q, counts)
            got = ce.get(c["q"])
            if got and beta:
                sc = dict(zip(got["ids"], got["scores"]))
                vals = [sc.get(r["id"], min(got["scores"])) for r in top]
                lo, hi = min(vals), max(vals)
                norm = [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in vals]
                n = len(top)
                order = sorted(range(n), key=lambda i: -((1 - beta) * (1 - i / max(1, n - 1)) + beta * norm[i]))
                top = [top[i] for i in order]
            s = search_eval.score(top + folded[50:], by_q[c["q"]]["regex"], counts.get(c["q"], 10))
            rows.append({"q": c["q"], "type": c["type"], "split": c["split"], "ndcg10": s["ndcg10"], "recall50": s["recall50"]})
        return rows
    results = {}
    for beta in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
        results[beta] = summary(rows_for(beta), o42)
        r = results[beta]
        print(f"beta {beta}: dev {r['development']['ndcg10']} held {r['held_out']['ndcg10']} all {r['all']['ndcg10']}")
    best = max(results, key=lambda b: results[b]["development"]["ndcg10"])
    secs = [v["seconds"] for v in ce.values()]
    print(json.dumps({"best_beta_on_development": best, "held_out_at_best": results[best]["held_out"],
                      "mean_seconds_per_query": round(sum(secs) / len(secs), 3)}))
    Path(args.out).write_text(json.dumps({"by_beta": results, "best": best}, indent=1), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("rerank-scores", "rerank-eval"):
        sp = sub.add_parser(name)
        sp.add_argument("--queries", default=str(EVAL))
        sp.add_argument("--counts", default=str(COUNTS))
        sp.add_argument("--cand", required=True)
        sp.add_argument("--weights", required=True)
        sp.add_argument("--out", required=True)
        sp.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
        sp.add_argument("--scores", default="")
    for name in ("collect", "report", "fit"):
        sp = sub.add_parser(name)
        sp.add_argument("--queries", default=str(EVAL))
        sp.add_argument("--counts", default=str(COUNTS))
        if name == "collect":
            sp.add_argument("--out", required=True)
            sp.add_argument("--signals", default="keyword,headword")
        else:
            sp.add_argument("--cand", required=True)
            sp.add_argument("--out", required=True)
        if name == "report":
            sp.add_argument("--weights", default="")
        if name == "fit":
            sp.add_argument("--sweeps", type=int, default=3)
            sp.add_argument("--signals", default="", help="only these lists (the deployable ones)")
    args = p.parse_args()
    {"collect": collect, "report": report, "fit": fit, "rerank-scores": rerank_scores,
     "rerank-eval": rerank_eval}[args.cmd](args)


if __name__ == "__main__":
    main()
