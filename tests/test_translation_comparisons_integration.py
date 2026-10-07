"""Reader-only transport of approved, different-edition comparisons."""

from copy import deepcopy
import json
import re
import sqlite3

from fastapi.testclient import TestClient

from backend import server, translation_comparisons, translation_previews
from backend.passage_analysis import PassageAnalysisService, _context
from backend.passage_ranker import _translations
from scripts.build_translation_comparisons import GREEK


def _poem(fragment="34a"):
    return next(json.loads(line) for line in GREEK.read_text(encoding="utf8").splitlines()
                if json.loads(line)["id"] == f"campbell-glp:alcaeus:{fragment}")


def test_exact_approved_copy_is_the_runtime_default():
    assert translation_comparisons.DATA_PATH.read_bytes() == (
        GREEK.parents[2] / "runtime/alcaeus-translations/translation-comparisons.public.json"
    ).read_bytes()
    for fragment in ("34a", "129", "130b", "326", "350"):
        result = translation_comparisons.for_passage(_poem(fragment))
        assert result["status"] == "available"
        assert result["model_eligible"] is False
        assert result["exact_edition_alignment"] is False


def test_passage_endpoint_attaches_only_exact_source_identity(monkeypatch, tmp_path):
    poem = _poem()
    unrelated = {**poem, "id": "synthetic:unrelated"}
    database = tmp_path / "passages.sqlite"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, data TEXT, work_id TEXT, sequence INTEGER, "
                    "source TEXT, author TEXT, quality TEXT)")
        for order, row in enumerate((poem, unrelated)):
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?)",
                        (row["id"], json.dumps(row, ensure_ascii=False), "test-work", order,
                         row["source"], row["author"], row["quality"]))

    def connect():
        con = sqlite3.connect(database)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(server, "connect", connect)
    monkeypatch.setattr(server, "legacy_schema", lambda: True)
    monkeypatch.setattr(server, "with_visual_themes", lambda row, _con: row, raising=False)
    monkeypatch.setattr(server, "evidence_lookup", lambda **_kwargs: {"ready": False, "claims": []})
    monkeypatch.setattr(server, "author_profile", lambda _author: None)
    monkeypatch.setattr(translation_previews, "project", lambda *_args, **_kwargs: {"translation_previews": []})

    client = TestClient(server.app)
    response = client.get("/api/passage", params={"id": poem["id"]})
    assert response.status_code == 200, response.text
    passage = response.json()
    comparison = passage["translation_comparisons"]
    assert comparison == translation_comparisons.for_passage(poem)
    assert comparison["campbell_record_id"] == poem["id"]
    assert passage["translation_previews"] == []
    assert "translation_of" not in comparison and "parent_id" not in comparison
    assert client.get("/api/passage", params={"id": unrelated["id"]}).json().get(
        "translation_comparisons") is None


def test_analysis_context_keeps_comparisons_separate_and_copied():
    passage = _poem("129")
    comparison = translation_comparisons.for_passage(passage)
    passage["translation_comparisons"] = deepcopy(comparison)
    passage["translation_previews"] = []
    passage["related"] = []
    context = _context(passage)
    assert context["translation_comparisons"] == comparison
    assert context["published_translations"] == []
    assert context["commentary"] == []
    assert context["structured_evidence"]["claims"] == []
    assert _translations(passage) == []
    item = context["translation_comparisons"]["translation_comparisons"][0]
    assert item["license"] == comparison["translation_comparisons"][0]["license"]
    assert item["reuse_status"] == comparison["translation_comparisons"][0]["reuse_status"]
    item["text"] = "Changed only in the response copy"
    assert passage["translation_comparisons"] == comparison
    assert _context({"id": "synthetic:unrelated", "related": []})["translation_comparisons"] is None


def test_analysis_response_is_reader_only_without_model_calls():
    passage = _poem("350")
    passage["translation_comparisons"] = translation_comparisons.for_passage(passage)
    passage["translation_previews"] = []
    passage["related"] = []
    match = re.search(r"[\u0370-\u03ff\u1f00-\u1fff]+", passage["text"])
    assert match
    calls = []
    service = PassageAnalysisService(lambda _id: passage,
                                     lambda *_args: {"candidates": [], "structured_evidence": {"claims": []}},
                                     ranker=lambda *_args, **_kwargs: calls.append("ranker"),
                                     sense_ranker=lambda *_args, **_kwargs: calls.append("sense_ranker"))
    response = service.analyze({"version": 1, "passage_id": passage["id"],
                                "start": match.start(), "end": match.end(),
                                "offset_unit": "codepoint", "selected_text": match.group()})
    assert response["context"]["translation_comparisons"] == passage["translation_comparisons"]
    assert response["context"]["published_translations"] == []
    assert response["ranking"]["status"] == "not_requested"
    assert response["sense_ranking"]["status"] == "not_requested"
    assert calls == []
