"""Release S: commentary notes as document expansion for search, with source, licence and display rules.

``data/commentary_context.sqlite`` (``MELOS_COMMENTARY_CONTEXT``) is built offline by
``scripts/build_commentary_context.py`` from open public-domain commentaries and from the owner's PDFs in
``data/commentary_inbox/``. Each note keeps its source, page or locator, link and licence, and the corpus
passages it is linked to (by the Greek words it quotes, matched in that commentary's poets' passages).

Display rule (owner, 2026-10-09): a public-domain note can be shown in full. Any other note (in copyright,
licensed, or the owner's PDFs unless stated public domain) is used only for derived, non-display signals
(the search list below, vectors, passage links); the public site shows at most a quotation of
``QUOTE_WORDS`` words with the full citation and a link (``display_note``).
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path

from .textutils import normalize, tokenize

ROOT = Path(__file__).resolve().parents[1]
QUOTE_WORDS = 30
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_LOCAL = threading.local()


def db_path():
    return Path(os.getenv("MELOS_COMMENTARY_CONTEXT", str(ROOT / "data/commentary_context.sqlite")))


def connect():
    path = db_path()
    if not path.exists():
        return None
    con = getattr(_LOCAL, "con", None)
    if con is None or getattr(_LOCAL, "path", None) != path:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        _LOCAL.con, _LOCAL.path = con, path
    return con


def is_public_domain(licence):
    return (licence or "").strip().lower().startswith("public domain")


def display_note(row):
    """A note as the public site may show it: full public-domain text, else a quotation of at most
    QUOTE_WORDS words with the citation and link."""
    full = is_public_domain(row["licence"])
    words = (row["text"] or "").split()
    text = " ".join(words) if full else " ".join(words[:QUOTE_WORDS]) + (" …" if len(words) > QUOTE_WORDS else "")
    return {"note_id": row["id"], "source": row["title"], "author": row["author"], "year": row["year"],
            "locator": row["locator"], "page": row["page"], "url": row["url"], "licence": row["licence"],
            "display": "full" if full else "quotation", "text": text,
            "citation": f"{row['author']}, {row['title']} ({row['year']})" + (f", {row['locator']}" if row["locator"] else "")}


def _terms(q):
    from .bridges import english_terms
    greek = [normalize(t) for t in tokenize(q) if GREEK.search(t)]
    return list(dict.fromkeys([t for t in greek if len(t) >= 2] + english_terms(q)))


def note_hits(q, limit=400, per_note=8):
    """Passages linked to the notes that best match the query (BM25 over note text), in note order."""
    con = connect()
    terms = _terms(q)
    if con is None or not terms:
        return []
    expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    notes = con.execute("SELECT f.id, bm25(note_fts) FROM note_fts f WHERE note_fts MATCH ? ORDER BY 2 LIMIT ?",
                        (expression, limit)).fetchall()
    out, seen = [], set()
    for note_id, rank in notes:
        for (passage_id,) in con.execute("SELECT passage_id FROM note_link WHERE note_id=? ORDER BY score DESC LIMIT ?",
                                         (note_id, per_note)):
            if passage_id in seen:
                continue
            seen.add(passage_id)
            src = con.execute("SELECT s.author, s.title, n.locator FROM note n JOIN source s ON s.slug=n.slug WHERE n.id=?",
                              (note_id,)).fetchone()
            out.append({"id": passage_id, "score": round(-float(rank), 4), "note_id": note_id,
                        "match_reason": f"Commentary note matches the query: {src[0]}, {src[1]}"
                                        + (f", {src[2]}" if src[2] else "")})
            if len(out) >= limit:
                return out
    return out


def notes_for_passage(passage_id, limit=20):
    con = connect()
    if con is None:
        return []
    rows = con.execute("SELECT n.id, n.locator, n.page, n.url, n.text, s.title, s.author, s.year, s.licence "
                       "FROM note_link l JOIN note n ON n.id=l.note_id JOIN source s ON s.slug=n.slug "
                       "WHERE l.passage_id=? ORDER BY l.score DESC LIMIT ?", (passage_id, limit)).fetchall()
    return [display_note(r) for r in rows]


def status():
    con = connect()
    if con is None:
        return {"ready": False}
    sources = [dict(r) for r in con.execute(
        "SELECT s.slug, s.title, s.author, s.year, s.licence, s.repository, s.url, "
        "(SELECT count(*) FROM note n WHERE n.slug=s.slug) notes, "
        "(SELECT count(DISTINCT l.passage_id) FROM note_link l JOIN note n ON n.id=l.note_id WHERE n.slug=s.slug) passages "
        "FROM source s ORDER BY s.slug")]
    return {"ready": True, "sources": sources, "quote_words": QUOTE_WORDS,
            "display_rule": "Public-domain notes are shown in full; any other note at most a quotation of "
                            f"{QUOTE_WORDS} words with its citation and link."}
