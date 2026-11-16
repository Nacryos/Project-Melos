"""Tests for the Phalaecian manner (L13) and elision / hiatus (L8) checks (backend/latin_metre_style.py) and the
profile they read (scripts/build_phalaecian_profile.py). The feature reader needs no data files; the checks on drafts
need the profile and the quantity lexicon and are skipped without them."""
from __future__ import annotations

import pytest

from backend import latin_metre_style as style
from backend.scansion.lexicon_la import LatinQuantityLexicon

HAVE_DATA = style.profile() is not None and LatinQuantityLexicon().available
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="needs the Phalaecian profile and the Latin quantity lexicon")
KEYS = {"id", "name", "ok", "blocking", "detail", "evidence"}


def word(form, pattern, flags=None):
    return {"form": form, "syl": [{"t": form, "q": q, "f": (flags or {}).get(i, [])} for i, q in enumerate(pattern)]}


# --- the feature reader (gold shape) ----------------------------------------------------------------
def test_features_of_a_plain_line():
    # cui dono lepidum novum libellum: spondaic base, word-ends after 1, 3, 6, 8
    f = style.line_features([word("cui", "L"), word("dōnō", "LL"), word("lepidum", "SSL"), word("novum", "SL"),
                             word("libellum", "SLL")])
    assert f["sounded"] == 11 and f["base"] == "spondee"
    assert f["word_ends"] == [1, 3, 6, 8] and f["break"] == "6th"
    assert f["final_word"] == {"form": "libellum", "syllables": 3, "prodelided_est": False}
    assert not f["elisions"] and ("elisions:0", "0 elisions in the line") in f["keys"]


def test_features_elision_kinds_and_position():
    # vīvāmus, mea Lesbia, atque amēmus: two elisions, at the 8th and the 9th; the word-end after Lesbi(a) is bridged
    f = style.line_features([word("vīvāmus,", "LLS"), word("mea", "SS"), word("Lesbia,", "LSE"), word("atque", "LE"),
                             word("amēmus", "SLL")])
    assert [(e["word"], e["at"], e["kind"]) for e in f["elisions"]] == [("Lesbia,", 8, "short vowel"), ("atque", 9, "short vowel")]
    assert f["word_ends"] == [3, 5] and f["word_ends_elided"] == [7, 8] and f["break"] == "5th"
    assert style.elided_kind("Catullō") == "long vowel or diphthong" and style.elided_kind("quantum") == "-m"
    assert style.elided_kind("meae") == "long vowel or diphthong" and style.elided_kind("atque") == "short vowel"


def test_features_prodelision_is_not_an_elision_and_makes_no_word_end():
    # et quantum est hominum venustiōrum (3.2): the gold writes -tum E, est long
    f = style.line_features([word("et", "L"), word("quantum", "LE"), word("est", "L"), word("hominum", "SSL"),
                             word("venustiōrum:", "SLSLL")])
    assert not f["elisions"] and [(e["word"], e["at"], e["kind"]) for e in f["prodelisions"]] == [("quantum", 3, "-m")]
    assert f["word_ends"] == [1, 3, 6]
    g = style.line_features([word("nōn", "L"), word("bellē", "LL"), word("ūteris", "LSS"), word("in", "L"),
                             word("jocō", "SL"), word("molestum", "SLE"), word("est", "L")])
    assert g["final_word"] == {"form": "molestum est", "syllables": 3, "prodelided_est": True}


def test_features_hiatus_kinds_and_iambic_base():
    f = style.line_features([word("ō", "L"), word("factum", "LL"), word("male!", "SS", {1: ["hiatus"]}), word("ō", "L"),
                             word("miselle", "SLS"), word("passer!", "LL")])
    assert [h["kind"] for h in f["hiatus"]] == ["beside an interjection"]
    g = style.line_features([word("malēst,", "SL"), word("mē", "E"), word("hercule,", "LSS", {2: ["hiatus"]}),
                             word("et", "L"), word("labōriōsē,", "SLSLL")])
    assert g["base"] == "iamb" and [h["kind"] for h in g["hiatus"]] == ["at punctuation"]
    assert g["elisions"][0]["monosyllable"] and g["elisions"][0]["kind"] == "long vowel or diphthong"


# --- the contract -----------------------------------------------------------------------------------
def test_missing_profile_is_unavailable_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_DATA_DIR", str(tmp_path))
    for fn, blocking in ((style.check, False), (style.check_elision, True)):
        r = fn("cui dono lepidum novum libellum")
        assert KEYS <= set(r) and r["ok"] is True and r["blocking"] is blocking and r["detail"].startswith("unavailable:")


