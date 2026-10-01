"""English queries reach Greek passages through linked English records, not Greek vectors alone.

Synthetic rows only. The fake semantic service returns a translation hit and
an unrelated Greek hit so the projection, the BM25 bridge and the feedback
signal can be checked without an encoder.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend import server
from backend.bridges import bm25_bridge_hits, english_terms, is_greek_query, prf_hits
from scripts import build_corpus


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    raw = root / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("SYNTHETIC", encoding="utf-8")
    common = {"source": "synthetic", "source_url": "https://example.org/x", "raw_path": "data/raw/synthetic.txt",
              "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "edition": "Synthetic edition",
              "language": "grc", "kind": "text", "quality": "source_text", "license": "test", "work": "Songs"}
    rows = [
        dict(common, id="apple", author="Sappho", citation="105a", text="οἶον τὸ γλυκύμαλον ἐρεύθεται ἄκρῳ ἐπ᾽ ὔσδῳ"),
        dict(common, id="apple-eng", author="Translator", citation="105a", language="eng", kind="translation",
             text="like the sweet apple that reddens on the topmost bough, forgotten by the apple pickers", parent_id="apple"),
        dict(common, id="moon", author="Sappho", citation="34", text="ἄστερες μὲν ἀμφὶ κάλαν σελάνναν"),
        dict(common, id="moon-note", author="Scholar", citation="34", language="eng", kind="commentary",
             text="the stars hide their bright faces around the full moon", parent_id="moon"),
        dict(common, id="oak", author="Sappho", citation="47", text="Ἔρος δ᾽ ἐτίναξέ μοι φρένας ὠς ἄνεμος κὰτ ὄρος δρύσιν ἐμπέτων"),
        dict(common, id="oak-twin", author="Alcaeus", citation="x", text="ἄνεμος κὰτ ὄρος δρύσιν ἐμπέτων φρένας ἐτίναξε"),
    ]
    processed = root / "data/processed"
    processed.mkdir(parents=True)
    fixture = processed / "synthetic.jsonl"
    fixture.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {fixture.name: {
        "verdict": "PASS", "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "records": len(rows)}}}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "DB", root / "data/corpus.sqlite")
    build_corpus.build(server.DB)

    class Dense:
        status = {"ready": True, "count": 6}

        def search(self, query, limit, **filters):
            # The English query matches the translation strongly and an unrelated
            # Greek passage weakly; the Greek target itself is not a dense hit.
            return [{"id": "apple-eng", "score": .8, "indexed_language": "eng", "indexed_kind": "translation",
                     "match_reason": "English translation embedding"},
                    {"id": "oak", "score": .3, "indexed_language": "grc", "indexed_kind": "text",
                     "match_reason": "Original passage embedding"}][:limit]

    monkeypatch.setattr(server, "semantic_service", lambda: Dense())
    return TestClient(server.app)


def test_bridge_helpers(client: TestClient):
    assert is_greek_query("γλυκύμαλον") and not is_greek_query("sweet apple")
    assert english_terms("the sweet apple on the topmost bough") == ["sweet", "apple", "topmost", "bough"]
    with sqlite3.connect(f"file:{server.DB.as_posix()}?mode=ro", uri=True) as con:
        bridge = bm25_bridge_hits(con, "apple pickers forgot the sweet apple")
        assert [hit["id"] for hit in bridge] == ["apple-eng"]
        feedback = prf_hits(con, ["oak"])
        assert "oak-twin" in {hit["id"] for hit in feedback}


def test_english_hybrid_query_returns_greek_parent_with_bridge_evidence(client: TestClient):
    result = client.get("/api/search", params={"q": "sweet apple on the topmost bough", "mode": "hybrid"}).json()
    ids = [row["id"] for row in result["results"]]
    assert ids[0] == "apple"
    top = result["results"][0]
    assert "bm25_bridge" in top["retrieval_ranks"] and "semantic" in top["retrieval_ranks"]
    assert any(hit["id"] == "apple-eng" for hit in top["matched_evidence"])
    assert any("English query" in warning for warning in result["warnings"])
    # Feedback from the dense Greek hit reaches the passage sharing its rare words.
    assert "oak-twin" in ids


def test_greek_hybrid_query_keeps_plain_fusion(client: TestClient):
    result = client.get("/api/search", params={"q": "γλυκύμαλον", "mode": "hybrid"}).json()
    assert result["results"][0]["id"] == "apple"
    assert not any("English query" in warning for warning in result["warnings"])
    assert "bm25_bridge" not in result["results"][0]["retrieval_ranks"]
