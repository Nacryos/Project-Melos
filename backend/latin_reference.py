"""Reader over the Latin reference stores in data/reference_la.sqlite (scripts/build_reference_la.py;
docs/latin/reference-stores.md): E. T. Merrill's commentary on Catullus and his Introduction (1893), and Allen and
Greenough's New Latin Grammar (1903), both public-domain books in the Perseus Digital Library's TEI.

Nothing here raises: without the database every lookup returns an empty result and `status()` says why.
Words are folded as everywhere in the Latin side (lower case, marks stripped, v -> u, j -> i).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path

from . import latin_lemma
from .latin_text import normalize_la, tokenize_la

_local = threading.local()
_cache: dict = {}
NOTE_COLS = "id, poem, line, line_start, line_end, kind, lemma, text, source_url"
STOP = frozenset("a an and the of in on to with for by or as at from is are".split())
SOURCES = {"merrill": "E. T. Merrill, Catullus (1893)", "ag": "Allen and Greenough's New Latin Grammar (1903)"}


def db_path() -> Path:
    if os.environ.get("MELOS_REFERENCE_LA"):
        return Path(os.environ["MELOS_REFERENCE_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "reference_la.sqlite"


def available() -> bool:
    return db_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(db_path()):
        db = sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        _local.db, _local.path = db, str(db_path())
    return db


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    if not available():
        return []
    try:
        return [dict(r) for r in _db().execute(sql, params)]
    except sqlite3.Error:
        return []


def _excerpt(text: str, terms: list[str], width: int = 240) -> str:
    """A window of the text around the first query term found in it (the folded text has the same length for plain
    letters; where it does not, the window is only roughly placed)."""
    folded = normalize_la(text)
    at = min((i for i in (folded.find(t) for t in terms) if i >= 0), default=0)
    if len(folded) != len(text):
        at = min(at, max(len(text) - width, 0))
    start = max(at - width // 3, 0)
    piece = text[start:start + width].strip()
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


def _terms(q: str) -> tuple[list[str], list[str]]:
    """The folded words of a query, and its content words (all of them when it has no other)."""
    terms = [t for t in (normalize_la(x) for x in tokenize_la(q or "")) if t] + re.findall(r"\d+", q or "")
    return terms, [t for t in terms if t not in STOP] or terms


def _fts(table: str, base: str, cols: str, q: str, limit: int) -> list[dict]:
    """Rows of `base` matching the words of q, best first within each step: the phrase, then all the content words,
    then any of them, then any word that opens like one of them ('hendecasyllable' reaches 'hendecasyllabic').
    A word in the heading or lemma column counts four times one in the text."""
    terms, content = _terms(q)
    if not terms or not available():
        return []
    quoted = [f'"{t}"' for t in content]
    stemmed = [f'"{t[:max(5, len(t) - 3)]}"*' for t in content if len(t) >= 7]
    queries = {'"' + " ".join(terms) + '"': "phrase", " AND ".join(quoted): "all words", " OR ".join(quoted): "any word"}
    if len(content) == 1:
        queries = {quoted[0]: "word"}
    if stemmed:
        queries.setdefault(" OR ".join(stemmed), "stem")
    out, seen = [], set()
    for match, label in queries.items():
        for r in _rows(f"SELECT {cols} FROM {table} f JOIN {base} b ON b.id = f.id WHERE {table} MATCH ? "
                       f"ORDER BY bm25({table}, 0.0, 4.0, 1.0) LIMIT ?", (match, limit)):
            if r["id"] not in seen and len(out) < limit:
                seen.add(r["id"])
                r["match"] = label
                r["excerpt"] = _excerpt(r["text"], content + [t[:max(5, len(t) - 3)] for t in content])
                out.append(r)
        if len(out) >= limit:
            break
    return out


def _poem_key(poem) -> str:
    return re.sub(r"\s+", "", str(poem or "")).lower().lstrip("0")


def commentary(poem: str, line: int | None = None) -> list[dict]:
    """Merrill's notes on a poem in his order (the headnote first); with `line`, the notes whose line or line range
    covers it (the headnote is left out)."""
    p = _poem_key(poem)
    if not p:
        return []
    rows = _rows(f"SELECT {NOTE_COLS} FROM merrill_notes WHERE poem = ? ORDER BY seq", (p,))
    if not rows and p.isdigit():              # 68 is printed as 68a / 68b, 18 under 18-20
        rows = [r for r in _rows(f"SELECT {NOTE_COLS} FROM merrill_notes ORDER BY seq")
                if re.fullmatch(rf"{p}[a-z]", r["poem"]) or _in_range(p, r["poem"])]
    if line is None:
        return rows
    try:
        n = int(line)
    except (TypeError, ValueError):
        return []
    return [r for r in rows if r["line_start"] is not None and r["line_start"] <= n <= (r["line_end"] or r["line_start"])]


def _in_range(p: str, poem: str) -> bool:
    m = re.fullmatch(r"(\d+)-(\d+)", poem)
    return bool(m) and int(m.group(1)) <= int(p) <= int(m.group(2))


def commentary_search(q: str, limit: int = 10) -> list[dict]:
    """Full-text search of Merrill's notes (lemma phrase and text)."""
    return _fts("merrill_notes_fts", "merrill_notes", "b.id, b.poem, b.line, b.line_start, b.line_end, b.kind, b.lemma, b.text, b.source_url", q, limit)


