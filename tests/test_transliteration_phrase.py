"""Synthetic search mechanics only; these fixtures are not literary data."""
import pytest
from backend import server
from backend.morphology import _from_roman
from backend.query_expansion import phrase_token_options, indexed_phrase_plan, confirm_source_phrases
from test_api import client


def test_explicit_macrons_survive_converter_and_options():
    assert _from_roman('ēri kydōniai') == 'ηρι κυδωνιαι'
    assert _from_roman('e\u0304ri kydo\u0304niai') == 'ηρι κυδωνιαι'
    options = phrase_token_options('ēri men ai te kydōniai')
    assert options[0] == [('ηρι', 0)]
    assert options[-1] == [('κυδωνιαι', 0)]


def test_options_preserve_short_words_and_bound_ambiguities():
    options = phrase_token_options('eri men ai te kydoniai')
    vocabulary = {word: 1 for group in options for word, _ in group}
    plan = indexed_phrase_plan(options, vocabulary)
    assert 'ηρι μεν αι τε κυδωνιαι' in plan['phrases']
    assert 'ηρι μην αι τε κυδωνιαι' not in plan['phrases']  # three swaps
    assert all(len(phrase.split()) == 5 for phrase in plan['phrases'])
    assert indexed_phrase_plan(options, {'ηρι': 1}) == {}
    crowded = phrase_token_options('eeee eeee eeee eeee')
    plan = indexed_phrase_plan(crowded, {word: 1 for group in crowded for word, _ in group})
    assert len(plan['phrases']) == 32 and plan['phrases_truncated']
    assert all('ηη' not in phrase for phrase in plan['phrases'])  # one swap per word


@pytest.mark.parametrize('query', ['ἦρι men ai te kydoniai', 'eri [...] kydoniai', '123 eri kydoniai', 'eri', 'a b'])
def test_ineligible_input_does_not_create_phrase_options(query):
    assert phrase_token_options(query) == []


@pytest.mark.parametrize('text', [
    'ἦρι [...] Κυδώνιαι', 'ἦρι … Κυδώνιαι', 'ἦρι . . . Κυδώνιαι',
    'ἦρι [Κυδώνιαι]', 'ἦρι Κυ[δώ]νιαι', 'ἦρι ⟨Κυδώνιαι⟩',
    'ἦρι Κυδω\u0323νιαι', 'ἦρι, Κυδώνιαι', 'ἦρι ξένον Κυδώνιαι',
    'ἦρι ⸢Κυδώνιαι⸣', 'ἦρι ⸤Κυδώνιαι⸥', 'ἦρι 〈Κυδώνιαι〉',
])
def test_source_confirmation_never_bridges_editorial_or_word_boundaries(text):
    assert confirm_source_phrases(text, ['ηρι κυδωνιαι']) == []


def test_source_confirmation_allows_only_whitespace_and_explicit_line_division():
    assert confirm_source_phrases('ἦρι\n Κυδώνιαι.', ['ηρι κυδωνιαι']) == ['ηρι κυδωνιαι']
    assert confirm_source_phrases('ἦρι Κυδώ-\nνιαι', ['ηρι κυδωνιαι']) == ['ηρι κυδωνιαι']
    assert confirm_source_phrases('παρήρι Κυδώνιαι', ['ηρι κυδωνιαι']) == []


def test_single_guillemet_supplies_cannot_confirm_source_phrase():
    # Source-shaped typography regression, not an authored corpus record.
    # CGL354 uses these supplied-text delimiters around this printed wording.
    assert confirm_source_phrases('‹ἀλλ’ ἅθ’›', ["αλλ' αθ'"]) == []
    assert confirm_source_phrases('ἦρι ‹μὲν› Κυδώνιαι', ['ηρι μεν κυδωνιαι']) == []


