"""Evaluate source-checked retrieval fixtures against the local corpus.

Run from the project root: py -3.13 scripts/evaluate_retrieval.py
Queries are synthetic evaluation fixtures, never historical corpus records.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import server
from backend.semantic import SemanticIndex

DEFAULT_QUERIES = ROOT / "data/evaluation/retrieval-queries.jsonl"
DEFAULT_REPORT = ROOT / "data/reports/retrieval-evaluation.json"
METHODS = (
    "lexical_greek", "lexical_assisted", "forms_greek",
    "dense_greek", "dense_assisted", "hybrid_greek", "hybrid_assisted",
)


def load_queries(path: Path, connection: sqlite3.Connection) -> list[dict]:
    """Reject stale IDs, invented source quotes, and unlinked English bridges."""
    fixtures = []
    seen = set()
    artifact_hashes = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        required = {"id", "query", "category", "target_id", "evidence_quote"}
        if not required <= row.keys() or not all(row.get(key) for key in required):
            raise ValueError(f"fixture line {number}: missing required field")
        if row["id"] in seen:
            raise ValueError(f"fixture line {number}: duplicate query ID")
        seen.add(row["id"])
        target = connection.execute("SELECT data FROM passages WHERE id=?", (row["target_id"],)).fetchone()
        if not target:
            raise ValueError(f"fixture {row['id']}: target passage absent")
        record = json.loads(target[0])
        if record.get("kind") != "text" or record.get("language") != "grc" or record.get("quality") != "source_text":
            raise ValueError(f"fixture {row['id']}: target is not eligible Greek text")
        if row["evidence_quote"] not in record["text"]:
            raise ValueError(f"fixture {row['id']}: Greek source quote absent")
        if not record.get("source_url") or not record.get("raw_path") or not record.get("raw_sha256"):
            raise ValueError(f"fixture {row['id']}: incomplete target provenance")
        raw_path = ROOT / record["raw_path"]
        if not raw_path.is_file():
            raise ValueError(f"fixture {row['id']}: target raw artifact missing")
        if raw_path not in artifact_hashes:
            artifact_hashes[raw_path] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if artifact_hashes[raw_path] != record["raw_sha256"]:
            raise ValueError(f"fixture {row['id']}: target raw artifact hash changed")
        row["source_evidence"] = {
            "source_url": record["source_url"],
            "raw_path": record["raw_path"],
            "raw_sha256": record["raw_sha256"],
            "citation": record.get("citation"),
            "quote": row["evidence_quote"],
            "text_sha256": hashlib.sha256(record["text"].encode("utf-8")).hexdigest(),
        }
        if row["category"] == "english_description":
            bridge_id, quote = row.get("bridge_id"), row.get("bridge_quote")
            if not bridge_id or not quote:
                raise ValueError(f"fixture {row['id']}: English bridge evidence required")
            bridge = connection.execute("SELECT data FROM passages WHERE id=?", (bridge_id,)).fetchone()
            if not bridge:
                raise ValueError(f"fixture {row['id']}: bridge record absent")
            bridge_record = json.loads(bridge[0])
            if bridge_record.get("parent_id") != row["target_id"] or quote not in bridge_record["text"]:
                raise ValueError(f"fixture {row['id']}: bridge quote or parent link invalid")
            if bridge_record.get("language") != "eng" or bridge_record.get("kind") not in {"commentary", "translation"}:
                raise ValueError(f"fixture {row['id']}: bridge is not English commentary/translation")
            row["source_evidence"]["bridge"] = {
                "id": bridge_id,
                "source_url": bridge_record.get("source_url"),
                "quote": quote,
            }
        elif row.get("bridge_id") or row.get("bridge_quote"):
            raise ValueError(f"fixture {row['id']}: unexpected English bridge")
        fixtures.append(row)
    if not fixtures:
        raise ValueError("evaluation set is empty")
    return fixtures


def credited_id(hit: dict) -> str | None:
    """Only an exact ID or explicit collector parent link earns credit."""
    return hit.get("parent_id") or hit.get("id")


def rank_of_target(hits: list[dict], target_id: str) -> int | None:
    for rank, hit in enumerate(hits, 1):
        if hit.get("id") == target_id or credited_id(hit) == target_id:
            return rank
    return None


def summarize(rows: list[dict], method: str) -> dict:
    ranks = [row["ranks"].get(method) for row in rows]
    count = len(ranks)
    return {
        "queries": count,
        "recall_at_1": round(sum(rank is not None and rank <= 1 for rank in ranks) / count, 4),
        "recall_at_5": round(sum(rank is not None and rank <= 5 for rank in ranks) / count, 4),
        "recall_at_10": round(sum(rank is not None and rank <= 10 for rank in ranks) / count, 4),
        "mrr_at_10": round(sum(1 / rank for rank in ranks if rank is not None and rank <= 10) / count, 4),
    }


def retrieve(method: str, query: str, *, index: SemanticIndex | None, limit: int = 10) -> list[dict]:
    if method.startswith("dense"):
        if index is None:
            raise RuntimeError("dense index is unavailable")
        hits = index.search(query, limit=max(limit, 20), language="grc" if method == "dense_greek" else None)
        if method == "dense_greek":
            hits = [hit for hit in hits if hit.get("indexed_kind") == "text"]
        return hits[:limit]
    mode = "hybrid" if method.startswith("hybrid") else "forms" if method == "forms_greek" else "words"
    greek_only = method.endswith("_greek")
    response = server.search(q=query, mode=mode, language="grc" if greek_only else "",
                             commentary_assisted=not greek_only, limit=max(limit, 20) if greek_only else limit)
    hits = response["results"]
    if greek_only:
        hits = [hit for hit in hits if hit.get("kind") == "text"]
    return hits[:limit]


def evaluate(queries_path: Path = DEFAULT_QUERIES, report_path: Path = DEFAULT_REPORT,
             methods: tuple[str, ...] = METHODS) -> dict:
    invalid = set(methods) - set(METHODS)
    if invalid:
        raise ValueError(f"unknown methods: {sorted(invalid)}")
    if not methods:
        raise ValueError("select at least one retrieval method")
    with sqlite3.connect(f"file:{server.DB.as_posix()}?mode=ro", uri=True) as connection:
        fixtures = load_queries(queries_path, connection)
    index = SemanticIndex(ROOT / "data/embeddings") if any(m.startswith("dense") for m in methods) else None
    if index is not None and not index.ready:
        raise RuntimeError("dense index is unavailable or stale; rebuild it before a paired evaluation")
    # The API's hybrid path and direct dense baseline must share one local model
    # instance. Two independent loads waste VRAM and can distort timing.
    if index is not None:
        server.semantic_service = lambda: index
    try:
        from transformers.utils.logging import disable_progress_bar
        disable_progress_bar()
    except ImportError:
        pass
    observations = []
    for number, item in enumerate(fixtures, 1):
        observation = {key: item[key] for key in ("id", "category", "query", "target_id", "source_evidence")}
        observation["ranks"] = {}
        observation["top_5_ids"] = {}
        for method in methods:
            hits = retrieve(method, item["query"], index=index)
            observation["ranks"][method] = rank_of_target(hits, item["target_id"])
            observation["top_5_ids"][method] = [hit.get("id") for hit in hits[:5]]
        observations.append(observation)
        print(f"{number}/{len(fixtures)} {item['id']}", flush=True)
    groups = defaultdict(list)
    for row in observations:
        groups[row["category"]].append(row)
    report = {
        "schema_version": 1,
        "fixture_sha256": hashlib.sha256(queries_path.read_bytes()).hexdigest(),
        "corpus_size_bytes": server.DB.stat().st_size,
        "embedding_manifest_sha256": hashlib.sha256((ROOT / "data/embeddings/manifest.json").read_bytes()).hexdigest() if index else None,
        "query_count": len(fixtures),
        "unique_target_count": len({row["target_id"] for row in fixtures}),
        "methods": list(methods),
        "metric_definition": "Each synthetic query has one judged Greek target ID. An exact hit or a hit with that explicit parent_id earns credit; other editions, shared citations, and similar passages do not. Recall@k and reciprocal rank use the first 10 displayed results; unjudged alternatives may be relevant but do not earn credit.",
        "overall": {method: summarize(observations, method) for method in methods},
        "by_category": {category: {method: summarize(rows, method) for method in methods} for category, rows in sorted(groups.items())},
        "observations": observations,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    args = parser.parse_args()
    report = evaluate(args.queries, args.report, tuple(args.methods))
    print(json.dumps(report["overall"], indent=2))


if __name__ == "__main__":
    main()
