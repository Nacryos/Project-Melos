"""Latin research routes over the corpus partition (data/corpus_la.sqlite): the evidence the composer agent reads
for a Latin poem (docs/prd/latin-composer.md §6). Owner session or the agent token, like the composer routes.

GET /api/la/concordance?q=&author=&limit=    lines printing a word (u/v, i/j folded), with poem citations
GET /api/la/forms?forms=a,b,c&author=        L1/L4 status of spellings: corpus tokens, author tokens, lexicon reading, lemma readings
GET /api/la/lemma?q=&author=                  a headword's counts by author (LASLA) and the forms the poet prints (forms_found)
GET /api/la/lemma/resolve?form=               lemma readings of one spelling
GET /api/la/status                            counts of the partition and of the lemma index
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from . import latin_backend, latin_lemma
from .composer_routes import require_owner_or_agent
from .latin_text import normalize_la

router = APIRouter()


def _need():
    if not latin_backend.available():
        raise HTTPException(503, {"code": "latin_corpus_missing", "message": "the Latin corpus partition is not built"})


@router.get("/api/la/status")
def status(_=Depends(require_owner_or_agent)):
    _need()
    row = latin_backend._db().execute("SELECT value FROM metadata WHERE key='build'").fetchone()
    return {**(json.loads(row["value"]) if row else {}), "lemma_index": latin_lemma.status()}


@router.get("/api/la/concordance")
def concordance(q: str = Query(..., min_length=1, max_length=80), author: str = Query("", max_length=80),
                limit: int = Query(20, ge=1, le=100), _=Depends(require_owner_or_agent)):
    _need()
    n = normalize_la(q)
    db = latin_backend._db()
    rows = db.execute("SELECT p.id, p.author, p.citation, p.text, t.form, t.count FROM tokens t JOIN passages p ON p.id=t.passage_id "
                      "WHERE t.normalized=? AND p.kind='text' " + ("AND lower(p.author)=lower(?) " if author else "") +
                      "ORDER BY p.sequence LIMIT ?", (n, author, limit) if author else (n, limit)).fetchall()
    out = []
    for r in rows:
        lines = [l for l in r["text"].split("\n") if n in normalize_la(l).split() or any(w == n for w in normalize_la(l).replace("'", " ").split())]
        out.append({"passage_id": r["id"], "author": r["author"], "citation": r["citation"], "form": r["form"],
                    "count": r["count"], "lines": lines[:4]})
    total = db.execute("SELECT COALESCE(SUM(t.count),0) AS n FROM tokens t JOIN passages p ON p.id=t.passage_id WHERE t.normalized=? AND p.kind='text'", (n,)).fetchone()["n"]
    return {"q": q, "normalized": n, "tokens": int(total), "passages": out}


@router.get("/api/la/forms")
def forms(forms: str = Query(..., min_length=1, max_length=2000), author: str = Query("", max_length=80),
          _=Depends(require_owner_or_agent)):
    _need()
    words = [w.strip() for w in forms.replace(",", " ").split() if w.strip()][:100]
    out = []
    for w in words:
        status, detail = latin_backend.form_status(w)
        att = latin_backend.attestation(w, author)
        out.append({"form": w, "status": status, "detail": detail, "tokens": att["tokens"], "author_tokens": att["author_tokens"],
                    "example": att["example"], "readings": latin_lemma.readings(w)[:4]})
    return {"author": author, "forms": out}


@router.get("/api/la/lemma")
def lemma(q: str = Query(..., min_length=1, max_length=80), author: str = Query("", max_length=80),
          limit: int = Query(40, ge=1, le=200), _=Depends(require_owner_or_agent)):
    """A headword (or a spelling, resolved to its first reading): counts by author and the forms each poet prints."""
    if not latin_lemma.available():
        raise HTTPException(503, {"code": "lemma_index_missing", "message": "the Latin lemma index is not built"})
    readings = latin_lemma.readings(q)
    lem = normalize_la(q)
    att = latin_lemma.lemma_attestation(lem, author)
    if not att["total"] and readings:
        lem = readings[0]["lemma"]
        att = latin_lemma.lemma_attestation(lem, author)
    return {"q": q, "lemma": lem, "readings_of_q": readings[:4], **att, "forms_found": latin_lemma.forms_found(lem, author, limit)}


@router.get("/api/la/lemma/resolve")
def lemma_resolve(form: str = Query(..., min_length=1, max_length=80), _=Depends(require_owner_or_agent)):
    return {"form": form, "readings": latin_lemma.readings(form)}
