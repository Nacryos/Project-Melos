"""HTTP API over the corpus headword index (release O). See docs/lemma-index.md."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
NOTE = ("Machine lemmatisation: each token's top-ranked headword with a confidence score (normalised evidence, "
        "not a calibrated probability). Default scope: searchable edited Greek text.")


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


def _pick(index, q, lemma_id, multi=False):
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
    return {"query": q, "resolution": index.resolve(q), "note": NOTE}


@router.get("/api/lemma/search")
def lemma_search(q: str = "", lemma_id: int = 0, author: str = "", genre: str = "", include_reference: bool = False,
                 order: str = "frequency", limit: int = Query(30, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Passages containing any inflected form of a headword (all forms, from the token index)."""
    index = _index()
    used, resolved = _pick(index, q, lemma_id, multi=True)
    result = index.search(used, include_reference=include_reference, author=author, genre=genre, limit=limit,
                          offset=offset, order=order) if used else {"total_passages": 0, "results": []}
    return _envelope(index, used, resolved, **result)


@router.get("/api/lemma/frequency")
def lemma_frequency(q: str = "", lemma_id: int = 0, include_reference: bool = False):
    index = _index()
    used, resolved = _pick(index, q, lemma_id)
    if not used:
        return _envelope(index, used, resolved, tokens=0)
    return _envelope(index, used, resolved, **index.frequency(used, include_reference=include_reference))


@router.get("/api/lemma/distribution")
def lemma_distribution(q: str = "", lemma_id: int = 0, include_reference: bool = False):
    """Author, genre and period distribution of a headword (the frequency tables only)."""
    data = lemma_frequency(q=q, lemma_id=lemma_id, include_reference=include_reference)
    return {k: v for k, v in data.items() if k not in ("possible_additional_tokens", "possible_additional_note")}


@router.get("/api/lemma/concordance")
def lemma_concordance(q: str = "", lemma_id: int = 0, author: str = "", genre: str = "", include_reference: bool = False,
                      order: str = "chronological", width: int = Query(60, ge=10, le=300),
                      limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Keyword in context, one line per occurrence, by headword (every inflected form)."""
    index = _index()
    used, resolved = _pick(index, q, lemma_id)
    if not used:
        return _envelope(index, used, resolved, total=0, lines=[])
    result = index.concordance(used, include_reference=include_reference, author=author, genre=genre, width=width,
                               limit=limit, offset=offset, order=order, text_lookup=_text_lookup())
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
                    offset: int = Query(0, ge=0)):
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
        terms.append(ids)
        resolution.append({"word": word, "lemmas": resolved[:1], "alternatives": resolved[1:4]})
    result = index.proximity(terms, window=window, ordered=ordered, author=author, genre=genre,
                             include_reference=include_reference, limit=limit, offset=offset,
                             text_lookup=_text_lookup())
    return {"query": q, "resolution": resolution, "window": window, "ordered": ordered,
            "scope_note": "Matches lie inside one stored passage; the window counts extra words between the terms.",
            "note": NOTE, **result}


@router.get("/api/concept/diachrony")
def concept_diachrony(q: str, include_reference: bool = False, semantic: bool = True,
                      max_lemmas: int = Query(6, ge=1, le=12)):
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
    result = index.diachrony(q, dense_ids=dense_ids, include_reference=include_reference, max_lemmas=max_lemmas)
    result["warnings"] = warnings
    result["version"] = "concept-diachrony-v1"
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
