"""Other-edition English remains literal, source-bound and non-aligned."""
from copy import deepcopy
import hashlib
import json

import pytest

from backend import translation_comparisons
from scripts import build_translation_comparisons as builder


def _poems():
    return [json.loads(line) for line in builder.GREEK.read_text(encoding='utf8').splitlines()]


def _sources():
    return {row['assignment_fragment']: row for row in
            map(json.loads, builder.SOURCE.read_text(encoding='utf8').splitlines())}


def _keys(value):
    if isinstance(value, dict):
        for key, subvalue in value.items():
            yield key
            yield from _keys(subvalue)
    elif isinstance(value, list):
        for subvalue in value:
            yield from _keys(subvalue)


def test_projection_is_deterministic_and_preserves_every_source_word(tmp_path):
    projected = builder.build()
    staged = builder.OUTPUT.read_bytes()
    assert hashlib.sha256(staged).hexdigest() == translation_comparisons.DATA_SHA256
    assert projected == json.loads(staged)
    assert builder.write(tmp_path / 'comparison.json') == translation_comparisons.DATA_SHA256
    sources = _sources()
    for record in projected['records']:
        source = sources[record['assignment_fragment']]
        item, = record['translation_comparisons']
        for key in ('text', 'paired_greek', 'translator', 'edition', 'citation', 'license', 'source_url'):
            assert item[key] == source[key]
        metadata = item['edition_difference_metadata']
        if 'campbell_text_reanchored' in metadata:
            # Campbell text corrected to the page image (2026-10-08): the approved diff must be
            # reproducible against the previous text and is recomputed against the corrected one.
            poem = next(p for p in _poems() if p['id'] == record['campbell_record_id'])
            other = source.get('paired_greek') or '\n'.join(
                c['text'] for c in source.get('source_chunks', []) if c.get('language') == 'grc')
            previous = source['campbell_comparison']['campbell_text']
            assert builder._token_differences(previous, other) == source['campbell_comparison']['exact_token_differences']
            assert metadata['exact_token_differences'] == builder._token_differences(poem['text'], other)
            assert metadata['campbell_text_reanchored']['previous_text_sha256'] == hashlib.sha256(previous.encode()).hexdigest()
        else:
            assert metadata['exact_token_differences'] == source['campbell_comparison']['exact_token_differences']
    keys = set(_keys(projected))
    assert not {'parent_id', 'translation_of', 'published_translations', 'source_claims', 'raw_path', 'ocr_path'} & keys
    assert 'C:\\Users' not in staged.decode('utf8') and 'runtime/' not in staged.decode('utf8')


def test_exact_campbell_records_receive_comparisons_only():
    for poem in _poems():
        result = translation_comparisons.for_passage(poem, path=builder.OUTPUT)
        assert result['status'] == 'available'
        assert result['campbell_record_id'] == poem['id']
        assert result['selection_aligned'] is result['exact_edition_alignment'] is False
        assert result['word_attestation'] is result['line_attestation'] is result['model_eligible'] is False
        item, = result['translation_comparisons']
        assert item['selection_aligned'] is item['exact_edition_alignment'] is item['model_eligible'] is False
        assert item['scope'] == 'whole_poem_other_edition'
        assert 'parent_id' not in item and 'translation_of' not in item
        item['text'] = 'changed caller copy'
        assert translation_comparisons.for_passage(poem, path=builder.OUTPUT)['translation_comparisons'][0]['text'] != item['text']


@pytest.mark.parametrize('key,value', [('text','changed'),('raw_sha256','0'*64),('source','perseus'),
    ('edition','another edition'),('author','someone else'),('kind','translation'),('language','eng'),
    ('quality','source_text'),('work','another work'),('source_url','https://example.invalid')])
def test_changed_identity_fails_closed(key,value):
    poem = {**_poems()[0], key:value}
    result = translation_comparisons.for_passage(poem,path=builder.OUTPUT)
    assert result['status'] == 'unavailable' and result['translation_comparisons'] == []


def test_metadata_wrong_record_missing_and_tampered_sidecar_fail_closed(tmp_path):
    poem = _poems()[0]
    for key in ('assignment_fragment','edition_fragment','source_pdf_sha256'):
        changed = deepcopy(poem)
        changed['metadata'][key] = 'wrong'
        assert translation_comparisons.for_passage(changed,path=builder.OUTPUT)['status'] == 'unavailable'
    assert translation_comparisons.for_passage({**poem,'id':'p2_alcaeus:34a'},path=builder.OUTPUT) is None
    assert translation_comparisons.for_passage(None,path=builder.OUTPUT) is None
    missing = tmp_path/'missing.json'
    assert translation_comparisons.for_passage(poem,path=missing)['status'] == 'unavailable'
    missing.write_bytes(builder.OUTPUT.read_bytes()+b' ')
    assert translation_comparisons.for_passage(poem,path=missing)['translation_comparisons'] == []


def test_rights_source_notes_and_vetoed_greek_are_preserved():
    for record in builder.build()['records']:
        fragment = record['assignment_fragment']
        item, = record['translation_comparisons']
        assert item['license_unrestricted'] is False
        if fragment in ('129','130b'):
            assert 'CC BY-NC-ND' in item['license']
            assert item['reuse_status'] == 'staging_only_noncommercial_unadapted_reuse_required'
            assert len(item['source_notes']) == 4
            assert item['source_note_markers']
        if fragment == '326':
            assert item['paired_greek'] is None
            assert item['paired_greek_images'][0]['scan_leaf'] == 366
            assert item['edition_difference_metadata']['exact_token_differences'] is None
            assert item['paired_greek_transcription_status'] == 'withheld_failed_OCR_use_source_scan'


@pytest.mark.parametrize('argument,path', [('source',builder.SOURCE),('approval',builder.APPROVAL),
    ('notes',builder.NOTES),('greek',builder.GREEK),('greek_approval',builder.GREEK_APPROVAL)])
def test_changed_source_or_approval_rejected_before_projection(tmp_path,argument,path):
    changed=tmp_path/'changed'
    changed.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='receipt mismatch'):
        builder.build(**{argument:changed})


def test_actual_source_artifacts_are_hash_checked_and_path_confined(tmp_path,monkeypatch):
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    path=tmp_path/'runtime/alcaeus-translations/source.html'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'external-source-receipt')
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    assert builder._artifact('runtime/alcaeus-translations/source.html',expected)==path.read_bytes()
    path.write_bytes(b'changed-source')
    with pytest.raises(ValueError,match='receipt mismatch'):
        builder._artifact('runtime/alcaeus-translations/source.html',expected)
    with pytest.raises(ValueError,match='escaped'):
        builder._artifact('../outside',expected)
