"""Synthetic language and display-policy fixtures, not corpus additions."""
from copy import deepcopy

import pytest

from backend.translation_languages import is_english_language, is_english_translation
from backend.passage_ranker import _translations
from backend import server
from test_api import client


@pytest.mark.parametrize('language', ['en', 'eng', 'EN', 'en-GB', 'en-US', 'eng-GB', ' en '])
def test_explicit_english_language_codes(language):
    assert is_english_language(language)
    assert is_english_translation({'language': language})


@pytest.mark.parametrize('language', ['ell', 'el', 'el-GR', 'grc', '', None, 'unknown', 'English', 'en_fake', 1])
def test_missing_or_nonenglish_language_is_not_english(language):
    assert not is_english_language(language)
    assert not is_english_translation({'language': language})


def test_jev_only_receives_english_and_does_not_guess_from_text():
    records = [{'record_id': str(index), 'parent_id': 'p', 'language': language,
                'text': 'Synthetic translation text.'}
               for index, language in enumerate(['ell', 'el', None, 'eng', 'en'])]
    original = deepcopy(records)
    projected = _translations({'id': 'p', 'translation_previews': records})
    assert [row['language'] for row in projected] == ['eng', 'en']
    assert records == original


def record(identifier, language, **changes):
    return {'id': identifier, 'author': 'Fixture translator', 'work': 'Synthetic work',
            'citation': identifier, 'text': 'translationprobe synthetic text',
            'kind': 'translation', 'language': language, 'quality': 'source_text',
            'edition': 'Fixture edition', **changes}


ROWS = [record('english', 'eng'), record('english-short', 'en'),
        record('modern-greek', 'ell'), record('modern-greek-short', 'el'),
        record('unknown-language', ''), record('original-greek', 'grc', kind='text')]


@pytest.mark.parametrize('client', [ROWS], indirect=True)
def test_default_word_search_only_displays_english_translations_and_keeps_originals(client):
    response = client.get('/api/search', params={'q': 'translationprobe', 'match': 'exact'})
    assert response.status_code == 200
    ids = {row['id'] for row in response.json()['results']}
    assert {'english', 'english-short', 'original-greek'} <= ids
    assert not ids & {'modern-greek', 'modern-greek-short', 'unknown-language'}


@pytest.mark.parametrize('client', [ROWS], indirect=True)
@pytest.mark.parametrize('language,identifier', [('ell', 'modern-greek'), ('el', 'modern-greek-short')])
def test_explicit_source_language_remains_retrievable_without_english_preview(client, language, identifier):
    response = client.get('/api/search', params={'q': 'translationprobe', 'match': 'exact', 'language': language})
    assert [row['id'] for row in response.json()['results']] == [identifier]
    assert not response.json()['results'][0].get('translation_previews')
