"""Latin research routes over the corpus partition (data/corpus_la.sqlite): the evidence the composer agent reads
for a Latin poem (docs/prd/latin-composer.md §6). Owner session or the agent token, like the composer routes.

GET /api/la/concordance?q=&author=&limit=    lines printing a word (u/v, i/j folded), with poem citations
GET /api/la/forms?forms=a,b,c&author=        L1/L4 status of spellings: corpus tokens, author tokens, lexicon reading, lemma readings
GET /api/la/lemma?q=&author=                  a headword's counts by author (LASLA) and the forms the poet prints (forms_found)
GET /api/la/lemma/resolve?form=               lemma readings of one spelling
GET /api/la/status                            counts of the partition and of the lemma index
POST /api/la/check {text, metre, author, only, evidence}   every check on whole lines (scripts/la_check.py's report)
GET /api/la/prosody?form=&author=             how the poets scan a form: quantities with loci (Catullus, then Virgil)
GET /api/la/dictionary?q=                     Lewis & Short entries of a word: senses, authors cited, period labels
GET /api/la/reverse?q=&limit=                 English -> Latin headwords whose Lewis & Short glosses carry the word
GET /api/la/commentary?poem=&line= | q= | words=   Merrill's notes on a poem or line, or searched; intro= his introduction
GET /api/la/grammar?section= | q=             Allen & Greenough by section number, or searched
"""
from __future__ import annotations

import importlib
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

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
          limit: int = Query(40, ge=1, le=200), context: str = Query("", max_length=400), _=Depends(require_owner_or_agent)):
    """A headword (or a spelling, resolved to its first reading, or to LatinCy's reading in `context`, the draft line
    holding it): counts by author and the forms each poet prints."""
    if not latin_lemma.available():
        raise HTTPException(503, {"code": "lemma_index_missing", "message": "the Latin lemma index is not built"})
    readings = latin_lemma.readings(q)
    if context:
        words = latin_backend.latin_words(context)
        idx = next((i for i, w in enumerate(words) if normalize_la(w) == normalize_la(q)), None)
        if idx is not None:
            readings, _how = latin_lemma.choose_reading(readings, latin_lemma.context_lemmas(words).get(idx))
    lem = normalize_la(q)
    att = latin_lemma.lemma_attestation(lem, author)
    if not att["total"] and readings:
        lem = readings[0]["lemma"]
        att = latin_lemma.lemma_attestation(lem, author)
    return {"q": q, "lemma": lem, "readings_of_q": readings[:4], **att, "forms_found": latin_lemma.forms_found(lem, author, limit)}


@router.get("/api/la/lemma/resolve")
def lemma_resolve(form: str = Query(..., min_length=1, max_length=80), context: str = Query("", max_length=400),
                  _=Depends(require_owner_or_agent)):
    """Readings of one spelling; with `context` (the draft line holding it) LatinCy's reading in context goes first."""
    reads = latin_lemma.readings(form)
    how = reads[0]["source"] if reads else "none"
    if context:
        words = latin_backend.latin_words(context)
        n = normalize_la(form)
        idx = next((i for i, w in enumerate(words) if normalize_la(w) == n), None)
        if idx is not None:
            reads, how = latin_lemma.choose_reading(reads, latin_lemma.context_lemmas(words).get(idx))
    return {"form": form, "readings": reads, "chosen_by": how}


# ------------------------------------------------------------------------- checks and reference stores (catullan-composer)

def _module(name: str):
    """A Latin module built on another branch of the work: 503 while it is absent or its data is not built."""
    try:
        return importlib.import_module(f".{name}", __package__)
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        raise HTTPException(503, {"code": "latin_module_unavailable", "message": f"{name}: {type(exc).__name__}: {exc}"})


def _call(name: str, function: str, *args, **kwargs):
    fn = getattr(_module(name), function, None)
    if fn is None:
        raise HTTPException(503, {"code": "latin_module_unavailable", "message": f"{name}.{function} is not defined"})
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, {"code": "latin_lookup_failed", "message": f"{name}.{function}: {type(exc).__name__}: {exc}"})


