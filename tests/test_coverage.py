"""Coverage arithmetic over synthetic test rows, never corpus evidence."""

import json
import sqlite3

from scripts.report_coverage import report


def test_casefold_label_collisions_remain_visible(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE passages (author TEXT, kind TEXT, language TEXT, quality TEXT, source TEXT);
            CREATE TABLE metadata (key TEXT, value TEXT);
        """)
        connection.executemany("INSERT INTO passages VALUES (?,?,?,?,?)", [
            ("Sappho", "text", "grc", "source_text", "synthetic-a"),
            ("sappho", "text", "grc", "needs_review", "synthetic-b"),
            ("sappho", "commentary", "eng", "source_text", "synthetic-b"),
        ])
        connection.execute("INSERT INTO metadata VALUES (?,?)", (
            "manifest", json.dumps({"passages": 3, "built_at": "synthetic", "files": []})
        ))
    data = report(db)
    sappho = next(item for item in data["core_targets_exact_label_only"]
                  if item["requested_name"] == "Sappho")
    assert sappho["matched_author_labels"] == ["Sappho", "sappho"]
    assert sappho["clean_greek_text_records"] == 1
    assert sappho["text_records"] == 2
    assert sappho["commentary_reference_records"] == 1
    assert data["total_records"] == 3


def test_unmatched_target_is_unknown_not_zero(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE passages (author TEXT, kind TEXT, language TEXT, quality TEXT, source TEXT);
            CREATE TABLE metadata (key TEXT, value TEXT);
        """)
        connection.execute("INSERT INTO passages VALUES (?,?,?,?,?)",
                           ("Σαπφώ", "text", "grc", "source_text", "synthetic"))
        connection.execute("INSERT INTO metadata VALUES (?,?)", (
            "manifest", json.dumps({"passages": 1, "built_at": "synthetic", "files": []})
        ))
    data = report(db)
    sappho = next(item for item in data["core_targets_exact_label_only"]
                  if item["requested_name"] == "Sappho")
    assert sappho["exact_label_match"] is False
    assert sappho["clean_greek_text_records"] is None
    assert data["authors"][0]["author_label"] == "Σαπφώ"
