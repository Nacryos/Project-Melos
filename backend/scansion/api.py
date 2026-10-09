"""HTTP routes for the scanner (not mounted in backend/server.py yet; see docs/scansion.md, "Shipping").

POST /api/scan                  scan text (metre-free), optionally fit a metre or an antistrophe
GET  /api/scan/rules            the meta-grammar as a tree, its parameters, features, calibration, examples
POST /api/scan/rules/validate   check an edited rules file; returns errors or the parsed tree
POST /api/scan/rules/save       write an edited rules file (only when MELOS_SCANSION_DEV=1)
"""
from __future__ import annotations

import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import engine, metre
from .lexicon import QuantityLexicon
from .quantity import Scanner

DATA = Path(__file__).resolve().parent / "data"
MAX_CHARS = 20_000
router = APIRouter()
_lock = threading.Lock()


class ScanRequest(BaseModel):
    text: str = Field(..., max_length=MAX_CHARS)
    metre: str | None = None                       # template name, "auto", or null
    responsion_with: str | None = Field(None, max_length=MAX_CHARS)
    lexicon: bool = True                            # use the optional lexical layer
    params: dict[str, float] | None = None          # tune the grammar's parameters for this request
    segment: bool = False                           # divide running text into verses of `metre`
    dialect: str = "none"                           # "none" | "aeolic" | "doric" | "ionic" | "attic"


class RulesText(BaseModel):
    yaml: str = Field(..., max_length=200_000)


@lru_cache(maxsize=1)
def _lexicon() -> QuantityLexicon | None:
    lex = QuantityLexicon()
    return lex if lex.available else None


_state: dict = {"grammar": None, "mtime": None}


def grammar() -> engine.Grammar:
    """The rules file, re-read when it changes on disk (so an edit takes effect on the next request)."""
    path = engine.DEFAULT_RULES
    mtime = path.stat().st_mtime
    with _lock:
        if _state["mtime"] != mtime:
            g, errors = engine.load(path)
            if errors:
                if _state["grammar"] is None:
                    raise HTTPException(500, {"rules_errors": errors})
                return _state["grammar"]          # keep serving the last good file
            _state.update(grammar=g, mtime=mtime)
        return _state["grammar"]


def _scanner(req_params: dict | None, use_lexicon: bool, dialect: str = "none") -> Scanner:
    g = grammar()
    if req_params:
        bad = [k for k, v in req_params.items() if k not in g.params or not 0 <= v <= 1]
        if bad:
            raise HTTPException(422, f"unknown parameter or value outside 0..1: {', '.join(bad)}")
        g = engine.Grammar({**g.params, **req_params}, g.vowel, g.unit, g.flags, g.source)
    if dialect not in ("none", "aeolic", "doric", "ionic", "attic"):
        raise HTTPException(422, "dialect must be none, aeolic, doric, ionic or attic")
    return Scanner(lexicon=_lexicon() if use_lexicon else None, grammar=g, dialect=dialect)


@router.post("/api/scan")
def scan(req: ScanRequest):
    t0 = time.perf_counter()
    sc = _scanner(req.params, req.lexicon, req.dialect)
    units = sc.scan(req.text)
    lines: dict[int, list] = {}
    for u in units:
        lines.setdefault(u.line, []).append(u)
    line_units = [lines[k] for k in sorted(lines)]
    out = {
        "version": 1,
        "units": [u.as_dict() for u in units],
        "lines": [{"line": k, "units": [u.index for u in lines[k]],
                   "pattern": "".join({"L": "–", "S": "⏑", "A": "?"}[u.label] for u in lines[k])}
                  for k in sorted(lines)],
        "lexicon": bool(req.lexicon and _lexicon() is not None),
        "rules": {"file": "backend/scansion/rules.yaml", "params": sc.grammar.params},
    }
    if req.metre == "auto":
        out["auto"] = metre.auto(line_units)
    elif req.metre:
        if req.metre not in metre.TEMPLATES:
            raise HTTPException(422, f"unknown metre {req.metre!r}; known: {', '.join(sorted(metre.TEMPLATES))}")
        if req.segment and len(line_units) == 1:
            segs = metre.segment(line_units[0], req.metre)
            out["fit"] = [{"units": [s, e], **f.as_dict()} for s, e, f in segs]
        else:
            out["fit"] = [f.as_dict() for f in metre.fit(line_units, req.metre)]
    if req.responsion_with:
        other = sc.scan_lines(req.responsion_with)
        out["responsion"] = {"antistrophe_units": [u.as_dict() for line in other for u in line],
                             "lines": metre.responsion(line_units, other)}
    out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


@router.get("/api/scan/rules")
def rules():
    g, errors = engine.load()
    doc = g.as_dict() if g else {}
    doc["errors"] = errors
    doc["yaml"] = engine.DEFAULT_RULES.read_text(encoding="utf-8")
    for name in ("rule_calibration.json", "rule_examples.json"):
        p = DATA / name
        doc[name.split(".")[0]] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    doc["metres"] = {k: v for k, v in metre.TEMPLATES.items()}
    return doc


@router.post("/api/scan/rules/validate")
def validate(body: RulesText):
    g, errors = engine.load(text=body.yaml)
    return {"ok": not errors, "errors": errors, "tree": g.as_dict() if g else None}


@router.post("/api/scan/rules/save")
def save(body: RulesText):
    if os.environ.get("MELOS_SCANSION_DEV") != "1":
        raise HTTPException(403, "saving the rules file is only allowed on the local dev server")
    g, errors = engine.load(text=body.yaml)
    if errors:
        return {"ok": False, "errors": errors}
    engine.DEFAULT_RULES.write_text(body.yaml, encoding="utf-8")
    return {"ok": True, "errors": []}
