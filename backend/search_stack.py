"""Release S stacked retrieval: further ranked candidate lists for weighted reciprocal-rank fusion.

Each retriever returns passage hits in relevance order (``id``, ``score``, ``match_reason``); fusion
(``backend.retrieval.fuse``) projects translation, commentary and note hits to their Greek parent through
explicit links only, and adds ``weight / (60 + rank)`` per list. The weights are not set by hand: they are
read from ``search_stack_weights.json``, fitted on the development queries of
``data/evaluation/search-eval-s.json`` (``scripts/search_lab_s.py fit``). A score is a rank device, never a
probability that a passage is about the query.

Retrievers:

- ``keyword``: BM25 (SQLite FTS5) over the normalised Greek text for the query's own words, plus a capped
  quota of spelling variants found in the corpus vocabulary (Aeolic/Doric/epic vowel and consonant
  correspondences, single/double consonants, movable nu, then one-letter edits for long words). A variant
  only ever adds candidates at a lower weight; it never replaces the printed word.
- ``headword``: passages containing the query's headwords (Greek words read as headwords; English words
  through dictionary head meanings), each widened to its dictionary variant group (ἔρος / ἔρως,
  σελάννα-type dialect headwords) from the release P/Q variant links.
- ``dense_<model>_<kind>``: cosine similarity between the query and passage vectors of one record kind
  (Greek text, English translation, commentary) for each deployed encoder.
- ``notes``: BM25 and vector matches over the commentary notes index (``backend.commentary_context``),
  projected to the passages the notes are linked to.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from .textutils import normalize, tokenize

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_PATH = Path(__file__).with_name("search_stack_weights.json")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
# Candidates per stack list in production: 200 (the lab collected 400; cutting the stack lists at 200
# changes development nDCG@10 by -0.001, and halves the records fusion has to read).
STACK_POOL = 200
BASE_SIGNALS = frozenset({"lexical", "forms", "semantic", "bm25_bridge", "lemma"})
KINDS = {"grc": "Greek text", "eng": "English translation", "comm": "commentary"}


def enabled():
    return os.getenv("MELOS_SEARCH_STACK", "1") != "0" and WEIGHTS_PATH.exists()


@lru_cache(maxsize=1)
def config():
    return json.loads(WEIGHTS_PATH.read_text(encoding="utf-8")) if WEIGHTS_PATH.exists() else {}


# ---------------------------------------------------------------- keyword (BM25 + spelling variants)
# Correspondences between Attic/Ionic, Aeolic, Doric and epic spellings, on normalised (accentless) keys.
VARIANT_RULES = [("η", "α"), ("α", "η"), ("ου", "ο"), ("ο", "ου"), ("ει", "ε"), ("ε", "ει"), ("ω", "ο"), ("ο", "ω"),
                 ("σσ", "ττ"), ("ττ", "σσ"), ("ζ", "σδ"), ("σδ", "ζ"), ("λλ", "λ"), ("λ", "λλ"), ("μμ", "μ"), ("μ", "μμ"),
                 ("νν", "ν"), ("ν", "νν"), ("σσ", "σ"), ("σ", "σσ"), ("ππ", "π"), ("π", "ππ"), ("αι", "α"), ("οι", "ο"),
                 ("ηι", "η"), ("ωι", "ω"), ("ευ", "ε"), ("οισα", "ουσα"), ("ουσα", "οισα"), ("αισ", "ασ"), ("ασ", "αισ")]
INITIAL_RULES = [("ρ", "βρ"), ("βρ", "ρ"), ("ε", "η"), ("α", "αι")]
ALPHABET = "αβγδεζηθικλμνξοπρστυφχψω"


@lru_cache(maxsize=4)
def _vocabulary(path, stamp):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {k: c for k, c in con.execute("SELECT normalized, count FROM vocabulary") if k}
    finally:
        con.close()


def vocabulary(con):
    path = con.execute("PRAGMA database_list").fetchone()[2]
    return _vocabulary(path, os.stat(path).st_mtime_ns) if path else {}


def spelling_variants(key, vocab, limit=8):
    """Indexed spellings close to ``key``: dialect correspondences first (similarity 0.8), then one-letter
    edits for words of six letters or more (0.5). Ranked by corpus frequency; at most ``limit``."""
    found = {}

    def rule_edits(word):
        out = set()
        for a, b in VARIANT_RULES:
            start = word.find(a)
            while start != -1:
                out.add(word[:start] + b + word[start + len(a):])
                start = word.find(a, start + 1)
        for a, b in INITIAL_RULES:
            if word.startswith(a):
                out.add(b + word[len(a):])
        if word.endswith("ν"):
            out.add(word[:-1])
        else:
            out.add(word + "ν")
        return out

    first = rule_edits(key)
    for cand in first | {e for w in first for e in rule_edits(w)}:
        if cand != key and cand in vocab:
            found[cand] = 0.8
    if len(key) >= 6:
        edits = set()
        for i in range(len(key) + 1):
            for c in ALPHABET:
                edits.add(key[:i] + c + key[i:])
                if i < len(key):
                    edits.add(key[:i] + c + key[i + 1:])
            if i < len(key):
                edits.add(key[:i] + key[i + 1:])
        for cand in edits:
            if cand != key and cand in vocab and cand not in found:
                found[cand] = 0.5
    ranked = sorted(found, key=lambda w: (-found[w], -vocab.get(w, 0)))[:limit]
    return {w: found[w] for w in ranked}


def _fts(con, terms, limit):
    expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    return con.execute(
        "SELECT p.id, bm25(passage_fts) FROM passage_fts JOIN passages p ON p.id=passage_fts.id "
        "WHERE passage_fts MATCH ? AND p.language='grc' AND p.kind='text' "
        "AND p.quality IN ('source_text','machine_corrected_ocr') ORDER BY 2 LIMIT ?", (expression, limit)).fetchall()


def keyword_hits(con, q, limit=400, variant_weight=0.6, quota=0.4):
    """BM25 over Greek text for the query's Greek words, with a weighted quota of spelling variants."""
    keys = [k for k in dict.fromkeys(normalize(t) for t in tokenize(q)) if k and GREEK.search(k) and len(k) >= 2]
    if not keys:
        return [], {}
    score = {}
    for pid, rank in _fts(con, keys, limit):
        score[pid] = -float(rank)
    vocab = vocabulary(con)
    variants = {}
    for key in keys:
        if len(key) >= 4:
            variants.update({v: s for v, s in spelling_variants(key, vocab).items() if v not in keys})
    if variants:
        cap, added = int(limit * quota), 0
        for pid, rank in _fts(con, list(variants), limit):
            value = variant_weight * -float(rank)
            if pid in score:
                score[pid] += value
            elif added < cap:
                score[pid] = value
                added += 1
    ranked = sorted(score, key=lambda p: -score[p])[:limit]
    return ([{"id": p, "score": round(score[p], 4),
              "match_reason": "BM25 over the Greek words" + (" and their indexed spelling variants" if variants else "")}
             for p in ranked], variants)


