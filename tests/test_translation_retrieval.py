"""Synthetic mechanics fixtures only; no literary text or attribution claims."""
from copy import deepcopy

import pytest

from backend import server
from backend.retrieval import fuse
from backend.semantic import SemanticIndex
from scripts.build_embeddings import build, source_rows
from test_api import client  # shared isolated synthetic corpus
from test_semantic import FakeEncoder


def row(identifier, **changes):
    return {"id": identifier, "author": "Fixture Translator", "work": "Fixture translation",
            "citation": identifier, "text": "sea fixture " + identifier,
            "kind": "translation", "language": "ell", "quality": "source_text",
            "edition": "Translation edition", **changes}


ROWS = [
    row("greek-parent", kind="text", language="grc", author="Ibycus", text="Greek fixture", edition="Greek edition"),
    row("linked", parent_id="greek-parent"),
    row("orphan", parent_id="missing"),
    row("page-only", metadata={"scope": "page"}),
    row("unrelated", parent_id="p3"),  # fixture parent is Beta, not Ibycus
    row("non-greek-parent", kind="text", language="eng", author="Ibycus"),
    row("non-greek-linked", parent_id="non-greek-parent"),
    row("excluded-parent", kind="text", language="grc", author="Ibycus", quality="needs_review"),
    row("excluded-linked", parent_id="excluded-parent"),
]


@pytest.mark.parametrize("client", [ROWS], indirect=True)
@pytest.mark.parametrize("mode", ["words", "forms", "themes", "hybrid"])
def test_translation_author_scope_in_all_retrieval_channels(client, monkeypatch, tmp_path, mode):
    """Real fake-encoder index + SQL + fusion, not a model network request."""
    directory = server.DB.parent / "translation-index"
    build(server.DB, directory, encoder=FakeEncoder())
    index = SemanticIndex(directory)
    index._model = FakeEncoder()
    monkeypatch.setattr(server, "semantic_service", lambda: index)
    response = client.get("/api/search", params={"q": "sea", "mode": mode,
                          "author": "Ibycus", "language": "ell", "match": "exact"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert {item["id"] for item in results} == {"linked"}
    assert results[0]["author"] == "Fixture Translator"
    assert "explicit Greek parent" in results[0]["author_scope_reason"]
    assert not client.get("/api/search", params={"q": "sea", "mode": mode,
        "author": "Ibycus", "language": "lat", "match": "exact"}).json()["results"]


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_ell_embedding_scope_requires_explicit_eligible_greek_parent(client, tmp_path):
    records = {record["id"]: record for record in source_rows(server.DB)}
    assert records["linked"]["context_authors"] == ["Ibycus"]
    assert records["linked"]["author"] == "Fixture Translator"
    for identifier in ("orphan", "page-only", "non-greek-linked", "excluded-linked"):
        assert records[identifier]["context_authors"] == []
    assert records["unrelated"]["context_authors"] == ["Beta"]
    directory = server.DB.parent / "translation-index"
    build(server.DB, directory, encoder=FakeEncoder())
    index = SemanticIndex(directory)
    index._model = FakeEncoder()
    hits = index.search("sea", author="Ibycus", language="ell")
    assert [hit["id"] for hit in hits] == ["linked"]
    assert hits[0]["match_reason"] == "Translation embedding"


@pytest.mark.parametrize("language,edition,expected", [
    ("", "", "g"), ("grc", "", "g"), ("ell", "", "t"),
    ("ell", "Translation edition", "t"), ("ell", "Greek edition", None),
    ("eng", "", None), ("grc", "Translation edition", None),
])
def test_fusion_projection_obeys_returned_record_constraints(language, edition, expected):
    records = {
        "g": row("g", author="Ibycus", kind="text", language="grc", edition="Greek edition"),
        "t": row("t", parent_id="g"),
    }
    before = deepcopy(records)
    result = fuse("sea", [records["t"]], [], [{"id": "t"}], records.get,
                  author="Ibycus", language=language, edition=edition)
    assert [item["id"] for item in result["results"]] == ([expected] if expected else [])
    assert records == before
    if expected:
        assert result["results"][0]["matched_evidence"][0]["author"] == "Fixture Translator"


@pytest.mark.parametrize("changes", [
    {"parent_id": None}, {"parent_id": "missing"}, {"parent_id": "other"},
    {"quality": "needs_review"}, {"kind": "text"},
])
def test_fusion_does_not_infer_parent_author(changes):
    records = {"g": row("g", author="Ibycus", kind="text", language="grc"),
               "other": row("other", author="Other", kind="text", language="grc"),
               "t": row("t", parent_id="g") | changes}
    assert not fuse("sea", [records["t"]], [], [], records.get,
                    author="Ibycus", language="ell")["results"]
    assert not fuse("sea", [records["t"]], [], [], records.get,
                    author="Ibycus", language="ell", commentary_assisted=False)["results"]


REFERENCE_ROWS = [dict(record, citation="fr. 286") for record in ROWS] + [
    row("other-fragment", parent_id="greek-parent", citation="fr. 287"),
    row("body-only-number", parent_id="greek-parent", citation="other", text="mentions 286"),
]


@pytest.mark.parametrize("client", [REFERENCE_ROWS], indirect=True)
@pytest.mark.parametrize("query,selected_author", [("Ibycus 286", ""), ("286", "Ibycus")])
def test_reference_navigation_retains_translation_identity(client, query, selected_author):
    params = {"q": query, "author": selected_author, "language": "ell"}
    result = client.get("/api/search", params=params).json()
    assert result["mode"] == "reference"
    assert [item["id"] for item in result["results"]] == ["linked"]
    item = result["results"][0]
    assert item["author"] == "Fixture Translator"
    assert item["reference_match"]["coverage"] == "translation"
    assert "explicit Greek parent" in item["author_scope_reason"]
    assert not client.get("/api/search", params=params | {"edition": "Greek edition"}).json()["results"]
    assert not client.get("/api/search", params=params | {"language": "lat"}).json()["results"]
    assert not client.get("/api/search", params={"q": "Ibycus 286", "author": "Sappho", "language": "ell"}).json()["results"]


@pytest.mark.parametrize("client", [REFERENCE_ROWS], indirect=True)
@pytest.mark.parametrize("mode", ["words", "forms", "hybrid", "reference"])
def test_include_reference_parent_quality_policy_is_consistent(client, monkeypatch, mode):
    class UnavailableSemantic:
        def search(self, *args, **kwargs):
            raise RuntimeError("Synthetic test has no semantic index")
    monkeypatch.setattr(server, "semantic_service", lambda: UnavailableSemantic())
    params = {"q": "286" if mode == "reference" else "sea", "author": "Ibycus", "language": "ell",
              "mode": "words" if mode == "reference" else mode, "match": "exact"}
    ordinary = client.get("/api/search", params=params).json()
    expanded = client.get("/api/search", params=params | {"include_reference": "true"}).json()
    assert "excluded-linked" not in {item["id"] for item in ordinary["results"]}
    assert "excluded-linked" in {item["id"] for item in expanded["results"]}
    assert not ({"orphan", "page-only", "unrelated", "non-greek-linked"} &
                {item["id"] for item in expanded["results"]})
