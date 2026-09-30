import json
import hashlib
import sqlite3

import pytest

from scripts import evaluate_retrieval as evaluation


def make_records(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    (tmp_path / "raw.html").write_text("source", encoding="utf-8")
    database = sqlite3.connect(":memory:")
    database.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, data TEXT)")
    greek = {"id": "greek", "text": "ἄστερες μὲν ἀμφὶ σελάνναν", "kind": "text", "language": "grc",
             "quality": "source_text", "source_url": "https://example.org/source", "raw_path": "raw.html",
             "raw_sha256": hashlib.sha256(b"source").hexdigest(), "citation": "Fragment 1"}
    note = {"id": "note", "text": "σελάννα moon", "kind": "commentary", "language": "eng",
            "parent_id": "greek", "source_url": "https://example.org/note"}
    database.executemany("INSERT INTO passages VALUES (?,?)", [(row["id"], json.dumps(row)) for row in (greek, note)])
    fixture = {"id": "moon", "query": "moon and stars", "category": "english_description",
               "target_id": "greek", "evidence_quote": "ἄστερες", "bridge_id": "note", "bridge_quote": "moon"}
    path = tmp_path / "queries.jsonl"
    path.write_text(json.dumps(fixture, ensure_ascii=False) + "\n", encoding="utf-8")
    return database, path, fixture


def test_source_quotes_and_parent_bridge_are_checked(tmp_path, monkeypatch):
    database, path, fixture = make_records(tmp_path, monkeypatch)
    loaded = evaluation.load_queries(path, database)
    assert loaded[0]["source_evidence"]["citation"] == "Fragment 1"
    assert loaded[0]["source_evidence"]["bridge"]["id"] == "note"
    fixture["evidence_quote"] = "invented Greek"
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="Greek source quote absent"):
        evaluation.load_queries(path, database)
    fixture["evidence_quote"] = "ἄστερες"
    fixture["bridge_quote"] = "invented gloss"
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="bridge quote or parent link invalid"):
        evaluation.load_queries(path, database)


def test_only_exact_id_or_explicit_parent_earns_credit():
    hits = [
        {"id": "different-edition", "citation": "Fragment 1"},
        {"id": "note", "parent_id": "greek"},
    ]
    assert evaluation.rank_of_target(hits, "greek") == 2
    assert evaluation.rank_of_target(hits[:1], "greek") is None
    assert evaluation.rank_of_target([{"id": "greek"}], "greek") == 1


def test_recall_and_reciprocal_rank_include_misses():
    rows = [{"ranks": {"dense_greek": 1}}, {"ranks": {"dense_greek": 5}},
            {"ranks": {"dense_greek": None}}]
    score = evaluation.summarize(rows, "dense_greek")
    assert score["recall_at_1"] == 0.3333
    assert score["recall_at_5"] == 0.6667
    assert score["mrr_at_10"] == 0.4
