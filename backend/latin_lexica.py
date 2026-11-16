"""The further Latin dictionaries: a reader over every data/lexica/lex_*.sqlite.

One file per dictionary, written by scripts/ingest_lexica_la.py and two sibling builders to one contract:
entries(id, headword, folded, text) with an index on folded, and meta(key, value) with name, title, language,
direction (la-de, la-fr, la-en, la-la, en-la, de-la), source_url, licence, retrieved, n_entries. A store may also
carry forms(folded, entry_id) for alternative headwords, an FTS5 table over entries, or, when the print could not
be cut into entries, pages(volume, col, text) with or without an FTS table. Everything here reads what is there.

A Latin word is looked up as backend/latin_dictionary.lookup does it: the spelling, the lemmas the lemma index
gives the form, and the headwords Lewis & Short resolves it to. English goes to the English-Latin dictionaries
(Smith & Hall, Riddle-Arnold), whose Latin answers carry marked quantities and are picked out by them.

Nothing raises; a missing or broken file is skipped; connections are read-only.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path

from . import latin_dictionary as ld

SNIPPET = 320
_local = threading.local()


def lex_dir() -> Path:
    if os.environ.get("MELOS_LEXICA_DIR"):
        return Path(os.environ["MELOS_LEXICA_DIR"])
    return ld.db_path().parent


def _paths() -> dict[str, Path]:
    try:
        return {p.stem[4:]: p for p in sorted(lex_dir().glob("lex_*.sqlite"))}
    except OSError:
        return {}


def _db(name: str) -> sqlite3.Connection | None:
    """A read-only connection to one store, per thread, reopened when the file changes; None if it cannot open."""
    path = _paths().get(name)
    if path is None:
        return None
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
        cache = _local.__dict__.setdefault("dbs", {})
        if cache.get(name, (None, None))[0] != stamp:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            cache[name] = (stamp, con)
        return cache[name][1]
    except (OSError, sqlite3.Error):
        return None


def _tables(con: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    except sqlite3.Error:
        return set()


def _fts(con: sqlite3.Connection, base: str) -> str:
    """The FTS table that indexes `base` (entries or pages), by name, or ''."""
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%fts5%'").fetchall()
    except sqlite3.Error:
        return ""
    names = [r[0] for r in rows]
    return next((n for n in names if n.startswith(base[:-1]) or n.startswith(base)), "")


def available() -> list[dict]:
    """One dict per store: its meta rows, plus path, entries and pages counted from the tables themselves."""
    out = []
    for name in _paths():
        con = _db(name)
        if con is None:
            continue
        try:
            tables = _tables(con)
            if not tables & {"entries", "pages"}:       # not a database, or not a dictionary
                continue
            meta = {r[0]: r[1] for r in con.execute("SELECT key, value FROM meta")} if "meta" in tables else {}
            if meta.get("name", name) != name:          # the file's name is the key everywhere (lex_tll_partial -> tll_partial)
                meta["declared_name"] = meta["name"]
            meta["name"] = name
            meta["entries"] = con.execute("SELECT count(*) FROM entries").fetchone()[0] if "entries" in tables else 0
            meta["pages"] = con.execute("SELECT count(*) FROM pages").fetchone()[0] if "pages" in tables else 0
            meta["path"] = str(_paths()[name])
            out.append(meta)
        except sqlite3.Error:
            continue
    return out


def _direction(name: str) -> str:
    return next((m.get("direction", "") for m in available() if m["name"] == name), "")


def _wanted(dicts: list[str] | str | None, prefix: str = "") -> list[str]:
    names = [m["name"] for m in available() if m.get("direction", "").startswith(prefix)]
    if dicts:
        asked = [d.strip() for d in (dicts.split(",") if isinstance(dicts, str) else dicts) if d and d.strip()]
        names = [n for n in asked if n in _paths()]
    return names


def latin_keys(word: str) -> list[tuple[str, str]]:
    """[(folded key, how)] to try for a Latin word: the spelling, then its lemmas, then L&S's headwords for it."""
    keys: list[tuple[str, str]] = []

    def add(key: str, how: str) -> None:
        if key and key not in [k for k, _ in keys]:
            keys.append((key, how))

    w = ld.fold(word)
    add(w, "headword")
    try:
        from . import latin_lemma
        for r in latin_lemma.readings(word)[:3]:
            add(ld.fold(r["lemma"]), f"form of {r['lemma']}")
    except Exception:  # noqa: BLE001
        pass
    try:
        for e in ld.lookup(word)[:4]:
            add(e["folded"], f"Lewis & Short {e['headword']}")
    except Exception:  # noqa: BLE001
        pass
    for e in ld.ENCLITICS:
        if len(w) > len(e) + 2 and w.endswith(e):
            add(w[:-len(e)], f"without -{e}")
    return keys


