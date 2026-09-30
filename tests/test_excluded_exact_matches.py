"""Synthetic coverage notices: counts are lexical diagnostics, not attestations."""
import pytest

from backend import server
from test_api import client  # shared isolated synthetic corpus fixture


def sample(identifier, **changes):
    return {"id": identifier, "author": "Alpha", "work": "Synthetic Coverage",
            "citation": identifier, "text": "αβγδε", "quality": "needs_review",
            "edition": "Synthetic coverage edition", **changes}


ROWS = [
    sample("visible-exact", quality="source_text"),
    sample("hidden-review"),
    sample("hidden-ocr", quality="machine_ocr"),
    sample("hidden-citation", citation="αβγδε", text="unrelated synthetic fixture"),
    sample("hidden-reference", kind="reference", quality="source_text"),
    sample("wrong-author", author="Beta"),
    sample("wrong-language", language="eng"),
    sample("wrong-edition", edition="Other synthetic edition"),
    sample("fuzzy-only", text="αβγδζ"),
    sample("substring-only", text="παρααβγδε"),
    sample("expanded-only", text="ζωή"),
]
PARAMS = {"q": "αβγδε", "author": "Alpha", "language": "grc",
          "edition": "Synthetic coverage edition", "match": "exact"}


def check_notice(result):
    notice = result["excluded_exact_matches"]
    assert notice["total"] == 4
    assert {(group["quality"], group["kind"], group["count"]) for group in notice["groups"]} == {
        ("needs_review", "text", 2), ("machine_ocr", "text", 1), ("source_text", "reference", 1)}
    assert "Exact normalized wording/citation only" in notice["method"]
    assert "excludes fuzzy, morphological and semantic matches" in notice["method"]


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_hidden_exact_count_respects_all_filters_and_never_calls_morphology(client, monkeypatch):
    def forbidden():
        raise AssertionError("A lexical coverage count must not ask a morphological model")
    monkeypatch.setattr(server, "morph_service", forbidden)
    monkeypatch.setattr(server, "semantic_service", forbidden)
    result = client.get("/api/search", params=PARAMS | {"mode": "words"}).json()
    assert [r["id"] for r in result["results"]] == ["visible-exact"]
    check_notice(result)


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_reference_toggle_includes_exact_records_and_removes_notice(client):
    result = client.get("/api/search", params=PARAMS | {"include_reference": "true"}).json()
    assert "excluded_exact_matches" not in result
    assert {r["id"] for r in result["results"]} == {
        "visible-exact", "hidden-review", "hidden-ocr", "hidden-citation", "hidden-reference"}
    assert next(r for r in result["results"] if r["id"] == "hidden-review")["quality"] == "needs_review"


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_zero_hidden_count_has_no_notice_and_theme_search_does_not_claim_coverage(client, monkeypatch):
    result = client.get("/api/search", params=PARAMS | {"q": "αβχψω"}).json()
    assert "excluded_exact_matches" not in result
    class Sem:
        def search(self, *args, **kwargs):
            return []
    monkeypatch.setattr(server, "semantic_service", lambda: Sem())
    thematic = client.get("/api/search", params=PARAMS | {"mode": "themes"}).json()
    assert "excluded_exact_matches" not in thematic


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_form_expansion_does_not_enlarge_exact_coverage_count(client, monkeypatch):
    calls = []
    class Morph:
        def analyze(self, form, limit=6):
            calls.append(form)
            return {"candidates": [], "expansion_lemmas": ["synthetic-lemma"], "warnings": []}
        def expansion_forms_for_lemma(self, lemma):
            return ["ζωή"]
    monkeypatch.setattr(server, "morph_service", lambda: Morph())
    result = client.get("/api/search", params=PARAMS | {"mode": "forms", "match": "fuzzy"}).json()
    check_notice(result)
    assert calls == ["αβγδε"]


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_hybrid_notice_uses_final_filters_not_broader_evidence_pool(client, monkeypatch):
    class Sem:
        def search(self, *args, **kwargs):
            return [{"id": "wrong-edition", "score": .99}, {"id": "fuzzy-only", "score": .98}]
    class Morph:
        def analyze(self, form, limit=6):
            return {"candidates": [], "expansion_lemmas": [], "warnings": []}
    monkeypatch.setattr(server, "semantic_service", lambda: Sem())
    monkeypatch.setattr(server, "morph_service", lambda: Morph())
    result = client.get("/api/search", params=PARAMS | {"mode": "hybrid"}).json()
    check_notice(result)
    assert [r["id"] for r in result["results"]] == ["visible-exact"]
    expanded = client.get("/api/search", params=PARAMS | {"mode": "hybrid", "include_reference": "true"}).json()
    assert "excluded_exact_matches" not in expanded
    assert "hidden-review" in {r["id"] for r in expanded["results"]}
    assert "wrong-edition" not in {r["id"] for r in expanded["results"]}


@pytest.mark.parametrize("client", [ROWS], indirect=True)
def test_publication_restricted_records_are_not_disclosed_in_counts(client, monkeypatch):
    monkeypatch.setenv("MELOS_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.delenv("MELOS_PUBLICATION_POLICY", raising=False)
    # Synthetic-test-source has no publication allowlist entry. Neither text
    # nor its existence/count should leak through the new diagnostic path.
    result = client.get("/api/search", params=PARAMS).json()
    assert result["results"] == []
    assert "excluded_exact_matches" not in result
