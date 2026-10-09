"""Release P: citation parsing, sourced genres/dates helpers, rates, head meanings, calibration, folding."""
import json
import sqlite3

import numpy as np
import pytest

from backend.citations import parse_citation, parse_range, contains, normalise_depth
from backend.lemma_glosses_index import head_meanings, gloss_terms
from backend.lemma_calibration import evidence_class, apply_model
from backend.lemma_index import rate_fields, LemmaIndex, _find_span
from backend.word_parser_candidates import compact_entry
import test_lemma_index as base
from test_lemma_index import build, PASSAGES


@pytest.mark.parametrize("query,kind,author,work,locus", [
    ("Il. 1.1", "locus", "Homer", "Iliad", [(1, ""), (1, "")]),
    ("Pind. O. 1.1", "locus", "Pindar", "Olympian Odes", [(1, ""), (1, "")]),
    ("Hes. Th. 116", "locus", "Hesiod", "Theogony", [(116, "")]),
    ("Sappho fr. 31", "fragment", "Sappho", None, [(31, "")]),
    ("Sappho 31", "fragment", "Sappho", None, [(31, "")]),
    ("Alc. 130b", "fragment", "Alcaeus", None, [(130, "b")]),
    ("AP 7.1", "locus", "Greek Anthology", None, [(7, ""), (1, "")]),
    ("Eur. Med. 1", "locus", "Euripides", None, [(1, "")]),
])
def test_parse_citation(query, kind, author, work, locus):
    parsed = parse_citation(query)
    assert parsed["kind"] == kind and parsed["author"] == author and parsed["work"] == work
    assert parsed["locus"] == locus


def test_parse_citation_urn_scheme_and_non_citations():
    urn = parse_citation("urn:cts:greekLit:tlg0012.tlg001.perseus-grc2:1.1-1.5")
    assert (urn["tlg_author"], urn["tlg_work"], urn["edition"]) == ("tlg0012", "tlg001", "perseus-grc2")
    assert urn["locus_end"] == [(1, ""), (5, "")]
    assert parse_citation("Sappho fr. 168A LP")["scheme"] == "Lobel-Page"
    assert parse_citation("Sapph. fr. 31 V")["scheme"] == "Voigt"
    assert parse_citation("Eur. Med. 1")["work_prefix"] == "med"
    for text in ("moon 3", "Sappho 31 moon", "rose-fingered dawn", "σελήνη"):
        assert parse_citation(text) is None
    assert parse_citation("urn:cts:greekLit:xyz1")["invalid"]


def test_parse_range_and_containment():
    assert parse_range("1.1–1.20") == (((1, ""), (1, "")), ((1, ""), (20, "")))
    assert parse_range("622–643") == (((622, ""),), ((643, ""),))
    assert parse_range("trochaic.1529–trochaic.1530") == (((1529, ""),), ((1530, ""),))
    assert parse_range("bergk_plg2_0215.1") is None and parse_range("Fragment 1") is None
    start, end = parse_range("1.1–1.20")
    assert contains(start, end, ((1, ""), (7, ""))) and not contains(start, end, ((2, ""), (1, "")))
    assert contains(start, end, ((1, ""),))  # a book-level citation
    assert normalise_depth(((3, ""), (511, "")), 1) == ((511, ""),)


def test_head_meanings_are_sense_heads_not_any_word():
    assert head_meanings("the moon") == ["moon"]
    assert "moon" not in head_meanings("Io, identified with the moon")
    assert head_meanings("a mate or companion") == ["mate", "companion"]
    assert "love" not in head_meanings("loved, beloved, dear") and head_meanings("to love") == ["love"]
    assert head_meanings("a seaman, sailor") == ["seaman", "sailor"]  # never "sea"
    terms = {t for t, field, _ in gloss_terms("the moon", {"heads": ["the moon"], "full": "the moon", "glosses": ["the moon"]})
             if field == 3}
    assert terms == {"=moon"}


def test_rate_fields_interval_and_small_sample():
    big = rate_fields(50, 1_000_000)
    assert big["per_10k"] == 0.5 and big["per_10k_ci95"][0] < 0.5 < big["per_10k_ci95"][1]
    assert not big["small_sample"]
    small = rate_fields(3, 4714)
    assert small["small_sample"] and small["per_10k_ci95"][1] > 2 * small["per_10k"]
    assert rate_fields(0, 0)["per_10k"] is None


