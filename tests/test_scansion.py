"""Tests for the metre-free scanner (backend/scansion). The core tests need no data files; the
lexical-hook tests are skipped when data/scansion/quantities.sqlite is absent."""
from __future__ import annotations

import time

import pytest

from backend.scansion import engine, metre
from backend.scansion.lexicon import QuantityLexicon
from backend.scansion.quantity import Scanner
from backend.scansion.syllabify import nuclei_of, words_of

CORE = Scanner(lexicon=None)
LEX = QuantityLexicon()
needs_lexicon = pytest.mark.skipif(not LEX.available, reason="quantity lexicon not built")


def units(text, sc=CORE):
    return [(u.text, round(u.p_long, 2), u.rule, u.vowel["rule"]) for u in sc.scan(text)]


def unit(text, piece, sc=CORE):
    """The unit whose text (or whose text without the line's initial consonants) is `piece`."""
    out = sc.scan(text)
    for u in out:
        if u.text.strip() == piece or text[u.nstart:u.end].strip() == piece:
            return u
    raise AssertionError(f"{piece!r} not among {[u.text for u in out]}")


# --- syllabification ------------------------------------------------------------------------------
def test_diphthongs_diaeresis_and_breathing_on_first_vowel():
    w = words_of("Πηληϊάδεω ἀίω αἰεί")
    kinds = [[n.kind for n in nuclei_of(x)] for x in w]
    assert kinds[0] == ["long", "long", "dichronon", "dichronon", "short", "long"]   # ϊ breaks ηι
    assert kinds[1] == ["dichronon", "dichronon", "long"]                            # ἀί: two vowels
    assert kinds[2] == ["diphthong", "diphthong"]


def test_units_are_nucleus_plus_following_consonants_across_words():
    assert [u.text for u in CORE.scan("πολλὰς δ’ ἰφθίμους")] == ["πολλ", "ὰς δ’", "ἰφθ", "ίμ", "ους"]


def test_elision_mark_inside_a_token_splits_the_words():
    assert [(w.text, w.elided) for w in words_of("δ᾽ἄλοχος")] == [("δ᾽", True), ("ἄλοχος", False)]


def test_written_crasis_is_one_long_unit():
    u = unit("ὠράνωἴθε", "ωἴθ")
    assert u.p_long == 1.0 and u.vowel["rule"] == "CRA-1"


def test_iota_adscript():
    assert unit("τῶι λόγωι", "ῶι λ").vowel["rule"] == "NAT-ISUB"


# --- the decision tree ----------------------------------------------------------------------------
def test_nature_and_position():
    assert unit("μῆνιν", "ῆν").p_long == 1.0                          # circumflex
    assert unit("ἐπὶ", "ἐπ").p_long == 0.0                            # ε before one consonant
    assert unit("τὸν δὲ", "ὸν δ").rule == "POS-ACROSS"                # ν | δ across the boundary
    assert unit("ἄλλος", "ἄλλ").rule == "POS-WORD"
    assert unit("τὸ ξίφος", "ὸ ξ").p_long == 1.0                      # double consonant opens next word


def test_muta_cum_liquida_is_its_own_tunable_node():
    u = unit("πατρός", "ατρ")
    assert u.rule == "MCL-WORD" and 0.4 <= u.p_long <= 0.8
    tuned = Scanner(params={"mcl_word": 1.0})
    assert unit("πατρός", "ατρ", tuned).p_long == 1.0


def test_hiatus_correption_is_one_explicit_node():
    u = unit("καὶ ἐγώ", "αὶ")
    assert u.rule == "COR-EXT" and u.p_long == pytest.approx(0.5)


def test_accent_rules_resolve_dichrona_without_a_lexicon():
    assert unit("φίλος", "ίλ").vowel["rule"] == "ACC-PAROX-SHORT"      # Smyth §170
    assert CORE.scan("θάλαττα")[-1].vowel["rule"] == "ACC-PROPAROX"
    assert CORE.scan("Μοῦσα")[-1].vowel["rule"] == "ACC-PROPERISP"


def test_enclitic_compound_keeps_accent_rules_off():
    u = unit("οὔτις ἀνδρῶν", "ις")
    assert not u.vowel["rule"].startswith("ACC-")


def test_unknown_dichronon_uses_the_tunable_default():
    u = unit("ἀγαθός", "ἀγ")
    assert u.vowel["rule"] == "DICH-UNK" and u.p_long == pytest.approx(CORE.grammar.params["dichronon_default"])


def test_line_end_is_flagged_not_decided_by_the_tree():
    last = CORE.scan("ἔλθε μοι")[-1]
    assert any(f["id"] == "FIN-ANC" for f in last.flags)


def test_synizesis_candidate_is_flagged():
    u = unit("Πηληϊάδεω", "ε")
    assert any(f["id"] == "SYN-CAND" for f in u.flags)


def test_every_unit_has_a_reason_with_a_rule_id_and_citation():
    for u in CORE.scan("ἄριστον μὲν ὕδωρ, ὁ δὲ χρυσὸς αἰθόμενον πῦρ"):
        assert u.reasons and all(r["id"] and r["cite"] for r in u.reasons)


