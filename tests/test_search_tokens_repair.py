"""Synthetic index-only fixtures; no historical/corpus data authored here."""
import hashlib
import json
import sqlite3

import pytest

from backend.textutils import normalize, search_text, tokenize
from scripts.build_corpus import SCHEMA
from scripts.repair_search_tokens import repair
from scripts import repair_search_tokens
from scripts.rebind_search_embeddings import rebind


def make_database(path):
    rows = [('broken', 'α̣β α̣β γ', 'grc', 'text', 'source_text'),
            ('shared', 'α γ', 'grc', 'text', 'source_text'),
            ('latin', 'a\u0323b c', 'lat', 'translation', 'source_text'),
            ('excluded', 'α̣β', 'grc', 'text', 'needs_review'),
            ('commentary', 'α̣β', 'grc', 'commentary', 'source_text'),
            ('null_quality', 'α γ', 'grc', 'text', None)]
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        con.execute('CREATE INDEX idx_token_passage ON tokens(passage_id)')
        con.execute('CREATE INDEX idx_token_normal ON tokens(normalized)')
        for i, (pid, text, language, kind, quality) in enumerate(rows):
            data = json.dumps({'id': pid, 'text': text, 'source_url': 'https://example.test/synthetic'})
            con.execute('INSERT INTO passages (id,work_id,source,author,work,edition,citation,language,kind,quality,text,normalized,data,sequence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (pid, 'work', 'fixture', 'Poet', 'Work', 'Edition', str(i), language, kind, quality,
                         text, normalize(search_text(text)), data, i))
            con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)', (pid, normalize(text), str(i), 'poet', 'work'))
        con.execute('INSERT INTO works (id,author,work,edition,source,language,count) VALUES (?,?,?,?,?,?,?)', ('work', 'Poet', 'Work', 'Edition', 'fixture', 'grc', 6))
        con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',
                        [('broken', 'α', 'α', 2), ('broken', 'β', 'β', 2), ('broken', 'γ', 'γ', 1),
                         ('shared', 'α', 'α', 1), ('shared', 'γ', 'γ', 1),
                         ('latin', 'a', 'a', 1), ('latin', 'b', 'b', 1), ('latin', 'c', 'c', 1),
                         ('null_quality', 'α', 'α', 1), ('null_quality', 'γ', 'γ', 1)])
        con.execute('INSERT INTO vocabulary SELECT normalized,min(form),sum(count) FROM tokens GROUP BY normalized')
        con.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps({'passages': 6, 'custom': 'preserve', 'search_layout_version': 1})))
        con.execute('INSERT INTO metadata VALUES (?,?)', ('other', 'preserve literally'))


def test_repairs_derivatives_and_rebinds_without_reembedding(tmp_path):
    source, output = tmp_path/'source.sqlite', tmp_path/'repaired.sqlite'
    make_database(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = repair(source, output)
    assert result['scanned_passages'] == 4
    assert result['changed_passages'] == 2
    assert result['source_records_unchanged']
    assert result['verified_unchanged_source_records'] == 6
    assert result['normalized_and_fts_unchanged']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with sqlite3.connect(output) as con:
        expected = tokenize('α̣β α̣β γ')
        assert dict(con.execute("SELECT form,count FROM tokens WHERE passage_id='broken'")) == {form: expected.count(form) for form in expected}
        assert con.execute("SELECT count(*) FROM tokens WHERE passage_id IN ('excluded','commentary')").fetchone()[0] == 0
        # A still-used old token must survive; counts include unaffected rows.
        assert con.execute("SELECT count FROM vocabulary WHERE normalized='α'").fetchone()[0] >= 2
        for key, count in con.execute('SELECT normalized,count FROM vocabulary'):
            assert count == con.execute('SELECT sum(count) FROM tokens WHERE normalized=?', (key,)).fetchone()[0]
        manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        assert manifest['custom'] == 'preserve'
        assert manifest['search_layout_version'] == 1
        assert manifest['tokenizer_version'] == repair_search_tokens.TOKENIZER_VERSION
    assert repair(output, tmp_path/'again.sqlite')['changed_passages'] == 0
    stat = source.stat()
    manifest_path, rebound = tmp_path/'vectors.json', tmp_path/'rebound.json'
    manifest_path.write_text(json.dumps({'corpus_mtime_ns': stat.st_mtime_ns, 'corpus_size': stat.st_size, 'vectors_file': 'unchanged.npy'}))
    assert rebind(source, output, manifest_path, rebound)['verified_unchanged_source_records'] == 6
    assert json.loads(rebound.read_text())['vectors_file'] == 'unchanged.npy'


def test_duplicate_token_rows_and_wrong_normalized_keys_repaired(tmp_path):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    make_database(source)
    with sqlite3.connect(source) as con:
        con.execute("INSERT INTO tokens VALUES ('shared','α','wrong',1)")
        con.execute("INSERT INTO vocabulary VALUES ('wrong','α',1)")
    assert repair(source, output)['changed_passages'] >= 1
    with sqlite3.connect(output) as con:
        assert con.execute("SELECT count(*) FROM vocabulary WHERE normalized='wrong'").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM tokens WHERE passage_id='shared'").fetchone()[0] == 2


def test_repairs_legacy_terminal_apostrophes_without_changing_source(tmp_path):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    make_database(source)
    with sqlite3.connect(source) as con:
        con.execute("UPDATE passages SET text=? WHERE id='shared'", ('αβ’ γ',))
        con.execute("DELETE FROM tokens WHERE passage_id='shared'")
        con.execute("INSERT INTO tokens VALUES ('shared','αβ','αβ',1)")
        con.execute("INSERT INTO tokens VALUES ('shared','γ','γ',1)")
        con.execute("INSERT INTO vocabulary VALUES ('αβ','αβ',1)")
    repair(source, output)
    with sqlite3.connect(output) as con:
        assert con.execute("SELECT form,normalized FROM tokens WHERE passage_id='shared' AND form LIKE 'αβ%'").fetchone() == ('αβ’', "αβ'")
        assert con.execute("SELECT text FROM passages WHERE id='shared'").fetchone()[0] == 'αβ’ γ'
        # The separate marked-letter fixture still contributes two αβ tokens;
        # the former bare token from this passage must no longer inflate it.
        assert con.execute("SELECT count FROM vocabulary WHERE normalized='αβ'").fetchone()[0] == 2


def test_refuses_existing_or_input_path(tmp_path):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    make_database(source)
    output.write_bytes(b'KEEP')
    for destination in (source, output):
        with pytest.raises(ValueError):
            repair(source, destination)
    assert output.read_bytes() == b'KEEP'


def test_concurrent_input_change_prevents_success(tmp_path, monkeypatch):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    make_database(source)
    with sqlite3.connect(source) as con:
        con.execute('PRAGMA journal_mode=WAL')
    original_check = repair_search_tokens._same_rows
    changed = False
    def mutate_after_snapshot(*args):
        nonlocal changed
        count = original_check(*args)
        if not changed:
            with sqlite3.connect(source) as concurrent:
                concurrent.execute("UPDATE metadata SET value='concurrent change' WHERE key='other'")
            changed = True
        return count
    monkeypatch.setattr(repair_search_tokens, '_same_rows', mutate_after_snapshot)
    with pytest.raises(RuntimeError, match='Input changed during repair'):
        repair(source, output)
    # The failed transaction never publishes a successful tokenizer version.
    with sqlite3.connect(output) as con:
        manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        assert 'tokenizer_version' not in manifest
