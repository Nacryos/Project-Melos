"""In-place upgrade of an older index yields the same columns a fresh build writes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from backend import server
from scripts.migrate_corpus_schema import migrate
from test_merging import client as merging_client  # noqa: F401 - fixture reuse (tests dir is on sys.path)


def test_migration_restores_merging_and_grouping(merging_client: TestClient, tmp_path: Path):
    with closing(sqlite3.connect(server.DB)) as con, con:
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
    with closing(sqlite3.connect(server.DB)) as con:
        assert con.execute("SELECT id, author_canonical, text_key FROM passages ORDER BY id").fetchall() == expected
        assert con.execute("SELECT passage_id, author_key FROM passage_authors ORDER BY 1,2").fetchall() == expected_authors
        manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        assert manifest["schema"] == 2 and manifest["statistics"]["authors"] == 5
    server.schema_ready.cache_clear()
    assert merging_client.get("/api/status").json()["mirror_grouping"] is True
    grouped = merging_client.get("/api/search", params={"q": "πολυστέφανε", "match": "exact"}).json()
    assert grouped["total"] == 3
    assert next(row for row in grouped["results"] if row["id"] == "z-direct")["mirrored_ids"] == ["a-mirror", "b-mirror"]


def test_ocr_promotion_rebuilds_vocabulary_from_tokens(merging_client: TestClient, tmp_path: Path):
    db = Path(server.DB)
    readme = tmp_path / "README.md"
    readme.write_text("| urn:test | a | b | c | d | auto-corrected |\n", encoding="utf-8")
    with closing(sqlite3.connect(db)) as con, con:
        original = json.loads(con.execute("SELECT data FROM passages WHERE id='ocr-raw'").fetchone()[0])
        text = original["text"]
        original.update(source="ogc", quality="machine_ocr", kind="text")
        original["metadata"] = {"ogc_urn": "urn:test", "quality_screening": {
            "block_label": "ocr_text_candidate", "bibliographic_scope": "poetry"
        }}
        con.execute("UPDATE passages SET source='ogc',data=? WHERE id='ocr-raw'",
                    (json.dumps(original, ensure_ascii=False),))
        # Simulate stale tokens left by an older index. The old incremental
        # vocabulary update would retain this form and double-count overlaps.
        con.execute("INSERT INTO tokens VALUES ('ocr-raw','legacy','legacy',7)")
        con.execute("INSERT OR REPLACE INTO vocabulary VALUES ('legacy','legacy',7)")
    first = migrate(db, promote=True, readme_path=readme, backup=False)
    assert first["promoted_corrected_ocr"] == 1
    with closing(sqlite3.connect(db)) as con:
        record = json.loads(con.execute("SELECT data FROM passages WHERE id='ocr-raw'").fetchone()[0])
        assert record["text"] == text and record["quality"] == "machine_corrected_ocr"
        assert con.execute("SELECT count(*) FROM vocabulary WHERE normalized='legacy'").fetchone()[0] == 0
        token_counts = con.execute("SELECT normalized,SUM(count) FROM tokens GROUP BY normalized ORDER BY normalized").fetchall()
        vocabulary_counts = con.execute("SELECT normalized,count FROM vocabulary ORDER BY normalized").fetchall()
        assert vocabulary_counts == token_counts
        manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        assert manifest["vocabulary"] == len(vocabulary_counts)
    second = migrate(db, promote=True, readme_path=readme, backup=False)
    assert second["promoted_corrected_ocr"] == 0
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT normalized,count FROM vocabulary ORDER BY normalized").fetchall() == vocabulary_counts
