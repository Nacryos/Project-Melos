"""HTTP API over the corpus headword index (release O). See docs/lemma-index.md."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
NOTE = ("Machine lemmatisation: each token's top-ranked headword with a confidence score (normalised evidence) "
        "and, where a calibration is deployed, probability (that score calibrated against treebank gold lemmas). "
        "Default scope: searchable edited Greek text.")


def _index():
    from .lemma_index import get_index
    try:
        return get_index()
    except FileNotFoundError as exc:
        raise HTTPException(503, "The corpus headword index is not available on this deployment.") from exc


def _text_lookup():
    from .server import connect
    cache = {}

    def lookup(identifier):
        if identifier not in cache:
            with connect() as con:
                row = con.execute("SELECT text FROM passages WHERE id=?", (identifier,)).fetchone()
            cache[identifier] = row[0] if row else None
        return cache[identifier]
    return lookup


def _pick(index, q, lemma_id, multi=False, combine_variants=False):
    used, resolved = _pick_ids(index, q, lemma_id, multi)
    if combine_variants and used:
        used = index.expand_variants(used)
    return used, resolved


def _pick_ids(index, q, lemma_id, multi=False):
    """(lemma ids used, resolution list). An explicit lemma_id wins; else the query's readings."""
    if lemma_id:
        brief = index.lemma_brief(lemma_id)
        if not brief.get("lemma"):
            raise HTTPException(404, "Unknown lemma_id")
        return [lemma_id], [dict(brief, via="lemma_id")]
    if not q.strip():
        raise HTTPException(422, "Give q (a Greek headword or form, or an English word) or lemma_id.")
    resolved = index.resolve(q)
    if not resolved:
        return [], []
    if multi and resolved[0]["via"] in ("english_dictionary_gloss", "transliterated_headword"):
        ids = [r["lemma_id"] for r in resolved]
    else:
        ids = [resolved[0]["lemma_id"]]
    # Capitalisation variants of one headword (ἠώς / Ἠώς) are counted together.
    return list(dict.fromkeys(i for lemma_id in ids for i in index.case_variants(lemma_id))), resolved


def _envelope(index, used, resolved, **payload):
    return {"lemma_ids": used, "resolution": resolved,
            "alternatives_note": ("The first reading is used; pass lemma_id to choose another." if len(resolved) > 1 else None),
            "index": {"version": index.manifest.get("version"), "built_at": index.manifest.get("built_at")},
            "note": NOTE, **payload}


@router.get("/api/lemma/status")
def lemma_status():
    return _index().status()


@router.get("/api/lemma/resolve")
def lemma_resolve(q: str):
    index = _index()
    resolution = index.resolve(q)
    for row in resolution[:3]:
        row["variant_group"] = index.variant_group(row["lemma_id"])
    return {"query": q, "resolution": resolution, "note": NOTE}


@router.get("/api/lemma/variants")
def lemma_variants(q: str = "", lemma_id: int = 0):
    """Dialect/poetic variant group of a headword (release P): headwords a dictionary entry names as forms
    of one another (ἔρος poet. for ἔρως), with the evidence."""
    index = _index()
    used, resolved = _pick(index, q, lemma_id)
    groups = [index.variant_group(i) for i in used]
    return {"query": q or None, "resolution": resolved, "variant_group": next((g for g in groups if g), None)}


@router.get("/api/lemma/search")
def lemma_search(q: str = "", lemma_id: int = 0, author: str = "", genre: str = "", include_reference: bool = False,
                 order: str = "frequency", limit: int = Query(30, ge=1, le=200), offset: int = Query(0, ge=0),
                 combine_variants: bool = False):
    """Passages containing any inflected form of a headword (all forms, from the token index), each with
    an excerpt around the first occurrence and the offsets of every occurrence (release P)."""
    index = _index()
    used, resolved = _pick(index, q, lemma_id, multi=True, combine_variants=combine_variants)
    result = index.search(used, include_reference=include_reference, author=author, genre=genre, limit=limit,
                          offset=offset, order=order, text_lookup=_text_lookup()) if used else {"total_passages": 0, "results": []}
    return _envelope(index, used, resolved, **result)


@router.get("/api/lemma/frequency")
def lemma_frequency(q: str = "", lemma_id: int = 0, include_reference: bool = False, combine_variants: bool = False):
    index = _index()
    used, resolved = _pick(index, q, lemma_id, combine_variants=combine_variants)
    if not used:
        return _envelope(index, used, resolved, tokens=0)
    return _envelope(index, used, resolved, **index.frequency(used, include_reference=include_reference))