def _rows(con: sqlite3.Connection, key: str, limit: int) -> list[sqlite3.Row]:
    rows = con.execute("SELECT id, headword, folded, text FROM entries WHERE folded=? ORDER BY id LIMIT ?", (key, limit)).fetchall()
    if len(rows) < limit and "forms" in _tables(con):
        have = {r["id"] for r in rows}
        rows += [r for r in con.execute("SELECT e.id, e.headword, e.folded, e.text FROM forms f JOIN entries e ON e.id=f.entry_id "
                                        "WHERE f.folded=? ORDER BY e.id LIMIT ?", (key, limit)) if r["id"] not in have]
    return rows[:limit]


def _entry(name: str, r: sqlite3.Row, how: str, full: bool) -> dict:
    text = r["text"] or ""
    return {"dict": name, "id": r["id"], "headword": r["headword"], "folded": r["folded"], "how": how,
            "text": text if full or len(text) <= SNIPPET else text[:SNIPPET].rsplit(" ", 1)[0] + " ...", "chars": len(text)}


def lookup(word: str, dicts: list[str] | str | None = None, limit: int = 3, *, full: bool = False) -> dict[str, list[dict]]:
    """{dictionary: [entries]} for a word. Latin-headword dictionaries get the word's spelling, lemmas and L&S
    headwords in turn (the first key that finds an entry wins); English and German ones get it lowercased."""
    out: dict[str, list[dict]] = {}
    if not (word or "").strip():
        return out
    keys = None
    for name in _wanted(dicts, "" if dicts else "la-"):     # unasked, a Latin word goes to the Latin-headword stores
        con = _db(name)
        if con is None:
            continue
        try:
            if "entries" not in _tables(con):
                continue
            if _direction(name).startswith("la-"):
                keys = keys if keys is not None else latin_keys(word)
                tries = keys
            else:
                tries = [(k, "headword") for k in _english_keys(word)]
            for key, how in tries:
                rows = _rows(con, key, limit)
                if rows:
                    out[name] = [_entry(name, r, how, full) for r in rows]
                    break
        except sqlite3.Error:
            continue
    return out


def gloss(word: str, dicts: tuple[str, ...] = ("georges", "gaffiot"), chars: int = 160) -> dict[str, str]:
    """{dictionary: one line} for a Latin word: the opening of its first entry, for evidence rows."""
    out = {}
    try:
        for name, es in lookup(word, list(dicts), 1, full=True).items():
            line = re.sub(r"\s+", " ", es[0]["text"])
            out[name] = line if len(line) <= chars else line[:chars].rsplit(" ", 1)[0] + " ..."
    except Exception:  # noqa: BLE001
        pass
    return out


def _english_keys(q: str) -> list[str]:
    """Headword spellings to try for an English (or German) query: as typed, without 'to ', and unpluralised."""
    w = re.sub(r"\s+", " ", (q or "").lower()).strip(" .,;:!?")
    w = re.sub(r"^(?:to|a|an|the) ", "", w)
    keys = [w]
    if w.endswith("ies") and len(w) > 4:
        keys.append(w[:-3] + "y")
    if w.endswith("es") and len(w) > 4:
        keys.append(w[:-2])
    if w.endswith("s") and len(w) > 3:
        keys.append(w[:-1])
    if w.endswith("ing") and len(w) > 5:
        keys += [w[:-3], w[:-3] + "e"]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


