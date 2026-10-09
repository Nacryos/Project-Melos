"""Vowel-quantity evidence for printed word forms (data/scansion/quantities.sqlite).

The table is built by scripts/scansion_build_lexicon.py from Morpheus, Wiktionary (Kaikki), the
Perseus LSJ and Logeion LSJ headwords. A lookup returns, per base letter of the form, the codes the
sources give: L / S (marked long / short), u (unmarked in a stem or dictionary form: unknown), e
(unmarked in a Morpheus ending: the ending tables mark long dichrona, so usually short).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .greek import accentless_key, base_letters, key

DICTIONARY_SOURCES = ("wiktionary", "lsj", "logeion")


@dataclass
class Evidence:
    found: bool
    via: str                                   # exact | accentless | elision_restored | none
    per_letter: list[dict[str, set[str]]] = field(default_factory=list)
    lemmas: set[str] = field(default_factory=set)


def default_path() -> Path:
    if os.environ.get("MELOS_SCANSION_LEXICON"):
        return Path(os.environ["MELOS_SCANSION_LEXICON"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data / "scansion" / "quantities.sqlite"


class QuantityLexicon:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or default_path())
        self._local = threading.local()
        self.available = self.path.exists()

    def _db(self):
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
            self._local.db = db
        return db

    def rows(self, k: str, column: str = "key") -> list[tuple[str, str, str]]:
        if not self.available:
            return []
        return self._db().execute(f"SELECT source, marks, lemmas FROM q WHERE {column}=?", (k,)).fetchall()

    def lookup(self, form: str) -> Evidence:
        return _lookup_cached(self, key(form))

    def counts(self) -> dict:
        if not self.available:
            return {}
        row = self._db().execute("SELECT v FROM meta WHERE k='counts'").fetchone()
        return json.loads(row[0]) if row else {}


@lru_cache(maxsize=200_000)
def _lookup_cached(lex: QuantityLexicon, k: str) -> Evidence:
    n = len(base_letters(k))
    rows = lex.rows(k)
    via = "exact"
    if not rows:
        rows = [r for r in lex.rows(accentless_key(k), "akey") if len(r[1]) == n]
        via = "accentless"
    if not rows:
        return Evidence(False, "none", [dict() for _ in range(n)])
    per = [dict() for _ in range(n)]
    lemmas: set[str] = set()
    for source, marks, lem in rows:
        if len(marks) != n:
            continue
        for i, code in enumerate(marks):
            if code != ".":
                per[i].setdefault(source, set()).add(code)
        lemmas.update(x for x in lem.split("|") if x)
    return Evidence(True, via, per, lemmas)


def lemma_keys(lemmas: set[str]) -> set[str]:
    """Accentless keys of lemma spellings (Morpheus lemmas are Beta Code)."""
    out = set()
    for lem in lemmas:
        if lem and lem[0].isascii():
            try:
                from betacode.conv import beta_to_uni
                lem = beta_to_uni(lem.rstrip("0123456789"))
            except Exception:  # pragma: no cover - betacode is a project dependency
                continue
        out.add(accentless_key(unicodedata.normalize("NFC", lem)))
    return out
