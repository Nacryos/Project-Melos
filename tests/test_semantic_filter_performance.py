"""Semantic filtering parity and filesystem-work bounds (no model download)."""

import json
import os

import numpy as np
import pytest

from backend import author_aliases
from backend.semantic import SemanticIndex


class FixedEncoder:
    def __init__(self):
        self.calls = 0

    def encode(self, *args, **kwargs):
        self.calls += 1
        return np.array([[1, 0]], dtype=np.float32)


def make_index(path, rows, scores, version="initial"):
    path.mkdir(exist_ok=True)
    (path / f"rows-{version}.json").write_text(json.dumps(rows), encoding="utf-8")
    np.save(path / f"vectors-{version}.npy", np.asarray([[score, 0] for score in scores], dtype=np.float32))
    manifest = {"index_version": 1, "dimensions": 2, "rows_file": f"rows-{version}.json",
                "vectors_file": f"vectors-{version}.npy", "model": "test", "model_revision": "test"}
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    index = SemanticIndex(path)
    index._model = FixedEncoder()
    return index


def rows_fixture():
    return [
        {"id": "other", "author": "Other", "language": "grc", "kind": "text"},
        {"id": "a", "author": "Alcaeus of Mytilene", "language": "grc", "kind": "text"},
        {"id": "joint", "author": "Sappho / Alcaeus", "language": "grc", "kind": "text"},
        {"id": "tr", "author": "Translator", "context_authors": ["Alcaeus"],
         "language": "ell", "kind": "translation", "parent_id": "a"},
        {"id": "note", "author": "Editor", "context_authors": ["Alcaeus of Mytilene", "Sappho"],
         "language": "eng", "kind": "commentary"},
        {"id": "ref", "author": "Alcaeus", "language": "grc", "kind": "reference"},
        {"id": "apparatus", "author": "Alcaeus", "language": "grc", "kind": "apparatus"},
        {"id": "s", "author": "Sappho", "language": "grc", "kind": "text"},
    ]


@pytest.mark.parametrize("author", [None, "Alcaeus", "ALCAEUS OF MYTILENE", "Sappho",
                                        ["Sappho", "Alcaeus"], "Sappho / Alcaeus", "missing"])
@pytest.mark.parametrize("language", [None, "grc", "ell", "eng"])
@pytest.mark.parametrize("include_reference", [False, True])
def test_filter_matches_exhaustive_reference_with_stable_ties(tmp_path, author, language, include_reference):
    rows = rows_fixture()
    scores = [0.99, 0.7, 0.7, 0.8, 0.5, 0.95, 0.92, 0.7]
    index = make_index(tmp_path / "index", rows, scores)
    requested = author if isinstance(author, list) else [author]
    sought = {author_aliases.canonical_key(label) for label in requested if label}
    expected = []
    for position in np.argsort(-np.asarray(scores, dtype=np.float32), kind="stable"):
        row = rows[position]
        keys = {key for label in [row["author"], *row.get("context_authors", [])]
                for key in author_aliases.component_keys(label)}
        if author and not (keys & sought):
            continue
        if language and row["language"] != language:
            continue
        if not include_reference and row["kind"] in {"reference", "apparatus"}:
            continue
        expected.append(row["id"])
    hits = index.search("sea", limit=3, author=author, language=language, include_reference=include_reference)
    assert [hit["id"] for hit in hits] == expected[:3]
    assert [hit["score"] for hit in hits] == [round(scores[[row["id"] for row in rows].index(hit["id"])], 6) for hit in hits]
    if not expected:
        assert index._model.calls == 0


def test_alias_table_read_once_per_request_not_per_row_and_changes_are_seen(tmp_path, monkeypatch):
    table_path = tmp_path / "aliases.json"
    table_path.write_text(json.dumps({"authors": [{"canonical": "Alcaeus", "labels": ["lyric poet"]}]}), encoding="utf-8")
    monkeypatch.setattr(author_aliases, "DEFAULT_TABLE", table_path)
    actual_table = author_aliases.table
    calls = []

    def counted_table(*args, **kwargs):
        calls.append(1)
        return actual_table(*args, **kwargs)

    monkeypatch.setattr(author_aliases, "table", counted_table)
    rows = [{"id": str(i), "author": "lyric poet", "kind": "text", "language": "grc"} for i in range(12000)]
    index = make_index(tmp_path / "index", rows, [0.5] * len(rows))
    assert len(index.search("sea", author="Alcaeus", limit=12000)) == 12000
    assert len(calls) == 1
    before = table_path.stat().st_mtime_ns
    table_path.write_text(json.dumps({"authors": [{"canonical": "Sappho", "labels": ["lyric poet"]}]}), encoding="utf-8")
    os.utime(table_path, ns=(before + 1000000, before + 1000000))
    assert not index.search("sea", author="Alcaeus")
    assert len(index.search("sea", author="Sappho")) == 30
    assert len(calls) == 3


def test_index_reload_rebuilds_filter_positions(tmp_path):
    directory = tmp_path / "index"
    index = make_index(directory, rows_fixture(), [0.5] * 8)
    before = (directory / "manifest.json").stat().st_mtime_ns
    make_index(directory, [{"id": "new", "author": "Alcaeus", "language": "grc", "kind": "text"}], [0.9], version="replacement")
    os.utime(directory / "manifest.json", ns=(before + 1000000, before + 1000000))
    assert [hit["id"] for hit in index.search("sea", author="Alcaeus")] == ["new"]


def test_author_filter_has_no_rank_cutoff(tmp_path):
    rows = [{"id": str(i), "author": "Other", "language": "grc", "kind": "text"} for i in range(12000)]
    rows.append({"id": "last", "author": "Alcaeus", "language": "grc", "kind": "text"})
    index = make_index(tmp_path / "index", rows, [0.99] * 12000 + [-0.1])
    assert [hit["id"] for hit in index.search("sea", author="Alcaeus")] == ["last"]
