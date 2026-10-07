"""The passage warm route caches parser analyses a few forms at a time."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.passage_routes import create_router


class FakeMachine:
    def __init__(self, known):
        self.known, self.cache, self.fetches = known, {}, []

    def analyze(self, form, visitor_id, fetch=True):
        if form in self.cache:
            return self.cache[form]
        if not fetch:
            return {"status": "cache_miss", "form": form, "machine_candidates": []}
        self.fetches.append(form)
        result = {"status": "ok" if form in self.known else "no_analyses", "form": form,
                  "machine_candidates": [{"lemma": form}] if form in self.known else []}
        self.cache[form] = result
        return result


def client(machine, text="ῤήα δ’ ἀνθρώποι[ς] θα[ν]άτω ῤύεσθε"):
    passage = {"id": "synthetic:warm", "kind": "text", "language": "grc", "text": text}
    app = FastAPI()
    app.include_router(create_router(lambda identifier: passage if identifier == passage["id"] else None,
                                     lambda form, identifier: {}, machine_service=machine))
    return TestClient(app), passage


def test_warm_fetches_each_printed_reading_once_and_tries_variants_for_unknown_forms():
    machine = FakeMachine({"δ’", "ἀνθρώποις", "θανάτω", "ῥήα", "ῥύεσθε"})
    api, passage = client(machine)
    first = api.post("/api/passage-morphology/warm", json={"passage_id": passage["id"]}).json()
    assert first["status"] == "ok" and first["forms"] == 5
    # The editor's readings are queried, never the bracketed printed strings;
    # the psilotic forms fall back to their labelled normalisations.
    assert "ἀνθρώποις" in machine.fetches and "θανάτω" in machine.fetches
    assert "ῤήα" in machine.fetches and "ῥήα" in machine.fetches
    assert first["statuses"].get("variant:ok") == 2
    second = api.post("/api/passage-morphology/warm", json={"passage_id": passage["id"]}).json()
    assert second["fetched"] == 0 and len(machine.fetches) == first["fetched"]


def test_warm_is_bounded_and_reports_the_remainder():
    machine = FakeMachine({"α", "β", "γ"})
    api, passage = client(machine, "α β γ δ ε")
    out = api.post("/api/passage-morphology/warm", json={"passage_id": passage["id"], "max_fetches": 2}).json()
    assert out["fetched"] == 2 and out["missing"] >= 3
    assert api.post("/api/passage-morphology/warm", json={"passage_id": "missing"}).status_code == 404
    assert api.post("/api/passage-morphology/warm", json={"passage_id": passage["id"], "max_fetches": 99}).status_code == 422


def test_warm_without_a_machine_service_is_unavailable():
    api, passage = client(None)
    assert api.post("/api/passage-morphology/warm", json={"passage_id": passage["id"]}).json()["status"] == "unavailable"
