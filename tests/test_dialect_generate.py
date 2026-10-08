"""Generate-and-test normalisation (release N) and editorial-bracket lookup rules.

Examples are words outside the release-M/N held-out sample.
"""
from __future__ import annotations

import unicodedata

from backend.dialect_generate import describe, elision_completions, generate, generate_and_test


def spellings(form):
    return [s for s, _ in generate(form)]


def nfc(text):
    return unicodedata.normalize("NFC", text)


def test_single_rules_produce_standard_spellings():
    assert "κτείνω" in spellings("κτέννω")          # geminate with lengthening ε -> ει
    assert "Μοῦσα" in spellings("Μοῖσα")            # οι for ου before σ
    assert "ἔχουσα" in spellings("ἔχοισα")
    assert "ὔζον" in spellings("ὔσδον")              # σδ for ζ
    assert "φίλαις" in spellings("φίλαισι")          # dative plural
    assert "ἡμέρα" in spellings("ἀμέρα")             # psilosis + ᾱ for η (two rules)
    assert "θυμός" in spellings("θῦμος")             # circumflex for acute, then accent moved


def test_bounded_and_rule_labelled():
    out = generate("ἀκαλαμάτας")
    assert len(out) <= 50 and all(1 <= len(rules) <= 3 for _, rules in out)
    assert describe(("geminate", "alpha_for_eta")).startswith("Normalised from Aeolic and Doric/Aeolic via")


def test_ou_for_u_only_on_printed_spelling():
    for _, rules in generate("Κούπρις"):
        assert "ou_for_u" not in rules[1:]


def test_elision_completion_and_aspirate_reversal():
    plain = [s for s, _ in elision_completions("ἀφ’", "ἵππων")]
    assert "ἀπό" in plain and "ἀφα" in plain
    assert ("ἀπό", ("aspirate_reversed", "elision_completed")) in elision_completions("ἀφ’", "ἵππων")
    # no rough breathing next: no τ/π/κ reading
    assert "ἀπό" not in [s for s, _ in elision_completions("ἀφ’", "ἐμοῦ")]
    assert elision_completions("οὐχ", "ὅπως") == [("οὐκ", ("aspirate_reversed",))]
    assert elision_completions("δ’", "ἔβα") == []    # a lone consonant is left to the parser
    assert describe(("aspirate_reversed", "elision_completed")).startswith("Projection:")


def engine(known):
    def analyze(spelling):
        if spelling in known:
            return {"status": "ok", "machine_candidates": [{"lemma": known[spelling], "features": {"pofs": "verb"}}]}
        return {"status": "no_analyses", "machine_candidates": []}
    return analyze


def test_generate_and_test_keeps_cheapest_successes_only():
    asked = []
    known = {"κτείνω": "κτείνω", "κτεινώ": "wrong"}

    def analyze(spelling):
        asked.append(spelling)
        return engine(known)(spelling)
    accepted, tried = generate_and_test("κτέννω", analyze)
    assert [s for s, _, _ in accepted] == ["κτείνω"]
    assert len(tried) == len(asked) and len(asked) <= 50
    nothing, tried = generate_and_test("ξξξ", engine({}))
    assert nothing == []


def test_passage_analysis_labels_generated_spellings(monkeypatch):
    from backend.passage_analysis import PassageAnalysisService
    monkeypatch.setenv("MELOS_MORPHEUS_LOCAL", "http://melos-morpheus:8080/api/v1/analysis/word")
    text = "κτέννω σε"
    passage = {"id": "synthetic:gen", "language": "grc", "kind": "text", "text": text,
               "author": "Synthetic fixture", "related": [], "translation_previews": []}

    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            if form == "κτείνω":
                return {"status": "ok", "receipt": {"id": "b" * 64}, "machine_candidates": [
                    {"id": "machine:x", "lemma": "κτείνω", "candidate_kind": "machine_analysis",
                     "basis": "machine_analysis", "receipt_id": "b" * 64,
                     "features": {"pofs": "verb", "pers": "1st", "num": "singular", "tense": "present",
                                  "mood": "indicative", "voice": "active"}}]}
            return {"status": "no_analyses", "machine_candidates": [], "receipt": None}

    service = PassageAnalysisService(lambda identifier: passage if identifier == passage["id"] else None,
                                     lambda form, pid: {"candidates": []}, machine_service=Machine())
    result = service.analyze({"passage_id": passage["id"], "start": 0, "end": 6, "offset_unit": "codepoint",
                              "selected_text": "κτέννω"})
    token = next(t for t in result["tokens"] if t["kind"] == "word")
    assert token["machine"]["status"] == "ok_normalised"
    candidate = token["machine"]["machine_candidates"][0]
    assert candidate["normalised_query"] == "κτείνω" and candidate["normalised_from"] == "κτέννω"
    assert candidate["normalisation_note"].startswith("Normalised from Aeolic via")
    assert token["text"] == "κτέννω"


def test_word_absorbs_edge_bracket_it_closes_or_opens():
    from backend.passage_analysis import tokenize_span
    def words(text):
        return [(t["text"], t["form"]) for t in tokenize_span(text, 0, len(text)) if t["kind"] == "word"]
    assert words("καὶ [τ]ὰν πόλιν") == [("καὶ", "καὶ"), ("[τ]ὰν", "τὰν"), ("πόλιν", "πόλιν")]
    assert words("ἔχοντε[ς] νῦν") == [("ἔχοντε[ς]", "ἔχοντες"), ("νῦν", "νῦν")]
    tokens = tokenize_span("[τὰν] πόλιν", 0, 11)
    assert [t["text"] for t in tokens][:3] == ["[", "τὰν", "]"]   # whole-word supplement unchanged
    for t in tokens:
        assert "[τὰν] πόλιν"[t["start"]:t["end"]] == t["text"]


def test_editorial_lookup_form_strips_marks_inside_one_word():
    from backend.passage_analysis import editorial_lookup_form
    assert editorial_lookup_form("ἄ[ρι]στος") == "ἄριστος"
    assert editorial_lookup_form("ἀμφι⟨βάλων⟩") == "ἀμφιβάλων"
    assert editorial_lookup_form(nfc("τὸ̣ν")) == "τὸν"
    assert editorial_lookup_form("ἀλλ’") == "ἀλλ’"
    assert editorial_lookup_form("[ ]") == "[ ]" and editorial_lookup_form("οὐ [κ]") == "οὐ [κ]"
