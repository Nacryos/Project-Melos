"""Release R: dialect grammar in parse ranking, derived forms, variant links, calibration groups.

General rules only; the words used here are not the lyric gold set's examples.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.passage_dialect import passage_dialect  # noqa: E402
from backend.dialect_rules import gate, label_fit  # noqa: E402
from backend.passage_analysis import hyphenated_word, tokenize_span  # noqa: E402
from backend.derived_forms import derived_link  # noqa: E402
from backend.aeolic_variants import lexical_variant, psilotic_variants  # noqa: E402
from backend.lemma_calibration import apply_model, context_group, genre_group, evidence_class  # noqa: E402


def cand(lemma, dial=None, **feats):
    raw = {key: value for key, value in feats.items()}
    if dial:
        raw["dial"] = dial
    return {"lemma": lemma, "features": raw}


def lesbian(form, nxt=(), prev=()):
    return {"form": form, "text": form, "passage_dialect": "lesbian",
            "context_words": {"next": [dict(w) for w in nxt], "prev": [dict(w) for w in prev]}}


def test_passage_dialect_from_author_and_id():
    assert passage_dialect({"author": "Sappho"}) == "lesbian"
    assert passage_dialect({"author": "ΑΛΚΑΙΟΣ"}) == "lesbian"
    assert passage_dialect({"author": "pindarus"}) == "doric"
    assert passage_dialect({"author": "", "id": "campbell-glp:alcman:1"}) == "doric"
    assert passage_dialect({"author": "Homer"}) is None


def test_dialect_label_gate_keeps_the_passage_dialect_reading():
    noun = cand("φέρη", "Attic epic Ionic", pofs="noun", case="accusative", num="singular", gend="feminine")
    inf = cand("φέρω", "Doric Aeolic", pofs="verb", mood="infinitive", tense="present", voice="active")
    kept, removed = gate([noun, inf], lesbian("φέρην"), None)
    assert kept == [inf] and removed[0][0] in ("dialect_label", "aeolic_infinitive_in_en")
    assert label_fit(inf, "lesbian") == "match" and label_fit(noun, "lesbian") == "other"
    # outside a dialect passage nothing is gated
    kept, removed = gate([noun, inf], {"form": "φέρην"}, None)
    assert len(kept) == 2 and not removed


def test_article_needs_an_agreeing_noun_or_a_plural_verb():
    article = cand("ὁ", pofs="article", case="nominative", num="plural", gend="feminine")
    conj = cand("εἰ", pofs="conjunction")
    verb = {"form": "λέγει", "folded": "λεγει", "readings": [{"POS": "VERB", "Person": "3", "Number": "Sing", "Mood": "Ind"}]}
    kept, removed = gate([article, conj], lesbian("αἰ", nxt=[verb]), None)
    assert kept == [conj] and removed[0][0] == "article_head"
    noun = {"form": "κόραι", "folded": "κοραι", "readings": [{"POS": "NOUN", "Case": "Nom", "Number": "Plur", "Gender": "Fem"}]}
    kept, removed = gate([article, conj], lesbian("αἰ", nxt=[noun]), None)
    assert len(kept) == 2
    # a pronominal article before δέ is the subject of a plural verb
    de = {"form": "δέ", "folded": "δε", "readings": []}
    plural = {"form": "λέγοισι", "folded": "λεγοισι", "readings": [{"POS": "VERB", "Person": "3", "Number": "Plur", "Mood": "Ind"}]}
    kept, removed = gate([article, conj], lesbian("αἰ", nxt=[de, plural]), None)
    assert len(kept) == 2
    # unknown neighbours are no evidence; a relative-pronoun alternative is left to the ranking
    kept, removed = gate([article, conj], lesbian("αἰ", nxt=[{"form": "ξ", "folded": "ξ", "readings": []}]), None)
    assert len(kept) == 2
    relative = cand("ὅς", pofs="pronoun", case="nominative", num="plural", gend="feminine")
    kept, removed = gate([article, relative], lesbian("αἰ", nxt=[verb]), None)
    assert len(kept) == 2


def test_iota_subscript_is_dative_singular():
    nom = cand("κόμη", pofs="noun", case="nominative", num="plural", gend="feminine")
    dat = cand("κόμη", pofs="noun", case="dative", num="singular", gend="feminine")
    kept, removed = gate([nom, dat], {"form": "κόμᾳ"}, None)
    assert kept == [dat] and removed[0][0] == "iota_subscript"


def test_prohibitive_me_keeps_imperative_or_subjunctive():
    ind = cand("γράφω", pofs="verb", mood="indicative", pers="3rd", num="singular", tense="present", voice="active")
    imp = cand("γράφω", pofs="verb", mood="imperative", pers="2nd", num="singular", tense="present", voice="active")
    me = {"form": "μὴ", "folded": "μη", "readings": []}
    kept, _ = gate([ind, imp], lesbian("γράφε", prev=[me]), None)
    assert kept == [imp]
    cond = {"form": "αἰ", "folded": "αι", "readings": []}
    kept, _ = gate([ind, imp], lesbian("γράφε", prev=[me, cond]), None)
    assert len(kept) == 2  # μή inside an εἰ/αἰ clause takes the indicative


def test_elided_iota_restoration_yields():
    a = {**cand("πολύς", pofs="adjective", case="accusative", num="plural", gend="neuter"), "normalised_query": "πόλλα"}
    i = {**cand("πολύς", pofs="adjective", case="dative", num="plural", gend="masculine"), "normalised_query": "πόλλοισι"}
    kept, removed = gate([a, i], lesbian("πόλλ’"), None)
    assert kept == [a] and removed[0][0] == "elision_vowel"


def test_lesbian_first_declension_as_is_genitive():
    acc = cand("τιμή", pofs="noun", case="accusative", num="plural", gend="feminine")
    gen = cand("τιμή", pofs="noun", case="genitive", num="singular", gend="feminine")
    kept, removed = gate([acc, gen], lesbian("τίμας"), None)
    assert kept == [gen] and removed[0][0] == "lesbian_accusative_plural_in_ais"


def test_dual_yields_in_lyric():
    dual = cand("ἄλλος", pofs="pronoun", case="nominative", num="dual", gend="feminine")
    sing = cand("ἄλλος", pofs="pronoun", case="nominative", num="singular", gend="feminine")
    kept, _ = gate([dual, sing], lesbian("ἄλλα"), None)
    assert kept == [sing]


def test_psilosis_reading_is_only_a_fallback():
    exact = cand("εἰμί", pofs="verb", mood="imperative", pers="2nd", num="singular")
    variant = {**cand("ἵημι", pofs="verb", mood="indicative", pers="2nd", num="singular"),
               "normalisation_rule": "psilosis", "normalised_query": "ἷε"}
    kept, removed = gate([exact, variant], lesbian("ἶε"), None)
    assert kept == [exact] and removed[0][0] == "psilosis_fallback_only"


def test_hyphenated_word_at_line_end_is_one_word():
    text = "ὦ φίλαι παρ-\nθένοι λέγω"
    words = [t for t in tokenize_span(text, 0, len(text)) if t["kind"] == "word"]
    assert [w["form"] for w in words] == ["ὦ", "φίλαι", "παρθένοι", "παρθένοι", "λέγω"]
    assert hyphenated_word(text, 0, 1) is None


def test_lexical_and_psilotic_variants():
    assert lexical_variant("ὀττι") is None or lexical_variant("ὀττι")[0] == "ὅτι"
    assert psilotic_variants("ὄρος")[0]["form"] == "ὅρος"
    assert psilotic_variants("εὖρος")[0]["form"] == "εὗρος"


def test_derived_link_needs_a_dictionary_entry_and_a_headword():
    entries = [{"lemma": "κάκιστος", "entry_text": "ka/kistos, h, on, Sup. of kako/s, worst", "id": "x1", "source": "LSJ"}]
    link = derived_link("κάκιστος", entries, lambda base: base == "κακός")
    assert link["base"] == "κακός" and link["relation"] == "superlative"
    assert derived_link("κάκιστος", entries, lambda base: False) is None
    adverb_of_verb = [{"lemma": "ἀγνοούντως", "entry_text": "a)gnoou/ntws, Adv. of a)gnoe/w, ignorantly", "id": "x2"}]
    assert derived_link("ἀγνοούντως", adverb_of_verb, lambda base: True) is None


def test_variant_sense_agreement_and_header_endings():
    from build_lemma_index import senses_agree, _header_ending
    assert senses_agree("a country", "the earth", ["land, country"], ["earth; land"])
    assert not senses_agree("of the sea", "the sun", ["of the sea"], ["the sun"])
    assert senses_agree("", "anything")
    assert _header_ending("ίδος") and _header_ending("ὁ") and not _header_ending("ῥέω")


def test_calibration_groups():
    assert genre_group("melic lyric") == "lyric" and genre_group("epic") == "epic" and genre_group("tragedy") == "drama"
    assert context_group("melic lyric", "lesbian") == "lyric|lesbian"
    model = {"all": [[0, 255, 0.9, 10]], "groups": {"lyric|lesbian": [[0, 899, 0.5, 10], [900, 1000, 0.8, 10]]}}
    assert apply_model(model, 200, 1) == 0.9
    assert apply_model(model, 200, 1, 0, "lyric|lesbian") == 0.8
    assert apply_model(model, 200, 1, 0, "epic|none") == 0.9
    assert evidence_class(1, 2) == "dialect_rule"
