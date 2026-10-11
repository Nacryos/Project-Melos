"""Latin research routes over the corpus partition (data/corpus_la.sqlite): the evidence the composer agent reads
for a Latin poem (docs/prd/latin-composer.md §6). Owner session or the agent token, like the composer routes.

GET /api/la/concordance?q=&author=&limit=    lines printing a word (u/v, i/j folded), with poem citations
GET /api/la/forms?forms=a,b,c&author=        L1/L4 status of spellings: corpus tokens, author tokens, lexicon reading
GET /api/la/status                            counts of the partition
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from . import latin_backend
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
    return json.loads(row["value"]) if row else {}


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
                    "example": att["example"]})
    return {"author": author, "forms": out}
