"""API regression tests over a deliberately synthetic, isolated corpus.

The fixture below is test data only. It is never copied into data/processed or
presented as a sourced literary passage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend import server
from scripts import build_corpus


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    root = tmp_path
    raw = root / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("SYNTHETIC TEST FIXTURE", encoding="utf-8")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    processed = root / "data/processed"
    processed.mkdir(parents=True)
    common = {
        "source": "synthetic-test-source",
        "source_url": "https://example.org/synthetic-test-only",
        "raw_path": "data/raw/synthetic.txt",
        "raw_sha256": digest,
        "edition": "Synthetic test edition",
        "language": "grc",
        "kind": "text",
        "quality": "source_text",
        "license": "test-only",
    }
    rows = [
        dict(common, id="p1", author="Alpha", work="Song", citation="1", text="μοῦσα φωνή"),
        dict(common, id="p2", author="Alpha", work="Song", citation="2", text="μοῖρα καλὴ"),
        dict(common, id="p3", author="Beta", work="Song", citation="3", text="ἀμουσία κόσμος",
             source_url="https://example.org/synthetic-other-page"),
        dict(common, id="p4", author="Alpha", work="Song", citation="4", text="μοῦσα κρυπτή", quality="machine_ocr"),
        dict(common, id="p5", author="Alpha", work="Song", citation="5", text="μοῦσα ἀβέβαιος", quality="needs_review"),
        dict(common, id="t1", author="Alpha", work="Song", citation="1", text="Muse voice", language="eng", kind="translation", parent_id="p1"),
        dict(common, id="p6", author="Alpha", work="Other", citation="1", text="<script>alert(1)</script> ἄνθος"),
        dict(common, id="p8", author="alpha", work="Lowercase", citation="1", text="ὕμνος"),
        dict(common, id="c1", author="Heather", work="Notes", citation="1", text="Muse discussion", language="eng", kind="commentary", parent_id="p1"),
        dict(common, id="c2", author="Heather", work="Notes", citation="2", text="Page note", language="eng", kind="commentary", metadata={"scope": "page"}),
        dict(common, id="c3", author="Heather", work="Notes", citation="3", text="Page stray", language="eng", kind="commentary", metadata={"scope": "page"},
             source_url="https://example.org/unrelated-page"),
        dict(common, id="c4", author="Heather", work="Notes", citation="4", text="Page orphan", language="eng", kind="commentary", parent_id="missing"),
    ]
    # Optional rows are synthetic mechanics fixtures, never literary evidence.
    rows.extend(dict(common, **row) for row in getattr(request, "param", []))
    fixture_file = processed / "synthetic.jsonl"
    fixture_file.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    (processed / "unreviewed.jsonl").write_text(
        json.dumps(dict(common, id="unreviewed", author="Gamma", work="Unreviewed",
                        citation="1", text="μοῦσα"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Isolated test gate: this is deliberately synthetic and is never used as
    # an independent audit decision about production collector outputs.
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {
        fixture_file.name: {"verdict": "PASS", "sha256": hashlib.sha256(fixture_file.read_bytes()).hexdigest(), "records": len(rows)}
    }}), encoding="utf-8")
    (reports / "collector.json").write_text(json.dumps({"raw_file": str(raw)}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "DB", root / "data/corpus.sqlite")
    build_corpus.build(server.DB)
    yield TestClient(server.app)


def test_status_and_work_navigation(client: TestClient):
    status = client.get("/api/status").json()
    assert status["passages"] == 12
    assert status["authors"] == 3
    assert status["author_labels"] == 4
    assert "unreviewed" not in {p["id"] for p in client.get("/api/search", params={"q": "μοῦσα", "include_reference": "true"}).json()["results"]}
    works = client.get("/api/works", params={"author": "Alpha"}).json()["works"]
    assert {w["work"] for w in works} == {"Song", "Other", "Lowercase"}
    song = next(w for w in works if w["work"] == "Song" and w["language"] == "grc")
    listing = client.get("/api/passages", params={"work_id": song["id"]}).json()
    assert listing["total"] == 4
    assert [p["id"] for p in listing["results"]] == ["p1", "p2", "p4", "p5"]
    passage = client.get("/api/passage", params={"id": "p1"}).json()
    assert passage["previous_id"] is None
    assert passage["next_id"] == "p2"
    assert {related["id"] for related in passage["related"]} == {"t1", "c1", "c2"}
    assert client.get("/api/passage", params={"id": "missing"}).status_code == 404


def test_search_unicode_filters_and_quarantine(client: TestClient):
    accented = client.get("/api/search", params={"q": "ΜΟΎΣΑ", "match": "exact"}).json()
    plain = client.get("/api/search", params={"q": "μουσα", "match": "exact"}).json()
    assert [r["id"] for r in accented["results"]] == [r["id"] for r in plain["results"]]
    assert [r["id"] for r in plain["results"]] == ["p1"]
    assert client.get("/api/search", params={"q": "μουσα", "author": "Beta", "match": "exact"}).json()["results"] == []
    assert {r["id"] for r in client.get("/api/search", params={"q": "μουσα", "include_reference": "true", "match": "exact"}).json()["results"]} == {"p1", "p4", "p5"}
    assert {r["id"] for r in client.get("/api/search", params={"q": "Muse", "language": "eng", "match": "exact"}).json()["results"]} == {"t1", "c1"}


def test_literal_syntax_and_url_paths(client: TestClient):
    assert client.get("/api/search", params={"q": "%_\\'\"", "match": "exact"}).status_code == 200
    assert client.get("/api/search", params={"q": "<script>", "match": "exact"}).status_code == 200
    assert client.get("/api/search", params={"q": "alert", "match": "exact"}).json()["results"][0]["id"] == "p6"
    assert client.get("/api/search", params={"q": "x" * 10000}).status_code == 422
    assert client.get("/api/search", params={"q": "muse", "mode": "bad"}).status_code == 400
    assert client.get("/api/search", params={"q": "muse", "limit": 1000}).status_code == 422
    assert client.get("/api/../backend/server.py").status_code == 404
    assert client.get("/data/raw/synthetic.txt").status_code == 404
    assert client.get("/data/corpus.sqlite").status_code == 404


@pytest.mark.parametrize("route", ["/api/search", "/api/usage-space"])
@pytest.mark.parametrize("query", ["x" * 1001, "x" * 1302, "\U0001f600" * 1001, "\ufeff" + "x" * 1000], ids=["1001", "1302", "astral-1001", "retained-bom"])
def test_oversize_search_rejected_before_services(client, monkeypatch, route, query):
    def unexpected(*args, **kwargs):
        raise AssertionError("Oversize query must not reach corpus, semantic or morphology services")
    monkeypatch.setattr(server, "connect", unexpected)
    monkeypatch.setattr(server, "semantic_service", unexpected)
    monkeypatch.setattr(server, "morph_service", unexpected)
    result = client.get(route, params={"q": f"  {query}  ", "mode": "hybrid"})
    assert result.status_code == 422
    assert "1000 Unicode characters" in result.json()["detail"]
    assert "not shortened or searched" in result.json()["detail"]


@pytest.mark.parametrize("query", ["x" * 1000, "\U0001f600" * 1000, "\u0085" + "x" * 1000 + "\u0085"], ids=["1000", "astral-1000", "trimmed-next-line"])
def test_maximum_search_query_accepted_without_utf16_counting(client, query):
    result = client.get("/api/search", params={"q": f"  {query}  ", "mode": "words", "match": "exact"})
    assert result.status_code == 200
    assert result.json()["results"] == []


def test_sources_hide_internal_paths(client: TestClient, tmp_path: Path):
    response = client.get("/api/sources")
    assert response.status_code == 200
    assert "audit-acceptance" not in {r["name"] for r in response.json()["reports"]}
    assert str(tmp_path).lower() not in response.text.lower()


def test_word_occurrences_and_parent_link(client: TestClient):
    word = client.get("/api/word", params={"form": "μοῦσα", "passage_id": "p1"}).json()
    assert word["context"]["id"] == "p1"
    assert {p["id"] for p in word["occurrences"]} == {"p1"}
    translation = client.get("/api/passage", params={"id": "t1"}).json()
    assert translation["parent_id"] == "p1"
    assert any(r["id"] == "p1" for r in translation["related"])


def test_unknown_work_is_empty(client: TestClient):
    response = client.get("/api/passages", params={"work_id": "not-a-work"})
    assert response.status_code == 200
    assert response.json() == {"results": [], "total": 0}


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-reference", "author": "Alpha", "work": "Fragments", "citation": "fr. 286 Page",
     "text": "Synthetic catalogue pointer only", "kind": "reference", "language": "mul",
     "metadata": {"greek_text_extracted": False}},
    {"id": "synthetic-irrelevant", "author": "Beta", "work": "Fragments", "citation": "fr. 286",
     "text": "Synthetic unrelated Alpha 286 mention"},
]], indirect=True)
def test_reference_intent_catalogue_only_not_broad_fallback(client: TestClient):
    for mode in ("words", "forms", "themes", "hybrid"):
        result = client.get("/api/search", params={"q": "Alpha 286", "mode": mode}).json()
        assert result["total"] == 1
        assert result["mode"] == "reference"
        assert result["results"][0]["id"] == "synthetic-reference"
        assert result["results"][0]["reference_match"]["coverage"] == "reference_only"
    assert client.get("/api/search", params={"q": "Alpha 286", "language": "grc"}).json()["total"] == 0
    empty = client.get("/api/search", params={"q": "Alpha 999", "mode": "hybrid"}).json()
    assert empty["total"] == 0
    assert empty["mode"] == "reference"
    conflict = client.get("/api/search", params={"q": "Alpha 286", "author": "Beta"}).json()
    assert conflict["total"] == 0
    assert any("conflicts" in warning for warning in conflict["warnings"])


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-fragment", "author": "Alpha", "work": "Fragments", "citation": "Frag. 31",
     "text": "SYNTHETIC FULL TEXT"},
    {"id": "synthetic-line", "author": "Alpha", "work": "Fragments", "citation": "Frag. 31.1",
     "text": "SYNTHETIC DOTTED LOCUS"},
]], indirect=True)
def test_reference_intent_primary_text_and_selected_author(client: TestClient):
    result = client.get("/api/search", params={"q": "31", "author": "Alpha"}).json()
    assert [record["id"] for record in result["results"]] == ["synthetic-fragment"]
    assert result["results"][0]["reference_match"]["coverage"] == "text"


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-split", "author": "Alpha", "work": "Layout", "citation": "test-layout",
     "text": "αβγ-\nδε ζηθ"},
]], indirect=True)
def test_joined_search_tokens_leave_printed_text_unchanged(client: TestClient):
    # Deliberately nonsense Greek strings test layout mechanics, not morphology.
    for query in ("αβγδε", "αβγδε ζηθ"):
        result = client.get("/api/search", params={"q": query, "match": "exact"}).json()
        assert [record["id"] for record in result["results"]] == ["synthetic-split"]
        assert result["results"][0]["text"] == "αβγ-\nδε ζηθ"
    word = client.get("/api/word", params={"form": "αβγδε", "passage_id": "synthetic-split"}).json()
    assert "synthetic-split" in {record["id"] for record in word["occurrences"]}
    assert client.get("/api/passage", params={"id": "synthetic-split"}).json()["text"] == "αβγ-\nδε ζηθ"


def test_exact_search_pages_have_stable_total_and_no_duplicates(client: TestClient):
    params = {"q": "μουσα", "match": "exact", "include_reference": "true", "limit": 1}
    pages = [client.get("/api/search", params=params | {"offset": offset}).json()
             for offset in range(4)]
    assert [page["total"] for page in pages] == [3, 3, 3, 3]
    assert [page["results"][0]["id"] for page in pages[:3]] == ["p1", "p4", "p5"]
    assert pages[3]["results"] == []
    assert client.get("/api/search", params=params | {"offset": -1}).status_code == 422


def test_form_expansion_pages_deduplicate_exact_hits(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class FixtureForms:
        def analyze(self, form, limit=6):
            return {"candidates": [{"lemma": "test-only-lemma"}], "expansion_lemmas": ["test-only-lemma"], "warnings": []}

        def expansion_forms_for_lemma(self, lemma):
            # Synthetic associations verify query mechanics, not morphology.
            return ["μοῦσα", "μοῖρα", "ἀμουσία"]

    monkeypatch.setattr(server, "morph_service", lambda: FixtureForms())
    params = {"q": "μοῦσα", "mode": "forms", "limit": 1}
    pages = [client.get("/api/search", params=params | {"offset": offset}).json()
             for offset in range(4)]
    assert [page["total"] for page in pages] == [3, 3, 3, 3]
    assert [page["results"][0]["id"] for page in pages[:3]] == ["p1", "p2", "p3"]
    assert pages[3]["results"] == []


def test_equivalent_form_relation_still_expands_search_without_becoming_a_parse(
        client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class FixtureMorphology:
        def analyze(self, form, limit=6):
            return {"candidates": [], "expansion_lemmas": [], "warnings": []}

        def expansion_forms_for_lemma(self, lemma):
            return []

    class FixtureEvidence:
        def forms_for_lemma(self, headword, limit=500):
            return []

        def candidate_analyses(self, form, limit=12):
            return {"candidates": []}

        def equivalent_forms_for_form(self, form, limit=500):
            # Synthetic relation demonstrates retrieval expansion only.
            return ["μοῖρα"] if form == "μοῦσα" else []

    monkeypatch.setattr(server, "morph_service", lambda: FixtureMorphology())
    monkeypatch.setattr(server, "evidence_service", lambda: FixtureEvidence())
    result = client.get("/api/search", params={"q": "μοῦσα", "mode": "forms"}).json()
    assert {row["id"] for row in result["results"]} == {"p1", "p2"}
    assert result["total"] == 2


def test_theme_pages_count_filtered_retrieval_window(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class FixtureSemantic:
        requested_limits = []

        def search(self, query, limit, **filters):
            self.requested_limits.append(limit)
            return [{"id": id, "score": 1 - i / 10, "match_reason": "synthetic ranking"}
                    for i, id in enumerate(["p1", "p4", "p2", "p5", "p3"])][:limit]

    index = FixtureSemantic()
    monkeypatch.setattr(server, "semantic_service", lambda: index)
    params = {"q": "synthetic theme", "mode": "themes", "limit": 1}
    pages = [client.get("/api/search", params=params | {"offset": offset}).json()
             for offset in range(4)]
    assert [page["total"] for page in pages] == [3, 3, 3, 3]
    assert [page["results"][0]["id"] for page in pages[:3]] == ["p1", "p2", "p3"]
    assert pages[3]["results"] == []
    assert index.requested_limits == [1000] * 4


def test_author_scope_uses_only_exact_label_or_source_links(client: TestClient):
    grouped = client.get("/api/authors").json()["authors"]
    alpha = next(item for item in grouped if item["author"] == "Alpha")
    assert alpha["labels"] == ["Alpha", "alpha"]
    assert alpha["count"] == 7
    assert {r["id"] for r in client.get("/api/search", params={
        "q": "Muse", "author": "ALPHA", "language": "eng", "match": "exact"
    }).json()["results"]} == {"t1", "c1"}
    commentary = client.get("/api/search", params={
        "q": "Page", "author": "Alpha", "language": "eng", "match": "exact"
    }).json()["results"]
    assert [r["id"] for r in commentary] == ["c2"]
    assert commentary[0]["author"] == "Heather"
    assert "author_scope_reason" in commentary[0]
    assert client.get("/api/search", params={
        "q": "Page", "author": "Beta", "language": "eng", "match": "exact"
    }).json()["results"] == []


def test_theme_projects_only_explicit_parent_and_page_notes_require_reference_opt_in(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class FixtureSemantic:
        def search(self, query, limit, **filters):
            return [{"id": id, "score": 0.9, "match_reason": "synthetic ranking"}
                    for id in ["c3", "c1", "c2", "p1"]][:limit]

    monkeypatch.setattr(server, "semantic_service", lambda: FixtureSemantic())
    common = {
        "q": "synthetic theme", "mode": "themes", "author": "alpha", "limit": 10
    }
    data = client.get("/api/search", params=common).json()
    assert [r["id"] for r in data["results"]] == ["p1"]
    assert data["results"][0]["author"] == "Alpha"
    evidence = data["results"][0]["matched_evidence"]
    assert [hit["id"] for hit in evidence] == ["c1", "p1"]
    assert evidence[0]["projection_scope"] == "explicit_parent_id"
    assert evidence[0]["author"] == "Heather"
    assert evidence[0]["parent_id"] == "p1"
    assert evidence[0]["text_excerpt"] == "Muse discussion"
    assert evidence[0]["excerpt_truncated"] is False
    assert data["results"][0]["retrieval_score_kind"] == "reciprocal_rank"
    opted = client.get("/api/search", params=common | {"include_reference": "true"}).json()
    assert [r["id"] for r in opted["results"]] == ["p1", "c2"]
    assert opted["results"][1]["author"] == "Heather"
    assert opted["results"][1]["matched_evidence"][0]["projection_scope"] == "unprojected_page_scope"
    assert "c3" not in {r["id"] for r in opted["results"]}
    english = client.get("/api/search", params=common | {"language": "eng"}).json()
    assert [r["id"] for r in english["results"]] == ["c1"]
    assert english["results"][0]["author"] == "Heather"
    assert client.get("/api/search", params=common | {"edition": "Not this edition"}).json()["results"] == []


def test_theme_grouped_pagination_has_no_repeated_parent(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class FixtureSemantic:
        requested_limits = []

        def search(self, query, limit, **filters):
            self.requested_limits.append(limit)
            return [{"id": id, "score": 1 - i / 10, "match_reason": "synthetic ranking"}
                    for i, id in enumerate(["c1", "t1", "p2", "p1", "c2"])][:limit]

    index = FixtureSemantic()
    monkeypatch.setattr(server, "semantic_service", lambda: index)
    common = {"q": "synthetic theme", "mode": "themes", "author": "Alpha", "limit": 1}
    pages = [client.get("/api/search", params=common | {"offset": offset}).json()
             for offset in range(3)]
    assert [page["total"] for page in pages] == [2, 2, 2]
    assert [page["results"][0]["id"] for page in pages[:2]] == ["p1", "p2"]
    assert pages[2]["results"] == []
    assert {hit["id"] for hit in pages[0]["results"][0]["matched_evidence"]} == {"c1", "t1", "p1"}
    opted = [client.get("/api/search", params=common | {"offset": offset, "include_reference": "true"}).json()
             for offset in range(4)]
    assert [page["total"] for page in opted] == [3] * 4
    assert [page["results"][0]["id"] for page in opted[:3]] == ["p1", "p2", "c2"]
    assert opted[3]["results"] == []
    assert index.requested_limits == [1000] * 7
