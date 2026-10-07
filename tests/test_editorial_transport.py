"""Source-bound G transport; no editorial projection becomes raw evidence."""

from copy import deepcopy
import json
import sqlite3

from fastapi.testclient import TestClient

from backend import editorial_readings as editorial_module, server, translation_previews
from backend.edition_commentary import for_passage as commentary_for_passage
from backend.editorial_readings import editorial_readings
from backend.passage_analysis import PassageAnalysisService
from scripts.build_translation_comparisons import GREEK


def _poem(fragment="129"):
    return next(row for row in map(json.loads, GREEK.read_text(encoding="utf8").splitlines())
                if row["id"] == f"campbell-glp:alcaeus:{fragment}")


def test_passage_endpoint_exposes_only_source_bound_editorial_spans(monkeypatch, tmp_path):
    poem = _poem()
    unrelated = {**poem, "id": "synthetic:unrelated", "source": "synthetic"}
    database = tmp_path / "passages.sqlite"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, data TEXT, work_id TEXT, sequence INTEGER, "
                    "source TEXT, author TEXT, quality TEXT)")
        for sequence, row in enumerate((poem, unrelated)):
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?)",
                        (row["id"], json.dumps(row, ensure_ascii=False), "test-work", sequence,
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
    assert passage["text"] == poem["text"]
    assert passage["editorial_readings"] == editorial_readings(poem)
    assert passage["published_commentary"]["status"] == "available"
    assert passage["structured_evidence"]["claims"] == []
    def broken_projection(_passage):
        raise ValueError("synthetic source metadata failure")
    monkeypatch.setattr(editorial_module, "editorial_readings", broken_projection)
    failed = client.get("/api/passage", params={"id": poem["id"]})
    assert failed.status_code == 200
    assert failed.json()["editorial_readings"]["status"] == "unavailable"
    assert failed.json()["text"] == poem["text"]
    other = client.get("/api/passage", params={"id": unrelated["id"]}).json()
    assert "editorial_readings" not in other


def _request(passage, start, end, **flags):
    return {"version": 1, "passage_id": passage["id"], "start": start, "end": end,
            "offset_unit": "codepoint", "selected_text": passage["text"][start:end], **flags}


def test_full_editorial_word_uses_generic_lookup_only_after_rankers():
    passage = _poem()
    passage["published_commentary"] = commentary_for_passage(passage)
    row = next(row for row in editorial_readings(passage)["rows"] if row["lookup_eligible"])
    calls, model_inputs = [], []

    def lookup(form, passage_id):
        calls.append((form, passage_id))
        return {"form": form, "candidates": [], "contextual_candidates": [],
                "structured_evidence": {"ready": False, "claims": []}}

    def ranker(result, **_kwargs):
        model_inputs.append(deepcopy(result))
        return {"status": "unavailable", "items": []}

    service = PassageAnalysisService(lambda _id: passage, lookup, ranker=ranker, sense_ranker=ranker)
    result = service.analyze(_request(passage, row["start"], row["end"], rerank=True))
    editorial = result["editorial_analysis"]
    assert editorial["status"] == "available"
    assert editorial["rows"][0]["original_text"] == row["original_text"]
    assert editorial["rows"][0]["projected_text"] == row["projected_text"]
    assert editorial["rows"][0]["start"] == row["start"]
    assert editorial["rows"][0]["lookup_status"] == "complete"
    assert (row["projected_text"], "") in calls
    assert all("editorial_analysis" not in payload for payload in model_inputs)
    assert result["selection"]["text"] == row["original_text"]
    assert "projected_text" not in json.dumps(result["tokens"], ensure_ascii=False)
    assert result["context"]["structured_evidence"]["claims"] == []
    assert editorial["limits"]["machine_fetches"] == 0
    assert editorial["limits"]["max_lookups"] == 16


def test_partial_editorial_piece_gives_expansion_hint_without_projected_lookup():
    passage = _poem()
    passage["published_commentary"] = commentary_for_passage(passage)
    row = next(row for row in editorial_readings(passage)["rows"] if row["lookup_eligible"])
    calls = []
    service = PassageAnalysisService(lambda _id: passage,
                                     lambda form, pid: calls.append((form, pid)) or {"candidates": []})
    result = service.analyze(_request(passage, row["start"], row["start"] + 1))
    editorial = result["editorial_analysis"]
    assert editorial["status"] == "partial_selection"
    assert editorial["rows"] == []
    assert editorial["selection_expansion_hints"][0]["start"] == row["start"]
    assert editorial["selection_expansion_hints"][0]["end"] == row["end"]
    assert editorial["limits"]["lookups"] == 0
    assert (row["projected_text"], "") not in calls


def test_unavailable_source_gate_leaves_conditional_analysis_unavailable():
    passage = _poem()
    passage["published_commentary"] = {"status": "unavailable"}
    calls = []
    service = PassageAnalysisService(lambda _id: passage,
                                     lambda form, pid: calls.append((form, pid)) or {"candidates": []})
    row = next(row for row in editorial_readings(passage)["rows"] if row["lookup_eligible"])
    result = service.analyze(_request(passage, row["start"], row["end"]))
    assert result["editorial_analysis"]["status"] == "unavailable"
    assert not any(pid == "" for _form, pid in calls)
