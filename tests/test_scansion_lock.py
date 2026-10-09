"""Release V: metre-locked resolution (reader only) and its absence from every composer path."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.reader_scan_routes import scan_passage
from backend.scansion import api as scan_api
from backend.scansion.lock import lock_line
from backend.scansion.quantity import SyllableResult
from backend.scansion.recorded_metres import recorded_metre

ROOT = Path(__file__).resolve().parents[1]
SAPPHO_1 = ("ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα,\nπαῖ Δίος δολόπλοκε, λίσσομαί σε,\n"
            "μή μ’ ἄσαισι μηδ’ ὀνίαισι δάμνα,\nπότνια, θῦμον,")


def unit(i, p):
    return SyllableResult(index=i, line=0, word=i, start=i, end=i + 1, text="α", p_long=p, rule="T", path=[], vowel={})


def test_band_shift_and_clamp_follow_the_owner_rule():
    # adonean -uu-F: positions 1 long, 2-3 short, 4 long, 5 line end (anceps)
    sylls = [unit(0, 0.4), unit(1, 0.7), unit(2, 0.95), unit(3, 0.5), unit(4, 0.5)]
    out = lock_line(sylls, "adonean")
    u = out["units"]
    assert out["template"] == "-uu-F"
    assert u[0]["adjusted"] and u[0]["p_after"] == 0.9                         # 40% where long is required → 90%
    assert u[1]["adjusted"] and u[1]["p_after"] == 0.2                         # 70% where short is required → 20%
    assert "position 2 requires short; 70% → 20%" in u[1]["reason"]
    assert u[2]["conflict"] and not u[2]["adjusted"] and u[2]["p_after"] == 0.95  # outside the band: flagged only
    assert u[3]["p_after"] == 1.0                                                # clamped
    assert u[4]["requires"] == "anceps" and not u[4]["adjusted"] and u[4]["p_after"] == 0.5


def test_recorded_metres_are_sourced_and_narrow():
    assert recorded_metre({"author": "Sappho", "citation": "1", "id": "campbell-glp:sappho:1"})["metre"] == "sapphic"
    assert recorded_metre({"author": "Sappho", "citation": "Fragment 31", "id": "digital-sappho:fr31:1"})["metre"] == "sapphic"
    assert recorded_metre({"author": "Sappho", "citation": "168B", "id": "dcc-sappho:frag-118-168:168B"}) is None
    assert recorded_metre({"author": "Sappho", "citation": "44", "id": "campbell-glp:sappho:44"}) is None
    assert recorded_metre({"author": "Alcaeus", "citation": "1"}) is None
    assert recorded_metre({"author": "Homer", "work": "Iliad", "citation": "1.1"})["metre"] == "hexameter"


def test_reader_scan_locks_a_recorded_poem_and_skips_editorial_lines():
    passage = {"id": "campbell-glp:sappho:1", "author": "Sappho", "citation": "1", "language": "grc",
               "text": SAPPHO_1 + "\nτυίδ’ ἔλθ’, αἴ ποτα [κἀτέρωτα"}
    out = scan_passage(passage)
    assert out["metre"]["metre"] == "sapphic" and out["dialect"] == "aeolic"
    assert out["text"] == passage["text"]
    locked = [line for line in out["lines"] if line["locked"]]
    assert len(locked) >= 3
    assert out["lines"][-1]["editorial"] and not out["lines"][-1]["locked"]
    gap = passage["text"].index("[")
    bracketed = [u for u in out["units"] if u["nucleus"][0] > gap]
    assert bracketed and all(u["editorial"] for u in bracketed)
    assert not any(u["editorial"] for u in out["units"] if u["line"] < 4)
    assert any("metre" in u for u in out["units"])


def test_reader_scan_without_a_recorded_metre_adjusts_nothing():
    out = scan_passage({"id": "x:1", "author": "Alcaeus", "citation": "34a", "language": "grc", "text": SAPPHO_1})
    assert out["metre"] is None and not any("metre" in u for u in out["units"])


def test_composer_paths_never_apply_the_metre_lock():
    # 1. /api/scan (what the composer canvas calls) returns the scanner's own probabilities, never a lock.
    app = FastAPI()
    app.include_router(scan_api.router)
    body = TestClient(app).post("/api/scan", json={"text": SAPPHO_1, "metre": "sapphic", "dialect": "aeolic"}).json()
    plain = scan_api._scanner(None, True, "aeolic").scan(SAPPHO_1)
    assert [u["p_long"] for u in body["units"]] == [round(u.p_long, 3) for u in plain]
    assert not any("metre" in u for u in body["units"]) and "lock" not in body
    # 2. The composer's code never reaches the lock or the reader's passage scan.
    for path in ("backend/compose_routes.py", "backend/scansion/api.py", "js/composer.js"):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert not re.search(r"scansion\.lock|lock_line|recorded_metre|/api/scan/passage|reader_scan", src), path
