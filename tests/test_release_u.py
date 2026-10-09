"""Release U: general rules with no corpus index (edition groups, headline rules, draft analysis, rate limits,
line loci, dialect rules, concept terms)."""
import json
import sqlite3

import numpy as np
import pytest

from backend import headline_rules as hr
from backend.aeolic_variants import aeolic_diphthong_before_s, lesbian_fallback_variants
from backend.dialect_rules import elided_plural_is_verb, gate
from backend.draft_analysis import compact, draft_passage, headline
from backend.fastcopy import deepcopy as fastcopy
from backend.lemma_glosses import dialect_headword_variants
from backend.line_spans import line_at, lines
from backend.passage_analysis import PassageAnalysisError, lean_word_result
from backend.passage_dialect import passage_dialect
from backend.rate_limit import RateLimiter


# ------------------------------------------------------------------ item 4: one edition of each fragment
def test_build_edition_groups_links_and_counts(monkeypatch):
    from scripts import build_edition_groups as b
    words = {1: {"σελαννα", "αστερες", "καλαν", "αμφι"}, 2: {"σελαννα", "αστερες", "καλαν", "αμφι", "λαμπει"},
             3: {"ποικιλοθρον", "αθανατ", "αφροδιτα"}, 4: {"ποικιλοθρον", "αθανατ", "αφροδιτα", "δολοπλοκε"}}
    source = {1: "ogc", 2: "campbell", 3: "ogc", 4: "ogc"}
    mapped = {1: False, 2: False, 3: True, 4: True}
    pairs = b.links_for_author([1, 2, 3, 4], words, source, mapped)
    assert (1, 2) in pairs  # different collections, the shorter's words all in the longer
    assert all({a, c} != {3, 4} for a, c in pairs)  # same collection (and both TLG-mapped) never linked


