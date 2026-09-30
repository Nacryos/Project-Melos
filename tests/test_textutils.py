"""Synthetic normalization fixtures, never corpus records."""
from backend.textutils import normalize, search_text, tokenize


def test_search_only_joins_greek_explicit_line_divisions():
    original = 'φωνεί-\nσας τεθυμιάμε-\r\n  νοι'
    assert search_text(original) == 'φωνείσας τεθυμιάμενοι'
    assert original == 'φωνεί-\nσας τεθυμιάμε-\r\n  νοι'
    assert tokenize(search_text(original)) == ['φωνείσας', 'τεθυμιάμενοι']


def test_search_does_not_reconstruct_uncertain_or_nondivided_text():
    for original in ['φωνεί- σας', 'φωνεί\nσας', 'φωνεί-\n[σας]',
                     'φωνεί-\n4 σας', 'φωνεί-\n\nσας', 'un-\nknown',
                     'φωνεί—\nσας', 'φωνεί-\n…σας']:
        assert search_text(original) == original


def test_greek_search_folds_subscript_without_adding_letter():
    assert normalize('ᾳ') == normalize('α')
    assert normalize('ῳ') == normalize('ω')


def test_search_sigma_and_editorial_text_preservation():
    assert normalize('ςϲΣ') == 'σσσ'
    assert normalize('[ἀ]') == '[α]'
    assert normalize('ἄμμι 31.7') == 'αμμι 31.7'
