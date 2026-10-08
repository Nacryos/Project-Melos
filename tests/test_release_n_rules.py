"""General rules added in release N from the live audit. Words are outside the held-out sample."""
from __future__ import annotations

from backend.interlinear import _dedupe_ranking, candidate_identity
from backend.lemma_glosses import attested_tie_lemma
from backend.pattern_morphology import pattern_candidates
from backend.short_gloss import corroborated_choice, normalise_gloss_case
from backend.source_labels import source_label
from backend.word_parser_candidates import clean_sense_labels, enrich_word_result, lemma_key


def features(form, pos="VERB", verbform=None):
    return [c["features"] for c in pattern_candidates(form, pos, predicted_verbform=verbform)]


def test_participle_and_imperative_endings_before_finite_ones():
    assert features("λύουσα")[0] == {"case": "Nom", "num": "Sing", "voice": "Act", "verbform": "Part",
                                      "gend": "Fem", "tense": "Pres", "pofs": "VERB"}
    assert {f["case"] for f in features("παιδευομένῳ")} == {"Dat"}
    assert features("γραφέσθω")[0]["mood"] == "Imp" and features("γραφέσθω")[0]["pers"] == "3"
    assert features("ἐπαίδευσαν")[0]["pers"] == "3" and features("ἐπαίδευσαν")[0]["num"] == "Plur"


def test_iota_subscript_endings_match():
    assert features("χλωρᾷ", "ADJ")[0]["case"] == "Dat"
    assert features("λευκῇ", "ADJ")[0] == {"case": "Dat", "num": "Sing", "gend": "Fem", "pofs": "ADJ"}


def test_attested_tie_lemma_only_when_one_is_attested():
    row = {"morphology_ranking": [{"lemma": "ἀγείρω", "score": 3.0}, {"lemma": "καταγείρω", "score": 3.0}]}
    counts = {"ἀγείρω": 12, "καταγείρω": 0}
    assert attested_tie_lemma(row, counts.get) == "ἀγείρω"
    assert attested_tie_lemma(row, {"ἀγείρω": 12, "καταγείρω": 6}.get) is None
    assert attested_tie_lemma(row, {"ἀγείρω": 3, "καταγείρω": 0}.get) is None


def sense(text, identifier):
    return {"id": identifier, "text": text}


def test_corroboration_prefers_most_confirmed_phrase_and_lower_case():
    groups = [("A", [sense("formerly, of old", "a1")], ["of old", "of old, long ago", "formerly"]),
              ("B", [sense("of old", "b1")], ["formerly, of old"])]
    assert corroborated_choice(groups)[1] == "of old"
    groups = [("A", [sense("Muse", "a1")], ["the muse", "muse"]), ("B", [sense("muse", "b1")], ["Muse"])]
    assert corroborated_choice(groups)[1] == "muse"
    groups = [("A", [sense("Apollo", "a1")], ["Apollo, god of song"]), ("B", [sense("Apollo", "b1")], ["Apollo"])]
    assert corroborated_choice(groups)[1] == "Apollo"


def test_gloss_case_follows_the_headword():
    assert normalise_gloss_case({"short_text": "To run"}, "τρέχω")["short_text"] == "to run"
    assert normalise_gloss_case({"short_text": "Apollo"}, "Ἀπόλλων")["short_text"] == "Apollo"
    assert normalise_gloss_case({"short_text": "I"}, "ἐγώ")["short_text"] == "I"
    assert normalise_gloss_case({"short_text": "NT word"}, "λόγος")["short_text"] == "NT word"


def test_ranking_dedupes_breathing_and_case_variants_only():
    rows = [{"lemma": "ἵππος", "features": {"pos": "NOUN", "case": "Nom"}},
            {"lemma": "ἴππος", "features": {"pos": "NOUN", "case": "Nom"}},   # smooth breathing
            {"lemma": "Ἵππος", "features": {"pos": "NOUN", "case": "Nom"}},   # capitalised
            {"lemma": "Ἵππος", "features": {"pos": "ADJ", "case": "Nom"}},    # another word class
            {"lemma": "ἱππός", "features": {"pos": "NOUN", "case": "Nom"}}]   # another accent
    ranking = [{"candidate_id": candidate_identity(r), "lemma": r["lemma"], "parse_short": "nom."} for r in rows]
    kept = _dedupe_ranking(ranking, rows)
    assert [item["lemma"] for item in kept] == ["ἵππος", "Ἵππος", "ἱππός"]
    assert len(kept) == 3