_QUANTITY = "āēīōūȳăĕĭŏŭÿĀĒĪŌŪĂĔĬŎŬ"
_MARKED = re.compile(rf"[A-Za-zæœ{_QUANTITY}̄̆]*[{_QUANTITY}̄̆][A-Za-zæœ{_QUANTITY}̄̆]*")
_ENDING = re.compile(r"^(?:a|ae|am|arum|e|ei|i|ii|is|ium|inis|onis|oris|eris|atis|itis|icis|idis|utis|us|um|orum|uum|ua|ēre|āre|īre|ĕre|ui|i|atum|itum)$")


_NUMBERED = re.compile(r"(?:^|[\s:])\d{1,2}\.\s+([a-zæœ]{3,})(?=[\s,:(])")      # "1. mappa (table n.)": no quantity to mark


class _Span:
    def __init__(self, start: int, stop: int) -> None:
        self._s, self._e = start, stop

    def start(self) -> int:
        return self._s

    def end(self) -> int:
        return self._e


def _is_headword(word: str) -> bool:
    """Is this unmarked word a Latin headword (of Lewis & Short)? Sorts 'mappa' from 'only' after a sense number."""
    try:
        return any(e["folded"] == ld.fold(word) for e in ld.lookup(word))
    except Exception:  # noqa: BLE001
        return False


def latin_words(text: str, limit: int = 12) -> list[dict]:
    """The Latin words an English-Latin article offers, in its order: Smith & Hall marks the quantities of the
    words it gives as answers and of nothing else, so a marked word is an answer. Each comes with the clause it
    stands in. Endings after a comma (dēlĭciae, ārum) are passed over."""
    out, seen = [], set()
    spots = [(m.start(), m.end(), m.group(0), True) for m in _MARKED.finditer(text or "")]
    spots += [(m.start(1), m.end(1), m.group(1), False) for m in _NUMBERED.finditer(text or "")]
    for start, stop, w, marked in sorted(spots):
        m = _Span(start, stop)
        if not marked and (ld.fold(w) in seen or not _is_headword(w)):
            continue
        plain = "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c))
        key = ld.fold(w)
        if len(key) < 3 or key in seen or (text[max(0, m.start() - 2):m.start()] == ", " and (_ENDING.match(plain.lower()) or len(key) < 4)):
            continue
        seen.add(key)
        end = min([i for i in (text.find(". ", m.end()), text.find("\n", m.end())) if i >= 0] or [len(text)])
        out.append({"word": w, "folded": key, "context": re.sub(r"\s+", " ", text[m.start():min(end + 1, m.start() + 160)]).strip()})
        if len(out) >= limit:
            break
    return out


def english(q: str, limit: int = 20, dicts: list[str] | str | None = None) -> list[dict]:
    """English -> Latin from the English-Latin dictionaries: the articles under the English headword, each with
    the Latin words it offers (`latin`: word, folded, context). Exact headwords first, then headwords that begin
    with the query."""
    out: list[dict] = []
    keys = _english_keys(q)
    if not keys:
        return out
    for name in _wanted(dicts, "en-"):
        con = _db(name)
        if con is None:
            continue
        try:
            rows: list[sqlite3.Row] = []
            for key in keys:
                rows = _rows(con, key, limit)
                if rows:
                    break
            how = "headword"
            if not rows:
                rows = con.execute("SELECT id, headword, folded, text FROM entries WHERE folded LIKE ? ORDER BY length(folded), id LIMIT ?",
                                   (keys[0].replace("%", "") + "%", min(limit, 5))).fetchall()
                how = "headword begins with the query"
            for r in rows:
                e = _entry(name, r, how, True)
                e["latin"] = latin_words(e["text"])
                out.append(e)
        except sqlite3.Error:
            continue
    return out[:limit]


def _match(q: str) -> str:
    terms = re.findall(r"[^\W\d_]+", q or "", re.UNICODE)
    return " ".join(f'"{t}"' for t in terms)


