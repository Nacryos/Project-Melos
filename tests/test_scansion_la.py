"""Tests for the Latin scanner (backend/scansion/quantity_la.py, rules_la.yaml, metres_la.yaml) and the
elision branches of the metre layer. The core tests need no data files."""
from __future__ import annotations

import pytest

from backend.scansion import metre
from backend.scansion.quantity_la import LatinScanner
from backend.scansion.syllabify_la import nuclei_of, words_of

CORE = LatinScanner()


def units(text, sc=CORE):
    return [(u.text.strip(), round(u.p_long, 2), u.rule) for u in sc.scan(text)]


def unit(text, piece, sc=CORE):
    for u in sc.scan(text):
        if u.text.strip() == piece or text[u.nstart:u.end].strip() == piece:
            return u
    raise AssertionError(f"{piece!r} not among {[u.text for u in sc.scan(text)]}")


def fit(text, m="phalaecian"):
    return metre.fit_line(CORE.scan(text), m)


# --- letters and syllables -------------------------------------------------------------------------
def test_iu_roles_and_diphthongs():
    ws = words_of("cui dono maior silua fluuius uua Iuppiter poeta coepi Orpheus deus Europa eunt sanguis suauis suus")
    kinds = {"".join(l.base for l in w.letters): [("".join(w.letters[i].base for i in n.letters), n.kind) for n in nuclei_of(w)]
             for w in ws}
    assert kinds["cui"] == [("ui", "diphthong")]
    assert kinds["maJor"][0] == ("a", "vowel") and len(kinds["maJor"]) == 2        # intervocalic i, double
    assert len(kinds["silva"]) == 2 and len(kinds["fluvius"]) == 3 and len(kinds["uva"]) == 2
    assert kinds["juppiter"][0] == ("u", "vowel")
    assert len(kinds["poeta"]) == 3 and kinds["coepi"][0] == ("oe", "diphthong")
    assert kinds["orpheus"][1] == ("eu", "diphthong") and len(kinds["deus"]) == 2
    assert kinds["europa"][0] == ("eu", "diphthong") and len(kinds["eunt"]) == 2
    assert len(kinds["sangwis"]) == 2 and len(kinds["swavis"]) == 2 and len(kinds["suus"]) == 2


def test_position_counts_qu_as_one_x_as_two_h_as_none():
    assert unit("atque amemus", "atqu").p_long == 1.0            # t + qu
    assert unit("aqua", "aqu").rule == "NATURE"                    # qu alone: no position
    assert unit("dixit", "dix").p_long == 1.0                      # x double
    assert unit("Zephyrus", "eph").rule == "NATURE"                # ph = one consonant, h silent
    assert unit("maior", "mai").p_long == 1.0                      # intervocalic i double


def test_muta_cum_liquida_is_weak_inside_the_word_but_position_across_a_prefix_or_boundary():
    assert unit("patris", "atr").rule == "MCL-WORD" and 0 < unit("patris", "atr").p_long < 1
    assert unit("abrumpit", "abr").p_long == 1.0                   # ab-rumpo
    assert unit("et rem", "et r").p_long == 1.0                    # t | r across a boundary
    assert unit("ille prex", "e pr").rule == "INIT-MCL"            # pr opens the next word


def test_s_impura_stays_short():
    u = unit("pote stolidum", "e st")
    assert u.rule == "S-IMPURA" and u.p_long < 0.3


# --- finals ----------------------------------------------------------------------------------------
def test_final_vowel_rules():
    assert unit("me tibi", "me t").vowel["rule"] == "MONO-LONG"
    assert unit("amare bene", "e b").vowel["rule"] == "FIN-E" and unit("amare bene", "e b").p_long < 0.1
    assert unit("die mihi", "e m").vowel["rule"] == "FIN-E-LIST"
    assert unit("nisi tu", "i t").vowel["rule"] == "FIN-I-SHORT"
    assert unit("ego sum", "o s").vowel["rule"] == "FIN-O-SHORT"
    assert unit("amo te", "o t").vowel["rule"] == "FIN-O-IAMB"
    assert unit("amabo te", "o t").vowel["rule"] == "FIN-O" and unit("amabo te", "o t").p_long >= 0.9
    assert unit("puellaque mea", "e m").vowel["rule"] == "ENCL-E"


def test_vowel_before_vowel_is_short_except_listed():
    assert unit("deus", "e").p_long <= 0.1
    assert unit("illius", "i").vowel["rule"] == "VAV-GEN" and unit("fiat", "i").vowel["rule"] == "VAV-LIST"


# --- elision, prodelision, hiatus -------------------------------------------------------------------
def test_elision_candidates_and_prodelision_flags():
    u = unit("Lesbia atque", "a")
    assert u.elision >= 0.9 and u.label == "E"
    u = unit("dictum est", "um")
    assert u.prodelision and u.prodelision["p"] >= 0.9 and u.elision == 0.0
    u = unit("male o", "e")
    assert 0 < u.elision < 0.9                                     # before an interjection: hiatus is not a violation


def test_catullus_hendecasyllables_fit_with_elision():
    assert fit("Cui dono lepidum nouum libellum").ok
    f = fit("Viuamus, mea Lesbia, atque amemus")
    assert f.ok and f.pattern == "–––⏑⏑–⏑–⏑–⏑" and sum(1 for a in f.assignment if a.get("elided")) == 2
    assert fit("soles occidere et redire possunt").ok
    assert fit("Passer, deliciae meae puellae").ok


def test_hiatus_before_interjection_is_allowed_but_elsewhere_a_violation():
    assert fit("o factum male! o miselle passer!").ok
    f = fit("ille amat ego odi te puellam amo")                  # 11 syllables only without elision: hiatus forced
    assert not f.ok and any(v.get("kind") == "hiatus" for v in f.violations)


def test_pyrrhic_base_is_improbable():
    ps = metre.parses(CORE.scan("Cui dono lepidum nouum libellum"), "xx-uu-u-u-F")
    best = max(ps, key=lambda t: t[0])[1]
    assert [w for _, _, w, _, _ in best[:2]] == ["L", "L"]


def test_decasyllable_variant_and_auto_detect():
    assert fit("non custos si fingar ille Cretum", "phalaecian_decasyllable").ok
    top = metre.auto(CORE.scan_lines("Cui dono lepidum nouum libellum\narida modo pumice expolitum"), language="la")
    assert top[0]["metre"] == "phalaecian"


def test_greek_units_have_no_elision_fields():
    from backend.scansion.quantity import Scanner
    for u in Scanner(lexicon=None).scan("πολλὰς δ’ ἰφθίμους"):
        assert u.elision == 0.0 and u.prodelision is None and u.label != "E"


def test_speed():
    import time
    t0 = time.perf_counter()
    for _ in range(50):
        fit("Viuamus, mea Lesbia, atque amemus")
    assert (time.perf_counter() - t0) / 50 < 0.02
