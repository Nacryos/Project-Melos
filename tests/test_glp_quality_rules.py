"""General lemma/gloss rules added for release M (random GLP sampling).

Examples are deliberately words outside the sampled spans.
"""
from __future__ import annotations

from copy import deepcopy

from backend.lemma_glosses import (attach_lemma_glosses, dialect_headword_variants, elided_lemma_candidates,
                                   headword_key, resolve, stem_shared)
from backend.short_gloss import metalanguage_only

HEX = "a" * 64


def entry(identifier, lemma, text, source="Perseus Middle Liddell TEI (Hopper open-source texts)"):
    sense = {"id": identifier + ":s1", "text": text, "evidence_type": "dictionary_sense", "source": source,
             "source_url": "https://example.org/" + identifier, "source_locator": {"node_path": "/1"},
             "raw_sha256": HEX, "lexicon_entry_id": identifier, "language": "eng"}
    return {"id": identifier, "lemma": lemma, "source": source, "dictionary_senses": [sense]}


def lookup_from(table):
    import unicodedata

    def fold(value):
        decomposed = unicodedata.normalize("NFD", value)
        return "".join(c for c in decomposed if unicodedata.category(c).startswith("L")).lower().replace("ς", "σ")

    def lookup(headword):
        exact = [row for row in table if row["lemma"] == headword]
        if exact:
            return {"match": "exact_headword", "entries": exact}
        folded = [row for row in table if fold(row["lemma"]) == fold(headword)]
        return {"match": "folded_headword" if folded else None, "entries": folded}
    return lookup


def test_metalanguage_only_labels_but_not_short_meanings():
    assert metalanguage_only("comparative")
    assert metalanguage_only("Adv.")
    assert metalanguage_only("poet. form")
    for meaning in ("in", "and", "old", "before", "the Muse", "to set"):
        assert not metalanguage_only(meaning)


def test_headword_key_drops_length_marks():
    assert headword_key("φῑ́λος") == "φίλος"
    assert headword_key("ἄγω2") == "ἄγω"
    assert headword_key("καὶ") == "καί"


def test_dialect_headword_variants_are_labelled():
    keys = {item["key"]: item["rule"] for item in dialect_headword_variants("θάλασσα")}
    assert keys["θαλαττα"] == "attic_tt_for_ss"
    assert {item["key"] for item in dialect_headword_variants("μάτηρ")} >= {"μητηρ"}
    assert "ξενοσ" in {item["key"] for item in dialect_headword_variants("ξεῖνος")}
    assert "Μουσα" in {item["key"] for item in dialect_headword_variants("Μῶσα")}


def test_elided_lemma_candidates():
    assert elided_lemma_candidates("δ’")[:2] == ["δε", "δα"]
    assert elided_lemma_candidates("δέ") == []


def test_stem_shared_guards_model_lemmas():
    assert stem_shared("ἔφυγον", "φεύγω")       # vowel gradation
    assert stem_shared("θάλατταν", "θάλαττα")
    assert not stem_shared("ἵππον", "ναῦς")


def test_resolve_dialect_headword():
    table = [entry("ml:1", "μήτηρ", "a mother")]
    found, senses, info = resolve("μάτηρ", {"features": {"POS": "NOUN"}}, lookup_from(table))
    assert found["id"] == "ml:1" and senses[0]["text"] == "a mother"
    assert info["lemma_normalisation"]["rule"] == "doric_aeolic_alpha_for_eta"


def test_resolve_lemma_printed_as_form():
    table = [entry("ml:2", "Χάρις", "grace")]
    found, _, info = resolve("Χάριτες", {"features": {"POS": "NOUN"}}, lookup_from(table),
                             lambda form: ["Χάρις"] if form == "Χάριτες" else [])
    assert found["id"] == "ml:2"
    assert info["lemma_normalisation"]["rule"] == "lemma_as_attested_form"


def test_resolve_elided_lemma_only_when_unique():
    lookup = lookup_from([entry("ml:3", "δέ", "but")])
    found, _, info = resolve("δ’", {"features": {"POS": "PART"}}, lookup)
    assert found["id"] == "ml:3" and info["lemma_normalisation"]["rule"] == "elided_lemma_restored"
    lookup = lookup_from([entry("ml:3", "δέ", "but"), entry("ml:4", "δή", "now")])
    found, _, _ = resolve("δ’", {"features": {"POS": "PART"}}, lookup)
    assert found is None


