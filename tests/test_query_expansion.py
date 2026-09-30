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


def test_incidental_beta_tokens_do_not_replace_a_description():
    # Synthetic vocabulary reproduces the actual faulty converter matches;
    # these are retrieval fixtures, not scholarly claims about either token.
    query = "the wedding of Hector and Andromache"
    vocabulary = {"τηε", "ανδ", "ανδρομαχη"}
    assert fallback_tokens(query, query_variants(query), vocabulary) == []


def test_unknown_source_words_stay_in_coverage_denominator():
    query = "logos etymos unknown vanished"
    # A defective/partial converter cannot assert full coverage after dropping
    # source words, even if all its remaining tokens are indexed.
    assert fallback_tokens(query, ["λογοσ ετυμοσ"], {"λογοσ", "ετυμοσ"}) == []
    assert fallback_tokens(query, ["λογοσ ετυμοσ ζζζ ψψψ"], {"λογοσ", "ετυμοσ"}) == []


def test_repeated_one_anchor_is_not_two_distinct_anchors():
    query = "logos logos"
    assert fallback_tokens(query, query_variants(query), {"λογοσ"}) == []


def test_terminal_sign_is_not_removed_to_claim_an_indexed_whole_word():
    query = "logos etymos est'"
    assert fallback_tokens(query, query_variants(query), {"λογοσ", "ετυμοσ", "εστ"}) == []
    found = fallback_tokens(query, query_variants(query), {"λογοσ", "ετυμοσ", "εστ'"})
    assert "εστ'" in found
    assert "εστ" not in found
    psili = "logos etymos est᾿"
    assert fallback_tokens(psili, query_variants(psili), {"λογοσ", "ετυμοσ", "εστ'"}) == []
    assert "εστ᾿" in fallback_tokens(psili, query_variants(psili), {"λογοσ", "ετυμοσ", "εστ᾿"})


def test_greek_punctuation_is_not_a_language_letter_or_coverage_word():
    query = "logos etymos ·"
    assert fallback_tokens(query, query_variants(query), {"λογοσ", "ετυμοσ"}) == ["λογοσ", "ετυμοσ"]


def test_dropped_word_plus_split_word_cannot_fake_aligned_coverage():
    query = "logos eros v lovalon"
    # The beta converter drops v and splits lovalon into lo + alon, leaving
    # the same aggregate word count. Per-source-word alignment must reject it.
    assert fallback_tokens(query, query_variants(query), {"λογοσ", "εροσ", "αλον"}) == []