def test_calibration_classes_and_step_function():
    assert evidence_class(1 | 16) == "context_agrees"
    assert evidence_class(1 | 32) == "context_chose"
    assert evidence_class(4) == "generated_spelling"
    assert evidence_class(1 | 16 | 64) == "damaged_word"
    model = {"all": [[0, 100, 0.4, 10], [101, 255, 0.9, 10]], "context_agrees": [[0, 255, 0.97, 50]]}
    assert apply_model(model, 50, 1) == 0.4 and apply_model(model, 200, 1) == 0.9
    assert apply_model(model, 50, 17) == 0.97


def test_compact_entry_keeps_first_senses_only():
    entry = {"id": "middle-liddell:x", "lemma": "φαίνω", "source": "Perseus Middle Liddell TEI (Hopper open-source texts)",
             "gloss": "to bring to light", "entry_text": "φαίνω " + "x" * 1000,
             "dictionary_senses": [{"text": f"sense {i}", "sense_path": [{"n": "A"}, {"n": str(i)}]} for i in range(9)]}
    out = compact_entry(entry, senses=3)
    assert [s["text"] for s in out["senses"]] == ["sense 0", "sense 1", "sense 2"] and out["sense_count"] == 9
    assert out["senses"][1]["label"] == "A.1" and len(out["entry_excerpt"]) <= 401
    assert "attribution" not in compact_entry(entry, brief=True)


@pytest.fixture()
def index(tmp_path):
    path = tmp_path / "lemma_index.sqlite"
    lemmas = build(path)
    con = sqlite3.connect(path)
    # ἔρως has a variant link from a fresh headword (as a dictionary "poet. for ἔρως" would give)
    con.execute("INSERT INTO lemma VALUES (99,'ἔρος','ερος','noun','headword',0,0,NULL,NULL)")
    con.execute("INSERT INTO lemma_variant VALUES (99,?,'poet.','LSJ','ἔρος, ὁ, poet. for ἔρως')", (lemmas["ἔρως"],))
    con.commit()
    con.close()
    ix = LemmaIndex(path)
    ix.lemma_ids = lemmas
    return ix


def test_variant_group_and_gloss_fallback(index):
    eros = index.lemma_ids["ἔρως"]
    group = index.variant_group(eros)
    assert set(group["lemma_ids"]) == {eros, 99}
    brief = index.lemma_brief(99)
    assert brief["gloss"] == "love, desire" and brief["gloss_via_variant"] == "ἔρως"
    assert set(index.expand_variants([eros])) >= {eros, 99}


def test_concordance_period_filter_and_lines(index):
    moon = index.lemma_ids["σελήνη"]
    texts = {i: t for i, _, t in PASSAGES}
    everything = index.concordance([moon], text_lookup=texts.get)
    assert everything["total"] == 4 and len(everything["lines"]) == 4
    undated = index.concordance([moon], text_lookup=texts.get, period="undated")
    assert undated["total"] <= everything["total"]
    with pytest.raises(ValueError):
        index.concordance([moon], text_lookup=texts.get, period="Bronze Age")


def test_search_has_excerpt_and_offsets(index):
    moon = index.lemma_ids["σελήνη"]
    texts = {i: t for i, _, t in PASSAGES}
    result = index.search([moon], text_lookup=texts.get)
    first = result["results"][0]
    start, end = first["match_offsets"][0]
    assert texts[first["id"]][start:end] == first["excerpt"]["keyword"]


def test_collocations_count_a_repeated_context_once(tmp_path):

    saved = list(base.PASSAGES)
    base.PASSAGES[:] = saved + [("p:sappho:34b", "Sappho", "ἄστερες μὲν ἀμφὶ κάλαν σελάνναν")]
    try:
        path = tmp_path / "ix.sqlite"
        lemmas = base.build(path)
        con = sqlite3.connect(path)
        con.execute("UPDATE passage SET work='Fragments', source='test'")
        con.commit()
        con.close()
        ix = LemmaIndex(path)
        result = ix.collocations(lemmas["σελήνη"], min_count=1, function_words=True)
        assert result["repeated_contexts_skipped"] == 1
    finally:
        base.PASSAGES[:] = saved