def _reading(row):
    return {"readings": [{"tokens": [row]}]}


def _syntax(text, lemma, start=0):
    return {"state": "ready", "tokens": [{"text": text, "lemma": lemma, "absolute_start": start,
                                          "absolute_end": start + len(text), "prediction_status": "predicted"}]}


def test_model_lemma_used_only_when_headword_and_stem_agree():
    table = [entry("ml:5", "ἵππος", "a horse")]
    row = {"kind": "word", "text": "ἵπποισι", "start": 0, "end": 7, "lemma": None, "features": {"POS": "NOUN"},
           "gloss": {"text": None}}
    summary = attach_lemma_glosses(_reading(row), lookup_from(table), syntax=_syntax("ἵπποισι", "ἵππος"))
    assert row["lemma"] == "ἵππος" and row["gloss"]["text"] == "a horse"
    assert row["lemma_source"]["basis"] == "syntax_model_lemma_dictionary_headword"
    assert row["gloss"]["selection_basis"] == "syntax_model_lemma_dictionary_headword_first_sense_not_contextual"
    assert summary["model_lemmas"] == 1
    # A model lemma that does not share the word's letters is never shown.
    row = {"kind": "word", "text": "ἵπποισι", "start": 0, "end": 7, "lemma": None, "features": {}, "gloss": {}}
    attach_lemma_glosses(_reading(row), lookup_from([entry("ml:6", "ναῦς", "a ship")]), syntax=_syntax("ἵπποισι", "ναῦς"))
    assert row["lemma"] is None and not row["gloss"].get("text")
    # Nor one that none of the ranked parser lemmas names.
    row = {"kind": "word", "text": "ἵπποισι", "start": 0, "end": 7, "lemma": None, "features": {}, "gloss": {},
           "morphology_ranking": [{"lemma": "ἱππεύς", "score": 1.0}, {"lemma": "ἵππιος", "score": 1.0}]}
    attach_lemma_glosses(_reading(row), lookup_from(table), syntax=_syntax("ἵπποισι", "ἵππος"))
    assert row["lemma"] is None


def test_elided_lemma_display_restored_when_gloss_present():
    row = {"kind": "word", "text": "δ’", "start": 0, "end": 2, "lemma": "δ’", "features": {"POS": "PART"},
           "gloss": {"text": "but", "short_text": "but"}}
    attach_lemma_glosses(_reading(row), lookup_from([entry("ml:3", "δέ", "but")]))
    assert row["lemma"] == "δέ" and row["lemma_source"]["printed_lemma"] == "δ’"


def test_corroborated_choice_skips_unconfirmed_lead_phrase():
    from backend.short_gloss import corroborated_choice
    ml = [{"text": "alius, another, one besides"}]
    lsj_text = "ἄλλος, η, ο: another, i.e. one besides what has been mentioned"
    choice = corroborated_choice([("ML", ml, [lsj_text])])
    assert choice[1] == "another"
    # A first sense that no other dictionary prints yields to the next dictionary's.
    choice = corroborated_choice([("ML", [{"text": "exactness"}], ["now, just, indeed", "at this point: hence, now"]),
                                  ("Autenrieth", [{"text": "now, just, indeed"}], ["Particle ... exactness", "hence, now"])])
    assert choice[0]["text"] == "now, just, indeed" and choice[1] == "now"
    # Confirmed first phrases are kept; no other dictionary -> no choice.
    assert corroborated_choice([("ML", [{"text": "to be, to exist"}], ["εἰμί: be, exist"])])[1] == "to be"
    assert corroborated_choice([("ML", [{"text": "alius, another"}], [])]) is None


def test_lemma_gloss_uses_corroborated_phrase():
    ml = entry("ml:7", "ἕτερος", "alter, one of two")
    lsj = entry("lsj:7", "ἕτερος", "one or the other of two", source="LSJ (Logeion edition, H. Dik) TEI")
    lsj["rendered_entry_text"] = "ἕτερος, α, ον: one of two, the other"
    row = {"kind": "word", "text": "ἕτερον", "lemma": "ἕτερος", "features": {"POS": "ADJ"}, "gloss": {}}
    attach_lemma_glosses(_reading(row), lookup_from([ml, lsj]))
    assert row["gloss"]["short_text"] == "one of two"
    assert row["gloss"]["short_text_method"] == "corroborated_phrase"
    assert row["gloss"]["text"] == "alter, one of two"


