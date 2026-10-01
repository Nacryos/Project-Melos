"""Retrieval laboratory: score search methods against judged queries.

Runs in-process against the corpus index (same code path as the API) so
variants can be compared before any of them touches production. Each method
returns a ranked list of passage IDs; a hit is credited to its explicit Greek
parent when it is a translation or commentary record, and to every indexed
copy of the same words. Records named in a query's ``exclude_ids`` (the
English record the query was taken from, and its siblings) are removed from
every candidate pool, so a method cannot win by finding the query text itself.

  python scripts/lab_eval.py --queries /lab/eval-queries.jsonl --out /lab/report-baseline.json \
      --methods dense_all dense_english_bridge hybrid_current bm25_bridge hybrid_bm25

Metrics are Recall@1/5/10 and MRR@10 over this corpus; they measure retrieval
of the judged passage, not Ancient Greek understanding.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import server  # noqa: E402
from backend.retrieval import fuse  # noqa: E402
from backend.textutils import normalize, tokenize  # noqa: E402
from backend.author_aliases import canonical_key, component_keys  # noqa: E402

STOPWORDS = set("""a an and are as at be but by for from has have he her his i in is it its of on or
she that the their them they this to was were which who will with you your not no so than then
there these those into upon when where while whom whose""".split())
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")


class Lab:
    def __init__(self, limit: int = 10, pool: int = 400, dense_pool: int = 1000):
        self.limit, self.pool, self.dense_pool = limit, pool, dense_pool
        self.index = server.semantic_service()
        self.con = sqlite3.connect(f"file:{server.DB.as_posix()}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self._record_cache: dict[str, dict | None] = {}
        self._english_cache: dict[str, str | None] = {}
        self.reranker = None

    # ----- corpus access -------------------------------------------------
    def record(self, identifier: str) -> dict | None:
        if identifier not in self._record_cache:
            row = self.con.execute("SELECT data, author_canonical, text_key FROM passages WHERE id=?", (identifier,)).fetchone()
            if row:
                data = json.loads(row["data"])
                data["_author_canonical"], data["_text_key"] = row["author_canonical"], row["text_key"]
                self._record_cache[identifier] = data
            else:
                self._record_cache[identifier] = None
        return self._record_cache[identifier]

    def credited(self, identifier: str) -> set[str]:
        """IDs a hit counts for: itself, its Greek parent, and copies of the same words."""
        record = self.record(identifier)
        if not record:
            return {identifier}
        ids = {identifier}
        parent = record.get("parent_id")
        if record.get("kind") in ("translation", "commentary") and isinstance(parent, str) and parent:
            ids.add(parent)
            record = self.record(parent) or record
        if record.get("_author_canonical") and record.get("_text_key"):
            ids.update(r[0] for r in self.con.execute(
                "SELECT id FROM passages WHERE author_canonical=? AND text_key=? AND quality=?",
                (record["_author_canonical"], record["_text_key"], record.get("quality"))))
        return ids

    def english_for(self, identifier: str, exclude: set[str]) -> str | None:
        """A linked English translation or commentary of a Greek passage, if any."""
        key = identifier
        if key not in self._english_cache:
            rows = self.con.execute(
                "SELECT id, text, kind FROM passages WHERE json_extract(data,'$.parent_id')=? AND language='eng' "
                "AND kind IN ('translation','commentary') ORDER BY CASE kind WHEN 'translation' THEN 0 ELSE 1 END, id",
                (identifier,)).fetchall()
            self._english_cache[key] = [(r["id"], r["text"]) for r in rows]  # type: ignore[assignment]
        for sibling_id, text in self._english_cache[key] or []:  # type: ignore[union-attr]
            if sibling_id not in exclude:
                return text
        return None

    # ----- candidate pools -----------------------------------------------
    def dense_hits(self, query: str, exclude: set[str], *, language: str | None = None, kind: str | None = None, limit: int | None = None) -> list[dict]:
        hits = self.index.search(query, limit=limit or self.dense_pool, include_reference=False)
        out = []
        for hit in hits:
            if hit["id"] in exclude:
                continue
            if language and hit.get("indexed_language") != language:
                continue
            if kind and hit.get("indexed_kind") != kind:
                continue
            out.append(hit)
        return out

    def lexical_hits(self, query: str, exclude: set[str], mode: str = "words") -> list[dict]:
        try:
            found = server.search(q=query, mode=mode, limit=self.pool, include_reference=False)
        except Exception:
            return []
        return [row for row in found.get("results", []) if row["id"] not in exclude]

    def bm25_bridge_hits(self, query: str, exclude: set[str], limit: int | None = None) -> list[dict]:
        """BM25 over linked English translations and commentary, projected later to Greek parents."""
        terms = [t for t in tokenize(normalize(query)) if len(t) > 2 and t not in STOPWORDS and not GREEK.search(t)]
        terms = list(dict.fromkeys(terms))[:24]
        if not terms:
            return []
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = self.con.execute(
            "SELECT p.id, bm25(passage_fts) rank FROM passage_fts JOIN passages p ON p.id=passage_fts.id "
            "WHERE passage_fts MATCH ? AND p.language='eng' AND p.kind IN ('translation','commentary') "
            "AND json_extract(p.data,'$.parent_id') IS NOT NULL ORDER BY rank LIMIT ?", (expression, limit or self.pool)).fetchall()
        return [{"id": r["id"], "score": -r["rank"], "match_reason": "BM25 over linked English records"} for r in rows if r["id"] not in exclude]

    def fused(self, query: str, exclude: set[str], *, weights=None, extra_signals=None, dense_language=None) -> list[dict]:
        greek = bool(GREEK.search(query))
        lexical = self.lexical_hits(query, exclude, "words")
        forms = self.lexical_hits(query, exclude, "forms") if greek or len(tokenize(query)) <= 2 else []
        dense = self.dense_hits(query, exclude, language=dense_language)
        extra = {}
        for name in (extra_signals or []):
            if name == "bm25_bridge":
                extra[name] = self.bm25_bridge_hits(query, exclude)
            elif name == "dense_english":
                extra[name] = self.dense_hits(query, exclude, language="eng")
        result = fuse(query, lexical, forms, dense, self.record, limit=self.limit * 5, offset=0,
                      commentary_assisted=True, author_key=canonical_key, author_keys=component_keys,
                      weights=weights, extra=extra)
        return result["results"]

    # ----- reranking -----------------------------------------------------
    def load_reranker(self, name: str):
        if self.reranker is None:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(name, max_length=512)
        return self.reranker

    def rerank(self, query: str, candidates: list[dict], exclude: set[str], model: str, top: int = 30, prefer_english: bool = True) -> list[dict]:
        pool = candidates[:top]
        if not pool:
            return []
        reranker = self.load_reranker(model)
        pairs = []
        for item in pool:
            text = None
            if prefer_english and not GREEK.search(query):
                text = self.english_for(item["id"], exclude)
            pairs.append((query, text or item.get("text") or ""))
        scores = reranker.predict(pairs, batch_size=16)
        order = sorted(range(len(pool)), key=lambda i: -float(scores[i]))
        return [dict(pool[i], rerank_score=float(scores[i])) for i in order] + candidates[top:]

    # ----- methods -------------------------------------------------------
    def run(self, method: str, query: str, exclude: set[str], rerank_model: str | None) -> list[str]:
        if method == "dense_all":
            hits = self.dense_hits(query, exclude, limit=self.limit * 3)
        elif method == "dense_greek_only":
            hits = self.dense_hits(query, exclude, language="grc", kind="text", limit=self.limit * 3)
        elif method == "dense_english_bridge":
            hits = self.dense_hits(query, exclude, language="eng", limit=self.limit * 3)
        elif method == "bm25_bridge":
            hits = self.bm25_bridge_hits(query, exclude, limit=self.limit * 3)
        elif method == "hybrid_current":
            hits = self.fused(query, exclude)
        elif method == "hybrid_bm25":
            hits = self.fused(query, exclude, extra_signals=["bm25_bridge"])
        elif method == "hybrid_bm25_w":
            hits = self.fused(query, exclude, extra_signals=["bm25_bridge", "dense_english"],
                              weights={"lexical": 1.0, "forms": 0.6, "semantic": 0.8, "bm25_bridge": 1.2, "dense_english": 1.2})
        elif method == "hybrid_english_dense":
            hits = self.fused(query, exclude, extra_signals=["dense_english"])
        elif method.startswith("rerank_"):
            base = method.removeprefix("rerank_")
            candidates = self.fused(query, exclude, extra_signals=["bm25_bridge", "dense_english"]) if base == "hybrid_bm25_w" else self.fused(query, exclude)
            hits = self.rerank(query, candidates, exclude, rerank_model or "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
        else:
            raise ValueError(method)
        return [hit["id"] for hit in hits]

    def rank_of(self, ids: list[str], targets: set[str]) -> int | None:
        seen: set[str] = set()
        position = 0
        for identifier in ids:
            credited = self.credited(identifier)
            # Collapse copies that credit the same passage into one rank step.
            key = frozenset(credited)
            if key in seen:
                continue
            seen.add(key)
            position += 1
            if credited & targets:
                return position
            if position >= self.limit:
                break
        return None


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    ranks = [row["rank"] for row in rows]
    return {
        "queries": n,
        "recall@1": round(sum(1 for r in ranks if r == 1) / n, 3) if n else None,
        "recall@5": round(sum(1 for r in ranks if r and r <= 5) / n, 3) if n else None,
        "recall@10": round(sum(1 for r in ranks if r and r <= 10) / n, 3) if n else None,
        "mrr@10": round(sum(1 / r for r in ranks if r and r <= 10) / n, 3) if n else None,
        "mean_seconds": round(sum(row["seconds"] for row in rows) / n, 3) if n else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--methods", nargs="+", default=["dense_all", "dense_english_bridge", "hybrid_current", "bm25_bridge", "hybrid_bm25"])
    parser.add_argument("--families", nargs="*", default=None)
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rerank-model", default=None)
    args = parser.parse_args()
    queries = [json.loads(line) for line in args.queries.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.families:
        queries = [q for q in queries if any(q["family"].startswith(f) for f in args.families)]
    if args.max_queries:
        queries = queries[:args.max_queries]
    lab = Lab(limit=args.limit)
    results: dict[str, list[dict]] = defaultdict(list)
    for number, query in enumerate(queries, 1):
        targets, exclude = set(query["target_ids"]), set(query.get("exclude_ids", []))
        for method in args.methods:
            started = time.time()
            try:
                ids = lab.run(method, query["query"], exclude, args.rerank_model)
                error = None
            except Exception as exc:  # noqa: BLE001 - report, keep going
                ids, error = [], str(exc)[:200]
            rank = lab.rank_of(ids, targets) if ids else None
            results[method].append({"id": query["id"], "family": query["family"], "author": query.get("author"),
                                    "rank": rank, "top": ids[:3], "seconds": round(time.time() - started, 3), "error": error})
        if number % 25 == 0:
            print(f"{number}/{len(queries)} queries", flush=True)
    report = {"queries": len(queries), "limit": args.limit, "methods": {}}
    families = sorted({q["family"] for q in queries})
    for method, rows in results.items():
        report["methods"][method] = {"overall": summarize(rows),
                                     "by_family": {fam: summarize([r for r in rows if r["family"] == fam]) for fam in families},
                                     "errors": sum(1 for r in rows if r["error"])}
    report["rows"] = {method: rows for method, rows in results.items()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'method':28} {'R@1':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6} {'s/q':>6}  families: " + ", ".join(families))
    for method, summary in report["methods"].items():
        o = summary["overall"]
        print(f"{method:28} {o['recall@1']:>6} {o['recall@5']:>6} {o['recall@10']:>6} {o['mrr@10']:>6} {o['mean_seconds']:>6}  "
              + "  ".join(f"{fam[:14]}:{summary['by_family'][fam]['recall@10']}" for fam in families))


if __name__ == "__main__":
    main()
