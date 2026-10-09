"""Search-quality evaluation (releases O and S): nDCG@10, P@10, recall@50 and first relevant rank.

  python scripts/search_eval.py count --corpus data/corpus.sqlite      # relevant-item counts (ideal DCG)
  python scripts/search_eval.py run --base https://greeklyric.com --out before.json
  python scripts/search_eval.py run --base ... --queries data/evaluation/search-eval-s.json          --counts data/evaluation/search-eval-s-counts.json --out s.json      # release S set (120 queries)
  python scripts/search_eval.py compare before.json after.json

Queries and the judgement rule: data/evaluation/search-eval-o.json (42 queries) and
data/evaluation/search-eval-s.json (the same 42 first, then 78 more). Every third query
(index 2, 5, 8, ...) is held out: it was not looked at while choosing ranking parameters.
A result is relevant when it is Greek edited text whose normalised text matches the query's
pattern (or, for imagery and motif queries, every pattern in ``all_of``). A later result that
is another copy/edition of an already counted relevant passage (same author; at least half of
the shorter text's words shared) gains nothing. recall@50 = distinct relevant passages in the
first 50 results / min(50, relevant passages in the corpus).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize  # noqa: E402

QUERIES = ROOT / "data/evaluation/search-eval-o.json"
SEARCHABLE = ("source_text", "machine_corrected_ocr")


class AllOf:
    """Every pattern must match (imagery and motif queries)."""

    def __init__(self, patterns):
        self.patterns = [re.compile(p) for p in patterns]

    def search(self, text):
        return all(p.search(text) for p in self.patterns)


def compile_query(q):
    return AllOf(q["all_of"]) if q.get("all_of") else re.compile(q["pattern"])


def load(path=None):
    data = json.loads(Path(path or QUERIES).read_text(encoding="utf-8"))
    for i, q in enumerate(data["queries"]):
        q["split"] = "held_out" if i % 3 == 2 else "development"
        q["regex"] = compile_query(q)
    return data


def words(text):
    return {w for w in re.findall(r"\w+", normalize(text or "")) if len(w) >= 4}


def relevant(record, regex):
    return (record.get("language") == "grc" and record.get("kind") == "text"
            and record.get("quality") in SEARCHABLE and bool(regex.search(normalize(record.get("text") or ""))))


def count(args):
    data = load(args.queries)
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    texts = [normalize(t) for (t,) in con.execute(
        "SELECT text FROM passages WHERE language='grc' AND kind='text' AND quality IN ('source_text','machine_corrected_ocr')")]
    out = {q["q"]: sum(1 for t in texts if q["regex"].search(t)) for q in data["queries"]}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


def fetch(base, q, limit, mode):
    url = base.rstrip("/") + "/api/search?" + urllib.parse.urlencode({"q": q, "mode": mode, "limit": limit,
                                                                        "commentary_assisted": "true"})
    for attempt in range(3):
        try:
            started = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "melos-search-eval"}),
                                        timeout=120) as r:
                return json.loads(r.read()), time.time() - started
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(2)


def score(results, regex, n_relevant, k=10, k_recall=50):
    gains, seen = [], []
    for record in results[:max(k, k_recall)]:
        g = 0
        if relevant(record, regex):
            w = words(record.get("text"))
            author = (record.get("author_canonical") or record.get("author") or "").casefold()
            dup = any(a == author and w and s and len(w & s) / min(len(w), len(s)) >= 0.5 for a, s in seen)
            if not dup:
                g = 1
                seen.append((author, w))
        gains.append(g)
    top = gains[:k]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(top))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, n_relevant)))
    first = next((i + 1 for i, g in enumerate(gains) if g), None)
    recall = sum(gains[:k_recall]) / min(k_recall, n_relevant) if n_relevant else 0.0
    return {"ndcg10": round(dcg / ideal, 4) if ideal else 0.0, "p10": sum(top) / k, "recall50": round(min(1.0, recall), 4),
            "first_relevant": first, "gains": top}


def run(args):
    data = load(args.queries)
    counts = json.loads(Path(args.counts).read_text(encoding="utf-8"))
    rows = []
    for q in data["queries"]:
        if args.split and q["split"] != args.split:
            continue
        payload, seconds = fetch(args.base, q["q"], args.limit, args.mode)
        results = payload.get("results") or []
        s = score(results, q["regex"], counts.get(q["q"], 10))
        rows.append({"q": q["q"], "type": q["type"], "split": q["split"], "seconds": round(seconds, 2), **s,
                     "top": [f"{r.get('author')} | {r.get('citation')} | {r.get('id')}" for r in results[:10]]})
        print(f"{q['split'][:3]} {s['ndcg10']:.3f} {q['q']}", flush=True)
    summary = summarise(rows)
    Path(args.out).write_text(json.dumps({"base": args.base, "mode": args.mode, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                          "summary": summary, "queries": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def summarise(rows):
    out = {}
    for split in ("development", "held_out", "all"):
        sel = [r for r in rows if split == "all" or r["split"] == split]
        if sel:
            out[split] = {"queries": len(sel), "ndcg10": round(sum(r["ndcg10"] for r in sel) / len(sel), 4),
                          "p10": round(sum(r["p10"] for r in sel) / len(sel), 4),
                          "recall50": round(sum(r.get("recall50", 0) for r in sel) / len(sel), 4),
                          "mean_seconds": round(sum(r["seconds"] for r in sel) / len(sel), 2)}
    for kind in sorted({r["type"] for r in rows}):
        sel = [r for r in rows if r["type"] == kind]
        out["type:" + kind] = round(sum(r["ndcg10"] for r in sel) / len(sel), 4)
    return out


def compare(args):
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.before, args.after))
    bq = {r["q"]: r for r in b["queries"]}
    for r in a["queries"]:
        o = bq.get(r["q"])
        if o:
            print(f"{r['split'][:3]} {r['ndcg10']:.3f} -> {o['ndcg10']:.3f}  first {r['first_relevant']} -> {o['first_relevant']}  {r['q']}")
    print(json.dumps({"before": a["summary"], "after": b["summary"]}, indent=1))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count"); c.add_argument("--corpus", required=True); c.add_argument("--out", default=str(ROOT / "data/evaluation/search-eval-o-counts.json"))
    c.add_argument("--queries", default=str(QUERIES))
    r = sub.add_parser("run"); r.add_argument("--base", required=True); r.add_argument("--out", required=True)
    r.add_argument("--queries", default=str(QUERIES)); r.add_argument("--limit", type=int, default=50)
    r.add_argument("--mode", default="hybrid"); r.add_argument("--split", default=""); r.add_argument("--counts", default=str(ROOT / "data/evaluation/search-eval-o-counts.json"))
    m = sub.add_parser("compare"); m.add_argument("before"); m.add_argument("after")
    args = p.parse_args()
    {"count": count, "run": run, "compare": compare}[args.cmd](args)


if __name__ == "__main__":
    main()
