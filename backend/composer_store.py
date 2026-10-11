"""Release W: the owner's composer store (``composer.sqlite``, PRD docs/prd/composer-agent.md §6).

Path: ``MELOS_COMPOSER_DB`` (default ``/app/runtime/composer.sqlite``, the API container's only writable mount).
One connection per call, ``BEGIN IMMEDIATE`` for every write (as backend/jev_gateway.py), WAL journal.

Tables: poems, lines, versions, pool, chat. Versions and chat are append-only: triggers refuse DELETE on both,
any UPDATE of chat, and any UPDATE of a version except its ``archived`` flag and ``back_translation`` (filled in
later by the agent). Nothing is deleted; versions are archived. Schema changes are numbered migrations recorded in
``schema_migrations``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

SOURCES = ("owner", "agent", "corpus")
ROLES = ("user", "assistant", "tool")
CHAT_WINDOW = 200

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE poems (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', settings_json TEXT NOT NULL DEFAULT '{}',
        english TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE lines (
        id INTEGER PRIMARY KEY, poem_id INTEGER NOT NULL REFERENCES poems(id), position INTEGER NOT NULL,
        current_version_id INTEGER REFERENCES versions(id));
    CREATE INDEX lines_poem ON lines(poem_id, position);
    CREATE TABLE versions (
        id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL REFERENCES lines(id), greek TEXT NOT NULL,
        back_translation TEXT, scansion_json TEXT, checks_json TEXT,
        source TEXT NOT NULL CHECK (source IN ('owner','agent','corpus')), note TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX versions_line ON versions(line_id, id);
    CREATE TABLE pool (
        id INTEGER PRIMARY KEY, poem_id INTEGER NOT NULL REFERENCES poems(id), slot_key TEXT NOT NULL,
        candidate_json TEXT NOT NULL, checks_json TEXT, created_at REAL NOT NULL);
    CREATE INDEX pool_slot ON pool(poem_id, slot_key, id);
    CREATE TABLE chat (
        id INTEGER PRIMARY KEY, poem_id INTEGER NOT NULL REFERENCES poems(id),
        role TEXT NOT NULL CHECK (role IN ('user','assistant','tool')), content TEXT NOT NULL,
        trace_json TEXT, created_at REAL NOT NULL);
    CREATE INDEX chat_poem ON chat(poem_id, id);
    CREATE TRIGGER versions_no_delete BEFORE DELETE ON versions
        BEGIN SELECT RAISE(ABORT, 'versions are append-only'); END;
    CREATE TRIGGER versions_frozen BEFORE UPDATE OF id, line_id, greek, scansion_json, checks_json, source, note,
        created_at ON versions BEGIN SELECT RAISE(ABORT, 'versions are append-only'); END;
    CREATE TRIGGER chat_no_delete BEFORE DELETE ON chat BEGIN SELECT RAISE(ABORT, 'chat is append-only'); END;
    CREATE TRIGGER chat_no_update BEFORE UPDATE ON chat BEGIN SELECT RAISE(ABORT, 'chat is append-only'); END;
    """),
    # Release X.1 (2026-10-10): the lines being typed but not yet saved with Enter, as the page keeps them
    # ([{id: line id or null, at: row index, draft}]), so they survive a browser change and the agent sees them.
    (2, "ALTER TABLE poems ADD COLUMN drafts_json TEXT NOT NULL DEFAULT '[]';"),
]

_ready: set[str] = set()
_ready_lock = threading.Lock()


class StoreError(Exception):
    """A request the store refuses (unknown id, version of another line, bad value): the route answers 404/422."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def db_path() -> Path:
    return Path(os.environ.get("MELOS_COMPOSER_DB", "/app/runtime/composer.sqlite"))


def _now() -> float:
    return time.time()


def _dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(text):
    return None if text is None else json.loads(text)


def migrate(con: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the schema version."""
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
    con.execute("BEGIN IMMEDIATE")
    try:
        done = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}
        for version, script in MIGRATIONS:
            if version in done:
                continue
            for statement in _statements(script):
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations VALUES (?,?)", (version, _now()))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return max(v for v, _ in MIGRATIONS)


