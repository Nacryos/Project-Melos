"""Synthetic TEI mechanics only; not a source corpus or linguistic evidence."""
import hashlib

import pytest

from backend import lexicon_render
from backend.lexical_quotes import lookup_quotes


@pytest.fixture
def archive(tmp_path, monkeypatch):
    raw = tmp_path / 'data/raw/lexica'
    raw.mkdir(parents=True)
    monkeypatch.setattr(lexicon_render, 'ROOT', tmp_path)
    monkeypatch.setattr(lexicon_render, 'RAW_ROOT', raw.resolve())
    def make(body, identifier='fixture'):
        path = raw / (identifier + '.xml')
        path.write_text(f'<root><entryFree id="{identifier}"><orth lang="greek">a)/nqrwpos</orth>{body}</entryFree></root>', encoding='utf-8')
        return {'id': 'synthetic:' + identifier, 'entry_id': identifier,
                'lemma': 'synthetic headword', 'source': 'PerseusDL LSJ TEI',
                'source_url': 'https://example.test/' + identifier,
                'raw_path': str(path), 'raw_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return make


def citation(quote="a)ll' a)/ge", label='Fixture 7'):
    return f'<cit><quote lang="greek">{quote}</quote><bibl>{label}</bibl></cit>'


def passage(text='ἀλλ᾽ ἄγε', **changes):
    return {'id': 'synthetic passage', 'language': 'grc', 'kind': 'text', 'quality': 'source_text', 'text': text, **changes}


def test_exact_complete_quote_keeps_owned_sense_gloss_and_citation(archive):
    record = archive('<sense id="earlier"><tr>Wrong earlier gloss</tr></sense>'
                     '<sense id="owned">metaph., <tr>Owned gloss</tr>' + citation() +
                     '<pos>Adv.</pos><tr>Wrong later gloss</tr>' + citation('a)/llos lo/gos', 'Other 9') + '</sense>')
    result = lookup_quotes('ἀλλ᾽', passage(), [record])
    assert result['searched_entries'] == 1
    hit, = result['hits']
    assert hit['sense_id'] == 'owned'
    assert hit['source_locator'] == './sense[2]/cit[1]'
    assert hit['source_gloss'] == 'Owned gloss'
    assert hit['citation'] == 'Fixture 7' and hit['citation_urn'] is None
    assert hit['raw_quote'] == "a)ll' a)/ge"
    assert hit['quote'] == 'ἀλλ’ ἄγε'
    assert hit['passage_spans'] == [{'start': 0, 'end': 8, 'text': 'ἀλλ᾽ ἄγε'}]
    assert hit['scope'] == 'dictionary_quotation_not_morphological_parse'
    assert 'analysis' not in hit and 'raw_path' not in hit
    assert 'not a claim' in hit['interpretation_warning']


@pytest.mark.parametrize('text', ['ἀλλ᾽ λόγος ἄγε', 'ἀλλ᾽', 'ἀλλ᾽ ... ἄγε', 'ἀλλ᾽ […] ἄγε',
                                  'ἀλλ᾽ 2 ἄγε', 'αλλ᾽ ἄγε', 'ἀλλ᾿ ἄγε', 'ἀλλὰ ἄγε'])
def test_no_partial_accent_elision_or_gap_guessing(archive, text):
    record = archive('<sense id="s"><tr>Fixture</tr>' + citation() + '</sense>')
    assert not lookup_quotes('ἀλλ᾽', passage(text), [record])['hits']


def test_original_offsets_survive_canonical_unicode_equivalence(archive):
    import unicodedata
    record = archive('<sense id="s">' + citation() + '</sense>')
    text = 'x ' + unicodedata.normalize('NFD', 'ἀλλ᾽ ἄγε') + ' y'
    result = lookup_quotes('ἀλλ᾽', passage(text), [record])
    hit, = result['hits']
    span, = hit['passage_spans']
    assert text[span['start']:span['end']] == span['text']
    assert span['start'] == 2
    assert hit['source_gloss'] is None
    assert hit['source_gloss_status'] == 'not_supplied_in_local_scope'


def test_no_gloss_or_bibliography_borrowed_from_other_scope(archive):
    record = archive('<sense id="parent"><tr>Parent gloss</tr><sense id="child">' + citation() +
                     '</sense><cit><quote lang="greek">a)ll\' a)/ge</quote></cit><bibl>Unowned 1</bibl></sense>')
    hit, = lookup_quotes('ἀλλ᾽', passage(), [record])['hits']
    assert hit['source_gloss'] is None and hit['sense_id'] == 'child'


def test_hash_mismatch_fails_closed_and_shortlist_is_disclosed(archive):
    record = archive('<sense id="s">' + citation() + '</sense>')
    result = lookup_quotes('ἀλλ᾽', passage(), [record | {'raw_sha256': 'wrong'}])
    assert not result['hits'] and result['warnings'] and result['searched_entries'] == 0
    limited = lookup_quotes('ἀλλ᾽', passage(), [record], entry_limit=0)
    assert limited['eligible_entries'] == 1 and limited['entries_truncated']
    assert limited['searched_entries'] == 0


@pytest.mark.parametrize('body', [
    '<sense><cit><quote lang="greek">a)ll\' a)/ge</quote></cit><bibl>Unowned</bibl></sense>',
    '<sense><cit><quote lang="greek">a)ll\' a)/ge</quote><bibl>A</bibl><bibl>B</bibl></cit></sense>',
    '<sense>' + citation('a)ll\' ... a)/ge') + '</sense>',
    '<sense>' + citation('a)ll\'') + '</sense>',
])
def test_ambiguous_source_ownership_or_incomplete_quote_omitted(archive, body):
    assert not lookup_quotes('ἀλλ᾽', passage(), [archive(body)])['hits']


def test_non_greek_or_no_clicked_form_never_matches(archive):
    record = archive('<sense>' + citation() + '</sense>')
    assert not lookup_quotes('ἀλλ᾽', passage(language='ell'), [record])['hits']
    assert not lookup_quotes('ἄλλος', passage(), [record])['hits']


def test_source_entity_placeholders_never_escape_as_raw_quote(archive):
    record = archive('<sense>' + citation("a)ll' &nbsp;a)/ge") + '</sense>')
    hit, = lookup_quotes('ἀλλ᾽', passage(), [record])['hits']
    assert hit['raw_quote'] == "a)ll' \u00a0a)/ge"
    assert 'character references decoded' in hit['raw_quote_encoding']
    assert not any(0xE000 <= ord(char) <= 0xF8FF for char in hit['raw_quote'])


@pytest.mark.parametrize('quality', ['needs_review', 'mixed_content', 'machine_ocr', None])
def test_unsafe_reading_contexts_are_not_aligned(archive, quality):
    record = archive('<sense>' + citation() + '</sense>')
    result = lookup_quotes('ἀλλ᾽', passage(quality=quality), [record])
    assert result['hits'] == [] and result['warnings']


def test_corrected_ocr_quality_remains_visible(archive):
    record = archive('<sense>' + citation() + '</sense>')
    result = lookup_quotes('ἀλλ᾽', passage(quality='machine_corrected_ocr'), [record])
    assert result['hits'][0]['passage_quality'] == 'machine_corrected_ocr'
    assert result['warnings']


def test_morphology_quote_evidence_does_not_promote_spelling_to_parse(archive, tmp_path):
    import json
    from backend.morphology import Morphology
    record = archive('<sense id="s"><tr>synthetic gloss</tr>' + citation("a)nqrwp' a)/ge") + '</sense>')
    record['lemma'] = 'ἄνθρωπος'
    entries = tmp_path / 'entries.jsonl'
    entries.write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
    forms = tmp_path / 'forms.jsonl'
    forms.write_text('', encoding='utf-8')
    result = Morphology(entries, forms).analyze('ἀνθρωπ᾽', passage('ἀνθρωπ᾽ ἄγε'))
    assert len(result['lexical_evidence']['hits']) == 1
    assert result['analysis_match_status'] == 'spelling_suggestions_only'
    assert result['candidates'][0]['edit_distance'] == 2
    assert result['candidates'][0]['analysis'] is None
    assert result['expansion_lemmas'] == []
