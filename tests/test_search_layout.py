"""Synthetic index fixtures; no added corpus or historical assertions."""
import json
import sqlite3

from backend.textutils import normalize
from scripts.build_corpus import SCHEMA
from scripts.repair_search_layout import repair


def test_repair_preserves_records_and_replaces_only_derived_index(tmp_path):
    source, output = tmp_path/'old.sqlite', tmp_path/'new.sqlite'
    text = 'φωνεί-\nσας'
    record = json.dumps({'id': 'test', 'text': text, 'source_url': 'https://example.org/test'})
    with sqlite3.connect(source) as con:
        con.executescript(SCHEMA)
        con.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
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
