"""Labelled Aeolic spelling normalisations used only as parser query variants."""
from backend.aeolic_variants import variants


def rules(form):
    return [(item["form"], item["rule"]) for item in variants(form)]


def test_psilotic_rho_and_psilosis_restore_the_standard_breathing():
    assert ("ῥήα", "psilotic_rho") in rules("ῤήα")
    assert ("ῥύεσθαι", "psilotic_rho") in rules("ῤύεσθαι")
    assert ("ὑπ’", "psilosis") in rules("ὐπ’")
    assert ("ὡς", "psilosis") in rules("ὠς")


def test_apocope_rebuilds_the_full_prefix():
    assert ("ἀνατρέχοντες", "apocope_ὀν") in rules("ὀντρέχοντες")
    assert ("καταγεγήρασ’", "apocope_καγ") in rules("καγγεγήρασ’")
    # Before a vowel there is no apocope to undo.
    assert not any(rule.startswith("apocope") for _, rule in rules("ὀνέπλησε"))


def test_recessive_accent_moves_one_vowel_group_right():
    assert ("τηλόθεν", "recessive_accent") in rules("τήλοθεν")
    assert ("ἐκτός", "recessive_accent") in rules("ἔκτος")
    # Diphthong: the acute lands on the second vowel.
    assert ("φιλαίτερος", "recessive_accent") in rules("φίλαιτερος")
    # A word accented on its last vowel group has nowhere to move.
    assert not any(rule == "recessive_accent" for _, rule in rules("πόλις")) or rules("πόλις")[0][0] == "πολίς"
    assert not any(rule == "recessive_accent" for _, rule in rules("ἐγώ"))


def test_gemination_zeta_and_onyma_rules_are_labelled():
    assert ("Ἐρίνυς", "aeolic_gemination_νν") in rules("Ἐρίννυς")
    assert ("καρυσσομένας", "aeolic_zeta_for_sigma") in rules("καρυζομένας")
    assert ("ὀνομακλέης", "aeolic_onyma") in rules("ὀνυμακλέης")


def test_circumflex_eu_and_capitalised_onyma_rules():
    assert ("κείσεσθ’", "circumflex_for_acute") in rules("κεῖσεσθ’")
    assert ("ἐρρύσαο", "aeolic_eu_for_err") in rules("εὐρύσαο")
    assert ("Ὀνομακλέης", "aeolic_onyma") in rules("Ὀνυμακλέης")


def test_every_variant_is_labelled_distinct_and_bounded():
    for form in ("ῤήα", "ὀντρέχοντες", "Ἐρίννυς", "ἄμμι", "ἔγων’", "δεῦτέ"):
        found = variants(form)
        assert len(found) <= 4
        assert len({item["form"] for item in found}) == len(found)
        assert all(item["form"] != form and item["tier"] == "dialect_normalised_query" and item["note"] for item in found)