def word_keys(word: str) -> list[str]:
    """The folded word and the lemmas the lemma index gives it (bella -> bella, bellum, bellus)."""
    form = normalize_la("".join(tokenize_la(word)[:1]))
    if not form:
        return []
    keys = [form]
    try:
        for r in latin_lemma.readings(form):
            lem = normalize_la(r.get("lemma") or "")
            if lem and lem not in keys:
                keys.append(lem)
    except Exception:  # noqa: BLE001 - the lemma index is optional
        pass
    return keys


def notes_for_words(words: list[str], limit: int = 5) -> list[dict]:
    """Per word, Merrill's notes that discuss it: notes whose lemma phrase holds the word or a form of its lemma
    first, then notes that print it in their text. [{word, keys, notes: [...]}], at most `limit` notes a word; each
    note says where it matched (`matched_in`: lemma / text) and on which form (`matched_form`)."""
    out = []
    for word in words or []:
        keys = word_keys(str(word))
        notes: list[dict] = []
        if keys and available():
            marks = ",".join("?" * len(keys))
            rows = _rows(
                f"SELECT n.id, n.poem, n.line, n.line_start, n.line_end, n.kind, n.lemma, n.text, n.source_url, "
                f"w.form AS matched_form, w.place AS place, (w.form = ?) AS exact FROM note_words w "
                f"JOIN merrill_notes n ON n.id = w.note_id WHERE w.form IN ({marks}) OR w.lemma IN ({marks}) "
                f"ORDER BY (w.place = 'lemma') DESC, exact DESC, n.seq", (keys[0], *keys, *keys))
            seen = set()
            for r in rows:
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                r["matched_in"] = "lemma" if r.pop("place") == "lemma" else "text"
                r.pop("exact", None)
                r["excerpt"] = _excerpt(r["text"], [r["matched_form"]])
                notes.append(r)
                if len(notes) >= limit:
                    break
        out.append({"word": word, "keys": keys, "notes": notes})
    return out


