"""L3 agreement and L10 word order (backend/latin_grammar.py) over backend.latin_morph readings: plain blunders are
caught, Catullus's own hendecasyllables pass, a missing data file is 'unavailable' and nothing raises."""
from __future__ import annotations

import re

import pytest

from backend import latin_grammar, latin_morph

pytestmark = pytest.mark.skipif(not latin_morph.available(), reason="data/morph_la.sqlite not built (scripts/build_morph_la.py)")

CATULLUS_1 = """Cui dono lepidum novum libellum
arida modo pumice expolitum?
Corneli, tibi; namque tu solebas
meas esse aliquid putare nugas."""
CATULLUS_5 = """Vivamus, mea Lesbia, atque amemus,
rumoresque senum severiorum
omnes unius aestimemus assis.
Soles occidere et redire possunt:
nobis cum semel occidit brevis lux,
nox est perpetua una dormienda.
Da mi basia mille, deinde centum,
dein mille altera, dein secunda centum,
deinde usque altera mille, deinde centum."""
CATULLUS_13 = """Cenabis bene, mi Fabulle, apud me
paucis, si tibi di favent, diebus,
si tecum attuleris bonam atque magnam
cenam, non sine candida puella
et vino et sale et omnibus cachinnis."""


def rules(result: dict, severity: str = "fail") -> list[tuple[str, str]]:
    return [(x["rule"], x["word"]) for x in result["evidence"] if x["severity"] == severity]


def test_analyses_shape_and_sources():
    reads = latin_morph.analyses("puellam")
    assert reads and all(set(latin_morph.KEYS) <= set(r) for r in reads)
    assert any(r["lemma"] == "puella" and r["pos"] == "NOUN" and (r["case"], r["number"], r["gender"]) == ("acc", "sg", "f")
               for r in reads)
    assert any(r["pos"] == "VERB" and r["person"] == "3" and r["number"] == "sg" for r in latin_morph.analyses("Venit"))
    assert {"ADP", "CONJ"} <= {r["pos"] for r in latin_morph.analyses("cum")}
    assert latin_morph.analyses("xyzzus") == [] and latin_morph.analyses("") == []


def test_enclitics_are_told_from_words_that_end_so():
    assert any(r.get("enclitic") == "cum" and r["case"] == "abl" for r in latin_morph.analyses("mecum"))
    assert any(r["case"] == "abl" for r in latin_morph.analyses("quibuscum"))
    for word in ("atque", "neque", "quoque", "bene", "sine"):
        assert latin_morph.lexical(word), word
    assert not latin_morph.lexical("rumoresque")
    assert latin_morph.enclitic_of("rumoresque") == ("rumores", "que")
    assert any(r.get("enclitic") == "que" and r["lemma"] == "rumor" for r in latin_morph.analyses("rumoresque"))


@pytest.mark.parametrize("draft, rule, word", [
    ("Ambulat cum puellam.", "b", "cum"),
    ("cum puellam", "b", "cum"),
    ("ad urbe venio.", "b", "ad"),
    ("ex urbem veni.", "b", "ex"),
    ("sine puellam venit.", "b", "sine"),
    ("in puellae sedet.", "b", "in"),
    ("de meos amores.", "b", "de"),
    ("bonus puella venit.", "c", "bonus"),
    ("puellae venit bellus.", "c", "bellus"),
    ("pueri bellus veniunt.", "c", "bellus"),
    ("Catullus veniunt.", "d", "Catullus"),
    ("ego venit.", "d", "ego"),
    ("tu amamus.", "d", "tu"),
    ("Catullus amo.", "d2", "Catullus"),
    ("puer quas amo venit.", "e", "quas"),
    ("vivamus mea Lesbia xyzzus.", "a", "xyzzus"),
])
def test_blunders_are_caught(draft, rule, word):
    result = latin_grammar.check(draft)
    assert result["id"] == "L3" and result["name"] == "agreement" and result["blocking"] is False
    assert (rule, word) in rules(result), result["detail"]
    assert result["ok"] is False
    item = next(x for x in result["evidence"] if (x["rule"], x["word"]) == (rule, word))
    assert item["line"] == 1 and (item["readings"] or rule == "a")


@pytest.mark.parametrize("draft", [
    "cum puella ambulat.", "mecum venit puella.", "quibuscum vivo.", "cum venit puella, gaudeo.", "bona puella venit.",
    "puella venit bella.", "pueri belli veniunt.", "ego venio.", "tu amas.", "Catullus venit.", "puella quam amo venit.",
    "ad urbem venio.", "in urbe sedet.", "in urbem venit.", "noctes per omnes vigilo.", "puella et puer veniunt.",
])
def test_correct_latin_passes(draft):
    result = latin_grammar.check(draft)
    assert result["ok"] is True and not rules(result), result["detail"]