def test_prose_is_scanned_too():
    out = CORE.scan("ἐπεὶ δὲ ὡς πρὸς εἰσαγωγὴν τῶν ἀρχομένων παιδεύεσθαι χρήσιμος ἡ πολυπειρία")
    assert len(out) > 20 and all(0 <= u.p_long <= 1 for u in out)


# --- the rules file -------------------------------------------------------------------------------
def test_default_rules_load_without_errors():
    g, errors = engine.load()
    assert errors == [] and g.vowel and g.unit


def test_rules_validation_reports_problems():
    bad = """
version: 1
params: {x: 2}
vowel:
  - id: A
    when: nucleus == "long" and open(1)
    p: 1
    reason: r
    cite: c
unit:
  - id: A
    when: not_a_feature
    p: 0.5
    reason: r
    cite: c
"""
    g, errors = engine.load(text=bad)
    assert g is None
    text = "\n".join(errors)
    assert "params.x" in text and "not allowed" in text and "unknown name `not_a_feature`" in text
    assert "duplicate id A" in text


def test_expression_language_cannot_reach_python():
    with pytest.raises(engine.RuleError):
        engine.Expr("__import__('os')", set(engine.FEATURES))
    with pytest.raises(engine.RuleError):
        engine.Expr("nucleus.upper()", set(engine.FEATURES))


# --- lexical hook ---------------------------------------------------------------------------------
@needs_lexicon
def test_lexicon_overrides_the_dichronon_default():
    sc = Scanner(lexicon=LEX)
    assert sc.scan("ψυχὰς")[0].vowel["rule"].startswith("LEX-L")


@needs_lexicon
def test_aeolic_selanna_final_alpha_is_long():
    """Composer exercise (docs/composer/exercise-log.md): νῦν σελάννα, ᾱ where Attic has σελήνη."""
    sc = Scanner(lexicon=LEX, dialect="aeolic")
    last = sc.scan("νῦν σελάννα")[-1]
    assert last.vowel["p_long"] >= 0.9


@needs_lexicon
def test_dialect_alpha_for_eta_needs_a_stated_dialect():
    on = Scanner(lexicon=LEX, dialect="doric")
    off = Scanner(lexicon=LEX)
    # λᾱθικᾱδής-type words: only the dialect statement licenses the η-correspondence
    a = [u.vowel["rule"] for u in on.scan("δάκτυλος ἀμέρα")]
    b = [u.vowel["rule"] for u in off.scan("δάκτυλος ἀμέρα")]
    assert "DIA-ETA" not in b
    assert a[-1] in ("DIA-ETA", "LEX-L")


# --- metre layer ----------------------------------------------------------------------------------
def test_hexameter_fit_with_synizesis():
    f = metre.fit_line(CORE.scan("μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος"), "hexameter")
    assert f.ok and f.pattern.startswith("–⏑⏑–⏑⏑–––⏑⏑–⏑⏑")


def test_sapphic_line_fits_and_auto_detect_ranks_it_first():
    line = CORE.scan("φαίνεταί μοι κῆνος ἴσος θέοισιν")
    assert metre.fit_line(line, "sapphic_hendecasyllable").ok
    assert metre.auto([line])[0]["metre"] == "sapphic_hendecasyllable"


def test_a_wrong_line_reports_where_it_fails():
    f = metre.fit_line(CORE.scan("μῆνιν ἄειδε θεὰ Ἀχιλῆος"), "hexameter")
    assert not f.ok and f.message


def test_responsion_resolves_an_ambiguous_syllable():
    a = CORE.scan("ἀγαθὸς ἔφη")      # ἀ- unknown dichronon
    b = CORE.scan("ἐκέλευσε τὸν")    # ἐ- certain short
    r = metre.responsion([a], [b])[0]
    assert r["strophe_posterior"][0] < 0.5


# --- speed ----------------------------------------------------------------------------------------
def test_one_line_well_under_50_ms():
    sc = Scanner(lexicon=LEX if LEX.available else None)
    line = "ἄριστον μὲν ὕδωρ, ὁ δὲ χρυσὸς αἰθόμενον πῦρ"
    sc.scan(line)  # warm the rules file and the database handle
    t0 = time.perf_counter()
    sc.scan("ἅτε διαπρέπει νυκτὶ μεγάνορος ἔξοχα πλούτου·")
    assert (time.perf_counter() - t0) * 1000 < 50


# --- HTTP contract --------------------------------------------------------------------------------
def test_post_api_scan_contract():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.scansion.api import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    r = c.post("/api/scan", json={"text": "μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος", "metre": "hexameter", "lexicon": False})
    assert r.status_code == 200
    body = r.json()
    assert {"units", "lines", "fit", "ms"} <= set(body)
    u = body["units"][0]
    assert {"start", "end", "p_long", "label", "rule", "reasons", "flags", "vowel"} <= set(u)
    assert body["fit"][0]["ok"]
    assert c.post("/api/scan", json={"text": "λόγος", "metre": "nonsense"}).status_code == 422
    assert c.post("/api/scan", json={"text": "λόγος", "params": {"mcl_word": 3}}).status_code == 422
    resp = c.post("/api/scan", json={"text": "ἀγαθὸς ἔφη", "responsion_with": "ἐκέλευσε τόν", "lexicon": False}).json()
    assert resp["responsion"]["lines"][0]["strophe_posterior"][0] < 0.5
