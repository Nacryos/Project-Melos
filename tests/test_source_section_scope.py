"""Synthetic source-section association checks, not literary evidence."""
import pytest
from test_api import client


@pytest.mark.parametrize('client', [[
    {'id': 'poem', 'author': 'Alpha', 'work': 'Fragments', 'citation': '1', 'text': 'αβγ',
     'source_url': 'https://example.org/section-test'},
    {'id': 'section', 'author': 'Editor', 'work': 'Notes', 'citation': 'Other witness',
     'text': 'Attribution disputed', 'language': 'eng', 'kind': 'commentary',
     'source_url': 'https://example.org/section-test',
     'metadata': {'scope': 'source_section', 'source_heading': 'Other witness'}},
    {'id': 'stray', 'author': 'Editor', 'work': 'Notes', 'citation': 'Other witness',
     'text': 'Attribution disputed', 'language': 'eng', 'kind': 'commentary',
     'source_url': 'https://example.org/unrelated-page', 'metadata': {'scope': 'source_section'}},
]], indirect=True)
def test_section_note_is_discoverable_without_becoming_passage_aligned(client):
    response = client.get('/api/search', params={'q': 'Attribution', 'author': 'Alpha', 'mode': 'words'}).json()
    assert [row['id'] for row in response['results']] == ['section']
    note = response['results'][0]
    assert note['author'] == 'Editor'
    assert note['metadata']['scope'] == 'source_section'
    assert 'parent_id' not in note
    related = client.get('/api/passage', params={'id': 'poem'}).json()['related']
    assert {row['id'] for row in related} == {'section'}
    assert 'parent_id' not in related[0]