def test_nothing_raises_on_odd_input():
    for fn in (style.check, style.check_elision):
        for text in ("", None, "\n\n", "12345 !!", "ἄειδε θεά"):
            r = fn(text)
            assert KEYS <= set(r) and isinstance(r["ok"], bool)
    assert style.check("cui dono lepidum novum libellum", metre_name="hexameter")["detail"].startswith("unavailable:")


# --- the profile ------------------------------------------------------------------------------------
@needs_data
def test_profile_counts_are_consistent():
    p = style.profile()
    d = p["denominators"]
    assert d["lines"] == d["hendecasyllables"] + d["decasyllables"] and d["gold_lines"] == d["lines"] + len(p["irregular_lines"])
    assert sum(v["n"] for v in p["base"]["overall"].values()) == d["lines"]
    assert sum(v["n"] for v in p["main_break"]["word_end_clear"].values()) == d["hendecasyllables"]
    assert sum(v["n"] for v in p["elision"]["kinds"].values()) == p["elision"]["total"] == sum(
        int(k) * v["n"] for k, v in p["elision"]["per_line"].items())
    assert p["base"]["overall"]["spondee"]["share"] > p["base"]["overall"]["iamb"]["share"] > 0
    assert "pyrrhic" not in p["base"]["overall"]                       # never a pyrrhic base
    assert p["word_end_after"]["6"]["n"] > p["word_end_after"]["5"]["n"] > p["word_end_after"]["4"]["n"]
    for k, v in p["rare_features"].items():
        assert v["share"] < p["rare_threshold"] and 1 <= len(v["loci"]) <= 5, k
    assert {h["locus"] for h in p["hiatus"]} == {"3.16", "38.2", "55.4"}
    assert {x["locus"].split(".")[0] for x in p["decasyllable_lines"]} == {"55", "58b"}


# --- L13 on drafts ----------------------------------------------------------------------------------
@needs_data
def test_l13_reports_each_feature_with_catullus_share_and_never_blocks():
    r = style.check("cui dono lepidum novum libellum\nvivamus, mea Lesbia, atque amemus")
    assert r["id"] == "L13" and r["name"] == "Phalaecian manner" and r["ok"] is True and r["blocking"] is False
    a, b = r["evidence"]
    assert a["base"] == "spondee" and a["word_ends"] == [1, 3, 6, 8] and a["final_word"]["syllables"] == 3
    assert [e["at"] for e in b["elisions"]] == [8, 9] and b["break"] == "5th"
    assert "spondee base (" in r["detail"] and "% of Catullus's lines" in r["detail"] and "word-ends after" in r["detail"]
    assert not r["warnings"]


@needs_data
def test_l13_warns_on_rare_features_with_number_and_loci():
    p = style.profile()
    r = style.check("te Campo quaesivimus minore\nvivamus, mea Lesbia, atque es\nxyz")
    assert r["ok"] is True and r["evidence"][0]["metre"] == "phalaecian_decasyllable"
    assert any("decasyllable" in w and "55" in w for w in r["warnings"])
    mono = p["features"]["final_syllables:1"]
    if r["evidence"][1]["fits"]:                                         # a monosyllable at line end: rare
        assert any(f"{mono['lines']} of {mono['of']} lines" in w and mono["loci"][0] in w for w in r["warnings"])
    assert "does not fit the metre" in r["detail"]


# --- L8 on drafts -----------------------------------------------------------------------------------
@needs_data
def test_l8_lists_elisions_with_kind_and_count():
    r = style.check_elision("vivamus, mea Lesbia, atque amemus\nTam gratum est mihi quam ferunt puellae")
    assert r["id"] == "L8" and r["name"] == "elision and hiatus" and r["ok"] is True and r["blocking"] is True
    kinds = [(e["type"], e.get("shown")) for e in r["evidence"]]
    assert ("elision", "atqu(e) amemus") in kinds and ("prodelision", "gratumst") in kinds
    assert f"of Catullus's {style.profile()['elision']['total']} elisions" in r["detail"]


@needs_data
def test_l8_hiatus_blocks_unless_catullus_has_the_kind():
    bad = style.check_elision("o factum male et miselle passer")
    assert bad["ok"] is False and bad["blocking"] is True and "hiatus male | et" in bad["detail"]
    assert [e["type"] for e in bad["evidence"]] == ["hiatus"] and bad["evidence"][0]["allowed"] is False
    good = style.check_elision("o factum male! o miselle passer!")          # Catullus 3.16
    assert good["ok"] is True and "3.16" in good["detail"] and good["evidence"][0]["allowed"] is True


@needs_data
def test_l8_restores_a_fused_or_elided_form_and_counts_monosyllables():
    r = style.check_elision("malest, Cornifici, tuo Catullo")
    assert "male est" in r["detail"]
    m = style.check_elision("malest, me hercule, et laboriose,")
    assert "the monosyllable me is elided" in m["detail"]
