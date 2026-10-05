"""Run real CPU inference on unmodified, existing corpus passages, offline.

Writes an audit artifact under runtime only; never updates corpus annotations.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.syntax_provider import SyntaxProvider


def main():
    connection = sqlite3.connect(f"file:{ROOT / 'data/corpus.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    common = "language='grc' AND quality='source_text' AND length(text) BETWEEN 40 AND 700"
    rows = []
    for where in ("text NOT LIKE '%[%' AND text NOT LIKE '%]%'", "(text LIKE '%[%' OR text LIKE '%]%')"):
        row = connection.execute(
            f"SELECT id,source,author,work,citation,text FROM passages WHERE {common} AND {where} "
            "ORDER BY CASE WHEN lower(author) LIKE '%sappho%' THEN 0 WHEN lower(author) LIKE '%ibycus%' THEN 1 ELSE 2 END, id LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("Required source passage not present")
        rows.append(dict(row))
    connection.close()

    def offline(*args, **kwargs):
        raise RuntimeError("Network access forbidden during syntax inference")

    socket.socket.connect = offline
    socket.create_connection = offline
    provider = SyntaxProvider()
    results = []
    for row in rows:
        started = time.perf_counter()
        result = provider.analyze(row["text"])
        normalized_seconds = time.perf_counter() - started
        assert all(row["text"][t["start"]:t["end"]] == t["text"] for t in result["tokens"])
        assert any(t["deprel"] for t in result["tokens"])
        started = time.perf_counter()
        identity_result = provider.analyze(row["text"], normalize_whitespace=False)
        identity_seconds = time.perf_counter() - started
        unresolved = lambda prediction: sum(t["attachment_status"] == "unresolved_nonlexical_head" for t in prediction["tokens"])
        results.append({"source": row, "input_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                        "seconds": normalized_seconds, "prediction": result,
                        "whitespace_ablation": {"identity_prediction": identity_result,
                                                "identity_seconds": identity_seconds,
                                                "normalized_unresolved_heads": unresolved(result),
                                                "identity_unresolved_heads": unresolved(identity_result),
                                                "scope": "Operational comparison only; no gold syntax or accuracy measurement. First normalized run includes cold load."}})
    output = ROOT / "runtime/models/odycy/inference-verification.json"
    output.write_text(json.dumps({"verified_at_utc": datetime.now(timezone.utc).isoformat(),
                                 "network_disabled": True, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output), "passages": [{"id": r["source"]["id"], "tokens": len(r["prediction"]["tokens"]), "seconds": r["seconds"]} for r in results]}))


if __name__ == "__main__":
    main()
