"""Synthetic normalization fixtures, never corpus records."""
from backend.textutils import normalize


def test_greek_search_folds_subscript_without_adding_letter():
    assert normalize('ᾳ') == normalize('α')
    assert normalize('ῳ') == normalize('ω')


def test_search_sigma_and_editorial_text_preservation():
    assert normalize('ςϲΣ') == 'σσσ'
    assert normalize('[ἀ]') == '[α]'
    assert normalize('ἄμμι 31.7') == 'αμμι 31.7'