def intro(section: str | None = None) -> list[dict]:
    """Merrill's Introduction: every numbered section in order; one section by its number ('86'); or the sections
    under a heading by its name ('Metres', 'Prosody')."""
    cols = "id, section, heading_n, heading, text, source_url"
    if section is None or str(section).strip() == "":
        return _rows(f"SELECT {cols} FROM merrill_intro ORDER BY seq")
    s = str(section).strip().lstrip("§").strip()
    if s.isdigit():
        return _rows(f"SELECT {cols} FROM merrill_intro WHERE section = ? ORDER BY seq", (str(int(s)),))
    return _rows(f"SELECT {cols} FROM merrill_intro WHERE lower(heading) LIKE ? ORDER BY seq", (s.lower().rstrip(".") + "%",))


def intro_search(q: str, limit: int = 10) -> list[dict]:
    return _fts("merrill_intro_fts", "merrill_intro", "b.id, b.section, b.heading_n, b.heading, b.text, b.source_url", q, limit)


def _ag_row(r: dict) -> dict:
    try:
        r["heading_path"] = json.loads(r["heading_path"])
    except (TypeError, ValueError):
        r["heading_path"] = []
    return r


def grammar(section: str) -> dict | None:
    """Allen and Greenough by section number: '603' is the whole section (its opening text in `text`, the lettered
    subsections in `subsections`, everything joined in `full_text`); '603f' or '603.f' is that subsection alone."""
    m = re.fullmatch(r"§*\s*(\d+)\s*\.?\s*([a-z])?\.?", str(section or "").strip().lower())
    if not m:
        return None
    num, sub = str(int(m.group(1))), m.group(2) or ""
    rows = [_ag_row(r) for r in _rows("SELECT id, section, sub, heading_path, text, source_url FROM ag_sections "
                                      "WHERE section = ? ORDER BY seq", (num,))]
    if not rows:
        return None
    if sub:
        return next((r for r in rows if r["sub"] == sub), None)
    head = next((r for r in rows if r["sub"] == ""), rows[0])
    subs = [r for r in rows if r["sub"]]
    full = "\n".join(([head["text"]] if head["sub"] == "" else []) + [f"{r['sub']}. {r['text']}" for r in subs])
    return {"id": f"ag:{num}", "section": num, "sub": "", "heading_path": head["heading_path"],
            "text": head["text"] if head["sub"] == "" else "", "subsections": subs, "full_text": full,
            "source_url": head["source_url"], "source": SOURCES["ag"]}


def _same(a: str, b: str) -> bool:
    """The same word but for a plural or like ending ('mute' and 'mutes', 'clause' and 'clauses')."""
    short, long = sorted((a, b), key=len)
    return a == b or (len(short) >= 4 and long.startswith(short) and len(long) - len(short) <= 2)


def _subjects() -> list[dict]:
    """The subject -> section map (Allen and Greenough's own index and headings), confirmed references only; read once."""
    key = (str(db_path()), db_path().stat().st_mtime if available() else 0)
    if _cache.get("key") != key:
        rows = _rows("SELECT source, subject, detail, head_fold, fold, ref, row_id FROM ag_subjects WHERE confirmed = 1 ORDER BY seq")
        for r in rows:
            r["head"] = [w for w in r.pop("head_fold").split() if w not in STOP]
            r["words"] = r.pop("fold").split()
        _cache["key"], _cache["rows"] = key, rows
    return _cache["rows"]


