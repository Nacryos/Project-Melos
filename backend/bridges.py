"""English-side retrieval bridges for queries that are not written in Greek.

Measured on judged queries built from the index's own translation and
commentary links (scripts/lab_eval.py, 2026-09-30): matching an English query
against Greek passage vectors finds the judged passage about one time in ten;
every method that works goes through English text linked to a Greek passage
and projects to its parent. These helpers supply two cheap extra ranked lists
for reciprocal-rank fusion:

- ``bm25_bridge_hits``: BM25 over indexed English translations and commentary
  that name a Greek parent. The hit is the English record; fusion projects it.
- ``prf_hits``: pseudo-relevance feedback. The rarest Greek words of the top
  dense Greek hits form a lexical query over Greek text. The seed passages are
  only a device for choosing words; nothing is asserted about them.

Neither bridge adds scores to cosine values; both stay rank lists. Both are
bounded and disclosed in the API's method and warnings.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable

from .textutils import normalize, tokenize

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
STOPWORDS = frozenset("""a an and are as at be but by for from has have he her his i in is it its of on or
she that the their them they this to was were which who will with you your not no so than then
there these those into upon when where while whom whose shall thou thee thy ye hath doth unto""".split())
SEARCHABLE = "('source_text','machine_corrected_ocr')"
# Fusion weights for a query without Greek letters. Measured 2026-09-30: the
# BM25 bridge raised both Recall@10 and MRR in every round; rare-word feedback
# (prf_hits) added recall but lowered MRR because wrong dense seeds boost wrong
# passages, and down-weighting the Greek-vector list or adding an English-only
# dense list lowered MRR too. Production fuses the bridge only; prf_hits stays
# available for the lab.
ENGLISH_QUERY_WEIGHTS = {"semantic": 1.0, "bm25_bridge": 1.0}


def is_greek_query(query: str) -> bool:
    return bool(GREEK.search(query or ""))


def english_terms(query: str, limit: int = 24) -> list[str]:
    terms = [t for t in tokenize(normalize(query)) if len(t) > 2 and t not in STOPWORDS and not GREEK.search(t)]
    return list(dict.fromkeys(terms))[:limit]


def _fts_expression(terms: Iterable[str]) -> str:
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


def bm25_bridge_hits(con: sqlite3.Connection, query: str, limit: int = 400) -> list[dict]:
    """English translations/commentary with a Greek parent, ranked by BM25 on the query's words."""
    terms = english_terms(query)
    if not terms:
        return []
    rows = con.execute(
        "SELECT p.id, bm25(passage_fts) rank FROM passage_fts JOIN passages p ON p.id=passage_fts.id "
        "WHERE passage_fts MATCH ? AND p.language='eng' AND p.kind IN ('translation','commentary') "
        f"AND p.quality IN {SEARCHABLE} AND json_extract(p.data,'$.parent_id') IS NOT NULL "
        "ORDER BY rank LIMIT ?", (_fts_expression(terms), limit)).fetchall()
    return [{"id": row[0], "score": -float(row[1]), "match_reason": "BM25 over linked English translation/commentary; projected to its Greek passage"}
            for row in rows]


def prf_hits(con: sqlite3.Connection, seed_ids: Iterable[str], limit: int = 400, *, seeds: int = 5,
             terms_per_seed: int = 6, max_frequency: int = 400) -> list[dict]:
    """Greek passages sharing rare words with the top dense Greek hits (pseudo-relevance feedback)."""
    candidates: dict[str, int] = {}
    for identifier in list(seed_ids)[:seeds]:
        row = con.execute("SELECT text FROM passages WHERE id=?", (identifier,)).fetchone()
        if not row or not row[0]:
            continue
        for token in set(tokenize(row[0])):
            key = normalize(token)
            if len(key) < 4 or not GREEK.search(key):
                continue
            count = con.execute("SELECT count FROM vocabulary WHERE normalized=?", (key,)).fetchone()
            if count and 1 < count[0] <= max_frequency:
                candidates[key] = min(candidates.get(key, 10 ** 9), count[0])
    if not candidates:
        return []
    terms = [key for key, _ in sorted(candidates.items(), key=lambda kv: kv[1])[:seeds * terms_per_seed]]
    rows = con.execute(
        "SELECT p.id, bm25(passage_fts) rank FROM passage_fts JOIN passages p ON p.id=passage_fts.id "
        f"WHERE passage_fts MATCH ? AND p.language='grc' AND p.kind='text' AND p.quality IN {SEARCHABLE} "
        "ORDER BY rank LIMIT ?", (_fts_expression(terms), limit)).fetchall()
    return [{"id": row[0], "score": -float(row[1]), "match_reason": "Shares rare words with the top dense Greek candidates (pseudo-relevance feedback)"}
            for row in rows]
