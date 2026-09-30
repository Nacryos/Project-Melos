"""Author-label merging, mirror grouping and corrected-OCR search over synthetic rows.

Every row below is test data. Labels are spelled the way real collectors spell
them (an English name, a "name of place" form, an aggregator slug, a Greek
form and a joint label) so the merge policy is exercised end to end.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend import server
from backend.author_aliases import canonical, canonical_key, component_keys
from scripts import build_corpus


SAME_TEXT = "χαῖρε πολυστέφανε Ἀλκαῖε φίλος"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    raw = root / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("SYNTHETIC TEST FIXTURE", encoding="utf-8")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    processed = root / "data/processed"
    processed.mkdir(parents=True)
    common = {
        "source": "direct-collector", "source_url": "https://example.org/synthetic",
        "raw_path": "data/raw/synthetic.txt", "raw_sha256": digest,
        "edition": "Synthetic edition", "language": "grc", "kind": "text",
        "quality": "source_text", "license": "test-only", "work": "Fragments",
    }
    # IDs are chosen so that plain alphabetical order would pick a mirror as
    # the representative; the direct collector must still win on preference.
    rows = [
        dict(common, id="z-direct", author="Alcaeus of Mytilene", citation="1", text=SAME_TEXT),
        dict(common, id="a-mirror", author="alcaeus-lyric", citation="1", text=SAME_TEXT,
             source="p2_ogc", edition="perseus-grc2"),
        dict(common, id="b-mirror", author="Αλκαίος", citation="fr. 1", text=SAME_TEXT,
             source="ogc_derived", edition="unspecified"),
        dict(common, id="c-ocr-copy", author="Alcaeus", citation="1", text=SAME_TEXT,
             source="bergk-ocr", quality="machine_corrected_ocr"),
        dict(common, id="variant", author="Alcaeus", citation="1", text="χαῖρε πολυστέφανε Ἀλκαῖε φίλε",
             source="other-edition", edition="Edition B"),
        dict(common, id="joint", author="Sappho / Alcaeus", citation="joint 1", text="κοινὸν μέλος Ἀλκαῖε"),
        dict(common, id="sappho", author="Sappho", citation="1", text="ποικιλόθρον᾽ Ἀφρόδιτα"),
        dict(common, id="ocr-good", author="ibycus", citation="Bergk 1", text="Ἔρος αὖτέ με κυανέοισιν",
             quality="machine_corrected_ocr", source="bergk-ocr"),
        dict(common, id="ocr-raw", author="Ibycus", citation="Bergk 2", text="Ἔρος αὖτέ με ἀκάθαρτος",
             quality="machine_ocr", source="bergk-ocr"),
        dict(common, id="messene", author="Alcaeus of Messene / Anthologia Palatina", citation="AP 1",
             text="ἄλλος Ἀλκαῖος ἐπίγραμμα"),
    ]
    fixture_file = processed / "synthetic.jsonl"
    fixture_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {
        fixture_file.name: {"verdict": "PASS", "sha256": hashlib.sha256(fixture_file.read_bytes()).hexdigest(),
                            "records": len(rows)}}}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "DB", root / "data/corpus.sqlite")
    build_corpus.build(server.DB)
    return TestClient(server.app)


def test_alias_table_merges_single_author_labels_only():
    assert canonical("Alcaeus of Mytilene") == canonical("alcaeus-lyric") == canonical("ΑΛΚΑΙΟΣ") == "Alcaeus"
    assert canonical_key("Ἀλκαῖος") == "alcaeus"
    assert canonical("Sappho / Alcaeus") == "Sappho / Alcaeus"
    assert component_keys("Sappho / Alcaeus") == ["sappho / alcaeus", "sappho", "alcaeus"]
    assert canonical("Alcaeus of Messene / Anthologia Palatina") != "Alcaeus"
    assert canonical("Heather Waddell") == "Heather Waddell"


def test_author_chooser_merges_spellings_and_keeps_joint_labels_apart(client: TestClient):
    authors = {item["author"]: item for item in client.get("/api/authors").json()["authors"]}
    assert set(authors["Alcaeus"]["labels"]) == {"Alcaeus of Mytilene", "alcaeus-lyric", "Αλκαίος", "Alcaeus"}
    assert authors["Alcaeus"]["count"] == 5 and authors["Alcaeus"]["merged"] is True
    assert set(authors["Ibycus"]["labels"]) == {"ibycus", "Ibycus"}
    assert "Sappho / Alcaeus" in authors and "Alcaeus of Messene / Anthologia Palatina" in authors
    assert client.get("/api/status").json()["authors"] == 5


def test_author_filter_reaches_every_spelling_and_joint_attributions(client: TestClient):
    params = {"q": "Ἀλκαῖε", "author": "Alcaeus", "match": "exact"}
    ids = {row["id"] for row in client.get("/api/search", params=params).json()["results"]}
    # Identical copies collapse into one representative; the variant wording and
    # the joint attribution are separate results. Messene is another poet.
    assert ids == {"z-direct", "c-ocr-copy", "variant", "joint"}
    greek = client.get("/api/search", params={"q": "Ἀλκαῖε", "author": "Αλκαίος", "match": "exact"}).json()
    assert {row["id"] for row in greek["results"]} == ids
    works = client.get("/api/works", params={"author": "alcaeus-lyric"}).json()["works"]
    assert {row["author"] for row in works} >= {"Alcaeus of Mytilene", "alcaeus-lyric", "Αλκαίος", "Alcaeus"}
    joint_only = client.get("/api/search", params={"q": "Ἀλκαῖε", "author": "Sappho / Alcaeus", "match": "exact"}).json()
    assert [row["id"] for row in joint_only["results"]] == ["joint"]


def test_identical_copies_collapse_with_direct_collector_first(client: TestClient):
    response = client.get("/api/search", params={"q": "πολυστέφανε", "match": "exact"}).json()
    # Three groups: the three edited copies, the corrected-OCR copy (its own
    # quality label) and the variant wording.
    assert response["total"] == 3
    collapsed = next(row for row in response["results"] if row["id"] == "z-direct")
    assert collapsed["mirror_count"] == 3
    assert collapsed["mirrored_ids"] == ["a-mirror", "b-mirror"]
    assert any("mirrored_ids" in warning for warning in response["warnings"])
    variant = next(row for row in response["results"] if row["id"] == "variant")
    assert variant["mirror_count"] == 1 and variant["mirrored_ids"] == []
    passage = client.get("/api/passage", params={"id": "b-mirror"}).json()
    assert [row["id"] for row in passage["mirrors"]] == ["z-direct", "a-mirror"]
    assert passage["author_canonical"] == "Alcaeus"
    paged = client.get("/api/search", params={"q": "πολυστέφανε", "match": "exact", "limit": 1, "offset": 1}).json()
    assert paged["total"] == 3 and len(paged["results"]) == 1


def test_fuzzy_and_fulltext_paths_also_group_copies(client: TestClient):
    fuzzy = client.get("/api/search", params={"q": "πολυστεφανε φιλος", "match": "fuzzy"}).json()
    assert fuzzy["total"] >= 1
    top = fuzzy["results"][0]
    assert top["id"] == "z-direct" and top["mirror_count"] == 3
    hybrid = client.get("/api/search", params={"q": "πολυστέφανε", "mode": "hybrid", "author": "Alcaeus"}).json()
    ids = [row["id"] for row in hybrid["results"]]
    assert "z-direct" in ids and "a-mirror" not in ids and "b-mirror" not in ids
    grouped = next(row for row in hybrid["results"] if row["id"] == "z-direct")
    assert set(grouped["mirrored_ids"]) == {"a-mirror", "b-mirror"}


def test_machine_corrected_ocr_is_searchable_and_raw_ocr_is_not(client: TestClient):
    default = client.get("/api/search", params={"q": "Ἔρος", "match": "exact"}).json()
    assert {row["id"] for row in default["results"]} == {"ocr-good"}
    assert default["results"][0]["quality"] == "machine_corrected_ocr"
    with_reference = client.get("/api/search", params={"q": "Ἔρος", "match": "exact", "include_reference": "true"}).json()
    assert {row["id"] for row in with_reference["results"]} == {"ocr-good", "ocr-raw"}
    status = client.get("/api/status").json()
    assert status["searchable_qualities"] == ["source_text", "machine_corrected_ocr"]
    listed = client.get("/api/passages").json()
    assert "ocr-good" in {row["id"] for row in listed["results"]}
    assert "ocr-raw" not in {row["id"] for row in listed["results"]}
    word = client.get("/api/word", params={"form": "Ἔρος"}).json()
    assert {row["id"] for row in word["occurrences"]} == {"ocr-good"}


def test_old_schema_index_still_merges_authors_without_grouping(client: TestClient):
    """An index built before this change keeps serving; only mirror grouping is off."""
    import sqlite3
    with sqlite3.connect(server.DB) as con:
        con.executescript("""
            DROP INDEX IF EXISTS idx_passage_canonical; DROP INDEX IF EXISTS idx_passage_mirror;
            ALTER TABLE passages DROP COLUMN author_canonical; ALTER TABLE passages DROP COLUMN text_key;
            DROP TABLE passage_authors; ALTER TABLE works DROP COLUMN author_canonical;
        """)
    server.schema_ready.cache_clear()
    status = client.get("/api/status").json()
    assert status["mirror_grouping"] is False
    assert any("predates mirror grouping" in warning for warning in status["warnings"])
    authors = {item["author"]: item for item in client.get("/api/authors").json()["authors"]}
    assert set(authors["Alcaeus"]["labels"]) == {"Alcaeus of Mytilene", "alcaeus-lyric", "Αλκαίος", "Alcaeus"}
    response = client.get("/api/search", params={"q": "Ἀλκαῖε", "author": "Alcaeus", "match": "exact"}).json()
    ids = {row["id"] for row in response["results"]}
    assert ids == {"z-direct", "a-mirror", "b-mirror", "c-ocr-copy", "variant", "joint"}
    assert all(row["mirror_count"] == 1 for row in response["results"])
    works = client.get("/api/works", params={"author": "Αλκαίος"}).json()["works"]
    assert {row["author"] for row in works} >= {"Alcaeus of Mytilene", "alcaeus-lyric", "Αλκαίος", "Alcaeus"}
    passage = client.get("/api/passage", params={"id": "b-mirror"}).json()
    assert passage["mirrors"] == [] and passage["author_canonical"] == "Alcaeus"
    hybrid = client.get("/api/search", params={"q": "πολυστέφανε", "mode": "hybrid", "author": "Alcaeus"}).json()
    assert {row["id"] for row in hybrid["results"]} >= {"z-direct"}
