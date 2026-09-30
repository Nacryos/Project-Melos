"""The owner-acceptance helper binds exact hashes so the fail-closed build still works."""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

import pytest

from scripts import build_corpus
from scripts.accept_owner_outputs import accept


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = tmp_path / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("SYNTHETIC", encoding="utf-8")
    common = {"source": "p2_synthetic", "source_url": "https://example.org/x", "raw_path": "data/raw/synthetic.txt",
              "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "author": "Ibycus of Rhegium",
              "work": "Fragments", "edition": "unspecified", "language": "grc", "kind": "text",
              "quality": "source_text", "license": "test"}
    write_rows(tmp_path / "data/processed/p2_synthetic.jsonl", [
        dict(common, id="s1", citation="1", text="Ἔρος αὖτέ με"),
        dict(common, id="s2", citation="2", text="κυανέοισιν ὑπὸ βλεφάροις"),
    ])
    write_rows(tmp_path / "data/processed/legacy.jsonl", [
        dict(common, id="l1", source="legacy", citation="1", text="ἄλλο μέλος"),
    ])
    (tmp_path / "data/reports").mkdir(parents=True)
    (tmp_path / "data/reports/audit-acceptance.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", tmp_path)
    return tmp_path


def test_accepted_files_are_indexed_and_a_later_edit_is_rejected(root: Path):
    accepted = accept(["p2_synthetic.jsonl", "legacy.jsonl"], root=root)
    assert accepted == {"p2_synthetic.jsonl": 2, "legacy.jsonl": 1}
    manifest = json.loads((root / "data/reports/audit-acceptance.json").read_text(encoding="utf-8"))
    assert manifest["files"]["p2_synthetic.jsonl"]["verdict"] == "PASS"
    assert manifest["files"]["p2_synthetic.jsonl"]["acceptance_origin"] == "data/reports/p2-text-acceptance.json"
    assert "owner acceptance" in manifest["files"]["legacy.jsonl"]["acceptance_basis"]
    db = root / "data/corpus.sqlite"
    build_corpus.build(db)
    import sqlite3
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT count(*) FROM passages").fetchone()[0] == 3
        assert con.execute("SELECT DISTINCT author_canonical FROM passages WHERE source='p2_synthetic'").fetchall() == [("Ibycus",)]
    # Touching the accepted file without re-accepting quarantines it again.
    path = root / "data/processed/p2_synthetic.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + json.dumps({"id": "s3"}) + "\n", encoding="utf-8")
    build_corpus.build(db)
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT count(*) FROM passages").fetchone()[0] == 1


def test_missing_file_and_bad_name_are_refused(root: Path):
    with pytest.raises(FileNotFoundError):
        accept(["p2_absent.jsonl"], root=root)
    with pytest.raises(ValueError):
        accept(["../p2_synthetic.jsonl"], root=root)