def _subject_hits(q: str, limit: int) -> list[dict]:
    """Sections the book's own index and headings give for q. Best first: a subject that is the query; one that holds
    it; an index entry whose subject and detail together hold it; then subjects made only of words of the query
    ('cum clauses' reaches the entry 'cum'). The clean headings stand before the OCR index within each step."""
    terms, content = _terms(q)
    content = [t for t in dict.fromkeys(content) if not t.isdigit()]
    if not content:
        return []
    found = []
    for n, s in enumerate(_subjects()):
        head = s["head"]
        if head and all(any(_same(t, w) for w in head) for t in content):
            step = 0 if len(head) == len(content) else 1
        elif all(any(_same(t, w) for w in s["words"]) for t in content):
            step = 2
        elif head and len(content) > 1 and all(any(_same(t, w) for t in content) for w in head):
            step = 3
        else:
            continue
        nth = min((i for i, t in enumerate(content) if any(_same(t, w) for w in head)), default=0)    # step 3: the query's first word first
        found.append((step, len(head) if step == 1 else len(s["words"]) if step == 2 else nth if step == 3 else 0,
                      s["source"] != "heading", n, s))
    out, seen = [], set()
    for step, _, _, _, s in sorted(found, key=lambda x: x[:4]):
        if s["row_id"] in seen:
            continue
        seen.add(s["row_id"])
        for r in _rows("SELECT id, section, sub, heading_path, text, source_url FROM ag_sections WHERE id = ?", (s["row_id"],)):
            r["match"] = "heading" if s["source"] == "heading" else "index"
            r["step"] = step
            r["subject"] = s["subject"] + (": " + s["detail"] if s["detail"] and s["source"] != "heading" else "")
            r["index_ref"] = s["ref"]
            r["excerpt"] = _excerpt(r["text"], content)
            out.append(r)
        if len(out) >= limit:
            break
    return out


def grammar_search(q: str, limit: int = 10) -> list[dict]:
    """Search of the grammar; one row per section or lettered subsection. The book's own subject map is asked first
    (`match` 'heading' for a heading of the Perseus text, 'index' for the printed Index of Words and Subjects, read
    by OCR and kept only where the section confirms it), then the full text (heading path and text).
    Order: subjects that hold the query (six places in ten at most); the phrase in the text; subjects made of words
    of the query, then index entries that hold it only with their detail (three places each); the rest of the text
    matches; whatever of the subject map is left."""
    try:
        subj = _subject_hits(q, limit)
    except Exception:  # noqa: BLE001 - a database without the subject table still searches the text
        subj = []
    text = _fts("ag_sections_fts", "ag_sections", "b.id, b.section, b.sub, b.heading_path, b.text, b.source_url", q, limit)
    strong = [r for r in subj if r["step"] <= 1][:max(1, (limit * 6 + 9) // 10)]
    order = (strong + [r for r in text if r["match"] in ("phrase", "word")] + [r for r in subj if r["step"] == 3][:3]
             + [r for r in subj if r["step"] == 2][:3] + text + subj)
    out, seen = [], set()
    for r in order:
        if r["id"] not in seen and len(out) < limit:
            seen.add(r["id"])
            r.pop("step", None)
            out.append(_ag_row(r))
    return out


def status() -> dict:
    """What is loaded: counts per store, the licences recorded at ingest, or the reason nothing is."""
    out = {"available": available(), "path": str(db_path()), "sources": SOURCES}
    if not available():
        out["reason"] = "reference database not built: run scripts/build_reference_la.py"
        return out
    try:
        meta = {r["key"]: r["value"] for r in _db().execute("SELECT key, value FROM metadata")}
        out["counts"] = {"merrill_notes": _db().execute("SELECT COUNT(*) FROM merrill_notes").fetchone()[0],
                         "merrill_intro": _db().execute("SELECT COUNT(*) FROM merrill_intro").fetchone()[0],
                         "ag_rows": _db().execute("SELECT COUNT(*) FROM ag_sections").fetchone()[0],
                         "ag_sections": _db().execute("SELECT COUNT(DISTINCT section) FROM ag_sections").fetchone()[0],
                         "ag_subjects": int(meta.get("ag_subjects_confirmed", 0) or 0)}
        out["built_at"] = meta.get("built_at", "")
        out["lemma_index"] = meta.get("lemma_index", "")
        out["lemma_index_now"] = latin_lemma.available()
        out["licences"] = {k.split(":", 1)[1]: json.loads(v) for k, v in meta.items() if k.startswith("manifest:")}
    except (sqlite3.Error, ValueError) as e:
        out["available"] = False
        out["reason"] = f"reference database unreadable: {e}"
    return out
