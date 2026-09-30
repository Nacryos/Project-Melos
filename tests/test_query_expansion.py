"""Synthetic, source-vocabulary-shaped fixtures for retrieval spelling keys."""

from backend.morphology import query_variants
from backend.query_expansion import fallback_tokens


def test_plain_roman_vowels_resolve_only_to_indexed_greek_forms():
    vocabulary = {"γυγεω", "του", "πολυχρυσου", "ευδουσιν", "ορεων",
                  "κορυφαι", "βαλλων", "χρυσοκομησ", "ερωσ", "βαλλον", "εροσ"}
    cases = {
        "Gygeo tou polychrysou": {"γυγεω", "πολυχρυσου"},
        "Eudousin d' oreon koryphai": {"ευδουσιν", "ορεων", "κορυφαι"},
        "ballon chrysokomes Eros": {"βαλλων", "χρυσοκομησ", "ερωσ"},
    }
    for query, expected in cases.items():
        found = fallback_tokens(query, query_variants(query), vocabulary)
        assert expected <= set(found)
        assert set(found) <= vocabulary


def test_exact_transliteration_does_not_widen_to_near_words():
    vocabulary = {"ουκ", "εστ", "ετυμοσ", "λογοσ", "ουτοσ", "ουτωσ", "ετυμωσ"}
    query = "ouk est etymos logos outos"
    assert fallback_tokens(query, query_variants(query), vocabulary) == [
        "ουκ", "εστ", "ετυμοσ", "λογοσ", "ουτοσ"]


def test_english_description_and_weak_matches_abstain():
    vocabulary = {"αφροδιτα", "ερωσ", "καλαν", "μεν", "θαλασσα"}
    for query in ("golden crowned Aphrodite", "wine dark sea", "love and longing",
                  "Eros", "θαλασσα and sea"):
        assert fallback_tokens(query, query_variants(query), vocabulary) == []


def test_bounded_output_and_no_invented_inflections():
    query = "Gygeo tou polychrysou"
    vocabulary = {"γυγεω", "του", "πολυχρυσου"}
    found = fallback_tokens(query, query_variants(query), iter(vocabulary))
    assert set(found) == vocabulary
    assert fallback_tokens("word " * 9, query_variants("word " * 9), vocabulary) == []
    assert len(found) <= 16
