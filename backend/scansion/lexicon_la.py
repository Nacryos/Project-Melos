"""Vowel-quantity evidence for Latin word forms (data/scansion/quantities_la.sqlite, built by
scripts/scansion_build_lexicon_la.py). Same table as the Greek lexicon; the lookup key is latin.key (u for v, i for j,
no marks). Codes per letter: L / S explicit, A either (the source says so), s short by the source's convention, u unmarked.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .latin import VOWELS, key as la_key

ENCLITICS = ("que", "ne", "ue")


@dataclass
class Evidence:
    found: bool
    via: str                                   # exact | enclitic | none
    per_letter: list[dict[str, set[str]]] = field(default_factory=list)
    lemmas: set[str] = field(default_factory=set)


def default_path() -> Path:
    if os.environ.get("MELOS_SCANSION_LEXICON_LA"):
        return Path(os.environ["MELOS_SCANSION_LEXICON_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data / "scansion" / "quantities_la.sqlite"


class LatinQuantityLexicon:
    language = "la"

    def __init__(self, path: Path | str | None = None, sources: tuple[str, ...] | None = None):
        self.path = Path(path or default_path())
        self.sources = tuple(sources) if sources else None
        self._local = threading.local()
        self.available = self.path.exists()

    def _db(self):
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
            self._local.db = db
        return db

    def rows(self, k: str) -> list[tuple[str, str, str]]:
        if not self.available:
            return []
        rows = self._db().execute("SELECT source, marks, lemmas FROM q WHERE key=?", (k,)).fetchall()
        return [r for r in rows if r[0] in self.sources] if self.sources else rows

    def lookup(self, form: str) -> Evidence:
        return _lookup_cached(self, la_key(form))

    def counts(self) -> dict:
        if not self.available:
            return {}
        row = self._db().execute("SELECT v FROM meta WHERE k='rows'").fetchone()
        return json.loads(row[0]) if row else {}

    def vowel_evidence(self, word_key: str, letter_index: int, word=None) -> tuple[str, str]:
        """(lex, sources) for the vowel at `letter_index` of the word: L, S, conflict, unmarked, unknown_word."""
        ev = self.lookup(word_key)
        if not ev.found:
            for e in ENCLITICS:
                if word_key.endswith(e) and len(word_key) > len(e) + 1:
                    stem = self.lookup(word_key[: -len(e)])
                    if stem.found:
                        tail = len(e)
                        if letter_index >= len(word_key) - tail:
                            return "S", "enclitic"            # the enclitic's own vowel is short
                        ev = Evidence(True, "enclitic", stem.per_letter + [dict() for _ in range(tail)], stem.lemmas)
                        break
            if not ev.found:
                return "unknown_word", ""
        if letter_index >= len(ev.per_letter):
            return "unknown_word", ""
        codes = ev.per_letter[letter_index]
        explicit = {src: {c for c in cs if c in "LS"} for src, cs in codes.items()}
        explicit = {src: cs for src, cs in explicit.items() if cs}
        convention = {src for src, cs in codes.items() if "s" in cs}      # unmarked = short in Winge and Wiktionary
        either = {src for src, cs in codes.items() if "A" in cs}          # the source itself says either (tibi, ubi)
        vals = set().union(*explicit.values()) if explicit else set()
        if convention:
            vals = vals | {"S"}                                            # a short-by-convention reading is evidence too
        if either:
            vals = vals | {"L", "S"}
        srcs = "+".join(sorted(set(explicit) | {s + "_convention" for s in convention if s not in explicit}))
        if len(vals) == 2:
            return "conflict", srcs                                        # basia: basiā (imperative) vs basia (plural)
        if vals == {"L"}:
            return "L", srcs
        if vals == {"S"}:
            return ("S", srcs) if explicit else ("S", "convention")
        if any("u" in cs for cs in codes.values()):
            return "unmarked", "+".join(sorted(codes))
        return "unmarked", ""


@lru_cache(maxsize=50_000)
def _lookup_cached(lex: LatinQuantityLexicon, k: str) -> Evidence:
    n = len(k)
    rows = lex.rows(k)
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
        if lem:
            lemmas.add(lem)
    return Evidence(True, "exact", per, lemmas)