def test_count_mask_drops_uncounted_editions(tmp_path, monkeypatch):
    from backend.lemma_index import LemmaIndex
    groups = tmp_path / "g.sqlite"
    con = sqlite3.connect(groups)
    con.executescript("CREATE TABLE edition_group(passage_id TEXT PRIMARY KEY, grp INTEGER, same_source_copy INTEGER,"
                      " counted INTEGER, primary_source TEXT); CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
    con.executemany("INSERT INTO edition_group VALUES (?,?,?,?,?)",
                    [("a", 1, 0, 1, "ogc"), ("b", 1, 0, 0, "ogc"), ("c", 1, 1, 0, "ogc")])
    con.execute("INSERT INTO meta VALUES ('manifest', '{}')")
    con.commit(); con.close()
    monkeypatch.setenv("MELOS_EDITION_GROUPS", str(groups))
    ix = LemmaIndex.__new__(LemmaIndex)
    import threading
    ix._lock = threading.Lock()
    ix._scope_counts = {}
    ix.pid_id = [None, "a", "b", "c", "d"]
    ix.id_pid = {"a": 1, "b": 2, "c": 3, "d": 4}
    ix.repeated = lambda: np.zeros(5, dtype=bool)
    ix.work_info = lambda: None
    mask = np.array([False, True, True, True, True])
    out = ix.count_mask(mask)
    assert out.tolist() == [False, True, False, False, True]
    kept, copies = ix.fold_edition_items([(2, 1), (1, 1), (4, 1)], out)
    assert [p for p, _ in kept] == [1, 4] and copies == {1: [2]}


# ------------------------------------------------------------------ item 5: fast lookup rules
def test_enclitic_accent_and_folded_lookup():
    assert hr.enclitic_accent_dropped("θῦμόν") == "θῦμον"
    assert hr.enclitic_accent_dropped("θῦμον") is None
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE form(id INTEGER, form TEXT, key TEXT, tokens INTEGER)")
    con.executemany("INSERT INTO form VALUES (?,?,?,?)", [(1, "εὕδω", "ευδω", 3), (2, "εὐδῶ", "ευδω", 1), (3, "θῦμον", "θυμον", 27)])
    fold = lambda s: "".join(c for c in __import__("unicodedata").normalize("NFD", s) if c.isalpha()).lower()
    assert hr.folded_lookup(con, "εὔδω", fold) == (1, "εὕδω", "breathing_folded")
    assert hr.folded_lookup(con, "θῦμόν", fold) == (3, "θῦμον", "enclitic_accent_dropped")


def test_aeolic_singular_and_duals():
    parses = ["nom. fem. du.", "voc. fem. du.", "acc. fem. du.", "nom. fem. sg."]
    out, rule = hr.aeolic_singular("σελάννα", "σελήνη", "noun", parses, "lesbian")
    assert out[0] == "nom. fem. sg." and not any(" du." in p for p in out) and rule == "aeolic_singular"
    out, _ = hr.aeolic_singular("μόνα", "μόνος", "adjective", ["nom. neut. pl.", "nom. fem. du."], "lesbian")
    assert out[:2] == ["nom. fem. sg.", "voc. fem. sg."] and "nom. neut. pl." in out
    assert hr.aeolic_singular("μόνα", "μόνος", "adjective", ["nom. neut. pl."], None) == (["nom. neut. pl."], None)
    assert hr.aeolic_singular("χώρα", "χώρα", "noun", ["nom. fem. sg."], "lesbian")[1] is None  # Attic ᾱ after ρ
    assert hr.duals_last(["nom. fem. du.", "nom. fem. sg."], None) == (["nom. fem. sg.", "nom. fem. du."], None)


def test_pronoun_vocative_and_name_vocative():
    assert hr.pronoun_vocative_only(["voc. masc. sg."], "pronoun")
    assert not hr.pronoun_vocative_only(["voc. masc. sg."], "noun")
    assert hr.latin_name("Ἀτθίς") == "Atthis" and hr.latin_name("Γογγύλα") == "Gongyla"
    assert hr.name_vocative("Ἄτθι", "Ἀτθίς", ["voc. fem. sg."], "Attic") == "Atthis (a name; vocative)"
    assert hr.name_vocative("Ἄτθι", "Ἀτθίς", ["nom. fem. sg."], "Attic") is None
    assert hr.name_vocative("Ἀθᾶναι", "Ἀθῆναι", ["voc. fem. pl."], "Athens") is None  # a city addressed stays a city


def test_name_vocative_on_interlinear_rows():
    il = {"readings": [{"tokens": [{"kind": "word", "text": "Ἄτθι", "lemma": "Ἀτθίς", "parse_short": "voc. fem. sg.",
                                     "gloss": {"text": "Athens", "short_text": "Athens"}}]}]}
    assert hr.apply_name_vocatives(il, lambda lemma: "Attic") == 1
    row = il["readings"][0]["tokens"][0]
    assert row["gloss"]["short_text"] == "Atthis (a name; vocative)" and row["gloss"]["dictionary_gloss"] == "Athens"


def test_aeolic_diphthong_before_sigma():
    assert aeolic_diphthong_before_s("παῖσαν") == ["πᾶσαν"]
    assert aeolic_diphthong_before_s("Μοῖσα") == ["Μοῦσα"]
    assert aeolic_diphthong_before_s("ἄγοισι") == ["ἄγουσι"]
    assert aeolic_diphthong_before_s("αἶσα") == [] and aeolic_diphthong_before_s("παῖς") == []
    rules = {v["rule"] for v in lesbian_fallback_variants("παῖσαν")}
    assert "aeolic_ais_ois_before_vowel" in rules


def test_ai_for_eta_subscript_headword_variant():
    keys = [v["key"] for v in dialect_headword_variants("θναίσκω")]
    assert "θνησκω" in keys


def _cand(**features):
    return {"lemma": "φημί", "features": features}


def test_elided_third_plural_kept_without_another_finite_verb():
    verb3pl = {"lemma": "φημί", "upos": "VERB", "source_tags": ["verb", "third person", "plural", "present", "indicative", "active"]}
    sg3 = {"lemma": "φημί", "upos": "VERB", "source_tags": ["verb", "third person", "singular", "present", "indicative", "active"]}
    lonely = {"form": "φαῖσ’", "passage_dialect": "lesbian",
              "context_words": {"prev": [{"form": "νάων", "folded": "ναων", "readings": [{"Case": "Gen", "POS": "NOUN"}]}],
                                "next": [{"form": "γᾶν", "folded": "γαν", "readings": [{"Case": "Acc", "POS": "NOUN"}]}]}}
    assert elided_plural_is_verb(lonely)
    kept, removed = gate([verb3pl, sg3], lonely, None)
    assert verb3pl in kept
    beside = {**lonely, "context_words": {"prev": [], "next": [{"form": "ἔρχεο", "folded": "ερχεο",
                                                                 "readings": [{"Mood": "Imp", "POS": "VERB"}]}]}}
    assert not elided_plural_is_verb(beside)
    kept, _ = gate([verb3pl, sg3], beside, None)
    assert verb3pl not in kept


# ------------------------------------------------------------------ item 1: draft analysis
def test_draft_passage_validation_and_dialect():
    passage, internal = draft_passage({"text": "φαίνεταί μοι κῆνος", "dialect": "aeolic"})
    assert passage["id"].startswith("draft:") and passage["dialect"] == "lesbian"
    assert internal["selected_text"] == passage["text"] and internal["end"] == len(passage["text"])
    assert passage_dialect(passage) == "lesbian"
    assert passage_dialect({**passage, "dialect": "ionic"}) is None
    assert passage_dialect({"id": "draft:x", "author": "Alcman", "dialect": None}) == "doric"
    for bad in ({"text": ""}, {"text": "hello"}, {"text": "λόγος", "dialect": "martian"}, {"text": "λόγος", "extra": 1},
                {"text": "λόγος", "detail": "huge"}):
        with pytest.raises(PassageAnalysisError):
            draft_passage(bad)


def test_headline_rule_and_compact():
    row = {"kind": "word", "text": "δ’", "lemma": None, "headline_lemma": "δέ",
           "morphology_ranking": [{"lemma": "δέ", "parse_short": "part.", "candidate_id": "c1"}],
           "candidate_meanings": [{"candidate_id": "c1", "features": {"POS": "PART"}}],
           "gloss": {"text": "but", "short_text": "but", "alternatives": [{"id": "s"}]}}
    assert headline(row) == ("δέ", {"POS": "PART"}, "part.")
    result = {"version": 1, "status": "ok", "draft": {}, "words": [], "syntax": {"status": "ok", "tokens": []},
              "meaning": {"status": "unavailable", "relationships": [1]}, "lint": {}, "limits": {}, "warnings": [],
              "interlinear": {"readings": [{"tokens": [row]}]}, "tokens": [{"big": "x" * 1000}]}
    out = compact(result)
    assert "tokens" not in out and out["relationships"] == [1]
    slim = out["interlinear"]["readings"][0]["tokens"][0]
    assert "candidate_meanings" not in slim and "alternatives" not in slim["gloss"]


def test_lean_word_result_keeps_text_and_first_senses():
    value = {"occurrences": [1], "observed_form_groups": [2],
             "lexicon_entries": [{"id": "e", "rendered_entry_text": "full", "dictionary_senses": list(range(9)),
                                  "dictionary_senses_excluded": [1]}],
             "candidates": [{"lemma": "x", "supporting_sources": [1], "dictionary_senses": list(range(9))}]}
    lean = lean_word_result(value)
    assert "occurrences" not in lean and "observed_form_groups" not in lean
    entry = lean["lexicon_entries"][0]
    assert entry["rendered_entry_text"] == "full" and len(entry["dictionary_senses"]) == 4
    assert "dictionary_senses_excluded" not in entry and "supporting_sources" not in lean["candidates"][0]
    assert value["lexicon_entries"][0]["dictionary_senses"] == list(range(9))  # the input is not changed


def test_fastcopy_matches_deepcopy():
    import copy
    tree = {"a": [1, {"b": (2, 3)}, {"c": {"d"}}], "e": "f"}
    out = fastcopy(tree)
    assert out == copy.deepcopy(tree) and out is not tree and out["a"][1] is not tree["a"][1]


# ------------------------------------------------------------------ item 2: abuse protection
def test_rate_limiter_per_client_and_connection():
    now = [0.0]
    limiter = RateLimiter(client_minute=3, client_day=100, connection_minute=5, clock=lambda: now[0])
    headers = {"x-forwarded-for": "1.1.1.1, 9.9.9.9"}
    assert [limiter.check(headers, "127.0.0.1") for _ in range(3)] == [0, 0, 0]
    assert limiter.check(headers, "127.0.0.1") > 0
    other = {"x-forwarded-for": "2.2.2.2, 9.9.9.9"}
    assert limiter.check(other, "127.0.0.1") == 0 and limiter.check(other, "127.0.0.1") == 0
    assert limiter.check({"x-forwarded-for": "3.3.3.3, 9.9.9.9"}, "") > 0  # the connection's own limit (5)
    now[0] = 61.0
    assert limiter.check(headers, "127.0.0.1") == 0


# ------------------------------------------------------------------ item 7: line loci
def test_line_at_printed_and_positional_numbers():
    text = "πρῶτος στίχος\nδεύτερος στίχος 5\nτρίτος στίχος"
    line = line_at(text, text.index("τρίτος"), "Fragment 96")
    assert line["text"] == "τρίτος στίχος" and line["line"] == 6 and line["line_basis"] == "printed"
    assert line["citation"] == "Fragment 96, l. 6"
    plain = "α β\nγ δ"
    assert line_at(plain, 4, "Fr. 1")["line_basis"] == "position_in_passage"
    assert [r[2] for r in lines(plain)] == ["α β", "γ δ"]


def test_cited_line_from_locus_range():
    from backend.citation_routes import cited_line
    words = "αβγδεζηθικλμνξοπρστυ"
    text = "\n".join(f"στίχος {words[i]}" for i in range(20))
    row = {"locus_start": "1.1", "locus_end": "1.20", "citation": "1.1-1.20"}
    line = cited_line({"locus": [1, 5]}, row, text)
    assert line["text"] == "στίχος ε" and line["line"] == 5 and line["line_basis"] == "locus"
    assert cited_line({"locus": [1, 5]}, row, "one long prose paragraph") is None
    assert cited_line({"locus": [[1, ""], [5, ""]]}, row, text)["text"] == "στίχος ε"  # the parser's [number, suffix]


def test_printed_line_number_with_full_stop():
    text = "7. ὤς ποτ’ ἀελίω\n8. δύντος ἀ βροδοδάκτυλος σελάννα"
    line = line_at(text, text.index("δύντος"), "Fragment 96")
    assert line["line"] == 8 and line["line_basis"] == "printed" and line["text"] == "δύντος ἀ βροδοδάκτυλος σελάννα"
