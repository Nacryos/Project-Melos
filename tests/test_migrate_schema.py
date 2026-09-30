"""In-place upgrade of an older index yields the same columns a fresh build writes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend import server
from scripts.migrate_corpus_schema import migrate
from test_merging import client as merging_client  # noqa: F401 - fixture reuse (tests dir is on sys.path)


def test_migration_restores_merging_and_grouping(merging_client: TestClient, tmp_path: Path):
    with sqlite3.connect(server.DB) as con:
        expected = con.execute("SELECT id, author_canonical, text_key FROM passages ORDER BY id").fetchall()
        expected_authors = con.execute("SELECT passage_id, author_key FROM passage_authors ORDER BY 1,2").fetchall()
        con.executescript("""
            DROP INDEX IF EXISTS idx_passage_canonical; DROP INDEX IF EXISTS idx_passage_mirror;
            ALTER TABLE passages DROP COLUMN author_canonical; ALTER TABLE passages DROP COLUMN text_key;
            DROP TABLE passage_authors; ALTER TABLE works DROP COLUMN author_canonical;
        """)
    server.schema_ready.cache_clear()
    assert merging_client.get("/api/status").json()["mirror_grouping"] is False
    report = migrate(Path(server.DB), promote=False, readme_path=None, backup=True)
    assert report["passages"] == 10 and report["merged_authors"] == 5
    assert Path(report["backup"]).is_file()
    with sqlite3.connect(server.DB) as con:
        assert con.execute("SELECT id, author_canonical, text_key FROM passages ORDER BY id").fetchall() == expected
        assert con.execute("SELECT passage_id, author_key FROM passage_authors ORDER BY 1,2").fetchall() == expected_authors
        manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        assert manifest["schema"] == 2 and manifest["statistics"]["authors"] == 5
    server.schema_ready.cache_clear()
    assert merging_client.get("/api/status").json()["mirror_grouping"] is True
    grouped = merging_client.get("/api/search", params={"q": "πολυστέφανε", "match": "exact"}).json()
    assert grouped["total"] == 3
    assert next(row for row in grouped["results"] if row["id"] == "z-direct")["mirrored_ids"] == ["a-mirror", "b-mirror"]
