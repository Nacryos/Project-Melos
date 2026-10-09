"""Campbell GLP selection: records, import idempotency and comparison-only translations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata

import pytest

from backend import translation_comparisons as tc
from scripts import import_campbell_glp as importer
from scripts import stage_corpus_addition as append

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'data/campbell_glp/campbell_glp.jsonl'
TRANSCRIPTION = ROOT / 'data/campbell_glp/transcription.json'


def _records():
    return [json.loads(line) for line in RECORDS.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_records_are_bound_to_the_committed_transcription():
    raw = TRANSCRIPTION.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    poems = json.loads(raw)['poems']
    records = _records()
    assert len(poems) == 237 and sum(p['approved_live'] for p in poems) == 5
    assert len(records) == 232 == len({r['id'] for r in records})
    approved = {'campbell-glp:alcaeus:' + n for n in ('34a', '129', '130b', '326', '350')}
    assert not approved & {r['id'] for r in records}
    for record in records:
        assert record['raw_sha256'] == digest and record['source'] == 'campbell_assignment'
        assert record['text'] == '\n'.join(line['text'] for line in record['lines'])
        assert unicodedata.is_normalized('NFC', record['text']) and '�' not in record['text']
        assert record['metadata']['source_pdf_sha256'] == tc.SOURCE_PDF_SHA256


def test_sidecar_hash_pin_and_comparison_contract():
    raw = tc.GLP_DATA_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == tc.GLP_DATA_SHA256
    payload = json.loads(raw)
    for record in payload['records']:
        for item in record['translation_comparisons']:
            assert item['selection_aligned'] is item['exact_edition_alignment'] is item['model_eligible'] is False
            assert item['language'] == 'eng' and item['scope'] == 'whole_poem_other_edition'
            assert int(item['license'].rsplit(' ', 1)[-1].rstrip(')')) <= 1930
            assert 'Campbell' not in item['translator'] and 'Elegy and Iambus' not in item['edition']


def test_translated_poem_gets_panel_gap_gets_none_and_tampering_fails_closed():
    records = {r['id']: r for r in _records()}
    translated = {r['campbell_record_id'] for r in json.loads(tc.GLP_DATA_PATH.read_text(encoding='utf-8'))['records']}
    poem = records[sorted(translated)[0]]
    result = tc.for_passage(deepcopy(poem))
    assert result['status'] == 'available' and result['comparison_count'] >= 1
    gap = next(r for i, r in records.items() if i not in translated)
    assert tc.for_passage(deepcopy(gap)) is None
    assert tc.for_passage({**poem, 'text': poem['text'] + ' '})['status'] == 'unavailable'
    assert tc.for_passage({**poem, 'id': 'perseus:x'}) is None


def test_import_is_idempotent_and_preserves_existing_rows(tmp_path):
    corpus = tmp_path / 'corpus.sqlite'
    con = sqlite3.connect(corpus)
    con.executescript('''
      CREATE TABLE passages (id TEXT PRIMARY KEY, work_id TEXT, source TEXT, author TEXT, work TEXT, edition TEXT,
        citation TEXT, language TEXT, kind TEXT, quality TEXT, text TEXT, normalized TEXT, data TEXT, sequence INTEGER,
        author_canonical TEXT, text_key TEXT);
      CREATE TABLE passage_authors (passage_id TEXT, author_key TEXT);
      CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized, citation, author, work);
      CREATE TABLE tokens (passage_id TEXT, form TEXT, normalized TEXT, count INTEGER);
      CREATE TABLE vocabulary (normalized TEXT PRIMARY KEY, form TEXT, count INTEGER);
      CREATE TABLE works (id TEXT PRIMARY KEY, author TEXT, work TEXT, edition TEXT, source TEXT, language TEXT,
        count INTEGER, author_canonical TEXT);
      CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);''')
    con.execute("INSERT INTO metadata VALUES ('manifest', ?)", (json.dumps({'schema': 2, 'files': []}),))
    con.commit()
    sample = tmp_path / 'sample.jsonl'
    sample.write_bytes(b''.join(RECORDS.read_bytes().splitlines(keepends=True)[:3]))
    first = importer.import_rows(corpus, sample)
    assert first['added'] == 3 and first['passages_after'] == 3
    snapshot = con.execute('SELECT * FROM passages ORDER BY id').fetchall()
    second = importer.import_rows(corpus, sample)
    assert second['added'] == 0 and second['already_present'] == 3
    assert con.execute('SELECT * FROM passages ORDER BY id').fetchall() == snapshot
    altered = json.loads(sample.read_text(encoding='utf-8').splitlines()[0])
    altered['text'] += ' x'
    bad = tmp_path / 'bad.jsonl'
    bad.write_text(json.dumps(altered, ensure_ascii=False) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='refusing to overwrite'):
        importer.import_rows(corpus, bad)
    con.close()
    assert append.sha(corpus)


def test_five_corrections_are_applied_bound_and_reapproved():
    from scripts import correct_campbell_five as fix
    rows = fix.corrected_rows()
    corrections = fix.load_corrections()
    assert len(rows) == 5 and len(corrections) == 11
    by_id = {r['id']: r for r in rows}
    for c in corrections:
        row = by_id[c['id']]
        assert row['lines'][c['line_index']]['text'] == c['new']
        assert c['old'] not in row['text'].split('\n')
        assert any(n['corrected'] == c['new'] and f"PDF p.{c['pdf_page']}" in n['reason']
                   for n in row['metadata']['text_corrections'])
    approval = json.loads(fix.APPROVAL.read_text(encoding='utf-8'))
    assert approval['package']['sha256'] == hashlib.sha256(fix.CORRECTED.read_bytes()).hexdigest()
    assert approval['revisions'][0]['previous_package_sha256'] == fix.ORIGINAL_SHA256
    assert tc.GREEK_PACKAGE_SHA256 == approval['package']['sha256']
    for row in rows:
        assert tc.for_passage(deepcopy(row))['status'] == 'available'


def test_open_survey_translations_fill_seventeen_gaps_english_only_with_partial_labels():
    from scripts import build_campbell_glp_translations as builder
    payload = json.loads(tc.GLP_DATA_PATH.read_text(encoding='utf-8'))
    by_id = {r['campbell_record_id']: r['translation_comparisons'] for r in payload['records']}
    assert payload['record_count'] == 226 == payload['comparison_count']
    opened = {i: items for i, items in by_id.items() if any('source_record' in item for item in items)}
    assert set(opened) == builder.OPEN_ACCEPTED and len(opened) == 17
    for poem_id, items in opened.items():
        (item,) = items
        assert item['language'] == 'eng' and item['model_eligible'] is False and item['selection_aligned'] is False
        assert item['license_basis'] and item['source_url'].startswith('https://archive.org/details/')
        assert item['source_provenance'] and all(p['source_image']['sha256'] and p['source_image']['iiif_url'] for p in item['source_provenance'])
        assert ' ;' not in item['text'] and '‘ ' not in item['text']
        assert (item.get('coverage') == 'partial') == (poem_id in builder.OPEN_PARTIAL)
    for poem_id in ('campbell-glp:phocylides:3', 'campbell-glp:archilochus:79a',
                    'campbell-glp:hipponax:24a', 'campbell-glp:hipponax:24b'):
        assert by_id[poem_id][0]['coverage_label'].startswith('Partial:')
    assert by_id['campbell-glp:archilochus:79a'][0]['text'].startswith('At Salmydessus')
    # German-only renderings stay out until the owner decides; they remain listed gaps.
    gaps = {g['id']: g for g in json.loads((ROOT / 'data/campbell_glp/translation_gaps.json').read_text(encoding='utf-8'))}
    assert 'campbell-glp:mimnermus:13' not in by_id and 'campbell-glp:phocylides:8' not in by_id
    assert gaps['campbell-glp:mimnermus:13']['open_survey_2026_10_09']['status'] == 'found_other_language'
    assert len(gaps) == 6


def test_open_record_projection_reaches_the_reader_bound_to_the_poem():
    records = {r['id']: r for r in _records()}
    result = tc.for_passage(deepcopy(records['campbell-glp:hipponax:24b']))
    assert result['status'] == 'available' and result['comparison_count'] == 1
    item = result['translation_comparisons'][0]
    assert item['translator'] == 'A. D. Knox' and item['coverage_kind'] == 'shared_rendering'