class LaCheckIn(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(..., min_length=1, max_length=4000)          # whole lines, one per line
    metre: str | None = Field("phalaecian", max_length=40)
    author: str | None = Field("Catullus", max_length=80)
    only: str | None = Field(None, max_length=80)                  # check ids, comma separated: "L7,L12"
    evidence: int = Field(3, ge=0, le=200)                         # evidence rows kept per check (0 = all)


CHECK_CHARS = 8000        # evidence of one /api/la/check is trimmed to this; agent tool results are cut at 10,000 characters


def check_budget_seconds() -> float:
    """Seconds allowed to the Latin-only checks of one /api/la/check (MELOS_LA_CHECK_BUDGET_MS, default 20000)."""
    try:
        return max(50, int(os.environ.get("MELOS_LA_CHECK_BUDGET_MS", "20000"))) / 1000
    except ValueError:
        return 20.0


@router.post("/api/la/check")
def la_check(body: LaCheckIn, _=Depends(require_owner_or_agent)):
    """Every check on a draft of whole lines: L7, L1, L4, L11, then L12, L8, L13, L3, L10, L14, L5, L6, each with a
    status (PASS / WARN / FAIL / unavailable), blocking failures first."""
    from . import composer_lint
    _need()
    text = "\n".join(l.strip() for l in body.text.replace(" / ", "\n").split("\n") if l.strip())
    only = {x.strip().upper() for x in (body.only or "").split(",") if x.strip()} or None
    metre = body.metre if body.metre not in (None, "", "auto", "none") else None
    r = composer_lint.check(text, metre_name=metre, author=body.author or "Catullus", language="la",
                            latin_budget=check_budget_seconds(), latin_only=only)
    order = {"FAIL": 0, "WARN": 1, "PASS": 2, "unavailable": 3}
    checks = []
    for c in r["checks"]:
        if only and c["id"].upper() not in only:
            continue
        rows = sorted(c.get("evidence") or [], key=lambda e: not (isinstance(e, dict) and e.get("warning")))     # warnings first
        kept = rows if not body.evidence else rows[:body.evidence]
        checks.append({"id": c["id"], "name": c.get("name"), "status": composer_lint.status_of(c), "blocking": bool(c.get("blocking")),
                       "detail": c.get("detail"), "evidence": kept, "evidence_rows": len(rows)})
    checks.sort(key=lambda c: order[c["status"]])
    while body.evidence and len(json.dumps(checks, ensure_ascii=False)) > CHECK_CHARS:      # the agent's tool result is cut at 10,000
        big = max(checks, key=lambda c: len(json.dumps(c["evidence"], ensure_ascii=False)))
        if not big["evidence"]:
            break
        big["evidence"] = big["evidence"][:-1]          # evidence_rows keeps the full count; only=<id>, evidence=0 returns all
    failed = [c["id"] for c in checks if c["status"] == "FAIL"]
    return {"pass": not failed, "blocking_failures": failed, "metre": metre, "author": body.author or "Catullus",
            "lines": [{"text": t, "pattern": s["pattern"], "syllables": " ".join(("(" + x["text"] + ")") if x["label"] == "E" else x["text"].replace(" ", "·") for x in s["syllables"]),
                       **({"fits": f["ok"], "fit": f["pattern"], "message": f["message"]} if f else {})}
                      for t, s, f in zip(text.split("\n"), r["scansion"]["lines"], (r["scansion"]["fit"] or []) + [None] * len(r["scansion"]["lines"]))],
            "checks": checks, "ms": r["ms"]}


@router.get("/api/la/prosody")
def la_prosody(form: str = Query(..., min_length=1, max_length=80), author: str = Query("", max_length=80),
               _=Depends(require_owner_or_agent)):
    return _call("latin_prosody", "attested", form, author)


@router.get("/api/la/dictionary")
def la_dictionary(q: str = Query(..., min_length=1, max_length=80), _=Depends(require_owner_or_agent)):
    return {"q": q, "entries": _call("latin_dictionary", "lookup", q)}


@router.get("/api/la/reverse")
def la_reverse(q: str = Query(..., min_length=1, max_length=120), limit: int = Query(20, ge=1, le=100),
               _=Depends(require_owner_or_agent)):
    return {"q": q, "headwords": _call("latin_dictionary", "reverse", q, limit)}


@router.get("/api/la/commentary")
def la_commentary(poem: str = Query("", max_length=12), line: int | None = Query(None, ge=1, le=500),
                  q: str = Query("", max_length=200), words: str = Query("", max_length=400),
                  intro: str = Query("", max_length=200), limit: int = Query(10, ge=1, le=50),
                  _=Depends(require_owner_or_agent)):
    """Merrill (1893): notes on `poem` (and `line`); else notes matching `q`; else notes on any of `words` (the
    draft's words, comma or space separated); `intro` searches his introduction."""
    if poem:
        return {"poem": poem, "line": line, "notes": _call("latin_reference", "commentary", poem, line)}
    if q:
        return {"q": q, "notes": _call("latin_reference", "commentary_search", q, limit)}
    if words:
        ws = [w for w in words.replace(",", " ").split() if w][:40]
        return {"words": ws, "notes": _call("latin_reference", "notes_for_words", ws, limit)}
    if intro:
        return {"intro": intro, "sections": _call("latin_reference", "intro_search", intro, limit)}
    raise HTTPException(422, {"code": "missing_query", "message": "give poem (and line), q, words or intro"})


@router.get("/api/la/grammar")
def la_grammar(section: str = Query("", max_length=20), q: str = Query("", max_length=200),
               limit: int = Query(10, ge=1, le=50), _=Depends(require_owner_or_agent)):
    """Allen & Greenough's New Latin Grammar: one section by number (e.g. 485 or 485c), or sections matching `q`."""
    if section:
        found = _call("latin_reference", "grammar", section)
        if found is None:
            raise HTTPException(404, {"code": "no_such_section", "message": f"Allen & Greenough has no section {section}"})
        return found
    if q:
        return {"q": q, "sections": _call("latin_reference", "grammar_search", q, limit)}
    raise HTTPException(422, {"code": "missing_query", "message": "give section or q"})