def _excerpt(text: str, q: str, width: int = 240) -> str:
    low, terms = (text or "").lower(), [t.lower() for t in re.findall(r"[^\W\d_]+", q or "", re.UNICODE)]
    at = min([i for i in (low.find(t) for t in terms) if i >= 0] or [0])
    a = max(0, at - width // 3)
    return ("... " if a else "") + re.sub(r"\s+", " ", text[a:a + width]).strip() + (" ..." if a + width < len(text) else "")


def search(q: str, dicts: list[str] | str | None = None, limit: int = 10) -> dict[str, list[dict]]:
    """Full text over the entries of each dictionary: {dictionary: [{id, headword, excerpt}]}. FTS5 where the store
    has it (all words of the query, any order), else a substring scan."""
    out: dict[str, list[dict]] = {}
    match = _match(q)
    if not match:
        return out
    for name in _wanted(dicts):
        con = _db(name)
        if con is None or "entries" not in _tables(con):
            continue
        try:
            fts = _fts(con, "entries")
            if fts:
                rows = con.execute(f"SELECT e.id, e.headword, e.text FROM {fts} f JOIN entries e ON e.id=f.rowid WHERE {fts} MATCH ? "
                                   "ORDER BY bm25(" + fts + ") LIMIT ?", (match, limit)).fetchall()
            else:
                rows = con.execute("SELECT id, headword, text FROM entries WHERE text LIKE ? LIMIT ?", (f"%{q.strip()}%", limit)).fetchall()
            if rows:
                out[name] = [{"dict": name, "id": r["id"], "headword": r["headword"], "excerpt": _excerpt(r["text"], q)} for r in rows]
        except sqlite3.Error:
            continue
    return out


def pages(q: str, dicts: list[str] | str | None = None, limit: int = 10) -> dict[str, list[dict]]:
    """For stores that keep whole pages (the Thesaurus where it could not be cut into entries):
    {dictionary: [{volume, col, excerpt}]} of the pages that contain the query."""
    out: dict[str, list[dict]] = {}
    match = _match(q)
    if not match:
        return out
    for name in _wanted(dicts):
        con = _db(name)
        if con is None or "pages" not in _tables(con):
            continue
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(pages)")]
            vol = "p.volume" if "volume" in cols else "NULL"
            col = next((f"p.{c}" for c in ("col", "col_from", "pdf_page", "page") if c in cols), "NULL")
            fts = _fts(con, "pages")
            rows = []
            if fts:
                try:
                    rows = con.execute(f"SELECT {vol} AS volume, {col} AS col, p.text AS text FROM {fts} f JOIN pages p ON p.rowid=f.rowid "
                                       f"WHERE {fts} MATCH ? ORDER BY bm25({fts}) LIMIT ?", (match, limit)).fetchall()
                except sqlite3.Error:
                    rows = []
            if not rows:
                rows = con.execute(f"SELECT {vol} AS volume, {col} AS col, p.text AS text FROM pages p WHERE p.text LIKE ? LIMIT ?",
                                   (f"%{q.strip()}%", limit)).fetchall()
            if rows:
                out[name] = [{"dict": name, "volume": r["volume"], "col": r["col"], "excerpt": _excerpt(r["text"], q)} for r in rows]
        except sqlite3.Error:
            continue
    return out


def query(q: str = "", *, en: str = "", search_text: str = "", dicts: str | None = None, limit: int = 3, full: bool = False) -> dict:
    """One call for the route, the agent tool and the CLI: a Latin word (q), English (en) or full text (search_text)."""
    try:
        out: dict = {"dictionaries": [{k: m.get(k) for k in ("name", "title", "direction", "entries", "pages", "licence")} for m in available()]}
        if q.strip():
            out["word"], out["lookup"] = q.strip(), lookup(q, dicts, limit, full=full)
            if not out["lookup"]:
                out["pages"] = pages(q, dicts, limit)
        if en.strip():
            rows = english(en, max(limit, 6), dicts)
            if not full:
                for r in rows:
                    r["text"] = r["text"] if len(r["text"]) <= 900 else r["text"][:900].rsplit(" ", 1)[0] + " ..."
            out["english"] = rows
        if search_text.strip():
            out["search"] = search(search_text, dicts, max(limit, 5))
            found = pages(search_text, dicts, max(limit, 5))
            if found:
                out["pages"] = found
        return out
    except Exception as exc:  # noqa: BLE001 - the reader never raises
        return {"dictionaries": [], "error": f"unavailable: {type(exc).__name__}: {exc}"}
