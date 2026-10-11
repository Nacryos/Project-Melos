"""The Latin language backend for the composer lint bank (docs/prd/latin-composer.md §2, §6).

Readers over the Latin corpus partition data/corpus_la.sqlite (scripts/build_corpus_la.py; env MELOS_CORPUS_LA) and
the quantity lexicon (backend/scansion/lexicon_la.py, which doubles as a closed-vocabulary form list: Winge's table is
Morpheus Latin's output, Wiktionary's tables are paradigms). Checks have the shape of backend/composer_lint.py's:
{id, name, ok, blocking, detail, evidence}.

  L1 forms        every word is printed in the Latin corpus (any author), else is a form the lexicon knows (a
                  Morpheus / Wiktionary paradigm form: "known, not printed in the corpus"); an enclitic -que/-ne/-ue
                  is split for the lookup. Blocking.
  L4 attestation  tokens of each spelling (u/v, i/j folded) in the corpus and in the chosen poet, with a citation.
  L11 verbatim    runs of 4+ words (or 3 with 15+ letters) printed word for word in the corpus (homage).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from .latin_text import normalize_la, tokenize_la

ENCLITICS = ("que", "ne", "ue")
VERBATIM_MIN, VERBATIM_SHORT, VERBATIM_LETTERS = 4, 3, 15
_local = threading.local()


def corpus_path() -> Path:
    if os.environ.get("MELOS_CORPUS_LA"):
        return Path(os.environ["MELOS_CORPUS_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "corpus_la.sqlite"


def available() -> bool:
    return corpus_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(corpus_path()):
        if not available():
            raise FileNotFoundError(f"Latin corpus not built: {corpus_path()}")
        db = sqlite3.connect(f"file:{corpus_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        _local.db, _local.path = db, str(corpus_path())
    return db


def _lexicon():
    from .scansion.lexicon_la import LatinQuantityLexicon
    lex = LatinQuantityLexicon()
    return lex if lex.available else None


def latin_words(text: str) -> list[str]:
    return [w for w in tokenize_la(text) if any(ch.isalpha() for ch in w)]


# ----------------------------------------------------------------------------------------------- L1 forms

@lru_cache(maxsize=8192)
def form_status(word: str) -> tuple[str, str]:
    """('corpus' | 'lexicon' | 'enclitic' | 'unknown', detail) for one spelling."""
    n = normalize_la(word)
    if not n:
        return "unknown", ""
    db = _db()
    row = db.execute("SELECT count FROM vocabulary WHERE normalized=?", (n,)).fetchone()
    if row:
        return "corpus", f"{row['count']} token(s)"
    lex = _lexicon()
    if lex is not None and lex.lookup(n).found:
        return "lexicon", "a paradigm form (Morpheus / Wiktionary), not printed in the corpus"
    for e in ENCLITICS:
        if n.endswith(e) and len(n) > len(e) + 1:
            stem = n[: -len(e)]
            if db.execute("SELECT 1 FROM vocabulary WHERE normalized=?", (stem,)).fetchone() or (lex is not None and lex.lookup(stem).found):
                return "enclitic", f"{stem} + -{e}"
    return "unknown", ""


def forms_check(words: list[str], author: str = "") -> dict:
    rows = [(w, *form_status(w)) for w in words]
    unknown = [w for w, s, _ in rows if s == "unknown"]
    notes = []
    if unknown:
        notes.append("no reading for " + ", ".join(unknown))
    lexonly = [w for w, s, _ in rows if s == "lexicon"]
    if lexonly:
        notes.append("known to the lexicon but not printed in the corpus: " + ", ".join(lexonly))
    encl = [f"{w} ({d})" for w, s, d in rows if s == "enclitic"]
    if encl:
        notes.append("enclitic: " + ", ".join(encl))
    if not notes:
        notes.append("every word is printed in the Latin corpus")
    return {"id": "L1", "name": "forms", "ok": not unknown, "blocking": True, "detail": "; ".join(notes),
            "evidence": [{"form": w, "reading": None if s == "unknown" else s, "detail": d} for w, s, d in rows]}


# ----------------------------------------------------------------------------------------------- L4 attestation

@lru_cache(maxsize=8192)
def attestation(word: str, author: str = "") -> dict:
    n = normalize_la(word)
    db = _db()
    total = db.execute("SELECT COALESCE(SUM(t.count),0) AS n FROM tokens t JOIN passages p ON p.id=t.passage_id "
                       "WHERE t.normalized=? AND p.kind='text'", (n,)).fetchone()["n"]
    by_author = None
    example = None
    if author:
        by_author = db.execute("SELECT COALESCE(SUM(t.count),0) AS n FROM tokens t JOIN passages p ON p.id=t.passage_id "
                               "WHERE t.normalized=? AND p.kind='text' AND lower(p.author)=lower(?)", (n, author)).fetchone()["n"]
    row = db.execute("SELECT p.author, p.citation, p.text FROM tokens t JOIN passages p ON p.id=t.passage_id "
                     "WHERE t.normalized=? AND p.kind='text' " + ("AND lower(p.author)=lower(?) " if author else "") +
                     "ORDER BY p.sequence LIMIT 1", (n, author) if author else (n,)).fetchone()
    if row is None and author:
        row = db.execute("SELECT p.author, p.citation, p.text FROM tokens t JOIN passages p ON p.id=t.passage_id "
                         "WHERE t.normalized=? AND p.kind='text' ORDER BY p.sequence LIMIT 1", (n,)).fetchone()
    if row is not None:
        line = next((l for l in row["text"].split("\n") if n in normalize_la(l)), "")
        example = {"author": row["author"], "citation": row["citation"], "line": line}
    return {"form": word, "tokens": int(total), "author_tokens": None if by_author is None else int(by_author),
            "dialect_tokens": None, "example": example}


def attestation_check(words: list[str], author: str = "") -> dict:
    rows = [attestation(w, author or "") for w in words]
    unattested = [r["form"] for r in rows if not r["tokens"]]
    in_poet = [r["form"] for r in rows if r["author_tokens"]]
    parts = [f"{len(rows) - len(unattested)}/{len(rows)} spellings printed in the Latin corpus"]
    if author:
        parts.append(f"{len(in_poet)} printed by {author}")
    if unattested:
        parts.append("not printed: " + ", ".join(unattested))
    return {"id": "L4", "name": "attestation", "ok": True, "blocking": False, "detail": "; ".join(parts), "evidence": rows}


# ----------------------------------------------------------------------------------------------- L11 verbatim

def _qualifies(words: list[str]) -> bool:
    letters = sum(ch.isalpha() for w in words for ch in w)
    return len(words) >= VERBATIM_MIN or (len(words) >= VERBATIM_SHORT and letters >= VERBATIM_LETTERS)


@lru_cache(maxsize=8192)
def _phrase_in_corpus(phrase: str):
    row = _db().execute("SELECT p.id, p.author, p.citation FROM passage_fts f JOIN passages p ON p.id=f.id "
                        "WHERE passage_fts MATCH ? AND p.kind='text' LIMIT 1", ('normalized : "' + phrase + '"',)).fetchone()
    return None if row is None else (row["id"], row["author"], row["citation"])


def verbatim_check(words: list[str]) -> dict:
    keys = [normalize_la(w).replace("'", " ").strip() for w in words]
    pairs = [(w, k) for w, k in zip(words, keys) if k]
    printed, keys = [w for w, _ in pairs], [k for _, k in pairs]
    runs, i = [], 0
    while i + VERBATIM_SHORT <= len(keys):
        hit, j = None, i + VERBATIM_SHORT
        while j <= len(keys):
            row = _phrase_in_corpus(" ".join(keys[i:j]))
            if row is None:
                break
            if _qualifies(printed[i:j]):
                hit = {"words": " ".join(printed[i:j]), "passage_id": row[0], "author": row[1], "citation": row[2]}
            j += 1
        if hit:
            runs.append(hit)
            i += len(hit["words"].split())
        else:
            i += 1
    return {"id": "L11", "name": "verbatim", "ok": not runs, "blocking": False,
            "detail": ("homage: " + "; ".join(f"“{r['words']}” = {r['author']} {r['citation']}" for r in runs)
                       if runs else "no run of 4+ words (or 3 long words) is copied from the Latin corpus"), "evidence": runs}


def dialect_check() -> dict:
    return {"id": "L2", "name": "dialect", "ok": True, "blocking": False, "detail": "not applicable to Latin", "evidence": []}
