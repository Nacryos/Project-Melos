"""Release O parser rules: dictionary headword over a model guess, names take the being's sense,
one ranked headline headword (passage rows and /api/word). Words differ from the audited ones."""
from __future__ import annotations

from backend.interlinear import _choose
from backend.lemma_glosses import choose, headline_choice
from backend.short_gloss import being_senses_first, sense_names_a_being
from backend.word_parser_candidates import enrich_word_result, word_headline

LSJ = "LSJ (Logeion edition, H. Dik) TEI"
ML = "Perseus Middle Liddell TEI (Hopper open-source texts)"


def machine(identifier, lemma, **features):
    return {"id": identifier, "lemma": lemma, "receipt_id": "c" * 64, "features": features,
            "basis": "machine_analysis", "candidate_kind": "machine_analysis"}


def headword_token(form, entries=(), extra=()):
    return {"text": form, "form": form,
            "source_candidates": [{"id": "s1", "lemma": form, "matched_form": form, "edit_distance": 0, "source": LSJ}],
            "machine": {"machine_candidates": [machine("m1", "ὕω", pofs="verb", mood="optative", num="singular",
                                                       pers="3rd", tense="present", voice="active"), *extra]},
            "lexicon_entries": list(entries)}


VERB_GUESS = {"upos": "VERB", "lemma": "ὕψω", "features": {"Mood": "Ind", "Number": "Plur", "Person": "3",
                                                         "Tense": "Pres", "VerbForm": "Fin", "Voice": "Act"}}


def test_printed_headword_is_not_overridden_by_a_model_pos_guess():
    token = headword_token("ὕψι")
    chosen, basis, _ = _choose(token, VERB_GUESS, None)
    assert basis == "printed_form_dictionary_headword_over_model" and chosen["lemma"] == "ὕψι"


def test_printed_headword_keeps_the_parse_of_its_cross_reference_target():
    pointer = {"id": "lsj:x", "lemma": "ὄψοι", "source": LSJ, "entry_text": "ὄψοι, Aeol. for ὀψέ"}
    token = headword_token("ὄψοι", [pointer], [machine("m2", "ὀψέ", pofs="adverb")])
    chosen, basis, _ = _choose(token, VERB_GUESS, None)
    assert basis == "printed_form_dictionary_headword_over_model" and chosen["lemma"] == "ὀψέ"


def test_model_lemma_naming_the_parse_is_strong_evidence():
    chosen, basis, _ = _choose(headword_token("ὕψι"), {**VERB_GUESS, "lemma": "ὕω"}, None)
    assert basis != "printed_form_dictionary_headword_over_model"


def test_model_agreeing_with_the_whole_other_parse_is_strong_evidence():
    agreeing = {"upos": "VERB", "lemma": "ὕψι", "features": {"Mood": "Opt", "Number": "Sing", "Person": "3",
                                                           "Tense": "Pres", "Voice": "Act"}}
    chosen, basis, _ = _choose(headword_token("ὕψι"), agreeing, None)
    assert basis != "printed_form_dictionary_headword_over_model" and chosen["lemma"] == "ὕω"


def test_elided_forms_are_left_to_the_ranking():
    token = headword_token("ὕψ’")
    assert _choose(token, VERB_GUESS, None)[1] != "printed_form_dictionary_headword_over_model"


def dictionary_sense(entry_id, number, text):
    return {"id": f"{entry_id}:{number}", "text": text, "evidence_type": "dictionary_sense", "source": ML,
            "source_url": "https://example.org/ml", "source_locator": {"n": number}, "raw_sha256": "a" * 64,
            "lexicon_entry_id": entry_id}


def test_being_sense_detection():
    assert sense_names_a_being({"text": "the Graces"}) and sense_names_a_being({"text": "a Nymph"})
    assert not sense_names_a_being({"text": "grace, loveliness"})
    assert not sense_names_a_being({"text": "used of Apollo"}) and not sense_names_a_being({"text": "Also, later"})
    senses = [{"text": "grace"}, {"text": "the Graces"}]
    assert [s["text"] for s in being_senses_first(senses)] == ["the Graces", "grace"]