ROWS = [
    {'id': 'phrase-a', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'A',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι ἄνθος'},
    {'id': 'phrase-b', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'B',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι δένδρον', 'edition': 'Other synthetic edition'},
    {'id': 'phrase-other-author', 'author': 'Beta', 'work': 'Synthetic', 'citation': 'C',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι ὕμνος'},
    {'id': 'phrase-damaged', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'D',
     'text': 'ἦρι μὲν [...] αἵ τε Κυδώνιαι'},
    {'id': 'phrase-review', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'E',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι κρυπτή', 'quality': 'needs_review'},
    {'id': 'phrase-modern', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'F',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι νέα', 'language': 'ell'},
]


@pytest.mark.parametrize('client', [ROWS], indirect=True)
def test_complete_source_phrase_filters_and_pagination(client):
    params = {'q': 'eri men ai te kydoniai', 'mode': 'words', 'author': 'Alpha', 'match': 'exact', 'limit': 1}
    pages = [client.get('/api/search', params=params | {'offset': i}).json() for i in range(3)]
    assert [page['total'] for page in pages] == [2, 2, 2]
    assert [pages[i]['results'][0]['id'] for i in range(2)] == ['phrase-a', 'phrase-b']
    assert pages[2]['results'] == []
    proof = pages[0]['transliteration_phrase']
    assert proof['matched_greek_phrases'] == ['ηρι μεν αι τε κυδωνιαι']
    assert proof['original_query'] == params['q']
    assert not proof['passages_truncated']
    assert pages[0]['results'][0]['match_reason'] == 'Source-confirmed transliteration phrase'
    assert pages[0]['results'][0]['matched_transliteration_phrases'] == proof['matched_greek_phrases']
    for filters in ({'author': 'Nobody'}, {'language': 'eng'}, {'language': 'ell'}, {'edition': 'missing'}):
        result = client.get('/api/search', params=params | filters).json()
        assert result['total'] == 0 and 'transliteration_phrase' not in result
    edition = client.get('/api/search', params=params | {'edition': 'Other synthetic edition'}).json()
    assert edition['total'] == 1 and edition['results'][0]['id'] == 'phrase-b'
    # Explicit macrons retain their long-vowel identity in ordinary exact lookup.
    macron = client.get('/api/search', params=params | {'q': 'ēri men ai te kydōniai', 'language': 'grc'}).json()
    assert macron['total'] == 2


@pytest.mark.parametrize('client', [ROWS], indirect=True)
def test_candidate_cap_is_disclosed_and_never_inflates_total(client, monkeypatch):
    from backend import query_expansion
    monkeypatch.setattr(query_expansion, 'MAX_PHRASE_PASSAGES', 1)
    result = client.get('/api/search', params={'q': 'eri men ai te kydoniai', 'mode': 'words',
                                               'author': 'Alpha', 'match': 'exact'}).json()
    assert result['total'] == 1
    assert result['transliteration_phrase']['passages_truncated']
    assert result['transliteration_phrase']['candidate_passages_checked'] == 1


@pytest.mark.parametrize('client', [[
    {'id': 'corrected', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'C',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι ἄνθος', 'quality': 'machine_corrected_ocr'},
    {'id': 'unreviewed-ocr', 'author': 'Alpha', 'work': 'Synthetic', 'citation': 'U',
     'text': 'ἦρι μὲν αἵ τε Κυδώνιαι δένδρον', 'quality': 'machine_ocr'},
]], indirect=True)
def test_existing_corrected_ocr_policy_is_preserved_without_inventing_token_coverage(client):
    for include_reference in ('false', 'true'):
        result = client.get('/api/search', params={'q': 'eri men ai te kydoniai', 'mode': 'words',
                                                   'match': 'exact', 'include_reference': include_reference}).json()
        assert [row['id'] for row in result['results']] == ['corrected']
        assert result['results'][0]['quality'] == 'machine_corrected_ocr'
        # The tier uses the existing token index; opt-in cannot manufacture a
        # token index for quarantined OCR, or relabel corrected OCR as verified.


@pytest.mark.parametrize('client', [ROWS], indirect=True)
def test_no_source_phrase_or_english_input_cannot_activate_tier(client):
    for query in ('eri te men ai kydoniai', 'the wedding of Hector and Andromache', 'xyzzy mxyzptlk'):
        result = client.get('/api/search', params={'q': query, 'mode': 'words', 'match': 'exact'}).json()
        assert result['total'] == 0 and 'transliteration_phrase' not in result


@pytest.mark.parametrize('client', [ROWS], indirect=True)
@pytest.mark.parametrize('dense_contains_phrase', [True, False])
def test_hybrid_prefers_source_phrase_over_unrelated_dense_hit(client, monkeypatch, dense_contains_phrase):
    class Sem:
        def search(self, *args, **kwargs):
            return [{'id': 'p2', 'score': .99}] + ([{'id': 'phrase-a', 'score': .8}] if dense_contains_phrase else [])
    monkeypatch.setattr(server, 'semantic_service', lambda: Sem())
    result = client.get('/api/search', params={'q': 'eri men ai te kydoniai', 'mode': 'hybrid', 'author': 'Alpha'}).json()
    assert result['results'][0]['id'] == 'phrase-a'
    assert result['transliteration_phrase']['matched_greek_phrases'] == ['ηρι μεν αι τε κυδωνιαι']
    assert result['transliteration_phrase']['ranking_policy'].startswith('Confirmed source phrases first')
    assert not any('English' in warning for warning in result['warnings'])


@pytest.mark.parametrize('client', [ROWS], indirect=True)
def test_hybrid_requested_chronology_is_not_replaced_by_phrase_priority(client, monkeypatch):
    class Sem:
        def search(self, *args, **kwargs):
            return [{'id': 'p2', 'score': .99}]
    monkeypatch.setattr(server, 'semantic_service', lambda: Sem())
    calls = []
    def ordered(results, order):
        calls.append(order)
        return sorted(results, key=lambda row: row['id'])
    monkeypatch.setattr(server, 'order_results', ordered)
    result = client.get('/api/search', params={'q': 'eri men ai te kydoniai', 'mode': 'hybrid',
                                               'author': 'Alpha', 'order': 'chronological'}).json()
    assert calls == ['chronological']
    assert result['results'][0]['id'] == 'p2'
    assert result['transliteration_phrase']['ranking_policy'].startswith('Requested chronology retained')
