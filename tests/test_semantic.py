import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from backend.semantic import SemanticIndex
from scripts.build_embeddings import build, encode_passage_batch


class FakeTokenizer:
    def num_special_tokens_to_add(self, pair=False):
        return 0

    def encode(self, text, add_special_tokens=False, truncation=False):
        return [ord(char) for char in text]

    def decode(self, ids, **kwargs):
        return "".join(chr(value) for value in ids)


class FakeEncoder:
    def __init__(self):
        self.calls = []
        self.tokenizer = FakeTokenizer()

    def encode(self, texts, **kwargs):
        self.calls.extend(texts)
        output = []
        for text in texts:
            vector = np.array([1.0, 0.0] if "sea" in text else [0.0, 1.0], dtype=np.float32)
            output.append(vector)
        return np.stack(output)


def make_db(path: Path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, source TEXT, text TEXT, language TEXT, kind TEXT, quality TEXT, author TEXT, data TEXT)")
        db.executemany(
            "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
            [
                ("greek", "ogc", "θάλασσα", "grc", "text", "source_text", "Sappho", json.dumps({"source_url": "https://example.org/page"})),
                ("english", "perseus", "the wine dark sea", "eng", "translation", "source_text", "Sappho", json.dumps({"parent_id": "greek"})),
                ("other", "perseus", "mountain", "eng", "text", "source_text", "Other", "{}"),
                ("ocr", "perseus", "sea", "eng", "text", "machine_ocr", "Other", "{}"),
            ],
        )


def test_build_search_checkpoint_and_translation_disclosure(tmp_path):
    db_path = tmp_path / "corpus.sqlite"
    index_dir = tmp_path / "index"
    make_db(db_path)
    index = SemanticIndex(index_dir)
    with pytest.raises(RuntimeError, match="not built"):
        index.search("sea")
    encoder = FakeEncoder()
    manifest = build(db_path, index_dir, encoder=encoder)
    assert manifest["count"] == manifest["eligible_count"] == 3
    assert len(encoder.calls) == 3
    assert index.ready  # index instance created before build refreshes itself
    index._model = encoder
    matches = index.search("sea", limit=2)
    assert matches[0]["id"] == "english"
    assert matches[0]["parent_id"] == "greek"
    assert matches[0]["match_reason"] == "English translation embedding"
    found, vectors = index.vectors_for(["english", "missing", "greek"])
    assert found == ["english", "greek"]
    assert vectors.shape == (2, 2)
    another = FakeEncoder()
    build(db_path, index_dir, encoder=another)
    assert another.calls == []
    assert index.search("mountain", author="Other")[0]["id"] == "other"
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE passages SET text='the open sea' WHERE id='other'")
    assert not index.ready
    with pytest.raises(RuntimeError, match="stale"):
        index.search("sea")
    build(db_path, index_dir, encoder=FakeEncoder())
    assert index.ready


def test_cap_reports_coverage(tmp_path):
    db_path = tmp_path / "corpus.sqlite"
    make_db(db_path)
    manifest = build(db_path, tmp_path / "index", max_passages=1, encoder=FakeEncoder())
    assert manifest["count"] == 1
    assert manifest["eligible_count"] == 3


def test_clean_commentary_is_available_as_labelled_bridge(tmp_path):
    db_path = tmp_path / "corpus.sqlite"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
            ("note", "scholarship", "the sea as exile", "eng", "commentary", "source_text", "Scholar", json.dumps({"parent_id": "greek"})),
        )
    index_dir = tmp_path / "index"
    build(db_path, index_dir, encoder=FakeEncoder())
    index = SemanticIndex(index_dir)
    index._model = FakeEncoder()
    hit = index.search("sea", author="Scholar")[0]
    assert hit["id"] == "note"
    assert hit["match_reason"] == "Commentary embedding"
    assert any(item["id"] == "note" for item in index.search("sea", author="sApPhO"))
    assert "Sappho" in hit["context_authors"]


@pytest.mark.parametrize('scope', ['page', 'source_section'])
def test_page_scope_author_link_does_not_change_record_author(tmp_path, scope):
    db_path = tmp_path / "corpus.sqlite"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
            ("page_note", "ogc", "sea notes", "eng", "commentary", "source_text", "Editor", json.dumps({"source_url": "https://example.org/page", "metadata": {"scope": scope}})),
        )
        db.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
            ('other_collection', 'unrelated', 'sea notes', 'eng', 'commentary', 'source_text', 'Editor',
             json.dumps({'source_url': 'https://example.org/page', 'metadata': {'scope': scope}})))
    index_dir = tmp_path / "index"
    build(db_path, index_dir, encoder=FakeEncoder())
    index = SemanticIndex(index_dir)
    index._model = FakeEncoder()
    hit = next(item for item in index.search("sea", author="SAPPHO") if item["id"] == "page_note")
    assert hit["context_authors"] == ["Sappho"]
    assert index._rows[next(i for i, row in enumerate(index._rows) if row["id"] == "page_note")]["author"] == "Editor"
    assert 'other_collection' not in {item['id'] for item in index.search('sea', author='Sappho')}


def test_all_tokens_contribute_to_long_passage_vector():
    encoder = FakeEncoder()
    vector, counts = encode_passage_batch(encoder, ["mountain" + "sea"], batch_size=2, max_seq_length=8)
    assert counts == [2]
    assert encoder.calls == ["mountain", "sea"]
    assert all(len(encoder.tokenizer.encode(text)) <= 8 for text in encoder.calls)
    assert vector.shape == (1, 2)
    assert vector[0, 0] > 0  # the late "sea" window contributed


def test_decoded_window_is_rechecked_before_encoder_truncation():
    class BoundaryTokenizer(FakeTokenizer):
        def encode(self, text, add_special_tokens=False, truncation=False):
            ids = super().encode(text, add_special_tokens, truncation)
            return ids + [0] if text.startswith("b") else ids

    encoder = FakeEncoder()
    encoder.tokenizer = BoundaryTokenizer()
    original = "12345678b12345678"
    _, counts = encode_passage_batch(encoder, [original], batch_size=2, max_seq_length=8)
    assert counts == [3]
    assert "".join(encoder.calls) == original
    assert all(len(encoder.tokenizer.encode(text)) <= 8 for text in encoder.calls)