def test_capitalised_word_takes_the_sense_naming_the_being():
    entry = {"id": "ml:charis", "lemma": "χάρις", "source": ML,
             "dictionary_senses": [dictionary_sense("ml:charis", "I", "grace, loveliness"),
                                   dictionary_sense("ml:charis", "II", "the Graces")]}
    named = choose([entry], {"text": "Χάριτες", "features": {"POS": "NOUN"}}, homograph_marked=False)
    common = choose([entry], {"text": "χάριτες", "features": {"POS": "NOUN"}}, homograph_marked=False)
    assert named[1][0]["text"] == "the Graces" and common[1][0]["text"] == "grace, loveliness"


def test_headline_breaks_a_tie_by_model_pos_then_frequency_and_drops_the_elided_spelling():
    row = {"kind": "word", "text": "μ’", "lemma": None,
           "morphology_ranking": [{"candidate_id": "a", "lemma": "ἐγώ", "score": 1.0},
                                  {"candidate_id": "b", "lemma": "ἐμός", "score": 0.8},
                                  {"candidate_id": "c", "lemma": "μ’", "score": 1.2}],
           "candidate_meanings": [{"candidate_id": "a", "features": {"POS": "PRON"}},
                                  {"candidate_id": "b", "features": {"POS": "ADJ"}}]}
    found = headline_choice(row, prediction={"upos": "PRON", "lemma": "με"}, next_text="ἔχει")
    assert found["headline_lemma"] == "ἐγώ" and found["headline_basis"] == "tie_broken_by_context_model_pos"
    assert found["headline_evidence"] == ["elided_before_vowel"] and found["headline_alternatives"] == ["ἐμός"]
    found = headline_choice(row, attestations={"ἐγώ": 3, "ἐμός": 40}.get, next_text="ἔχει")
    assert found["headline_lemma"] == "ἐμός" and found["headline_basis"] == "tie_broken_by_frequency_prior"
    assert found["headline_tie_broken"]


def test_headline_of_a_selected_row_is_its_dictionary_headword():
    row = {"kind": "word", "text": "Χάριτες", "lemma": "Χάριτες", "selection_basis": "morphology_ranked_by_syntax",
           "gloss": {"lemma_dictionary": {"status": "available", "lemma": "Χάριτες",
                                          "lemma_normalisation": {"rule": "lemma_as_attested_form", "to": "χάρις"}}},
           "morphology_ranking": [{"lemma": "Χάριτες", "score": 3.0}]}
    lookup = {"Χάρις": {"match": "exact_headword", "entries": [{"id": "x", "lemma": "Χάρις"}]}}.get
    found = headline_choice(row, lookup=lambda value: lookup(value) or {})
    assert found["headline_lemma"] == "Χάρις" and found["headline_basis"] == "morphology_ranked_by_syntax"


class NoEngine:
    def analyze(self, form, visitor, fetch=False):
        return {"status": "no_analyses", "machine_candidates": [], "receipt": None}


def test_word_lookup_returns_a_ranked_headline():
    result = {"form": "μ’", "analysis_match_status": "source_analysis_available",
              "context": {"text": "ἀλλά μ’ ἔχει πόθος"},
              "candidates": [{"lemma": "μ’", "matched_form": "μ’", "edit_distance": 0},
                             *[{"lemma": "ἐγώ", "matched_form": "μ᾽", "analysis": "p-s---ma-"} for _ in range(2)],
                             *[{"lemma": "ἐμός", "matched_form": "μ᾽", "analysis": "a-p---na-"} for _ in range(2)],
                             {"lemma": "μέν", "matched_form": "μέν", "analysis": "d--------", "edit_distance": 2}]}
    enrich_word_result(result, "μ’", machine_service=NoEngine(), lemma_attestations={"ἐγώ": 60, "ἐμός": 20}.get)
    assert result["headline_lemma"] == "ἐγώ" and result["headline_basis"] == "tie_broken_by_frequency_prior"
    assert result["headline_alternatives"] == ["ἐμός"] and result["headline_evidence"] == ["elided_before_vowel"]
    again = enrich_word_result(dict(result), "μ’", machine_service=NoEngine(), lemma="ἐμός")
    assert again["headline_lemma"] == "ἐμός" and again["headline_basis"] == "caller_lemma"


