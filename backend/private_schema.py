"""Private store schema and search fold, shared by the API and the ingest container (release T).

Standard library only: the network-less ingest image imports this without the web stack.
"""
from .textutils import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, editor TEXT, year TEXT, kind TEXT NOT NULL,
  language TEXT, rights_basis TEXT NOT NULL, acquired_from TEXT, citation TEXT NOT NULL, source_name TEXT,
  sha256 TEXT NOT NULL UNIQUE, original_ref TEXT, pages INTEGER, ocr_pages INTEGER, ingested_at TEXT,
  manifest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages(
  doc_id TEXT NOT NULL, page_no INTEGER NOT NULL, page_label TEXT, method TEXT, text TEXT NOT NULL,
  PRIMARY KEY(doc_id, page_no));
CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(
  folded, doc_id UNINDEXED, page_no UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS passage_links(
  doc_id TEXT NOT NULL, page_no INTEGER NOT NULL, passage_id TEXT NOT NULL, score REAL NOT NULL, method TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS passage_links_passage ON passage_links(passage_id);
CREATE INDEX IF NOT EXISTS passage_links_page ON passage_links(doc_id, page_no);
"""

KINDS = ("commentary", "translation", "edition", "lexicon", "grammar", "other")


def fold(text: str) -> str:
    """Accent-, case- and final-sigma-folded search key (same fold as the public corpus)."""
    return normalize(text)
