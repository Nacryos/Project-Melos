"""Isolated reviewed-exclusion policy fixtures, never production corpus edits."""
import json

import pytest

from backend.morphology import Morphology, _REVIEWED_SOURCE_EXCLUSIONS, _source_exclusion


def service(tmp_path, forms):
    entries = [{'lemma': 'ἐγώ', 'source': 'synthetic dictionary',
                'source_url': 'https://example.test/dictionary', 'gloss': 'synthetic I/me fixture'}]
    paths = [tmp_path / 'entries.jsonl', tmp_path / 'forms.jsonl']
    for path, rows in zip(paths, (entries, forms)):
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    return Morphology(*paths)


def test_exact_reviewed_token_is_disclosed_but_never_interpreted(tmp_path):
    rule = _REVIEWED_SOURCE_EXCLUSIONS[0]
    # Policy regression fixture from the exact reviewed selector, not an
    # invented correction or an added literary token.
    rejected = dict(rule['match'], raw_path='private/local/file.xml', source='test source')
    model = service(tmp_path, [rejected, rejected])
    before = model.forms_path.read_bytes()
    result = model.analyze('φαίνεταί')
    assert not result['candidates']
    assert not result['lexicon_entries']
    assert not result['observed_form_groups']
    assert not result['expansion_lemmas']
    assert not result['attested_forms']
    assert model.forms_for_lemma('ἐγώ') == []
    assert model.expansion_forms_for_lemma('ἐγώ') == []
    assert len(result['quarantined_source_analyses']) == 1
    retained = result['quarantined_source_analyses'][0]
    for key in rule['match']:
        assert retained[key] == rule['match'][key]
    assert retained['status'] == 'quarantined_source_annotation'
    assert 'raw_path' not in retained and 'gloss' not in retained
    assert any('quarantined' in warning for warning in result['warnings'])
    assert model.forms_path.read_bytes() == before


@pytest.mark.parametrize('field', list(_REVIEWED_SOURCE_EXCLUSIONS[0]['match']))
def test_exclusion_does_not_generalize_beyond_reviewed_identity(field):
    row = dict(_REVIEWED_SOURCE_EXCLUSIONS[0]['match'])
    assert _source_exclusion(row)
    row[field] += '-different'
    assert _source_exclusion(row) is None


def test_unrelated_ambiguity_is_retained_without_voting(tmp_path):
    rows = [{'form': 'αβγ', 'lemma': lemma, 'analysis': 'synthetic parse',
             'source_url': 'https://example.test/source'} for lemma in ('αβδ', 'αβε')]
    result = service(tmp_path, rows).analyze('αβγ')
    assert {item['lemma'] for item in result['candidates']} == {'αβδ', 'αβε'}
    assert result['quarantined_source_analyses'] == []
    assert result['expansion_lemmas'] == []


def test_independent_source_reading_is_not_removed_with_rejected_token(tmp_path):
    rejected = dict(_REVIEWED_SOURCE_EXCLUSIONS[0]['match'])
    independent = dict(rejected, sentence_id='synthetic-independent-token')
    result = service(tmp_path, [rejected, independent]).analyze('φαίνεται')
    assert len(result['candidates']) == 1
    assert len(result['quarantined_source_analyses']) == 1
    locations = result['observed_form_groups'][0]['forms'][0]['source_refs'][0]['locations']
    assert [location['sentence_id'] for location in locations] == ['synthetic-independent-token']
