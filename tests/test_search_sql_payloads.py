"""Synthetic regression checks for payload-free search grouping/windows."""
import json
import sqlite3

import pytest

from backend import server
from test_merging import client


@pytest.mark.parametrize('offset,limit', [(0, 20), (1, 2), (3, 1)])
def test_compact_grouping_preserves_count_order_mirrors_and_full_payload(client, offset, limit):
    # Large metadata is not a ranking key and must survive final hydration.
    with sqlite3.connect(server.DB) as db:
        row = json.loads(db.execute("SELECT data FROM passages WHERE id='z-direct'").fetchone()[0])
        row['synthetic_padding'] = 'x' * 200_000
        db.execute("UPDATE passages SET data=? WHERE id='z-direct'", (json.dumps(row),))
    matched_tail = ',0 priority,1 matched FROM passages p WHERE p.language=\'grc\''
    window = ('), grouped AS (SELECT matched.*,'
              + server.grouping('priority,mirror_pref(source,quality),matched DESC,sequence,id') + ' FROM matched) ')
    old = 'WITH matched AS (SELECT p.*' + matched_tail + window
    compact = 'WITH matched AS (SELECT ' + server.search_row_columns() + matched_tail + window
    ordering = 'mirror_pref(source,quality),author,work,sequence,id'
    with server.connect() as db:
        expected_total = db.execute(old + 'SELECT count(*) FROM grouped WHERE rn=1').fetchone()[0]
        expected = db.execute(old + 'SELECT data,id,copies,copy_ids FROM grouped WHERE rn=1 ORDER BY '
                              + ordering + ' LIMIT ? OFFSET ?', [limit, offset]).fetchall()
        traces = []
        db.set_trace_callback(traces.append)
        assert server.count_search_groups(db, compact, []) == expected_total
        actual = server.fetch_search_page(db, compact, ordering, [], limit, offset)
        assert [tuple(row[key] for key in ('data', 'id', 'copies', 'copy_ids')) for row in actual] == [tuple(row) for row in expected]
        count_sql, page_sql = traces
        assert 'p.*' not in count_sql and 'p.*' not in page_sql
        assert count_sql.endswith('FROM matched GROUP BY ' + server.group_columns() + ')')
        assert 'SELECT payload.data FROM passages payload WHERE payload.id=selected.id' in page_sql
        plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + page_sql)]
        assert any('CORRELATED SCALAR SUBQUERY' in step for step in plan)
        assert any('SEARCH payload USING INDEX' in step for step in plan)


def test_compact_projection_never_carries_source_text_or_json(client):
    columns = server.search_row_columns().split(',')
    assert {'p.id', 'p.author_canonical', 'p.text_key', 'p.quality'} <= set(columns)
    assert not {'p.text', 'p.normalized', 'p.data', 'p.citation', 'p.edition'} & set(columns)
    with sqlite3.connect(server.DB) as db:
        db.executescript('DROP INDEX idx_passage_canonical; DROP INDEX idx_passage_mirror; '
                         'ALTER TABLE passages DROP COLUMN author_canonical; '
                         'ALTER TABLE passages DROP COLUMN text_key; DROP TABLE passage_authors;')
    server.schema_ready.cache_clear()
    assert 'p.author_canonical' not in server.search_row_columns()
    assert 'p.text_key' not in server.search_row_columns()
