"""The Latin backend of the composer lint bank (backend/latin_backend.py through composer_lint.check(language="la")).
Needs data/corpus_la.sqlite (scripts/build_corpus_la.py) and the Latin quantity lexicon; skipped without them."""
from __future__ import annotations

import pytest

from backend import composer_lint, latin_backend
from backend.scansion.lexicon_la import LatinQuantityLexicon

needs_data = pytest.mark.skipif(not latin_backend.available() or not LatinQuantityLexicon().available,
                                reason="Latin corpus or lexicon not built")


def by_id(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


@needs_data
def test_a_catullan_line_passes_every_check_and_is_flagged_as_homage():
    r = composer_lint.check("Vivamus mea Lesbia, atque amemus", metre_name="phalaecian", author="Catullus", language="la")
    assert r["pass"] and by_id(r, "L7")["ok"] and by_id(r, "L1")["ok"]
    assert by_id(r, "L2")["detail"] == "not applicable to Latin" and not by_id(r, "L2")["blocking"]
    l4 = by_id(r, "L4")
    assert "5/5 spellings printed" in l4["detail"] and all(e["author_tokens"] for e in l4["evidence"])
    assert not by_id(r, "L11")["ok"] and "Carmina 5" in by_id(r, "L11")["detail"]
    assert r["scansion"]["language"] == "la" and r["scansion"]["fit"][0]["ok"]


@needs_data
def test_unknown_form_fails_l1_and_lexicon_only_form_passes_with_a_note():
    r = composer_lint.check("blorpus mea Lesbia atque amemus", metre_name="phalaecian", language="la")
    assert not r["pass"] and not by_id(r, "L1")["ok"] and "blorpus" in by_id(r, "L1")["detail"]
    r = composer_lint.check("amabimus mea Lesbia atque amemus", metre_name="phalaecian", language="la")
    assert by_id(r, "L1")["ok"] and "not printed in the corpus" in by_id(r, "L1")["detail"]


@needs_data
def test_metre_rejects_a_wrong_line_and_u_v_spellings_meet():
    r = composer_lint.check("Vivamus mea Lesbia et amemus semper", metre_name="phalaecian", language="la")
    assert not by_id(r, "L7")["ok"]
    r = composer_lint.check("uiuamus mea Lesbia atque amemus", metre_name="phalaecian", author="Catullus", language="la")
    assert by_id(r, "L1")["ok"] and by_id(r, "L4")["evidence"][0]["author_tokens"]


@needs_data
def test_elision_across_the_caret_gives_the_slot_back():
    # prefix: Vi-va-mus me-a Les-bi-a = 8 syllables typed; the client leaves "u-F"; "atque amemus" needs 4 slots
    # because the prefix's final -a elides before atque: the lint must fit "-u-F" with that syllable included.
    r = composer_lint.check("atque amemus", metre_name="phalaecian", prefix="Vivamus mea Lesbia,", remaining_template="u-F",
                            language="la")
    assert by_id(r, "L7")["ok"], by_id(r, "L7")["detail"]
    assert r["scansion"]["remaining_template"] == "-u-F"
    assert r["scansion"]["fit"][0]["remaining_template"] == ""


def test_greek_default_is_untouched():
    r = composer_lint.check("ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα", metre_name="sapphic_hendecasyllable")
    assert r["scansion"]["language"] == "grc" and r["scansion"]["dialect"] == "none"
    with pytest.raises(Exception):
        composer_lint.check("x", language="xx")


def test_context_lemmas_align_tokens_and_rerank_readings(monkeypatch):
    """LatinCy's reading of the whole draft (one call) re-ranks a form's LASLA readings: quod as the conjunction when
    the context says so; an enclitic split by the tokeniser is rejoined to its host word."""
    from backend import latin_lemma
    fake = [{"text": "quod", "lemma": "quod", "pos": "SCONJ", "morph": ""},
            {"text": "uirum", "lemma": "uir", "pos": "NOUN", "morph": "Case=Acc"},
            {"text": "que", "lemma": "que", "pos": "CCONJ", "morph": ""}]
    monkeypatch.setattr(latin_lemma, "latincy_tokens", lambda text: fake)
    ctx = latin_lemma.context_lemmas(["quod", "virumque"])
    assert ctx == {0: {"lemma": "quod", "upos": "SCONJ", "morph": ""}, 1: {"lemma": "uir", "upos": "NOUN", "morph": "Case=Acc"}}
    reads = [{"lemma": "qui", "upos": "PRON", "count": 163, "source": "lasla"}, {"lemma": "quod", "upos": "SCONJ", "count": 119, "source": "lasla"}]
    chosen, how = latin_lemma.choose_reading(reads, ctx[0])
    assert chosen[0]["lemma"] == "quod" and how == "lasla+context"
    assert latin_lemma.choose_reading(reads, None)[0][0]["lemma"] == "qui"
    assert latin_lemma.choose_reading([], ctx[1]) == ([{"lemma": "uir", "upos": "NOUN", "count": 0, "source": "latincy", "morph": "Case=Acc"}], "latincy context")
    # a tokenisation that does not add up to the words stops the alignment instead of mislabelling
    monkeypatch.setattr(latin_lemma, "latincy_tokens", lambda text: [{"text": "quo", "lemma": "quo", "pos": "ADV", "morph": ""}])
    assert latin_lemma.context_lemmas(["quod"]) == {}
    monkeypatch.setattr(latin_lemma, "latincy_tokens", lambda text: [])
    assert latin_lemma.context_lemmas(["quod"]) == {}


@needs_data
def test_l4_uses_the_contextual_reading(monkeypatch):
    from backend import latin_lemma
    monkeypatch.setattr(latin_lemma, "latincy_tokens", lambda text: [{"text": "quod", "lemma": "quod", "pos": "SCONJ", "morph": ""}])
    r = latin_backend.attestation_check(["quod"], "Catullus")
    e = r["evidence"][0]
    assert e["lemma"] == "quod" and e["lemma_source"] == "lasla+context" and e["readings"][0]["lemma"] == "quod"
