"""Synthetic index fixtures; no added corpus or historical assertions."""
import json
import sqlite3
import pytest

from backend.textutils import normalize
from scripts.build_corpus import SCHEMA
from scripts.repair_search_layout import repair
from scripts.rebind_search_embeddings import rebind


def test_repair_preserves_records_and_replaces_only_derived_index(tmp_path):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    text = 'φωνεί-\nσας'
    record = json.dumps({'id': 'test', 'text': text, 'source_url': 'https://example.org/test'})
    with sqlite3.connect(source) as con:
        con.executescript(SCHEMA)
        con.execute('INSERT INTO passages (id,work_id,source,author,work,edition,citation,language,kind,quality,text,normalized,data,sequence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('test','work','fixture','Poet','Work','Edition','1','grc','text','source_text',text,normalize(text),record,0))
        con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)',('test',normalize(text),'1','poet','work'))
        con.executemany('INSERT INTO tokens VALUES (?,?,?,?)', [('test','φωνεί',normalize('φωνεί'),1),('test','σας','σασ',1)])
        con.executemany('INSERT INTO vocabulary VALUES (?,?,?)', [(normalize('φωνεί'),'φωνεί',1),('σασ','σας',1)])
        con.execute('INSERT INTO metadata VALUES (?,?)',('manifest','{"passages":1}'))
    result = repair(source, output)
    assert result['changed_passages'] == 1
    with sqlite3.connect(output) as con:
        assert con.execute('SELECT text,data FROM passages').fetchone() == (text,record)
        assert con.execute('SELECT normalized FROM passages').fetchone()[0] == normalize('φωνείσας')
        assert con.execute('SELECT form,count FROM tokens').fetchall() == [('φωνείσας',1)]
        assert con.execute('SELECT form,count FROM vocabulary').fetchall() == [('φωνείσας',1)]
        assert con.execute('SELECT id FROM passage_fts WHERE passage_fts MATCH ?', (normalize('φωνείσας'),)).fetchall() == [('test',)]
    with sqlite3.connect(source) as con:
        assert con.execute('SELECT normalized FROM passages').fetchone()[0] == normalize(text)
    assert repair(output, tmp_path/'again.sqlite')['changed_passages'] == 0
    manifest = tmp_path/'manifest.json'
    stat = source.stat()
    manifest.write_text(json.dumps({'corpus_mtime_ns': stat.st_mtime_ns,
                                    'corpus_size': stat.st_size, 'vectors_file': 'unchanged.npy'}))
    rebound = tmp_path/'new-manifest.json'
    assert rebind(source,output,manifest,rebound)['verified_unchanged_source_records'] == 1
    assert json.loads(rebound.read_text())['vectors_file'] == 'unchanged.npy'
    with sqlite3.connect(output) as con:
        con.execute("UPDATE passages SET text='changed source' WHERE id='test'")
    with pytest.raises(ValueError, match='Passage inputs differ'):
        rebind(source,output,manifest,tmp_path/'must-not-exist.json')
    assert not (tmp_path/'must-not-exist.json').exists()
