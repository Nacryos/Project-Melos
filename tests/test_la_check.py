"""L5 collocation and L6 manner evidence (backend/latin_style.py), the Latin-only checks wired into
composer_lint.check(language="la"), scripts/la_check.py, and the Greek path left as it was.
Needs data/corpus_la.sqlite, data/lemma_index_la.sqlite and the Hypotactic gold; skipped without them."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from backend import composer_lint, latin_backend, latin_lemma, latin_style
from backend.scansion.lexicon_la import LatinQuantityLexicon

ROOT = Path(__file__).resolve().parents[1]
needs_data = pytest.mark.skipif(not latin_style.available() or not latin_style.gold_path().exists()
                                or not LatinQuantityLexicon().available, reason="Latin corpus, lemma index or gold not built")
CATULLUS_1 = "Cui dono lepidum novum libellum\narida modo pumice expolitum?"
NEW_IDS = [cid for cid, *_ in composer_lint.LATIN_CHECKS]


def by_id(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


def la_check_module():
    spec = importlib.util.spec_from_file_location("la_check", ROOT / "scripts" / "la_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------------------------------- L5

@needs_data
def test_collocation_finds_catullus_own_pairs_with_loci():
    c = latin_style.check_collocation(CATULLUS_1)
    assert (c["id"], c["name"], c["blocking"], c["ok"]) == ("L5", "collocation", False, True)
    pairs = {e["pair"]: e for e in c["evidence"] if e["kind"] == "pair"}
    e = pairs["lepidus + libellus"]
    assert e["author"] == "Catullus" and e["same_line"] >= 1 and e["loci"][0]["citation"] == "Carmina 1.1"
    assert all(e["author"] == "Catullus" for e in pairs.values())
    adjacent = {e["words"]: e for e in c["evidence"] if e["kind"] == "adjacent"}
    assert adjacent["novum libellum"]["author"] == "Catullus" and adjacent["novum libellum"]["passages"] >= 1
    base = next(e for e in c["evidence"] if e["kind"] == "baseline")
    assert base["poems"] >= 40 and 0 < base["p10"] < base["median"] < 1


@needs_data
def test_collocation_reports_pairs_without_parallel_and_warns_below_the_held_out_line():
    c = latin_style.check_collocation("flumina ingentia bella proeliorum\nocelle tabernam rosa pumice natat")
    none = [e for e in c["evidence"] if e["kind"] == "pair" and not e["author"]]
    assert none and "without parallel" in c["detail"] and not c["blocking"]
    base = latin_style.collocation_baseline()
    pairs = [e for e in c["evidence"] if e["kind"] == "pair"]
    share = sum(1 for e in pairs if e["author"]) / len(pairs)
    assert c["ok"] is not (len(pairs) >= base["min_pairs"] and share < base["p10"])


# ----------------------------------------------------------------------------------------------- L6

@needs_data
def test_manner_counts_groups_position_and_diminutives():
    c = latin_style.check_manner(CATULLUS_1)
    assert (c["id"], c["name"], c["blocking"], c["ok"]) == ("L6", "manner evidence", False, True)
    w = next(e for e in c["evidence"] if e["kind"] == "word" and e["form"] == "libellum")
    assert w["lemma"] == "libellus" and w["diminutive_of"] == "liber" and w["tokens"]["polymetrics"] >= 3
    assert w["diminutive"] in ("Lewis & Short", "by suffix")
    assert w["start"] == 9 and w["line_final"] and w["position"]["lemma"]["usual_start"] == 9
    assert w["position"]["lemma"]["line_final"] >= 2
    m = {e["marker"]: e for e in c["evidence"] if e["kind"] == "marker"}
    assert m["diminutives"]["draft"] == 1 and 5 < m["diminutives"]["poet_per_100"] < 20
    assert m["vocatives"]["poet_count"] > 100 and m["diminutives"]["poet_lines"] == 552


@needs_data
def test_manner_warns_for_a_lemma_outside_the_polymetrics_and_outside_catullus():
    c = latin_style.check_manner("flumina ingentia facetus proeliorum")
    assert c["ok"] is False and not c["blocking"]
    rows = {e["form"]: e for e in c["evidence"] if e["kind"] == "word"}
    assert "not in the polymetrics" in rows["flumina"]["warning"] and rows["flumina"]["tokens"]["long poems"] >= 1
    assert rows["proeliorum"]["lemma"] == "proelium"            # two unranked readings: the one Catullus uses
    assert "not in Catullus" in rows["facetus"]["warning"] and "not in Catullus: facetus" in c["detail"]


@needs_data
def test_an_unranked_spelling_takes_the_lemma_the_author_uses():
    words = {w["form"]: w for line in latin_style.read_draft("basium osculum") for w in line["words"]}
    assert words["basium"]["lemma"] == "basium"                 # not basis (genitive plural), which Catullus never uses


def test_diminutives_come_from_suffix_and_index():
    if not latin_lemma.available():
        pytest.skip("lemma index not built")
    assert latin_style.diminutive_base("libellus") == "liber" and latin_style.diminutive_base("ocellus") == "oculus"
    assert latin_style.diminutive_base("flosculus") == "flos" and latin_style.diminutive_base("oculus") is None
    assert latin_style.diminutive_base("populus") is None and latin_style.diminutive_base("amo") is None


@needs_data
def test_a_spelling_with_two_lemmas_shows_the_evidence_for_each():
    """bella is bellum (war) and bellus (pretty): beside venusta the adjective leads, and both are counted."""
    data = latin_style.check_manner("non est bella satis? parum venusta?")
    bella = [r for r in data["evidence"] if r.get("kind") == "word" and r["form"] == "bella"]
    assert [r["lemma"] for r in bella][:2] == ["bellus", "bellum"]
    assert bella[0]["tokens"]["polymetrics"] >= 1 and "agrees" in bella[0]["reading"]
    assert bella[1]["alternative_to"] == "bellus" and bella[1]["tokens"]["total"] >= 1
    assert "bella = bellus" in data["detail"]


def test_lewis_and_short_decides_a_diminutive_and_the_suffix_rule_is_the_fallback(monkeypatch):
    if not latin_lemma.available() or latin_style._ls_entries("libellus") in (None, []):
        pytest.skip("lemma index or dictionary not built")
    assert latin_style.diminutive_info("libellus") == ("liber", "Lewis & Short")
    assert latin_style.diminutive_info("misellus") == ("miser", "Lewis & Short")
    for lemma in ("puella", "tabula", "oraculum", "populus"):          # an entry that does not say dim.
        assert latin_style.diminutive_info(lemma) is None
    assert all(how in ("Lewis & Short", "by suffix") for _l, _b, _n, how in latin_style.diminutives())
    monkeypatch.setattr(latin_style, "_ls_entries", lambda lemma: None)   # no dictionary
    latin_style.diminutive_info.cache_clear()
    assert latin_style.diminutive_info("libellus") == ("liber", "by suffix")
    latin_style.diminutive_info.cache_clear()


def test_style_checks_never_raise_and_report_unavailable(monkeypatch):
    monkeypatch.setattr(latin_style, "available", lambda: False)
    for fn, cid in ((latin_style.check_collocation, "L5"), (latin_style.check_manner, "L6")):
        c = fn("Cui dono")
        assert c["id"] == cid and c["ok"] is True and not c["blocking"] and c["detail"].startswith("unavailable:")
    monkeypatch.undo()
    monkeypatch.setattr(latin_style, "read_draft", lambda text: 1 / 0)
    assert latin_style.check_manner("Cui dono")["detail"].startswith("unavailable:")
    assert latin_style.check_collocation("Cui dono")["detail"].startswith("unavailable:")


# ----------------------------------------------------------------------------------------------- the bank

@needs_data
def test_latin_path_returns_the_new_checks_and_a_missing_module_is_unavailable(monkeypatch):
    real = composer_lint._latin_call

    def call(module, function, text, metre_name, author):
        if module == "latin_grammar":
            raise ModuleNotFoundError("No module named 'backend.latin_grammar'")
        if module != "latin_style":
            return {"id": "", "name": "", "ok": True, "blocking": module == "latin_prosody", "detail": f"stub {function}", "evidence": []}
        return real(module, function, text, metre_name, author)

    monkeypatch.setattr(composer_lint, "_latin_call", call)
    r = composer_lint.check(CATULLUS_1, metre_name="phalaecian", author="Catullus", language="la", latin_budget=60)
    ids = [c["id"] for c in r["checks"]]
    assert ids == ["L7", "L1", "L2", "L4", "L11", *NEW_IDS]
    assert by_id(r, "L3")["detail"].startswith("unavailable: ModuleNotFoundError") and by_id(r, "L3")["ok"] is True
    assert by_id(r, "L10")["detail"].startswith("unavailable:") and not by_id(r, "L10")["blocking"]
    assert by_id(r, "L12")["blocking"] and by_id(r, "L12")["name"] == "prosody attestation"
    assert by_id(r, "L5")["ok"] and "content-word pairs" in by_id(r, "L5")["detail"] and r["pass"]
    assert composer_lint.status_of(by_id(r, "L3")) == "unavailable" and composer_lint.status_of(by_id(r, "L7")) == "PASS"
    only = composer_lint.check(CATULLUS_1, metre_name="phalaecian", language="la", latin_budget=60, latin_only={"L5"})
    assert [c["id"] for c in only["checks"]] == ["L7", "L1", "L2", "L4", "L11", "L5"]


@needs_data
def test_a_blocking_latin_check_fails_the_candidate_and_a_timeout_does_not(monkeypatch):
    def call(module, function, text, metre_name, author):
        if function == "check_elision":
            return {"id": "L8", "name": "elision and hiatus", "ok": False, "blocking": True, "detail": "hiatus", "evidence": []}
        if module == "latin_prosody":
            import time
            time.sleep(0.6)
        return {"id": "", "ok": True, "blocking": False, "detail": "stub", "evidence": []}

    monkeypatch.setattr(composer_lint, "_latin_call", call)
    r = composer_lint.check("Vivamus mea Lesbia, atque amemus", metre_name="phalaecian", language="la", latin_budget=0.2)
    assert not r["pass"] and composer_lint.status_of(by_id(r, "L8")) == "FAIL"
    assert by_id(r, "L12")["detail"].startswith("unavailable: timeout") and by_id(r, "L12")["ok"] is True


@needs_data
def test_a_candidate_that_leaves_slots_open_gets_no_whole_line_checks(monkeypatch):
    monkeypatch.setattr(composer_lint, "_latin_call", lambda *a: {"id": "", "ok": True, "blocking": False, "detail": "stub", "evidence": []})
    r = composer_lint.check("mea Lesbia", metre_name="phalaecian", prefix="Vivamus", remaining_template="uu-u-u-F", language="la")
    assert [c["id"] for c in r["checks"]] == ["L7", "L1", "L2", "L4", "L11"]
    r = composer_lint.check("atque amemus", metre_name="phalaecian", prefix="Vivamus mea Lesbia,", remaining_template="u-F", language="la")
    assert [c["id"] for c in r["checks"]][5:] == NEW_IDS


def test_greek_path_is_unchanged(monkeypatch):
    """The Greek bank never starts a Latin-only check and returns the same ids and keys as before."""
    def boom(*a, **k):
        raise AssertionError("a Latin-only check ran on the Greek path")

    monkeypatch.setattr(composer_lint, "latin_checks_start", boom)
    monkeypatch.setattr(composer_lint, "_latin_call", boom)
    r = composer_lint.check("ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα", metre_name="sapphic_hendecasyllable")
    assert [c["id"] for c in r["checks"]] == ["L7", "L1", "L2", "L4", "L11"]
    assert set(r) == {"pass", "scansion", "checks", "budget_ms", "ms"}
    assert set(r["ms"]) == {"L7", "L1", "L2+L4", "L11", "total"}
    assert set(r["scansion"]) == {"language", "dialect", "metre", "remaining_template", "template", "lines", "fit"}
    assert r["scansion"]["language"] == "grc"
    for c in r["checks"]:
        assert set(c) - {"template"} == {"id", "name", "ok", "blocking", "detail", "evidence"}


# ----------------------------------------------------------------------------------------------- the command

@needs_data
def test_la_check_prints_scansion_then_checks_and_exits_by_blocking_failure(capsys, monkeypatch):
    la = la_check_module()
    stub = {"id": "", "ok": True, "blocking": False, "detail": "stub", "evidence": []}
    real = composer_lint._latin_call
    monkeypatch.setattr(composer_lint, "_latin_call",
                        lambda m, f, *a: real(m, f, *a) if m == "latin_style" else dict(stub))
    assert la.main([CATULLUS_1.replace("\n", "\\n")]) == 0
    out = capsys.readouterr().out
    assert "PASS (no blocking failure)" in out and " 1  Cui dono lepidum novum libellum" in out
    assert "| " in out and "–" in out and "fits" in out
    assert out.index("WARN        L11") < out.index("PASS        L7")
    assert "L5   collocation" in out and "L6   manner evidence" in out
    assert la.main(["blorpus mea Lesbia atque amemus", "--only", "L1,L7", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert "L1" in data["blocking_failures"] and {c["id"] for c in data["checks"]} == {"L1", "L7"}
    assert all(c["status"] in ("PASS", "WARN", "FAIL", "unavailable") for c in data["checks"])


def test_la_check_scansion_rows_mark_elision_and_bars():
    la = la_check_module()
    line = {"syllables": [{"text": t, "label": l} for t, l in
                          [("ar", "L"), ("id", "S"), ("a m", "A"), ("od", "S"), ("o p", "A"), ("um", "L"), ("ic", "S"),
                           ("e", "E"), ("exp", "L"), ("ol", "S"), ("it", "L"), ("um", "S")]]}
    top, bottom = la.scansion_rows(line, {"ok": True, "pattern": "–⏑–⏑⏑–⏑–⏑–⏑"}, "phalaecian")
    assert top == "a ri | da mo do pu | mi c(e) ex po li tum"            # true syllables, the elided vowel in brackets
    assert bottom.replace(" ", "") == "–⏑|–⏑⏑–|⏑–⏑–⏑" and top.index("|") == bottom.index("|")
    assert [i for i, ch in enumerate(bottom) if ch == "|"] == [i for i, ch in enumerate(top) if ch == "|"]


def test_true_syllables_divide_as_latin_does():
    la = la_check_module()
    units = lambda *ts: [{"text": t, "label": "L"} for t in ts]
    assert [c for c, _ in la.true_syllables(units("Cui d", "on", "o l", "ep", "id", "um n", "ov", "um"))] == \
        ["Cui", "do", "no", "le", "pi", "dum", "no", "vum"]
    assert [c for c, _ in la.true_syllables(units("atr", "is, qu", "inqu", "e", "aqu", "ae"))] == ["a", "tris", "quin", "que", "a", "quae"]
    assert [c for c, _ in la.true_syllables(units("ell", "exp", "ulchr", "a"))] == ["el", "lex", "pul", "chra"]


@needs_data
def test_la_check_brief_is_the_scansion_and_one_line_per_check(capsys, monkeypatch):
    la = la_check_module()
    monkeypatch.setattr(composer_lint, "_latin_call", lambda *a: {"id": "", "ok": True, "blocking": False, "detail": "x" * 400, "evidence": [{"a": 1}]})
    assert la.main(["an nostros metuis, miselle, risus?", "--brief"]) == 0
    out = capsys.readouterr().out.split("\n")
    assert out[3].strip() == "an nos | tros me tu is | mi sel le ri sus" and out[4].rstrip().endswith("fits")
    checks = [l for l in out if l.startswith(("PASS", "WARN", "FAIL", "unavailable"))]
    assert len(checks) == 5 + len(NEW_IDS) and not any(l.lstrip().startswith("- ") for l in out)
    assert all(len(l) <= 38 + la.BRIEF_DETAIL for l in checks)


# ----------------------------------------------------------------------------------------------- the routes

@pytest.fixture()
def la_app():
    from fastapi import FastAPI
    from backend import latin_routes
    app = FastAPI()
    app.include_router(latin_routes.router)
    return app, latin_routes.require_owner_or_agent


LA_ROUTES = [
    ("post", "/api/la/check", {"text": "Cui dono lepidum novum libellum / arida modo pumice expolitum?"}, {"pass", "blocking_failures", "lines", "checks", "ms"}),
    ("get", "/api/la/prosody", {"form": "modo"}, {"form", "patterns"}),
    ("get", "/api/la/dictionary", {"q": "lepidus"}, {"q", "entries"}),
    ("get", "/api/la/reverse", {"q": "sparrow", "limit": 5}, {"q", "headwords"}),
    ("get", "/api/la/commentary", {"poem": "1", "line": 1}, {"poem", "notes"}),
    ("get", "/api/la/commentary", {"q": "pumice"}, {"q", "notes"}),
    ("get", "/api/la/grammar", {"section": "540"}, {"section", "text"}),
    ("get", "/api/la/grammar", {"q": "sequence of tenses", "limit": 3}, {"q", "sections"}),
]


def _ask(client, method, path, params):
    return client.post(path, json=params) if method == "post" else client.get(path, params=params)


@pytest.mark.parametrize("method,path,params,keys", LA_ROUTES)
def test_la_routes_need_the_owner_or_the_agent(la_app, monkeypatch, method, path, params, keys):
    from fastapi.testclient import TestClient
    for name in ("MELOS_OWNER_TOKEN", "MELOS_AGENT_TOKEN", "MELOS_DEV_AUTH", "MELOS_AUTH_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    app, _dep = la_app
    assert _ask(TestClient(app), method, path, params).status_code in (401, 403, 404)


@needs_data
@pytest.mark.parametrize("method,path,params,keys", LA_ROUTES)
def test_la_routes_answer_with_the_expected_keys(la_app, method, path, params, keys):
    from fastapi.testclient import TestClient
    app, dep = la_app
    app.dependency_overrides[dep] = lambda: "owner"
    r = _ask(TestClient(app), method, path, params)
    if r.status_code == 503:
        pytest.skip(f"store not built: {r.json()}")
    assert r.status_code == 200 and keys <= set(r.json())
    if path == "/api/la/check":
        d = r.json()
        assert d["pass"] and [c["id"] for c in d["checks"]][0] == "L11" and len(r.text) < 10000       # WARN first; fits a tool result
        assert all(set(c) == {"id", "name", "status", "blocking", "detail", "evidence", "evidence_rows"} for c in d["checks"])


@needs_data
def test_la_check_route_rejects_an_unknown_field_and_keeps_only_the_checks_asked_for(la_app):
    from fastapi.testclient import TestClient
    app, dep = la_app
    app.dependency_overrides[dep] = lambda: "owner"
    c = TestClient(app)
    assert c.post("/api/la/check", json={"text": "Cui dono", "nope": 1}).status_code == 422
    r = c.post("/api/la/check", json={"text": "Cui dono lepidum novum libellum", "only": "L5,L7", "evidence": 0})
    assert {x["id"] for x in r.json()["checks"]} == {"L5", "L7"}
