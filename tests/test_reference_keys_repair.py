"""Synthetic normalizer migrations; fixtures are not scholarly source data."""
import hashlib
import json
import sqlite3

import pytest

from backend.evidence import EvidenceIndex
from backend.normalization_contract import NORMALIZATION_VERSION
from backend.wiktionary import AuditGateError, WiktionaryLookup, build_index
from scripts.build_evidence import build
from scripts.repair_reference_keys import MARK, repair
from scripts import repair_reference_keys
from test_evidence import _claim, _stage


def evidence_fixture(root):
    claims = [_claim('fixture:marked', {'type': 'form', 'form': 'α' + MARK}, 'morphology',
                     {'forms': [{'form': 'β' + MARK, 'tags': ['synthetic']}]}),
              _claim('fixture:bare', {'type': 'form', 'form': 'α'}, 'lemma', {'form': 'α'})]
    _stage(root, claims)
    path = root/'data/evidence.sqlite'
    build(root, path)
    with sqlite3.connect(path) as con:
        con.execute('DROP TABLE lookup_metadata')
        con.execute("UPDATE claims SET normalized_form='α' WHERE id='fixture:marked'")
        con.execute("UPDATE form_edges SET normalized_form='β'")
    return path


def wiki_fixture(root, *, headword=MARK, escaped=False):
    source, audit, path = root/'data/lexica/wiktionary-entries.jsonl', root/'data/reports/wiktionary-audit.json', root/'data/wiktionary.sqlite'
    source.parent.mkdir(parents=True)
    audit.parent.mkdir(parents=True)
    record = {'id': 'fixture:sign', 'source_url': 'https://example.test/fixture',
              'entry': {'word': headword, 'lang_code': 'grc', 'forms': [{'form': "'"}, {'form': 'β' + MARK}]}}
    source.write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
    audit.write_text(json.dumps({'status': 'accepted', 'output_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}))
    build_index(source, audit, path)
    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM metadata WHERE key='normalization_version'")
        if MARK in headword:
            con.execute("UPDATE entries SET headword_key=''")
            con.execute("DELETE FROM lookup_keys WHERE kind='headword'")
        con.execute("UPDATE lookup_keys SET key='β' WHERE form_index=1")
        if escaped:
            con.execute('UPDATE entries SET record_json=?', (json.dumps(record, ensure_ascii=True),))
    return path, source, audit


def test_evidence_keys_repaired_without_claim_or_acceptance_changes(tmp_path):
    source = evidence_fixture(tmp_path)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match='normalization'):
        EvidenceIndex(source).lookup('α' + MARK)
    output = tmp_path/'fixed.sqlite'
    report = repair(source, output, 'evidence', tmp_path)
    assert report['changed_normalized_rows'] == {'claims': 1, 'form_edges': 1}
    assert report['source_fields_unchanged']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    index = EvidenceIndex(output)
    assert [row['id'] for row in index.lookup('α' + MARK)['claims']] == ['fixture:marked']
    assert [row['id'] for row in index.lookup('α')['claims']] == ['fixture:bare']
    assert index.lookup('β' + MARK)['claims'][0]['subject']['form'] == 'α' + MARK
    assert repair(output, tmp_path/'again.sqlite', 'evidence', tmp_path)['changed_normalized_rows'] == {'claims': 0, 'form_edges': 0}


def test_wiki_keys_derived_from_unmodified_source_with_new_headword_edge(tmp_path):
    source, entries, audit = wiki_fixture(tmp_path)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(AuditGateError, match='normalization'):
        WiktionaryLookup(entries, audit, source)
    output = tmp_path/'fixed.sqlite'
    report = repair(source, output, 'wiktionary', tmp_path)
    assert report['changed_entries'] == report['changed_headword_keys'] == 1
    assert report['lookup_key_row_difference'] == 3
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    service = WiktionaryLookup(entries, audit, output)
    try:
        assert service.lookup(MARK)['total'] == 1
        assert service.lookup('β' + MARK)['total'] == 1
    finally:
        service.close()
    with sqlite3.connect(output) as con:
        assert con.execute("SELECT count(*) FROM lookup_keys WHERE key=?", ("'",)).fetchone()[0] == 1
        assert dict(con.execute('SELECT key,value FROM metadata'))['normalization_version'] == NORMALIZATION_VERSION
    assert repair(output, tmp_path/'again.sqlite', 'wiktionary', tmp_path)['changed_entries'] == 0


def test_changed_accepted_source_fails_before_creating_output(tmp_path):
    source = evidence_fixture(tmp_path)
    claim_path = tmp_path/'data/claims/synthetic.jsonl'
    claim_path.write_text(claim_path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    output = tmp_path/'invalid.sqlite'
    with pytest.raises(ValueError, match='hash mismatch'):
        repair(source, output, 'evidence', tmp_path)
    assert not output.exists()


def test_existing_output_not_overwritten(tmp_path):
    source = evidence_fixture(tmp_path)
    output = tmp_path/'existing.sqlite'
    output.write_bytes(b'KEEP')
    with pytest.raises(ValueError):
        repair(source, output, 'evidence', tmp_path)
    assert output.read_bytes() == b'KEEP'


def test_escaped_json_form_key_not_missed(tmp_path):
    source, entries, audit = wiki_fixture(tmp_path, headword='α', escaped=True)
    output = tmp_path/'fixed.sqlite'
    result = repair(source, output, 'wiktionary', tmp_path)
    assert result['changed_entries'] == 1
    assert result['changed_headword_keys'] == 0
    service = WiktionaryLookup(entries, audit, output)
    try:
        assert service.lookup('β' + MARK)['total'] == 1
    finally:
        service.close()


def test_unknown_prior_normalizer_refused(tmp_path):
    source = evidence_fixture(tmp_path)
    with sqlite3.connect(source) as con:
        con.execute('CREATE TABLE lookup_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.execute("INSERT INTO lookup_metadata VALUES ('normalization_version','future-unknown')")
    output = tmp_path/'invalid.sqlite'
    with pytest.raises(RuntimeError, match='Unknown normalization version'):
        repair(source, output, 'evidence', tmp_path)
    with sqlite3.connect(output) as con:
        assert con.execute("SELECT value FROM lookup_metadata WHERE key='normalization_version'").fetchone()[0] == 'future-unknown'


def test_source_field_mutation_rejected(tmp_path, monkeypatch):
    source = evidence_fixture(tmp_path)
    check = repair_reference_keys._rows_equal
    def corrupt_then_verify(original, revised, query, transform=None):
        if query.startswith('SELECT * FROM claims'):
            revised.execute("UPDATE claims SET status='machine_proposed' WHERE id='fixture:marked'")
        return check(original, revised, query, transform)
    monkeypatch.setattr(repair_reference_keys, '_rows_equal', corrupt_then_verify)
    with pytest.raises(RuntimeError, match='Unexpected reference/source field change'):
        repair(source, tmp_path/'invalid.sqlite', 'evidence', tmp_path)


def test_concurrent_input_write_rolls_back_version_publication(tmp_path, monkeypatch):
    source = evidence_fixture(tmp_path)
    with sqlite3.connect(source) as con:
        con.execute('PRAGMA journal_mode=WAL')
    check = repair_reference_keys._rows_equal
    changed = False
    def concurrent_then_verify(*args, **kwargs):
        nonlocal changed
        count = check(*args, **kwargs)
        if not changed:
            with sqlite3.connect(source) as concurrent:
                concurrent.execute("UPDATE input_files SET records=records+1")
            changed = True
        return count
    monkeypatch.setattr(repair_reference_keys, '_rows_equal', concurrent_then_verify)
    output = tmp_path/'invalid.sqlite'
    with pytest.raises(RuntimeError, match='Input snapshot changed'):
        repair(source, output, 'evidence', tmp_path)
    with sqlite3.connect(output) as con:
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name='lookup_metadata'").fetchone()[0] == 0
