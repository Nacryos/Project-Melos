"""Coverage arithmetic over synthetic test rows, never corpus evidence."""

import json
import sqlite3

from scripts.report_coverage import render_markdown, report


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


def test_greek_and_slug_labels_merge_into_the_requested_name(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE passages (author TEXT, kind TEXT, language TEXT, quality TEXT, source TEXT);
            CREATE TABLE metadata (key TEXT, value TEXT);
        """)
        connection.executemany("INSERT INTO passages VALUES (?,?,?,?,?)", [
            ("Σαπφώ", "text", "grc", "source_text", "synthetic"),
            ("sappho-of-lesbos", "text", "grc", "machine_corrected_ocr", "synthetic"),
            ("Sappho / Alcaeus", "text", "grc", "source_text", "synthetic"),
            ("Nobody Known", "text", "grc", "source_text", "synthetic"),
        ])
        connection.execute("INSERT INTO metadata VALUES (?,?)", (
            "manifest", json.dumps({"passages": 4, "built_at": "synthetic", "files": []})
        ))
    data = report(db)
    sappho = next(item for item in data["core_targets"] if item["requested_name"] == "Sappho")
    assert sappho["exact_label_match"] is False
    assert sappho["merged_label_match"] is True
    assert sappho["matched_author_labels"] == ["sappho-of-lesbos", "Σαπφώ"]
    assert sappho["clean_greek_text_records"] == 1
    assert sappho["searchable_greek_text_records"] == 2
    # The joint attribution is never folded into one poet.
    assert "Sappho / Alcaeus" in sappho["unmerged_similar_labels"]
    unknown = next(item for item in data["core_targets"] if item["requested_name"] == "Ibycus")
    assert unknown["merged_label_match"] is False and unknown["clean_greek_text_records"] is None
    assert {item["merged_author"] for item in data["merged"]} == {"Sappho", "Sappho / Alcaeus", "Nobody Known"}
    markdown = render_markdown(data)
    assert "| Sappho | `sappho-of-lesbos`, `Σαπφώ` | 1 | 2 |" in markdown
    assert "Sappho / Alcaeus" in markdown
