"""Read-only access to the owner's private corpus store (release T).

The store is a SQLite file built on the box by ``scripts/private_ingest.py`` from the
owner's drop folder (``/home/alvin/melos-private``) and mounted read-only into the
API container (``MELOS_PRIVATE_STORE``). It is never part of the repository or the
Vercel build.

Two kinds of callers, kept apart on purpose:

* owner routes (``backend/private_mode.py``) call the ``owner_*`` functions, which demand
  an ``OwnerContext`` from a verified session and return full text tagged with ``MARKER``;
* public code may use private material only through ``backend/private_gate.py`` (the single
  gate). A test fails if any other backend module imports this one.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path

from .private_auth import OwnerContext
from .private_schema import KINDS, SCHEMA, fold  # noqa: F401 - re-exported

MARKER = "private-owner-only"
LABEL = "Private — owner only"

_WORD = re.compile(r"\w+", re.UNICODE)


def store_path() -> Path:
    return Path(os.environ.get("MELOS_PRIVATE_STORE", "/private/private.sqlite"))


_local = threading.local()


def _connect() -> sqlite3.Connection | None:
    path = store_path()
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = getattr(_local, "con", None)
    if cached is not None and getattr(_local, "stamp", None) == stamp:
        return cached
    if cached is not None:
        cached.close()
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    _local.con, _local.stamp = con, stamp
    return con


def available() -> bool:
    try:
        con = _connect()
        return bool(con and con.execute("SELECT 1 FROM documents LIMIT 1").fetchone())
    except sqlite3.Error:
        return False


def fts_query(text: str, any_term: bool = False) -> str:
    """A safe FTS5 query from free text: folded words, each quoted (no operators)."""
    words = [w for w in _WORD.findall(fold(text)) if len(w) > 1 or not w.isascii()][:12]
    return (" OR " if any_term else " ").join(f'"{w}"' for w in dict.fromkeys(words))


# --------------------------------------------------------------------------- shared raw access
# Used by the owner functions below and by private_gate (which never returns page text).

def _search_pages(query: str, limit: int) -> list[sqlite3.Row]:
    con = _connect()
    if con is None or not query.strip():
        return []
    rows: list[sqlite3.Row] = []
    for any_term in (False, True):
        match = fts_query(query, any_term)
        if not match:
            return []
        try:
            rows = con.execute(
                "SELECT doc_id, page_no, bm25(page_fts) AS rank FROM page_fts WHERE page_fts MATCH ? "
                "ORDER BY rank LIMIT ?", (match, limit)).fetchall()
        except sqlite3.Error:
            return []
        if rows:
            break
    return rows


def _links_for_pages(pages: list[tuple[str, int]]) -> list[sqlite3.Row]:
    con = _connect()
    if con is None or not pages:
        return []
    out = []
    for doc_id, page_no in pages:
        out += con.execute("SELECT doc_id, page_no, passage_id, score, method FROM passage_links "
                           "WHERE doc_id=? AND page_no=? ORDER BY score DESC LIMIT 20", (doc_id, page_no)).fetchall()
    return out


def _page_row(doc_id: str, page_no: int) -> sqlite3.Row | None:
    con = _connect()
    if con is None:
        return None
    return con.execute(
        "SELECT p.doc_id, p.page_no, p.page_label, p.method, p.text, d.title, d.author, d.editor, d.year, d.kind, "
        "d.language, d.citation, d.rights_basis FROM pages p JOIN documents d USING(doc_id) "
        "WHERE p.doc_id=? AND p.page_no=?", (doc_id, page_no)).fetchone()


# --------------------------------------------------------------------------- owner payloads

def _require(owner: OwnerContext) -> None:
    if not isinstance(owner, OwnerContext):
        raise PermissionError("private text needs a verified owner session")


def _item(row: sqlite3.Row, **extra) -> dict:
    label = row["page_label"] or str(row["page_no"])
    return {"visibility": MARKER, "label": LABEL, "doc_id": row["doc_id"], "title": row["title"],
            "author": row["author"] or "", "editor": row["editor"] or "", "year": row["year"] or "",
            "kind": row["kind"], "language": row["language"] or "", "citation": row["citation"],
            "page": label, "pdf_page": row["page_no"], "method": row["method"],
            "source": f"{row['citation']}, p. {label}", "text": row["text"], **extra}


def _payload(items: list[dict], **extra) -> dict:
    return {"visibility": MARKER, "label": LABEL, "results": items, "total": len(items), **extra}


def owner_status(owner: OwnerContext) -> dict:
    _require(owner)
    con = _connect()
    if con is None:
        return _payload([], available=False)
    docs, pages = con.execute("SELECT count(*), coalesce(sum(pages),0) FROM documents").fetchone()
    links = con.execute("SELECT count(*) FROM passage_links").fetchone()[0]
    return _payload([], available=True, documents=docs, pages=pages, passage_links=links)


def owner_documents(owner: OwnerContext) -> dict:
    _require(owner)
    con = _connect()
    if con is None:
        return _payload([], available=False)
    items = [{"visibility": MARKER, "label": LABEL, **dict(row)} for row in con.execute(
        "SELECT doc_id, title, author, editor, year, kind, language, citation, rights_basis, acquired_from, "
        "source_name, pages, ocr_pages, ingested_at FROM documents ORDER BY author, title")]
    return _payload(items)


def owner_page(owner: OwnerContext, doc_id: str, page_no: int) -> dict | None:
    _require(owner)
    row = _page_row(doc_id, page_no)
    if row is None:
        return None
    con = _connect()
    neighbours = con.execute("SELECT min(page_no), max(page_no) FROM pages WHERE doc_id=?", (doc_id,)).fetchone()
    return _payload([_item(row)], first_page=neighbours[0], last_page=neighbours[1])


def owner_passage(owner: OwnerContext, passage_id: str, limit: int = 20) -> dict:
    """Private pages linked to a public passage (shared Greek wording or the manifest's own links)."""
    _require(owner)
    con = _connect()
    if con is None:
        return _payload([], passage_id=passage_id)
    links = con.execute("SELECT doc_id, page_no, max(score) AS score, group_concat(DISTINCT method) AS methods "
                        "FROM passage_links WHERE passage_id=? GROUP BY doc_id, page_no ORDER BY score DESC LIMIT ?",
                        (passage_id, limit)).fetchall()
    items = []
    for link in links:
        row = _page_row(link["doc_id"], link["page_no"])
        if row is not None:
            items.append(_item(row, link_score=round(link["score"], 3), link_methods=link["methods"].split(",")))
    return _payload(items, passage_id=passage_id)


def owner_search(owner: OwnerContext, q: str, limit: int = 20) -> dict:
    _require(owner)
    items = []
    for hit in _search_pages(q, limit):
        row = _page_row(hit["doc_id"], hit["page_no"])
        if row is not None:
            items.append(_item(row, rank=round(-hit["rank"], 3)))
    return _payload(items, q=q)


def owner_lemma(owner: OwnerContext, lemma: str, limit: int = 20) -> dict:
    """Pages naming a headword: the folded headword, or a word starting with its stem (4+ letters)."""
    _require(owner)
    con = _connect()
    key = fold(lemma).strip()
    if con is None or not key or not _WORD.fullmatch(key):
        return _payload([], lemma=lemma)
    terms = [f'"{key}"']
    stem = key[:-2] if len(key) >= 6 else (key[:-1] if len(key) >= 5 else "")
    if stem:
        terms.append(f'"{stem}" *')
    try:
        hits = con.execute("SELECT doc_id, page_no, bm25(page_fts) AS rank FROM page_fts WHERE page_fts MATCH ? "
                           "ORDER BY rank LIMIT ?", (" OR ".join(terms), limit)).fetchall()
    except sqlite3.Error:
        hits = []
    items = []
    for hit in hits:
        row = _page_row(hit["doc_id"], hit["page_no"])
        if row is not None:
            items.append(_item(row, rank=round(-hit["rank"], 3)))
    return _payload(items, lemma=lemma, matched=[key] + ([stem + "…"] if stem else []))
