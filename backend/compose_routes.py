"""Release V: next-line suggestions for the composer canvas (POST /api/compose/suggest, GET /api/compose/status).

The loop of docs/composer/loop-design.md §4: propose → deterministic lint → repair, at most three rounds.

Proposers:
- ``corpus`` (live): lines from the chosen poet's own poems near the draft (hybrid search over the draft's
  last lines, then the whole draft, then all poets), preferring the line that follows the best-matching line
  of each passage. These are attested lines, quoted with their citation, not new composition (loop-design
  §7 Q2: homage or copying is the owner's call; each one carries an L11 note).
- ``llm`` (not configured): no text-generating model is reachable from the API host. The only model
  credential there is TypeSafe Jev, which answers choice and score questions and cannot write Greek.
  ``status()`` says what is needed.

Lint, per candidate (verdicts pass / warn / fail with evidence; overall fail if any check fails):
  L7 metre (scanner fit of the candidate as the draft's next line; fail on positions against the scanner),
  L1 forms (corpus headword index: warn on one unread word, fail on more),
  L2 dialect (the source poet's dialect against the target), L4 attestation, L11 verbatim quotation (info).
Repair: candidates that fail are dropped and the next round widens retrieval, excluding what was seen.
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .composer_access import require_owner
from .composer_lint import FROM_PASSAGE_DIALECT as _FROM_PASSAGE_DIALECT, SCAN_DIALECTS
from .rate_limit import RateLimiter

# Release W: owner-only (docs/prd/composer-agent.md §6); signed out, every /api/compose/* path is 404.
router = APIRouter(dependencies=[Depends(require_owner)])
_limit = RateLimiter(client_minute=int(os.environ.get("MELOS_COMPOSE_CLIENT_MINUTE", 12)),
                     client_day=int(os.environ.get("MELOS_COMPOSE_CLIENT_DAY", 600)),
                     connection_minute=int(os.environ.get("MELOS_COMPOSE_CONNECTION_MINUTE", 120)))
ROUNDS = 3
PER_PASSAGE = 4
VERSION = "compose-suggest-v1"


class SuggestRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(..., min_length=1, max_length=2000)
    author: str | None = Field(None, max_length=80)
    metre: str | None = Field(None, max_length=40)          # a scanner template, "auto", or none
    dialect: str | None = Field(None, max_length=20)        # none | aeolic | doric | ionic | attic
    k: int = Field(3, ge=1, le=5)


def llm_status() -> dict:
    return {"configured": False, "provider": None,
            "reason": ("No text-generating model is reachable from the API host. The only model credential there is "
                       "TypeSafe Jev, which answers choice and score questions and does not write text; no local "
                       "generative model is installed."),
            "needs": ("A text-generating model (an API key or a local model) installed on the API host, chosen by the "
                      "owner (docs/composer/loop-design.md §7 Q3). Until then suggestions are attested lines from the "
                      "corpus.")}


@router.get("/api/compose/status")
def status():
    from .scansion import metre
    return {"version": VERSION, "llm": llm_status(), "proposers": ["corpus"],
            "metres": sorted(metre.TEMPLATES), "dialects": list(SCAN_DIALECTS)}


def _target_dialect(dialect: str | None, author: str | None) -> str:
    from .composer_lint import target_dialect
    return target_dialect(dialect, author)


def _clean_lines(result: dict, seen: set[str]) -> list[dict]:
    """Complete, readable lines of a search result, the line after its best-matching line first."""
    from .line_spans import line_at, lines
    from .textutils import normalize
    text = result.get("text") or ""
    rows = lines(text)
    best = (result.get("best_line") or {}).get("start")
    best_index = next((i for i, (s, _, _) in enumerate(rows) if s == best), None)
    order = list(range(len(rows)))
    if best_index is not None:
        order.sort(key=lambda i: (i != best_index + 1, abs(i - best_index)))
    out = []
    for i in order:
        start, _, raw = rows[i]
        if any(ch in raw for ch in "[]†⟨⟩<>{}*") or " . " in raw or raw.rstrip().endswith(("-", "‐")):
            continue
        if i and rows[i - 1][2].rstrip().endswith(("-", "‐")):
            continue                                          # begins inside a word split from the line above
        info = line_at(text, start, result.get("citation") or result.get("work") or result.get("id"))
        clean = info["text"].strip()
        key = normalize(clean)
        if len(clean.split()) < 2 or key in seen:
            continue
        seen.add(key)
        out.append({"greek": clean, "basis": "follows the matching line" if best_index is not None and i == best_index + 1
                    else "line of a related passage",
                    "source": {"passage_id": result.get("id"), "author": result.get("author"),
                               "citation": info["citation"], "line": info["line"]}})
        if len(out) >= PER_PASSAGE:
            break
    return out


def _propose(query: str, author: str, seen: set[str], limit: int) -> list[dict]:
    from .server import search_response
    found = search_response(q=query, mode="hybrid", author=author, limit=limit)
    pool = []
    for result in found.get("results") or []:
        if result.get("kind") == "text" and result.get("language") == "grc":
            pool.extend(_clean_lines(result, seen))
    return pool


def _lint(cand: dict, *, scanner, metre_name: str | None, template: str | None, target_dialect: str,
          author: str) -> dict:
    from .passage_dialect import passage_dialect
    from . import composer_lint as lint
    checks = []
    units = [u for line in scanner.scan_lines(cand["greek"]) for u in line]
    pattern = lint.pattern_of(units)
    if metre_name and template:
        shared, fit = lint.metre_check(units, metre_name, template)
        cand["fit"] = {**fit, "pattern": fit["pattern"] or pattern}
        checks.append({"id": "L7", "name": "metre", "verdict": "pass" if shared["ok"] else "fail",
                       "message": shared["detail"], "evidence": shared["evidence"]})
    else:
        checks.append({"id": "L7", "name": "metre", "verdict": "info",
                       "message": f"no metre chosen; scansion {pattern}", "evidence": []})
    words = lint.greek_words(cand["greek"])
    unread = []
    if words:
        try:
            _rows, unread = lint.unread_forms(words, author)
        except HTTPException:
            unread = []
        verdict = "pass" if not unread else "warn" if len(unread) == 1 else "fail"
        checks.append({"id": "L1", "name": "forms", "verdict": verdict,
                       "message": "every word has a reading" if not unread else f"no reading for {', '.join(unread)}",
                       "evidence": [{"form": w} for w in unread]})
    source = cand["source"]
    own = _FROM_PASSAGE_DIALECT.get(passage_dialect({"author": source.get("author") or "", "id": source.get("passage_id") or ""}) or "", "none")
    if target_dialect == "none":
        checks.append({"id": "L2", "name": "dialect", "verdict": "info", "message": f"source dialect: {own}", "evidence": []})
    else:
        checks.append({"id": "L2", "name": "dialect", "verdict": "pass" if own == target_dialect else "warn",
                       "message": (f"{own} like the target" if own == target_dialect
                                   else f"source is {own}, target {target_dialect}"), "evidence": []})
    quote = {"passage_id": source.get("passage_id"), "citation": source.get("citation"), "quote": cand["greek"]}
    checks.append({"id": "L4", "name": "attestation", "verdict": "pass",
                   "message": f"attested: {source.get('author')}, {source.get('citation')}", "evidence": [quote]})
    checks.append({"id": "L11", "name": "novelty", "verdict": "info",
                   "message": "verbatim line of the corpus (homage or copying is the owner's call)", "evidence": [quote]})
    verdicts = [c["verdict"] for c in checks]
    cand["pattern"] = pattern
    cand["checks"] = checks
    cand["verdict"] = "fail" if "fail" in verdicts else "warn" if "warn" in verdicts else "pass"
    return cand


@router.post("/api/compose/suggest")
def suggest(req: SuggestRequest, request: Request):
    wait = _limit.check(request.headers, request.client.host if request.client else "")
    if wait:
        raise HTTPException(429, detail="Too many suggestion requests from this client; try again shortly.",
                            headers={"Retry-After": str(wait)})
    from .scansion import api as scan_api, metre
    t0 = time.perf_counter()
    draft = [line.strip() for line in req.text.split("\n") if line.strip()]
    if not draft:
        raise HTTPException(422, {"code": "empty", "message": "Type at least one line of Greek."})
    author = (req.author or "").strip()
    target_dialect = _target_dialect(req.dialect, author)
    scanner = scan_api._scanner(None, True, target_dialect)
    draft_lines = scanner.scan_lines("\n".join(draft))
    metre_name = req.metre or None
    detected = None
    if metre_name == "auto":
        ranked = metre.auto(draft_lines)
        detected = ranked[0] if ranked and ranked[0]["lines_fitting"] else None
        metre_name = detected["metre"] if detected else None
    elif metre_name and metre_name not in metre.TEMPLATES:
        raise HTTPException(422, {"code": "unknown_metre", "message": f"unknown metre {metre_name!r}"})
    position = len(draft)
    template = metre.TEMPLATES[metre_name][position % len(metre.TEMPLATES[metre_name])] if metre_name else None

    from .textutils import normalize
    seen = {normalize(line) for line in draft}
    queries = [("\n".join(draft[-2:]), author, 10), ("\n".join(draft[-6:]), author, 20), ("\n".join(draft[-6:]), "", 20)]
    rounds, kept, failed = [], [], []
    for number, (query, scope, limit) in enumerate(queries[:ROUNDS], 1):
        if number == 3 and not author:
            break                                               # round 3 widens the poet scope; nothing to widen
        r0 = time.perf_counter()
        pool = _propose(query, scope, seen, limit)
        for cand in pool:
            _lint(cand, scanner=scanner, metre_name=metre_name, template=template,
                  target_dialect=target_dialect, author=author)
            (failed if cand["verdict"] == "fail" else kept).append(cand)
        rounds.append({"round": number, "scope": scope or "all poets", "query_lines": query.count("\n") + 1,
                       "proposed": len(pool), "passing": sum(c["verdict"] != "fail" for c in pool),
                       "ms": round((time.perf_counter() - r0) * 1000)})
        if len(kept) >= req.k:
            break
    rank = {"pass": 0, "warn": 1, "fail": 2}
    ordered = sorted(kept, key=lambda c: rank[c["verdict"]]) + failed     # stable: retrieval order within a verdict
    candidates = ordered[: req.k]
    for i, cand in enumerate(candidates):
        cand["id"] = f"c{i + 1}"
    return {"version": VERSION, "generator": {"proposer": "corpus", "llm": llm_status()},
            "target": {"author": author or None, "dialect": target_dialect, "metre": metre_name,
                       "metre_detected": detected, "line": position + 1, "template": template},
            "candidates": candidates, "halted": not any(c["verdict"] != "fail" for c in candidates),
            "rounds": rounds, "ms": round((time.perf_counter() - t0) * 1000)}