def _statements(script: str) -> list[str]:
    """Split a migration into statements (executescript would commit the open transaction)."""
    out, buf = [], []
    for line in script.strip().splitlines():
        buf.append(line)
        joined = "\n".join(buf).strip()
        if joined.endswith(";") and sqlite3.complete_statement(joined):
            out.append(joined)
            buf = []
    if "\n".join(buf).strip():
        out.append("\n".join(buf).strip())
    return out


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    key = str(path.resolve())
    if key not in _ready:
        with _ready_lock:
            if key not in _ready:
                con.execute("PRAGMA journal_mode=WAL")
                migrate(con)
                _ready.add(key)
    return con


class _Tx:
    """``with _Tx() as con:`` one BEGIN IMMEDIATE transaction, committed on success, rolled back on error."""

    def __enter__(self):
        self.con = connect()
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, exc_type, *_):
        try:
            self.con.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.con.close()


def _read():
    return _Closing(connect())


class _Closing:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *_):
        self.con.close()


# ------------------------------------------------------------------------------------------------ rows → dicts

def _poem(row) -> dict:
    return {"id": row["id"], "title": row["title"], "settings": _loads(row["settings_json"]) or {},
            "english": row["english"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "archived": bool(row["archived"]),
            "drafts": (_loads(row["drafts_json"]) if "drafts_json" in row.keys() else None) or []}


def _line(row) -> dict:
    return {"id": row["id"], "poem_id": row["poem_id"], "position": row["position"],
            "current_version_id": row["current_version_id"]}


def _version(row) -> dict:
    return {"id": row["id"], "line_id": row["line_id"], "greek": row["greek"], "back_translation": row["back_translation"],
            "scansion": _loads(row["scansion_json"]), "checks": _loads(row["checks_json"]), "source": row["source"],
            "note": row["note"], "created_at": row["created_at"], "archived": bool(row["archived"])}


def _chat(row) -> dict:
    return {"id": row["id"], "poem_id": row["poem_id"], "role": row["role"], "content": row["content"],
            "trace": _loads(row["trace_json"]), "created_at": row["created_at"]}


def _pool(row) -> dict:
    return {"id": row["id"], "poem_id": row["poem_id"], "slot_key": row["slot_key"],
            "candidate": _loads(row["candidate_json"]), "checks": _loads(row["checks_json"]),
            "created_at": row["created_at"]}


def _need(con, table: str, row_id: int):
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    if row is None:
        raise StoreError(404, f"no such {table[:-1]}")
    return row


# ------------------------------------------------------------------------------------------------ poems

def list_poems(include_archived: bool = False) -> list[dict]:
    with _read() as con:
        sql = "SELECT * FROM poems" + ("" if include_archived else " WHERE archived=0") + " ORDER BY updated_at DESC"
        return [_poem(r) for r in con.execute(sql)]


def create_poem(title: str = "", settings: dict | None = None, english: str = "") -> dict:
    now = _now()
    with _Tx() as con:
        cur = con.execute("INSERT INTO poems(title, settings_json, english, created_at, updated_at) VALUES (?,?,?,?,?)",
                          (title, _dumps(settings or {}), english, now, now))
        return _poem(_need(con, "poems", cur.lastrowid))


def get_poem(poem_id: int) -> dict:
    with _read() as con:
        return _poem(_need(con, "poems", poem_id))


def update_poem(poem_id: int, *, title: str | None = None, settings: dict | None = None, english: str | None = None,
                archived: bool | None = None, drafts: list | None = None) -> dict:
    with _Tx() as con:
        _need(con, "poems", poem_id)
        for column, value in (("title", title), ("settings_json", _dumps(settings) if settings is not None else None),
                              ("english", english), ("archived", int(archived) if archived is not None else None),
                              ("drafts_json", _dumps(drafts) if drafts is not None else None)):
            if value is not None:
                con.execute(f"UPDATE poems SET {column}=? WHERE id=?", (value, poem_id))
        con.execute("UPDATE poems SET updated_at=? WHERE id=?", (_now(), poem_id))
        return _poem(_need(con, "poems", poem_id))


def _touch(con, poem_id: int) -> None:
    con.execute("UPDATE poems SET updated_at=? WHERE id=?", (_now(), poem_id))


# ------------------------------------------------------------------------------------------------ lines

def insert_line(poem_id: int, position: int | None = None) -> dict:
    """A new empty line at ``position`` (0-based; default: the end); later lines move down one."""
    with _Tx() as con:
        _need(con, "poems", poem_id)
        count = con.execute("SELECT COUNT(*) FROM lines WHERE poem_id=?", (poem_id,)).fetchone()[0]
        position = count if position is None else max(0, min(int(position), count))
        con.execute("UPDATE lines SET position=position+1 WHERE poem_id=? AND position>=?", (poem_id, position))
        cur = con.execute("INSERT INTO lines(poem_id, position) VALUES (?,?)", (poem_id, position))
        _touch(con, poem_id)
        return _line(_need(con, "lines", cur.lastrowid))


def get_line(line_id: int) -> dict:
    with _read() as con:
        return _line(_need(con, "lines", line_id))


def update_line(line_id: int, *, position: int | None = None, current_version_id: int | None = None) -> dict:
    """Move a line to ``position`` (others close up) and/or make one of its own versions current."""
    with _Tx() as con:
        line = _need(con, "lines", line_id)
        poem_id = line["poem_id"]
        if position is not None:
            count = con.execute("SELECT COUNT(*) FROM lines WHERE poem_id=?", (poem_id,)).fetchone()[0]
            new, old = max(0, min(int(position), count - 1)), line["position"]
            if new < old:
                con.execute("UPDATE lines SET position=position+1 WHERE poem_id=? AND position>=? AND position<?",
                            (poem_id, new, old))
            elif new > old:
                con.execute("UPDATE lines SET position=position-1 WHERE poem_id=? AND position>? AND position<=?",
                            (poem_id, old, new))
            con.execute("UPDATE lines SET position=? WHERE id=?", (new, line_id))
        if current_version_id is not None:
            version = _need(con, "versions", current_version_id)
            if version["line_id"] != line_id:
                raise StoreError(422, "that version belongs to another line")
            con.execute("UPDATE lines SET current_version_id=? WHERE id=?", (current_version_id, line_id))
        _touch(con, poem_id)
        return _line(_need(con, "lines", line_id))


# ------------------------------------------------------------------------------------------------ versions

def add_version(line_id: int, greek: str, *, source: str = "owner", note: str = "", scansion=None, checks=None,
                back_translation: str | None = None, make_current: bool = True) -> dict:
    if source not in SOURCES:
        raise StoreError(422, f"source must be one of {', '.join(SOURCES)}")
    with _Tx() as con:
        line = _need(con, "lines", line_id)
        cur = con.execute("INSERT INTO versions(line_id, greek, back_translation, scansion_json, checks_json, source, "
                          "note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (line_id, greek, back_translation, _dumps(scansion), _dumps(checks), source, note, _now()))
        if make_current:
            con.execute("UPDATE lines SET current_version_id=? WHERE id=?", (cur.lastrowid, line_id))
        _touch(con, line["poem_id"])
        return _version(_need(con, "versions", cur.lastrowid))


def get_version(version_id: int) -> dict:
    with _read() as con:
        return _version(_need(con, "versions", version_id))


def update_version(version_id: int, *, archived: bool | None = None, make_current: bool = False,
                   back_translation: str | None = None) -> dict:
    with _Tx() as con:
        version = _need(con, "versions", version_id)
        line = _need(con, "lines", version["line_id"])
        if archived is not None:
            con.execute("UPDATE versions SET archived=? WHERE id=?", (int(archived), version_id))
            if archived and line["current_version_id"] == version_id and not make_current:
                # The line falls back to its newest version that is not archived (or none).
                row = con.execute("SELECT id FROM versions WHERE line_id=? AND archived=0 ORDER BY id DESC LIMIT 1",
                                  (line["id"],)).fetchone()
                con.execute("UPDATE lines SET current_version_id=? WHERE id=?", (row[0] if row else None, line["id"]))
        if back_translation is not None:
            con.execute("UPDATE versions SET back_translation=? WHERE id=?", (back_translation, version_id))
        if make_current:
            con.execute("UPDATE lines SET current_version_id=? WHERE id=?", (version_id, line["id"]))
        _touch(con, line["poem_id"])
        return _version(_need(con, "versions", version_id))


# ------------------------------------------------------------------------------------------------ chat, pool

def add_chat(poem_id: int, role: str, content: str, trace=None) -> dict:
    if role not in ROLES:
        raise StoreError(422, f"role must be one of {', '.join(ROLES)}")
    with _Tx() as con:
        _need(con, "poems", poem_id)
        cur = con.execute("INSERT INTO chat(poem_id, role, content, trace_json, created_at) VALUES (?,?,?,?,?)",
                          (poem_id, role, content, _dumps(trace), _now()))
        return _chat(_need(con, "chat", cur.lastrowid))


def recent_chat(poem_id: int, limit: int = CHAT_WINDOW) -> list[dict]:
    with _read() as con:
        rows = con.execute("SELECT * FROM chat WHERE poem_id=? ORDER BY id DESC LIMIT ?", (poem_id, limit)).fetchall()
        return [_chat(r) for r in reversed(rows)]


def add_pool(poem_id: int, slot_key: str, candidate, checks=None) -> dict:
    with _Tx() as con:
        _need(con, "poems", poem_id)
        cur = con.execute("INSERT INTO pool(poem_id, slot_key, candidate_json, checks_json, created_at) VALUES (?,?,?,?,?)",
                          (poem_id, slot_key, _dumps(candidate), _dumps(checks), _now()))
        return _pool(_need(con, "pool", cur.lastrowid))


def pool_for(poem_id: int, slot_key: str | None = None, limit: int = 200) -> list[dict]:
    with _read() as con:
        _need(con, "poems", poem_id)
        if slot_key:
            rows = con.execute("SELECT * FROM pool WHERE poem_id=? AND slot_key=? ORDER BY id DESC LIMIT ?",
                               (poem_id, slot_key, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM pool WHERE poem_id=? ORDER BY id DESC LIMIT ?", (poem_id, limit)).fetchall()
        return [_pool(r) for r in reversed(rows)]


# ------------------------------------------------------------------------------------------------ whole poem

def full(poem_id: int, chat_limit: int = CHAT_WINDOW) -> dict:
    """The poem, its lines in order with every version (archived included), and the last ``chat_limit`` chat rows."""
    with _read() as con:
        con.execute("BEGIN")  # one consistent snapshot
        poem = _poem(_need(con, "poems", poem_id))
        lines = [_line(r) for r in con.execute("SELECT * FROM lines WHERE poem_id=? ORDER BY position, id", (poem_id,))]
        versions: dict[int, list] = {}
        for r in con.execute("SELECT v.* FROM versions v JOIN lines l ON l.id=v.line_id WHERE l.poem_id=? ORDER BY v.id",
                             (poem_id,)):
            versions.setdefault(r["line_id"], []).append(_version(r))
        for line in lines:
            line["versions"] = versions.get(line["id"], [])
            line["current"] = next((v for v in line["versions"] if v["id"] == line["current_version_id"]), None)
        rows = con.execute("SELECT * FROM chat WHERE poem_id=? ORDER BY id DESC LIMIT ?", (poem_id, chat_limit)).fetchall()
        con.execute("COMMIT")
    return {"poem": poem, "lines": lines, "chat": [_chat(r) for r in reversed(rows)]}


def agent_context(poem_id: int, caret: dict | None = None) -> dict:
    """What the agent service is told about the poem (PRD §7): settings, English, current Greek of every line.
    A line being typed but not yet saved (``poem.drafts``, release X.1) stands in for its saved text, marked
    ``unsaved``; drafts of rows that have no saved line yet follow as further positions."""
    data = full(poem_id, chat_limit=0)
    poem = data["poem"]
    drafts = [d for d in poem["drafts"] if isinstance(d, dict) and isinstance(d.get("draft"), str) and d["draft"].strip()]
    by_line = {d["id"]: d["draft"] for d in drafts if d.get("id") is not None}
    lines = []
    for line in data["lines"]:
        current = line["current"] or {}
        unsaved = line["id"] in by_line
        lines.append({"position": line["position"], "line_id": line["id"],
                      "greek": by_line[line["id"]] if unsaved else current.get("greek", ""),
                      "back_translation": None if unsaved else current.get("back_translation"), "unsaved": unsaved})
    for d in sorted((d for d in drafts if d.get("id") is None), key=lambda d: d.get("at", 0)):
        lines.append({"position": len(lines), "line_id": None, "greek": d["draft"], "back_translation": None, "unsaved": True})
    return {"poem_id": poem["id"], "title": poem["title"], "settings": poem["settings"], "english": poem["english"],
            "lines": lines, "caret": caret or {}}