@pytest.mark.parametrize("poem", [CATULLUS_1, CATULLUS_5, CATULLUS_13])
def test_catullus_passes_both_checks(poem):
    for result in (latin_grammar.check(poem), latin_grammar.check_word_order(poem)):
        assert result["ok"] is True and not rules(result), result["detail"]
        assert not result["detail"].startswith("unavailable")


def test_sentences_run_over_line_ends():
    assert latin_grammar.check("venit puella\nbella.")["ok"] is True
    result = latin_grammar.check("venit puella.\nbellus.")
    assert rules(result) == [] and rules(result, "note") == [("c", "bellus")]      # alone in its sentence: a substantive
    assert latin_grammar.check("puella venit\nbellus.")["evidence"][0]["line"] == 2


@pytest.mark.parametrize("draft, rule, word", [
    ("Enim venit puella.", "postpositive", "Enim"),
    ("Venit puella. Autem ridet.", "postpositive", "Autem"),
    ("Quoque venit puella.", "postpositive", "Quoque"),
    ("venit puella ad.", "preposition", "ad"),
    ("puella xyzque venit.", "enclitic", "xyzque"),
])
def test_word_order_blunders(draft, rule, word):
    result = latin_grammar.check_word_order(draft)
    assert result["id"] == "L10" and result["name"] == "word order" and result["blocking"] is False
    assert (rule, word) in rules(result) and result["ok"] is False, result["detail"]


def test_word_order_allowances():
    for draft in ("venit enim puella.", "puella quoque venit.", "atque venit puella.", "neque venit.", "puellaque venit.",
                  "venitne puella?", "paulo ante venit. puella ante.", "ad urbem venit"):
        result = latin_grammar.check_word_order(draft)
        assert result["ok"] is True and not rules(result), (draft, result["detail"])
    note = latin_grammar.check_word_order("puella hicque venit.")
    assert note["ok"] is True and rules(note, "note") == [("enclitic", "hicque")]
    assert set(latin_grammar.postpositives()) >= {"enim", "autem", "quoque"}
    assert all(c["first"] == 0 for c in latin_grammar.postpositives().values())


def test_unavailable_and_never_raises(monkeypatch, tmp_path):
    for bad in ("", "   \n\n", "?!.;:", "123 ... ---", None):
        for fn in (latin_grammar.check, latin_grammar.check_word_order):
            result = fn(bad)
            assert result["ok"] is True and set(result) == {"id", "name", "ok", "blocking", "detail", "evidence"}
    monkeypatch.setenv("MELOS_MORPH_LA", str(tmp_path / "absent.sqlite"))
    for fn in (latin_grammar.check, latin_grammar.check_word_order):
        result = fn("Ambulat cum puellam.")
        assert result["ok"] is True and result["detail"].startswith("unavailable:") and result["evidence"] == []


# --- readings to confirm: a rule that passes only on a rarer reading says so (ok stays True) ---

def confirms(result: dict) -> list[str]:
    return [x["message"] for x in result["evidence"] if x["rule"] == "confirm"]


@pytest.mark.parametrize("draft, word, needle", [
    ("cum puellam amo.", "cum", "passes only if *cum* is the conjunction"),
    ("sine puellam vivo.", "vivo", "*sine* passes only if *vivo* is the ablative of *uiuus*"),
    ("per vias ambulat puella bellum.", "bellum", "passes only if *bellum* is the noun *bellum*"),
])
def test_rescued_blunders_draw_a_note(draft, word, needle):
    result = latin_grammar.check(draft)
    assert result["ok"] and not rules(result)
    notes = [x for x in result["evidence"] if x["rule"] == "confirm"]
    assert [x["word"] for x in notes] == [word] and notes[0]["severity"] == "note"
    assert needle in notes[0]["message"] and "1 reading to confirm" in result["detail"]
    assert re.search(r"\((Catullus|Horace)[^)]*\d\)", notes[0]["message"])          # the LASLA counts are shown


def test_far_partner_is_noted():
    result = latin_grammar.check("puella magnus venit per vias et hortum amat poeta.")
    assert result["ok"] and any("agrees with nothing next to it (*puella*); taken with *poeta* in line 1" in m for m in confirms(result))


@pytest.mark.parametrize("draft", [
    "cum puella venit, gaudeo.", "cum venit puella, gaudeo.", "sine puella vivo.", "puella bella venit.",
    "bellum amat puella.", "ad caelum lepido vocare versu.",
])
def test_sound_latin_draws_no_confirm_note(draft):
    result = latin_grammar.check(draft)
    assert result["ok"] and not confirms(result), result["detail"]


def test_confirm_notes_need_the_lemma_index(monkeypatch, tmp_path):
    monkeypatch.setenv("MELOS_LEMMA_INDEX_LA", str(tmp_path / "none.sqlite"))
    latin_grammar.reading_counts.cache_clear()
    try:
        result = latin_grammar.check("sine puellam vivo.")
        assert result["ok"] and not result["detail"].startswith("unavailable")
    finally:
        monkeypatch.undo()
        latin_grammar.reading_counts.cache_clear()