@router.get("/api/lemma/distribution")
def lemma_distribution(q: str = "", lemma_id: int = 0, include_reference: bool = False, combine_variants: bool = False):
    """Author, genre and period distribution of a headword (the frequency tables only)."""
    data = lemma_frequency(q=q, lemma_id=lemma_id, include_reference=include_reference,
                           combine_variants=combine_variants)
    return {k: v for k, v in data.items() if k not in ("possible_additional_tokens", "possible_additional_note")}


@router.get("/api/lemma/concordance")
def lemma_concordance(q: str = "", lemma_id: int = 0, author: str = "", genre: str = "", include_reference: bool = False,
                      order: str = "chronological", width: int = Query(60, ge=10, le=300),
                      limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), period: str = "",
                      undated: bool = False, fold_editions: bool = True, combine_variants: bool = False):
    """Keyword in context, one line per occurrence, by headword (every inflected form). Release P:
    `period` (a period label) or `undated=true`; other collections' copies of a line folded under it."""
    index = _index()
    used, resolved = _pick(index, q, lemma_id, combine_variants=combine_variants)
    if not used:
        return _envelope(index, used, resolved, total=0, lines=[])
    try:
        result = index.concordance(used, include_reference=include_reference, author=author, genre=genre, width=width,
                                   limit=limit, offset=offset, order=order, text_lookup=_text_lookup(),
                                   period="undated" if undated else period, fold_editions=fold_editions)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _envelope(index, used, resolved, **result)


@router.get("/api/lemma/collocations")
def lemma_collocations(q: str = "", lemma_id: int = 0, window: int = Query(5, ge=1, le=20),
                       min_count: int = Query(3, ge=1, le=1000), measure: str = "log_likelihood", author: str = "",
                       genre: str = "", include_reference: bool = False, limit: int = Query(30, ge=1, le=200)):
    if measure not in ("log_likelihood", "pmi"):
        raise HTTPException(422, "measure must be log_likelihood or pmi")
    index = _index()
    used, resolved = _pick(index, q, lemma_id)
    if not used:
        return _envelope(index, used, resolved, collocates=[])
    result = index.collocations(used[0], window=window, min_count=min_count, measure=measure, author=author,
                                genre=genre, include_reference=include_reference, limit=limit)
    return _envelope(index, used, resolved, **result)


@router.get("/api/lemma/proximity")
def lemma_proximity(q: str, window: int = Query(0, ge=0, le=50), ordered: bool = True, author: str = "",
                    genre: str = "", include_reference: bool = False, limit: int = Query(30, ge=1, le=200),
                    offset: int = Query(0, ge=0), cross_passages: bool = False, combine_variants: bool = False):
    """Phrase (ordered, window 0) or proximity search by headword: each word is read as its headword(s)."""
    index = _index()
    words = q.split()
    if not 2 <= len(words) <= 6:
        raise HTTPException(422, "Give two to six words.")
    terms, resolution = [], []
    for word in words:
        resolved = index.resolve(word)
        if not resolved:
            return {"query": q, "resolution": resolution + [{"word": word, "lemmas": []}], "total": 0, "results": [],
                    "note": f"No headword found for {word}."}
        ids = index.case_variants(resolved[0]["lemma_id"])
        if combine_variants:
            ids = index.expand_variants(ids)
        terms.append(ids)
        resolution.append({"word": word, "lemmas": resolved[:1], "alternatives": resolved[1:4]})
    result = index.proximity(terms, window=window, ordered=ordered, author=author, genre=genre,
                             include_reference=include_reference, limit=limit, offset=offset,
                             text_lookup=_text_lookup(), cross_passages=cross_passages)
    scope = ("Matches lie inside one stored passage or run on into the following stored passages of the same "
             "edition when their line numbers continue (crosses_passages, match_passages); "
             if cross_passages else "Matches lie inside one stored passage; ")
    return {"query": q, "resolution": resolution, "window": window, "ordered": ordered,
            "cross_passages": cross_passages,
            "scope_note": scope + "the window counts extra words between the terms.",
            "note": NOTE, **result}


@router.get("/api/concept/diachrony")
def concept_diachrony(q: str, include_reference: bool = False, semantic: bool = True,
                      max_lemmas: int = Query(6, ge=1, le=12), combine_variants: bool = False):
    """Headwords expressing a concept with frequency by period and author date, and collocates per period."""
    if not q.strip() or len(q) > 200:
        raise HTTPException(422, "Give a short concept (an English word or phrase, or a Greek headword).")
    index = _index()
    dense_ids, warnings = [], []
    if semantic:
        try:
            from .server import semantic_service
            dense_ids = [hit["id"] for hit in semantic_service().search(q, limit=1000, language="grc")]
        except Exception as exc:  # noqa: BLE001 - the dictionary part stands alone
            warnings.append("Meaning index unavailable; semantic candidates omitted: " + type(exc).__name__)
    result = index.diachrony(q, dense_ids=dense_ids, include_reference=include_reference, max_lemmas=max_lemmas,
                             text_lookup=_text_lookup(), combine_variants=combine_variants)
    result["warnings"] = warnings
    result["version"] = "concept-diachrony-v2"
    return result