# ---------------------------------------------------------------- headwords with variant groups
def headword_hits(q, *, greek, limit=400, variant_weight=0.8):
    try:
        from .lemma_index import get_index
        index = get_index()
    except (ImportError, OSError, FileNotFoundError, sqlite3.Error):
        return [], []
    groups, used = [], []

    def widen(group):
        for lemma_id, weight in list(group.items()):
            for cid in index.case_variants(lemma_id):
                group.setdefault(cid, weight)
            for mid in (index.variant_group(lemma_id) or {}).get("lemma_ids", []):
                group.setdefault(int(mid), weight * variant_weight)
        return group

    if greek:
        for token in tokenize(q)[:8]:
            readings = index.resolve(token, limit=3)
            if not readings:
                continue
            group = {readings[0]["lemma_id"]: 1.0}
            for extra in readings[1:]:
                if (extra.get("form_probability") or 0) >= 0.25:
                    group[extra["lemma_id"]] = float(extra["form_probability"])
            groups.append(widen(group))
            used.append({"word": token, **readings[0]})
    else:
        readings = index.resolve(q, limit=6)
        readings = [r for r in readings if str(r.get("via", "")).startswith("english")]
        if readings:
            groups.append(widen({r["lemma_id"]: float(r.get("gloss_match") or 1.0) for r in readings}))
            used.extend(readings)
    if not groups:
        return [], []
    hits = index.passage_signal(groups, limit=limit)
    for hit in hits:
        hit["match_reason"] = (f"Contains the headword(s), or a dictionary variant of them, of "
                               f"{hit.pop('groups_matched')} of {len(groups)} query word group(s)")
    return hits, used


