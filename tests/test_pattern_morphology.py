"""Ending-based analyses: the last tier for words no lexicon or parser knows."""
from backend.interlinear import canonical_features, compact_parse
from backend.pattern_morphology import pattern_candidates


def parses(form, pos=None):
    return [compact_parse(canonical_features(c)) for c in pattern_candidates(form, pos)]


def test_nominal_endings_give_labelled_case_number_gender():
    assert "acc. masc. sg." in parses("Ὕρραον", "NOUN")
    assert "dat. fem. pl." in parses("λυκαιμίαις", "ADJ")
    assert "gen. pl." in parses("τυνδέων", "NOUN")
    assert "nom. fem. pl." in parses("ἄγκονναι", "NOUN")
    assert "acc. fem. sg." in parses("Αἰολήαν", "ADJ")
    for candidate in pattern_candidates("Ὕρραον", "NOUN"):
        assert candidate["candidate_kind"] == "pattern_analysis"
        assert candidate["lemma"] is None and candidate["tier"] == "ending_pattern_only"
        assert candidate["pattern_ending"] == "ον" and "ending" in candidate["note"]


def test_verbal_endings_follow_the_predicted_part_of_speech():
    assert "1st sg. pres. ind. act." in parses("ἀσυννέτημμι", "VERB")
    assert not any("pres." in parse for parse in parses("ἀσυννέτημμι", "NOUN"))
    # Without a prediction both tables are consulted.
    both = parses("ἔλυσα")
    assert "nom. fem. sg." in both and "1st sg. aor. ind. act." in both


def test_short_or_endingless_forms_yield_nothing():
    assert pattern_candidates("ἀ", "NOUN") == []
    assert pattern_candidates("κρ", "NOUN") == []
    assert len(pattern_candidates("Ὦγεσιλαΐδα", "NOUN")) <= 6