@router.on_event("startup")
def _load_index_in_background():
    """Open and warm the headword index after start-up so the first request does not pay for it."""
    import threading

    def load():
        try:
            from .lemma_index import get_index
            get_index()
        except Exception:  # noqa: BLE001 - the routes report unavailability themselves
            pass
    threading.Thread(target=load, daemon=True).start()


# ----------------------------------------------------------------------------- release P: n-grams
def _ngram_db():
    import os
    import sqlite3
    from pathlib import Path
    path = Path(os.getenv("MELOS_NGRAM_INDEX", str(Path(__file__).resolve().parents[1] / "data/ngrams.sqlite")))
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(503, "The lemma n-gram lists are not available on this deployment.")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


@router.get("/api/lemma/ngrams/groups")
def lemma_ngram_groups():
    """Authors, genres and periods with n-gram lists (passages and tokens in each)."""
    import json
    with _ngram_db() as con:
        manifest = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        groups = [dict(r) for r in con.execute("SELECT * FROM grp ORDER BY kind, tokens DESC")]
    return {"groups": groups, "manifest": manifest}


@router.get("/api/lemma/ngrams")
def lemma_ngrams(kind: str = "corpus", name: str = "all", n: int = Query(0, ge=0, le=4), q: str = "",
                 include_function_words: bool = False, limit: int = Query(30, ge=1, le=400)):
    """Frequent headword n-grams (2-4) of an author, genre or period, ranked by log-likelihood G2."""
    import json
    if kind not in ("author", "genre", "period", "corpus"):
        raise HTTPException(422, "kind must be author, genre, period or corpus")
    if n == 1:
        raise HTTPException(422, "n is 2, 3 or 4 (0 = all lengths)")
    with _ngram_db() as con:
        manifest = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        group = con.execute("SELECT * FROM grp WHERE kind=? AND lower(name)=lower(?)", (kind, name)).fetchone()
        if group is None and kind == "author":
            from .author_aliases import canonical
            group = con.execute("SELECT * FROM grp WHERE kind=? AND name=?", (kind, canonical(name))).fetchone()
        if group is None:
            raise HTTPException(404, f"No n-gram list for {kind} {name!r}; see /api/lemma/ngrams/groups.")
        sql = "SELECT * FROM ngram WHERE kind=? AND name=?"
        params = [kind, group["name"]]
        if n:
            sql += " AND n=?"
            params.append(n)
        if not include_function_words:
            sql += " AND function_only=0"
        ids = []
        if q.strip():
            index = _index()
            resolved = index.resolve(q)
            if not resolved:
                return {"group": dict(group), "query": q, "ngrams": [], "note": "No headword found for the query."}
            ids = [str(i) for i in index.case_variants(resolved[0]["lemma_id"])]
        rows = []
        source = sql + " ORDER BY g2 DESC"
        if ids and con.execute("SELECT 1 FROM sqlite_master WHERE name='ngram_lemma'").fetchone():
            # Release Q: phrases indexed by headword (not only the group's top list).
            source = (sql.replace("FROM ngram WHERE", "FROM ngram_lemma WHERE") +
                      f" AND lemma_id IN ({','.join('?' * len(ids))}) ORDER BY g2 DESC")
            params = params + [int(i) for i in ids]
        seen = set()
        for row in con.execute(source, params):
            if row["lemma_ids"] in seen:
                continue
            seen.add(row["lemma_ids"])
            gram_ids = row["lemma_ids"].split()
            if ids and not set(ids) & set(gram_ids):
                continue
            rows.append({"n": row["n"], "lemmas": row["lemmas"].split(" "), "lemma_ids": [int(x) for x in gram_ids],
                         "count": row["count"], "expected": row["expected"], "g2": row["g2"], "per_10k": row["per_10k"],
                         "function_only": bool(row["function_only"]), "example_passage": row["example"]})
            if len(rows) >= limit:
                break
    return {"group": dict(group), "query": q or None, "ngrams": rows, "statistic": manifest.get("statistic"),
            "scope": manifest.get("scope"), "min_count": manifest.get("min_count"),
            "note": ("Consecutive top-ranked headwords inside one stored passage (machine lemmatisation); ranked by "
                     "log-likelihood G2 of the last headword after its prefix. Function-word-only n-grams are "
                     "hidden unless include_function_words=true.")}