def test_offline_variants_elision_crasis_and_alpha():
    from backend.aeolic_variants import alpha_for_eta, crasis_second_words, elision_restorations
    assert "ἀλλά" in [v["form"] for v in elision_restorations("ἀλλ’")]
    assert "φέροντα" in [v["form"] for v in elision_restorations("φέροντ’")]
    assert elision_restorations("ἀλλά") == []
    assert "ἐγώ" in [v["form"] for v in crasis_second_words("κἀγώ")]
    assert "ὄνομα" in [v["form"] for v in crasis_second_words("τοὔνομα")]
    assert "ἱμάτιον" in [v["form"] for v in crasis_second_words("θοἰμάτιον")]
    assert "ὁ" in [v["form"] for v in crasis_second_words("χὠ")]
    assert crasis_second_words("καλός") == []
    assert "μήτηρ" in [v["form"] for v in alpha_for_eta("μάτηρ")]
    assert "ἁδύς" not in [v["form"] for v in alpha_for_eta("αὐδή")]  # diphthong αυ untouched


def test_recorded_form_variant_tier_labels_parses():
    from backend.passage_analysis import PassageAnalysisService
    text = "ἀλλ’ ἔβα"
    passage = {"id": "synthetic:elision", "language": "grc", "kind": "text", "text": text,
               "author": "Synthetic fixture", "related": [], "translation_previews": []}
    recorded = {"ἀλλά": {"candidates": [{"lemma": "ἀλλά", "analysis": "c--------", "matched_form": "ἀλλά",
                                         "edit_distance": 0, "source": "synthetic treebank"}]}}

    def lookup(form, passage_id):
        return deepcopy(recorded.get(form, {"candidates": []}))

    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            return {"status": "cache_miss", "machine_candidates": [], "receipt": None}

    service = PassageAnalysisService(lambda identifier: passage if identifier == passage["id"] else None,
                                     lookup, machine_service=Machine())
    result = service.analyze({"passage_id": passage["id"], "start": 0, "end": 4, "offset_unit": "codepoint",
                              "selected_text": "ἀλλ’"})
    token = next(t for t in result["tokens"] if t["kind"] == "word")
    assert token["machine"]["status"] == "ok_normalised_source"
    candidate = token["machine"]["machine_candidates"][0]
    assert candidate["normalised_query"] == "ἀλλά" and candidate["normalisation_rule"] == "elision_restored"
    assert "matched_form" not in candidate
    row = next(r for r in result["interlinear"]["readings"][0]["tokens"] if r["kind"] == "word")
    assert row["lemma"] == "ἀλλά" and row["features"]["POS"] == "CCONJ"


def test_sense_class_label_prep_vs_adverb():
    from backend.interlinear import sense_class_compatible, sense_class_label
    entry = {"rendered_entry_text": "ἀμφί: I. adv., on both sides, about; — II. prep. w. gen., about, concerning"}
    adverb = {"text": "on both sides, about"}
    preposition = {"text": "about, concerning"}
    assert sense_class_label(adverb, entry) == "ADV"
    assert sense_class_label(preposition, entry) == "ADP"
    assert not sense_class_compatible(adverb, entry, "ADP")
    assert sense_class_compatible(preposition, entry, "ADP")
    assert sense_class_compatible(adverb, entry, "NOUN")


def test_resolve_psilotic_lemma():
    found, _, info = resolve("ὀ", {"features": {"POS": "DET"}}, lookup_from([entry("ml:8", "ὁ", "the"), entry("ml:9", "ὅ", "which")]))
    assert found["id"] == "ml:8" and info["lemma_normalisation"]["rule"] == "aeolic_psilosis_lemma"


def test_corroboration_keeps_one_letter_meanings():
    from backend.short_gloss import corroborated_choice
    choice = corroborated_choice([("Autenrieth", [{"text": "I, me."}], ["ἐγώ, gen. ἐμοῦ: I"])])
    assert choice[1] == "I"
