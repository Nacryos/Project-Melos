"""Owner-commissioned literal translations: fail-closed binding, fallback-only transport, search rows."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend import literal_translations, server, translation_comparisons, translation_previews
from backend.passage_analysis import _context
from backend.passage_ranker import _translations
from scripts import build_literal_translations as build
from scripts import import_literal_translations as importer

ROOT = Path(__file__).resolve().parents[1]
POEMS = build.greek_records()
SIDECAR = json.loads(literal_translations.DATA_PATH.read_text(encoding="utf-8"))
ROWS = [json.loads(line) for line in build.ROWS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sidecar_is_the_pinned_build_of_the_committed_source():
    assert _sha(literal_translations.DATA_PATH) == literal_translations.DATA_SHA256
    assert SIDECAR["source_sha256"] == _sha(ROOT / SIDECAR["source_file"])
    sidecar, rows = build.build(ROOT / SIDECAR["source_file"])
    assert sidecar == SIDECAR
    assert rows == ROWS
    assert SIDECAR["model_eligible"] is False and SIDECAR["display_policy"] == "fallback_only"
    assert SIDECAR["record_count"] == 59 and SIDECAR["line_count"] == 506
    poets = {r["campbell_record_id"].split(":")[1] for r in SIDECAR["records"]}
    assert poets == {"sappho", "alcaeus", "anacreon"}


def test_every_record_binds_to_its_campbell_text_line_for_line():
    for record in SIDECAR["records"]:
        poem = POEMS[record["campbell_record_id"]]
        result = literal_translations.for_passage(poem)
        assert result["status"] == "available", record["campbell_record_id"]
        assert result["model_eligible"] is False and result["published_source"] is False
        assert result["display_policy"] == "fallback_only" and result["evidence_type"] == "literal_machine_translation"
        assert result["line_count"] == len(poem["lines"]) == len(result["lines"])
        assert [line["greek"] for line in result["lines"]] == [line["text"] for line in poem["lines"]]
        assert all(isinstance(line["english"], str) for line in result["lines"])
        assert result["text"] == "\n".join(line["english"] for line in result["lines"])
        # The projection is a copy: editing the response leaves the sidecar untouched.
        result["lines"][0]["english"] = "changed"
        assert literal_translations.for_passage(poem)["lines"][0]["english"] != "changed"


def test_changed_greek_or_unknown_poem_fails_closed():
    poem = deepcopy(POEMS["campbell-glp:sappho:31"])
    assert literal_translations.for_passage({**poem, "id": "synthetic:other"}) is None
    poem["text"] = poem["text"].replace("φαίνεταί", "φαίνεται")
    result = literal_translations.for_passage(poem)
    assert result["status"] == "unavailable" and result["lines"] == []
    short = deepcopy(POEMS["campbell-glp:sappho:31"])
    short["lines"] = short["lines"][:-1]
    assert literal_translations.for_passage(short)["status"] == "unavailable"


def test_published_english_flag_follows_previews_and_comparisons():
    poem = deepcopy(POEMS["campbell-glp:alcaeus:45"])
    assert translation_comparisons.for_passage(poem) is None
    assert literal_translations.for_passage(poem)["published_english_available"] is False
    sappho = deepcopy(POEMS["campbell-glp:sappho:31"])
    sappho["translation_comparisons"] = translation_comparisons.for_passage(sappho)
    assert sappho["translation_comparisons"]["status"] == "available"
    assert literal_translations.for_passage(sappho)["published_english_available"] is True
    poem["translation_previews"] = [{"text": "Published English", "language": "eng"}]
    assert literal_translations.for_passage(poem)["published_english_available"] is True


def test_passage_endpoint_attaches_fallback_and_hides_the_search_row(monkeypatch, tmp_path):
    poem = deepcopy(POEMS["campbell-glp:alcaeus:45"])
    row = next(r for r in ROWS if r["parent_id"] == poem["id"])
    database = tmp_path / "passages.sqlite"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, data TEXT, work_id TEXT, sequence INTEGER, "
                    "source TEXT, author TEXT, quality TEXT)")
        for order, record in enumerate((poem, row)):
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?)",
                        (record["id"], json.dumps(record, ensure_ascii=False), "test-work", order,
                         record["source"], record["author"], record["quality"]))

    def connect():
        con = sqlite3.connect(database)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(server, "connect", connect)
    monkeypatch.setattr(server, "legacy_schema", lambda: True)
    monkeypatch.setattr(server, "with_visual_themes", lambda record, _con: record, raising=False)
    monkeypatch.setattr(server, "evidence_lookup", lambda **_kwargs: {"ready": False, "claims": []})
    monkeypatch.setattr(server, "author_profile", lambda _author: None)
    monkeypatch.setattr(translation_previews, "project", lambda *_args, **_kwargs: {"translation_previews": []})
    client = TestClient(server.app)
    passage = client.get("/api/passage", params={"id": poem["id"]}).json()
    literal = passage["literal_translation"]
    assert literal["status"] == "available" and literal["published_english_available"] is False
    assert literal["campbell_record_id"] == poem["id"] and literal["line_count"] == 9
    assert "translation_comparisons" not in passage
    # The corpus row credits the poem in search but is not "related source material".
    assert [r["id"] for r in passage["related"]] == []
    # Analysis context and ranker never see the literal rendering.
    passage.setdefault("related", [])
    context = _context(passage)
    assert "literal_translation" not in context and context["published_translations"] == []
    assert _translations(passage) == []


def test_corpus_rows_are_machine_translation_children_of_their_poems():
    assert len(ROWS) == 59
    loaded = importer.load_records(build.ROWS)
    assert set(loaded) == {r["id"] for r in ROWS}
    for row in ROWS:
        poem = POEMS[row["parent_id"]]
        assert row["id"] == poem["id"] + ":literal"
        assert (row["kind"], row["language"], row["quality"]) == ("translation", "eng", "machine_translation")
        assert row["metadata"]["model_eligible"] is False and row["metadata"]["display_policy"] == "fallback_only"
        assert row["metadata"]["campbell_text_sha256"] == hashlib.sha256(poem["text"].encode("utf-8")).hexdigest()
        assert len(row["lines"]) == len(poem["lines"]) and row["text"] == "\n".join(l["text"] for l in row["lines"])
        assert row["raw_sha256"] == SIDECAR["source_sha256"]
    # A row rewritten to look like a published source is refused.
    bad = tmp = deepcopy(ROWS[0])
    bad["quality"] = "source_text"
    path = ROOT / "tests" / "_tmp_literal_rows.jsonl"
    try:
        path.write_text(json.dumps(tmp, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            importer.load_records(path)
        except ValueError as error:
            assert "scope" in str(error)
        else:
            raise AssertionError("published-looking row accepted")
    finally:
        path.unlink(missing_ok=True)
