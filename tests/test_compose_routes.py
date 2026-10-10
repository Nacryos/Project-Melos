"""Release V: composer suggestions (backend/compose_routes.py) without the corpus: candidate lines, lint, loop."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import compose_routes as cr
from backend.composer_access import require_owner
from backend.scansion import api as scan_api

FR168B = {"id": "dcc-sappho:frag-118-168:168B", "kind": "text", "language": "grc", "author": "Sappho",
          "citation": "168B", "text": "δέδυκε μὲν ἀ σελάννα\nκαὶ Πληΐαδες· μέσαι δὲ\nνύκτες, παρὰ δ’ ἔρχετ’ ὤρα,\nἔγω δὲ μόνα κατεύδω.",
          "best_line": {"start": 0}}
FR96 = {"id": "digital-sappho:fr96:1", "kind": "text", "language": "grc", "author": "Sappho", "citation": "Fragment 96",
        "text": "]Σαρδ . [ . .]\n2. πόλ]λακι τυίδε̣ [ν]ῶν ἔχοισα\nνῦν δὲ Λῦδαισιν ἐμπρέπεται γυναί-\nκεσσιν ὤς ποτ’ ἀελίω\n"
                "δύντος ἀ βροδοδάκτυλος σελάννα", "best_line": {"start": 46}}


def test_clean_lines_prefer_the_next_line_and_skip_damaged_or_split_lines():
    seen = set()
    rows = cr._clean_lines(FR168B, seen)
    assert rows[0]["greek"] == "καὶ Πληΐαδες· μέσαι δὲ"
    assert rows[0]["basis"] == "follows the matching line"
    assert rows[0]["source"]["citation"] == "168B, line 2 of the stored text"
    assert len(rows) == 4 and len(seen) == 4
    assert cr._clean_lines(FR168B, seen) == []            # nothing twice
    texts = [r["greek"] for r in cr._clean_lines(FR96, set())]
    assert texts == ["δύντος ἀ βροδοδάκτυλος σελάννα"]     # brackets, gaps, a split word and its tail are skipped


@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_search(q, mode, author, limit):
        calls.append((q, author, limit))
        return {"results": [FR168B, FR96] if author else []}

    def fake_headlines(forms, author=""):
        return {"tokens": [{"printed": f, "lemma": None if f == "Πληΐαδες·" else "x"} for f in forms]}

    import backend.server as server  # noqa: F401  (only the attribute is replaced)
    monkeypatch.setattr("backend.server.search_response", fake_search, raising=False)
    monkeypatch.setattr("backend.word_headlines.headlines", fake_headlines)
    monkeypatch.setattr(cr, "_limit", cr.RateLimiter(client_minute=2, client_day=10, connection_minute=10))
    app = FastAPI()
    app.include_router(cr.router)
    app.dependency_overrides[require_owner] = lambda: "owner"   # release W: the routes are owner-only
    c = TestClient(app)
    c.calls = calls
    return c


def test_suggest_lints_each_candidate_and_ranks_failures_last(client):
    r = client.post("/api/compose/suggest", json={"text": "δέδυκε μὲν ἀ σελάννα", "author": "Sappho", "metre": "auto", "k": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generator"]["llm"]["configured"] is False and body["generator"]["proposer"] == "corpus"
    assert body["target"]["dialect"] == "aeolic" and body["target"]["line"] == 2
    cands = body["candidates"]
    assert 1 <= len(cands) <= 3
    for c in cands:
        ids = [k["id"] for k in c["checks"]]
        assert ids == ["L7", "L1", "L2", "L4", "L11"]
        assert c["verdict"] in ("pass", "warn", "fail")
        assert c["source"]["citation"]
    verdicts = [c["verdict"] for c in cands]
    assert verdicts == sorted(verdicts, key=["pass", "warn", "fail"].index)
    assert all(c["greek"] != "δέδυκε μὲν ἀ σελάννα" for c in cands)        # the draft's own line is never offered
    assert body["rounds"] and body["rounds"][0]["scope"] == "Sappho"


def test_suggest_without_author_stops_after_two_rounds_and_validates(client):
    r = client.post("/api/compose/suggest", json={"text": "μῆνιν ἄειδε θεὰ", "metre": "hexameter"})
    assert r.status_code == 200 and r.json()["candidates"] == [] and len(r.json()["rounds"]) == 2
    assert client.post("/api/compose/suggest", json={"text": "x", "metre": "limerick"}).status_code in (422, 429)


def test_suggest_rate_limit_per_forwarded_client(client):
    hdr = {"x-forwarded-for": "203.0.113.9, 198.51.100.7"}
    codes = [client.post("/api/compose/suggest", json={"text": "   "}, headers=hdr).status_code for _ in range(3)]
    assert codes == [422, 422, 429]


def test_status_lists_metres_and_llm_state(client):
    s = client.get("/api/compose/status").json()
    assert "sapphic" in s["metres"] and s["llm"]["configured"] is False and s["llm"]["needs"]


def test_scanner_lexicon_cache_is_bounded():
    from backend.scansion import lexicon
    assert lexicon._lookup_cached.cache_info().maxsize == 50_000
    assert scan_api.MAX_CHARS == 20_000