def test_sense_labels_that_are_not_numbers_are_moved():
    entry = {"dictionary_senses": [{"sense_path": [{"n": "Perseus"}]}, {"sense_path": [{"n": "II"}]},
                                   {"sense_path": [{"n": "3"}]}]}
    clean_sense_labels(entry)
    assert entry["dictionary_senses"][0]["sense_path"][0] == {"n": None, "n_raw": "Perseus"}
    assert "Perseus editors" in entry["dictionary_senses"][0]["sense_note"]
    assert [s["sense_path"][0]["n"] for s in entry["dictionary_senses"][1:]] == ["II", "3"]


def test_source_labels_are_readable():
    assert source_label("campbell_assignment").startswith("Campbell")
    assert source_label("new_collection") == "New Collection"


class Engine:
    def __init__(self, known):
        self.known = known

    def analyze(self, form, visitor, fetch=False):
        if form in self.known:
            return {"status": "ok", "receipt": {"id": "c" * 64, "parser_version": "morpheus-local-v1",
                                                "engine_revision": "alpheios-project/morpheus@" + "1" * 40 + " (dist/stemlib); x"},
                    "machine_candidates": [{"id": "m1", "lemma": self.known[form], "receipt_id": "c" * 64,
                                            "features": {"pofs": "noun", "case": "nominative", "num": "singular"}}]}
        return {"status": "no_analyses", "machine_candidates": [], "receipt": None}


def test_word_lookup_gets_parser_candidates_and_headword_entries():
    result = {"form": "χώρα", "analysis_match_status": "spelling_suggestions_only",
              "candidates": [{"lemma": "χῶρος", "analysis": "n-s---mn-"}],
              "lexicon_entries": [{"id": "x", "lemma": "χῶρος", "dictionary_senses": []}]}
    headwords = {"χώρα": {"match": "exact_headword", "entries": [{"id": "y", "lemma": "χώρα", "dictionary_senses": []}]}}
    enrich_word_result(result, "χώρα", machine_service=Engine({"χώρα": "χώρα"}), headword_lookup=headwords.get)
    assert result["analysis_match_status"] == "parser_analysis_only"
    assert result["spelling_suggestions"][0]["lemma"] == "χῶρος"
    assert [c["lemma"] for c in result["candidates"]] == ["χώρα"]
    assert result["parse_source"]["kind"] == "machine_analysis" and "local build" in result["parse_source"]["label"]
    assert {e["id"] for e in result["lexicon_entries"]} == {"x", "y"}


def test_word_lookup_nfc_lemmas_and_requested_headword_first():
    oxia = "εἰμί"  # εἰμί written with U+1F77
    result = {"form": "εἰμί", "analysis_match_status": "headword_only", "candidates": [],
              "lexicon_entries": [{"id": "a", "lemma": "εἶμι"}, {"id": "b", "lemma": oxia}]}
    enrich_word_result(result, "εἰμί", machine_service=Engine({}), lemma="εἰμί")
    assert result["lexicon_entries"][0]["id"] == "b" and result["lexicon_entries"][0]["lemma_raw"] == oxia
    assert lemma_key("†εἰμί") == lemma_key(oxia)


def test_capitalised_headword_uses_lower_case_entry_only_if_it_names_a_being():
    from backend.short_gloss import entry_names_a_being
    assert entry_names_a_being({"dictionary_senses": [{"text": "a maiden"}, {"text": "II. a Muse, goddess of song"}]})
    assert not entry_names_a_being({"dictionary_senses": [{"text": "the care of a household"}],
                                    "entry_text": "Xen. Oec. 3.4, Plat."})
