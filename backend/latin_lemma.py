"""Reader over the Latin lemma index data/lemma_index_la.sqlite (scripts/build_lemma_index_la.py; docs/latin/lemma-index.md).

Readings of a spelling come from LASLA's human lemmas (recorded, by frequency), then from the quantity lexicon's
Morpheus lemmas (Winge's table) for forms LASLA never prints. Attestation per author is by lemma (headword) and by
form (`forms_found`), with one example line per form. The index is licensed data (CC BY-NC-SA) used server-side:
the API returns lemma strings, counts and the corpus's own lines, never the annotation.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from .latin_text import normalize_la

_local = threading.local()
CONVENTIONS = {"neque": "nec", "atque": "ac"}      # LASLA lemmatises nec and ac as themselves


def index_path() -> Path:
    if os.environ.get("MELOS_LEMMA_INDEX_LA"):
        return Path(os.environ["MELOS_LEMMA_INDEX_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "lemma_index_la.sqlite"


def available() -> bool:
    return index_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(index_path()):
        db = sqlite3.connect(f"file:{index_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        _local.db, _local.path = db, str(index_path())
    return db


@lru_cache(maxsize=16384)
def readings(form: str) -> list[dict]:
    """[{lemma, upos, count, source}] for a spelling: LASLA by frequency, else Morpheus lemmas from the quantity lexicon."""
    n = normalize_la(form)
    if not n:
        return []
    out = []
    if available():
        for r in _db().execute("SELECT lemma, upos, SUM(count) AS c FROM form_lemma WHERE normalized=? GROUP BY lemma, upos ORDER BY c DESC", (n,)):
            out.append({"lemma": r["lemma"], "upos": r["upos"], "count": int(r["c"]), "source": "lasla"})
    if not out:
        from .scansion.lexicon_la import LatinQuantityLexicon
        lex = LatinQuantityLexicon()
        if lex.available:
            ev = lex.lookup(n)
            for lem in sorted(ev.lemmas)[:5]:
                lem = lem.lower().replace("v", "u").replace("j", "i").rstrip("0123456789")
                if lem:
                    out.append({"lemma": lem, "upos": "", "count": 0, "source": "morpheus"})
    if not out:
        out = latincy_readings(form)
    return out


def latincy_url() -> str:
    return os.environ.get("MELOS_LATINCY_URL", "").rstrip("/")


def latincy_readings(form: str) -> list[dict]:
    """The LatinCy sidecar's reading of one form (scripts/latincy_service.py); [] when it is not configured or down."""
    url = latincy_url()
    if not url:
        return []
    try:
        import httpx
        r = httpx.post(url + "/lemmatize", json={"text": form}, timeout=3.0)
        r.raise_for_status()
        toks = r.json().get("tokens") or []
    except Exception:  # noqa: BLE001 - the sidecar is optional
        return []
    return [{"lemma": t["lemma"], "upos": t.get("pos", ""), "count": 0, "source": "latincy", "morph": t.get("morph", "")} for t in toks[:3]]


def latincy_tokens(text: str) -> list[dict]:
    """Lemma, POS and morphology for a whole draft (one sidecar call); [] when unavailable."""
    url = latincy_url()
    if not url:
        return []
    try:
        import httpx
        r = httpx.post(url + "/lemmatize", json={"text": text}, timeout=5.0)
        r.raise_for_status()
        return r.json().get("tokens") or []
    except Exception:  # noqa: BLE001
        return []


@lru_cache(maxsize=4096)
def lemma_attestation(lemma: str, author: str = "") -> dict:
    """Counts of a headword across LASLA's Catullus and Horace, by author and work, with whether a text is held."""
    if not available():
        return {"lemma": lemma, "total": 0, "by_author": {}}
    db = _db()
    lem = normalize_la(lemma)
    rows = db.execute("SELECT author, SUM(count) AS c, MAX(in_corpus) AS ic FROM author_lemma WHERE lemma=? GROUP BY author", (lem,)).fetchall()
    by_author = {r["author"]: {"tokens": int(r["c"]), "in_corpus": bool(r["ic"])} for r in rows}
    return {"lemma": lem, "total": sum(v["tokens"] for v in by_author.values()), "by_author": by_author,
            "author_tokens": by_author.get(author, {}).get("tokens") if author else None}


def forms_found(lemma: str, author: str = "", limit: int = 40) -> list[dict]:
    if not available():
        return []
    db = _db()
    lem = normalize_la(lemma)
    q = "SELECT author, form, normalized, SUM(count) AS c, MIN(example_passage) AS p, MIN(example_line) AS l FROM author_form WHERE lemma=? "
    args: list = [lem]
    if author:
        q += "AND lower(author)=lower(?) "
        args.append(author)
    q += "GROUP BY author, normalized ORDER BY c DESC LIMIT ?"
    args.append(limit)
    return [{"author": r["author"], "form": r["form"], "count": int(r["c"]), "example_passage": r["p"], "example_line": r["l"]}
            for r in db.execute(q, args)]


def status() -> dict:
    if not available():
        return {"available": False}
    row = _db().execute("SELECT value FROM metadata WHERE key='build'").fetchone()
    return {"available": True, **(json.loads(row["value"]) if row else {})}
