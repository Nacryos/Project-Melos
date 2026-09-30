"""Synthetic spelling-boundary tests, not historical attestations."""
import pytest

from backend.server import phrase_pattern
from backend.textutils import normalize
from test_api import client


def matches(query, text):
    return bool(phrase_pattern(normalize(query)).search(normalize(text)))


def test_exact_words_do_not_claim_elided_and_bare_forms_are_identical():
    for mark in "'’᾽ʼ":
        assert matches("α'", 'α' + mark + ' β')
        assert not matches('α', 'α' + mark + ' β')
        assert not matches("α'", 'α β')
        assert not matches('β', 'α' + mark + 'β')
        assert not matches("α'", 'α' + mark + 'β')
        assert matches("α'β", 'α' + mark + 'β')
    assert matches('α β', 'α\nβ')
    assert not matches('α β', 'α, β')


def test_adjacent_quotes_are_literal_without_supplying_editorial_interpretations():
    assert matches("α'", "'α'")
    assert not matches('α', "'α'")
    assert matches('α', '“α”')
    assert matches("α'", "α''β")
    assert matches('β', "α''β")
    assert not matches('β', "α'β")


def test_non_greek_wording_keeps_existing_quotation_and_possessive_behavior():
    assert matches('love', "'love'")
    assert matches('students', "students' notes")
    assert matches('amor', "'amor'")
    assert matches('café', "'café'")


@pytest.mark.parametrize('client', [[
    {'id': 'terminal', 'text': 'αβγ’ δεζ'},
    {'id': 'bare', 'text': 'αβγ δεζ'},
    {'id': 'internal', 'text': 'αβγ’δεζ'},
]], indirect=True)
def test_exact_api_returns_only_literal_whole_form(client):
    for query, expected in [("αβγ'", 'terminal'), ('αβγ', 'bare'), ("αβγ'δεζ", 'internal')]:
        result = client.get('/api/search', params={'q': query, 'mode': 'words', 'match': 'exact'}).json()
        assert {row['id'] for row in result['results']} == {expected}