# ---------------------------------------------------------------- dense retrievers
class DenseIndex:
    """Vectors of one encoder over release O's passage rows, searchable per record kind."""

    def __init__(self, directory):
        directory = Path(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.manifest = manifest
        self.model = manifest["model_key"]
        self.rows = json.loads((directory / manifest["rows_file"]).read_text(encoding="utf-8"))
        self.vectors = np.load(directory / manifest["vectors_file"], mmap_mode="r")
        kind = np.asarray([r.get("kind") for r in self.rows], dtype=object)
        lang = np.asarray([r.get("language") for r in self.rows], dtype=object)
        self.masks = {"grc": (lang == "grc") & (kind == "text"),
                      "eng": (lang == "eng") & (kind == "translation"),
                      "comm": kind == "commentary"}
        self.positions = {k: np.flatnonzero(m) for k, m in self.masks.items()}
        self.sub = {}
        self.lock = threading.Lock()

    def matrix(self, kind):
        # Each kind's vectors are read once into float32 (a few hundred MB for Greek text at most).
        with self.lock:
            if kind not in self.sub:
                self.sub[kind] = np.asarray(self.vectors[self.positions[kind]], dtype=np.float32)
            return self.sub[kind]

    def search(self, vector, kind, limit=400, allowed=None):
        scores = self.matrix(kind) @ vector
        positions = self.positions[kind]
        if allowed is not None:
            keep = allowed[positions]
            scores = np.where(keep, scores, -np.inf)
        top = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit]
        top = top[np.argsort(-scores[top], kind="stable")]
        out = []
        for i in top:
            if not np.isfinite(scores[i]):
                continue
            row = self.rows[int(positions[i])]
            out.append({"id": row["id"], "score": round(float(scores[i]), 5), "parent_id": row.get("parent_id"),
                        "indexed_kind": row.get("kind"), "indexed_language": row.get("language"),
                        "match_reason": f"{self.model} vector similarity ({KINDS[kind]})"})
        return out


_DENSE, _ENCODERS, _LOCK = {}, {}, threading.Lock()


def dense_root():
    return Path(os.getenv("MELOS_S_EMBEDDINGS", str(ROOT / "data/embeddings-s")))


def dense_index(model):
    with _LOCK:
        if model not in _DENSE:
            path = dense_root() / model
            _DENSE[model] = DenseIndex(path) if (path / "manifest.json").exists() else None
        return _DENSE[model]


def encoder(model):
    with _LOCK:
        if model not in _ENCODERS:
            from .encoders import Encoder
            _ENCODERS[model] = Encoder(model)
        return _ENCODERS[model]


@lru_cache(maxsize=4)
def _precomputed(path):
    import json as _json
    return _json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=2048)
def query_vector(model, q):
    # Evaluation lab only: query vectors encoded beforehand in another environment
    # ({model: {query: vector}}), for a model this process cannot load.
    pre = os.getenv("MELOS_S_QUERY_VECTORS")
    if pre and q in _precomputed(pre).get(model, {}):
        return np.asarray(_precomputed(pre)[model][q], dtype=np.float32)
    if model == "bge-m3":
        # The model already loaded for release O's dense list (one copy in memory, same encoding).
        from .server import semantic_service
        index = semantic_service()
        with index._encode_lock:
            vec = index._get_model(index._manifest).encode([q.strip()], normalize_embeddings=True)[0]
        return np.asarray(vec, dtype=np.float32)
    return encoder(model).encode([q], query=True)[0]


def dense_hits(model, kind, q, limit=400):
    index = dense_index(model)
    if index is None:
        return []
    return index.search(query_vector(model, q), kind, limit)


# ---------------------------------------------------------------- the stack
def stack_lists(q, *, con, greek, english, signals=None, limit=400):
    """{signal name: ranked hits} for every retriever with a non-zero weight in this query class."""
    cfg = config()
    weights = (cfg.get("greek" if greek else "english") or {}) if signals is None else dict.fromkeys(signals, 1.0)
    lists, info = {}, {"seconds": {}}
    import time
    for name, weight in weights.items():
        if not weight or name in BASE_SIGNALS:
            continue
        started = time.perf_counter()
        if name == "keyword":
            lists[name], info["keyword_variants"] = keyword_hits(con, q, limit)
        elif name == "headword":
            lists[name], info["headwords"] = headword_hits(q, greek=greek, limit=limit)
        elif name.startswith("dense_"):
            _, model, kind = name.split("_", 2)
            lists[name] = dense_hits(model, kind, q, limit)
        elif name == "notes":
            from .commentary_context import note_hits
            lists[name] = note_hits(q, limit=limit)
        info["seconds"][name] = round(time.perf_counter() - started, 3)
    return lists, info


def weights_for(greek):
    cfg = config()
    return dict(cfg.get("greek" if greek else "english") or {})