class RestoringEngine:
    """Parses only the restored spellings με (ἐγώ acc.) and μά (a made-up neut. pl. of ἐμός)."""
    known = {"με": ("ἐγώ", {"pofs": "pronoun", "case": "accusative", "num": "singular", "pers": "1st"}),
             "μά": ("ἐμός", {"pofs": "adjective", "case": "accusative", "num": "plural", "gend": "neuter"})}

    def __init__(self):
        self.asked = []

    def analyze(self, form, visitor, fetch=False):
        self.asked.append(form)
        if form in self.known:
            lemma, features = self.known[form]
            return {"status": "ok", "machine_candidates": [{"id": form, "lemma": lemma, "features": features}]}
        return {"status": "no_analyses", "machine_candidates": [], "receipt": None}


def test_word_lookup_tie_lists_each_restored_form_and_parse():
    from backend.word_parser_candidates import elision_restorations
    engine = RestoringEngine()
    found = elision_restorations("μ’", "μ’", engine)
    assert found == {"ἐγώ": [{"restored_form": "με", "parse": "acc. 1st sg."}],
                     "ἐμός": [{"restored_form": "μά", "parse": "acc. neut. pl."}]}
    assert all(spelling[1:] in ("ε", "έ", "α", "ά", "ο", "ό", "ι", "ί", "αι", "αί", "οι", "οί") for spelling in engine.asked)
    result = {"form": "μ’", "context": {"text": "ἀλλά μ’ ἔχει"},
              "candidates": [{"lemma": "ἐγώ", "matched_form": "μ᾽", "analysis": "p"},
                             {"lemma": "ἐμός", "matched_form": "μ᾽", "analysis": "a"}]}
    enrich_word_result(result, "μ’", machine_service=engine, lemma_attestations={"ἐγώ": 9, "ἐμός": 4}.get)
    assert result["headline_lemma"] == "ἐγώ" and result["headline_tie_broken"]
    assert [(a["lemma"], a["readings"][0]["restored_form"]) for a in result["alternatives"]] == [("ἐγώ", "με"), ("ἐμός", "μά")]


def test_lemma_fast_path_returns_the_dictionary_with_the_full_shape():
    from backend.word_parser_candidates import lemma_dictionary_result
    lookup = {"χάρις": {"match": "exact_headword", "entries": [{"id": "x", "lemma": "χάρις", "dictionary_senses": []}]}}.get
    result = lemma_dictionary_result("χάρις", "χάρις", lambda value: lookup(value) or {})
    assert result["lookup_mode"] == "lemma_dictionary_fast_path" and result["headline_lemma"] == "χάρις"
    assert [e["id"] for e in result["lexicon_entries"]] == ["x"] and result["candidates"] == []
    assert {"occurrences", "contextual_candidates", "parser_candidates", "selected_lemma"} <= set(result)


def test_word_lookup_headline_prefers_the_dictionary_reading_of_a_printed_headword():
    result = {"form": "ὄψοι", "candidates": [{"lemma": "ὄψοι", "matched_form": "ὄψοι", "edit_distance": 0}],
              "parser_candidates": [{"lemma": "ὕω", "candidate_kind": "machine_analysis", "analysis_text": "3rd sg."},
                                    {"lemma": "ὕω", "candidate_kind": "machine_analysis", "analysis_text": "3rd sg."},
                                    {"lemma": "ὀψέ", "candidate_kind": "machine_analysis", "analysis_text": "adv."}]}
    entries = {"ὄψοι": [{"id": "p", "lemma": "ὄψοι", "entry_text": "ὄψοι, Aeol. for ὀψέ"}],
               "ὀψέ": [{"id": "q", "lemma": "ὀψέ"}], "ὕω": [{"id": "r", "lemma": "ὕω"}]}
    lookup = lambda value: {"match": "exact_headword", "entries": entries.get(value, [])}
    found = word_headline(result, "ὄψοι", headword_lookup=lookup, attestations={"ὕω": 30, "ὀψέ": 5}.get)
    assert found["headline_lemma"] == "ὀψέ" and found["headline_basis"] == "dictionary_reading_of_printed_form"
