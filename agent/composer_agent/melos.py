"""The Melos tools as one in-process SDK MCP server. Each tool is an HTTP call back to melos-api.

`propose_candidates` is the generate-then-discard gate: every candidate is linted by
POST /api/composer/check before anything leaves this service; failures go back to the model.
"""
from __future__ import annotations

import asyncio
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

SERVER = "melos"
Emit = Callable[[dict], Awaitable[None]]


def _s(t: str, d: str, **kw) -> dict:
    return {"type": t, "description": d, **kw}


def _schema(required: tuple[str, ...] = (), **props) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}


Q = _s("string", "Headword or English word (q)")
AUTHOR = _s("string", "Limit to one author, e.g. Sappho")
GENRE = _s("string", "Limit to a genre, e.g. 'melic lyric'")
LIMIT = _s("integer", "Max rows")
VARIANTS = _s("boolean", "Combine dialect/poetic variant headwords (ἔρος with ἔρως)")
DIALECT = _s("string", "lesbian | doric | ionic | all")
GREEK = _s("string", "Greek text")

# name -> (method, path, description, input schema)
HTTP_TOOLS: dict[str, tuple[str, str, str, dict]] = {
    "search": ("GET", "/api/search", "Search the corpus. mode: words | forms | hybrid | themes (English theme -> the poet's "
               "own images). Returns passages with best_line and citation.",
               _schema(("q",), q=_s("string", "Query"), mode=_s("string", "words|forms|hybrid|themes"), author=AUTHOR, limit=LIMIT)),
    "word": ("GET", "/api/word", "Dictionary entries and parses for a Greek form (compact=true for short entries; "
             "lemma= for a headword's dictionary).",
             _schema(("form",), form=_s("string", "Greek form"), lemma=_s("string", "Headword"), compact=_s("boolean", "Short entries"))),
    "morpheus": ("POST", "/api/machine-analysis", "Local Morpheus parse of one form, with dialect tags (epic, Aeolic...).",
                 _schema(("form",), form=_s("string", "One Greek word"))),
    "headlines": ("POST", "/api/words/headlines", "Fast parse of up to 400 forms at once: headword, gloss, parses; "
                  "pass the target dialect or author so Aeolic forms read right.",
                  _schema(("forms",), forms=_s("array", "Greek forms", items={"type": "string"}), dialect=DIALECT, author=AUTHOR)),
    "analyze_text": ("POST", "/api/analyze-text", "Parse a draft in context (parse ranking, dialect gates, syntax).",
                     _schema(("text",), text=GREEK, dialect=DIALECT, author=AUTHOR)),
    "dialectize": ("POST", "/api/dialectize", "Attic -> Lesbian/Doric/Ionic spellings, kept only when attested or parsed, "
                   "each labelled with its rules.",
                   _schema(("forms",), forms=_s("array", "Attic forms", items={"type": "string"}), dialect=DIALECT, author=AUTHOR)),
    "scan": ("POST", "/api/scan", "Scan Greek verse: per-syllable quantity with rule and reason; metre= a template name "
             "(sapphic, alcaic, ...) or auto to fit.",
             _schema(("text",), text=GREEK, metre=_s("string", "Template name or auto"),
                     dialect=_s("string", "none | aeolic | doric | ionic | attic"))),
    "lemma_resolve": ("GET", "/api/lemma/resolve", "English or Greek word -> headword candidates.", _schema(("q",), q=Q)),
    "lemma_search": ("GET", "/api/lemma/search", "Passages with any form of a headword; forms_found is the author's form "
                     "inventory (the best attestation evidence).",
                     _schema(("q",), q=Q, author=AUTHOR, genre=GENRE, limit=LIMIT, combine_variants=VARIANTS)),
    "lemma_frequency": ("GET", "/api/lemma/frequency", "Headword frequency per author/genre/period with rates.",
                        _schema(("q",), q=Q, combine_variants=VARIANTS)),
    "concordance": ("GET", "/api/lemma/concordance", "Keyword in context for a headword, one line per locus.",
                    _schema(("q",), q=Q, author=AUTHOR, genre=GENRE, limit=LIMIT, combine_variants=VARIANTS)),
    "collocations": ("GET", "/api/lemma/collocations", "Collocates of a headword (log-likelihood), by author or genre.",
                     _schema(("q",), q=Q, author=AUTHOR, genre=GENRE, window=_s("integer", "Window 1-20"), limit=LIMIT,
                             min_count=_s("integer", "Minimum count"))),
    "proximity": ("GET", "/api/lemma/proximity", "Passages where 2-6 headwords occur near each other (an image pair).",
                  _schema(("q",), q=_s("string", "2-6 Greek words, space separated"), window=_s("integer", "0 = phrase"),
                          author=AUTHOR, genre=GENRE, limit=LIMIT)),
    "ngrams": ("GET", "/api/lemma/ngrams", "Frequent headword n-grams of an author/genre/period (kind=author, name=Sappho).",
               _schema(("kind", "name"), kind=_s("string", "author|genre|period|corpus"), name=_s("string", "Group name"),
                       n=_s("integer", "2-4, 0 = all"), q=_s("string", "Only n-grams with this headword"), limit=LIMIT)),
    "concept_diachrony": ("GET", "/api/concept/diachrony", "English concept -> the Greek headwords for it, scoped by author/genre.",
                          _schema(("q",), q=_s("string", "Concept, e.g. longing"), author=AUTHOR, genre=GENRE,
                                  max_lemmas=_s("integer", "1-12"))),
    "cite": ("GET", "/api/cite", "Resolve a citation (Sappho fr. 31, Il. 1.1) to records and the cited line.",
             _schema(("q",), q=_s("string", "Citation"), limit=LIMIT)),
    "commentary": ("GET", "/api/commentary/notes", "Commentary notes on a stored passage (passage_id from search results).",
                   _schema(("passage_id",), passage_id=_s("string", "Passage id"), limit=LIMIT)),
}

CANDIDATE = {"type": "object", "required": ["greek", "english_span"], "properties": {
    "greek": _s("string", "The continuation, Greek, accented, in the target dialect"),
    "english_span": _s("string", "The words of the English source it carries"),
    "slots": _s("string", "Metrical slots it fills, e.g. '–⏑–– (positions 1-4 of line 2)'"),
    "evidence": _s("array", "Short evidence notes, e.g. 'σελάννα: Sappho 96, 154'; 'not in Sappho; Alcaeus 34a has πήλοθεν'",
                   items={"type": "string"})}}


def norm(greek: str) -> str:
    return " ".join(unicodedata.normalize("NFC", greek or "").split())


def text(payload: Any, limit: int = 0, error: bool = False) -> dict:
    out = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if limit and len(out) > limit:
        out = out[:limit] + f"\n[truncated: {len(out) - limit} more characters; narrow the query]"
    return {"content": [{"type": "text", "text": out}], **({"is_error": True} if error else {})}


@dataclass
class Ctx:
    """Per-request state shared by the tool handlers."""
    http: httpx.AsyncClient
    emit: Emit
    settings: Any
    poem: dict
    slot: dict | None = None
    target: int = 0                    # pool: stop after this many passing candidates (0 = chat, no target)
    max_rounds: int = 4
    rounds: int = 0
    passed: int = 0
    rejected: Counter = field(default_factory=Counter)
    rejected_count: int = 0
    seen: set = field(default_factory=set)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    lint_limit: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(8))

    @property
    def poem_settings(self) -> dict:
        return self.poem.get("settings") or {}

    async def call(self, method: str, path: str, args: dict) -> httpx.Response:
        args = {k: v for k, v in args.items() if v not in (None, "")}
        headers = {"X-Composer-Token": self.settings.token}
        url = self.settings.melos_api_url + path
        if method == "GET":
            return await self.http.get(url, params=args, headers=headers, timeout=self.settings.http_timeout)
        return await self.http.post(url, json=args, headers=headers, timeout=self.settings.http_timeout)

    async def lint(self, greek: str) -> dict:
        """POST /api/composer/check. Any transport or HTTP failure counts as a blocking failure."""
        s, slot = self.poem_settings, self.slot or {}
        body = {"greek": greek, "metre": s.get("metre"), "dialect": s.get("dialect"), "author": s.get("author"),
                "remaining_template": slot.get("remaining_template")}
        async with self.lint_limit:
            try:
                r = await self.call("POST", "/api/composer/check", body)
                r.raise_for_status()
                result = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                return {"pass": False, "checks": [{"id": "lint_unavailable", "ok": False, "blocking": True,
                                                   "detail": type(exc).__name__}]}
        checks = result.get("checks") or []
        ok = result.get("pass") is True and not any(c.get("blocking") and not c.get("ok") for c in checks)
        return {**result, "pass": ok, "checks": checks}


def _http_tool(ctx: Ctx, name: str, method: str, path: str, desc: str, schema: dict):
    @tool(name, desc, schema, annotations=None)
    async def handler(args: dict) -> dict:
        await ctx.emit({"type": "tool", "name": name, "summary": _summary(args)})
        try:
            r = await ctx.call(method, path, args)
        except httpx.HTTPError as exc:
            return text(f"{name} failed: {type(exc).__name__}", error=True)
        try:
            body = r.json()
        except ValueError:
            body = r.text
        if r.status_code >= 400:
            return text({"status": r.status_code, "error": body}, ctx.settings.tool_result_chars, error=True)
        return text(body, ctx.settings.tool_result_chars)
    return handler


def _summary(args: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", []))[:200]


def _failures(checks: list) -> list:
    return [c for c in checks if c.get("blocking") and not c.get("ok")]


def build_tools(ctx: Ctx) -> list:
    tools = [_http_tool(ctx, n, *spec) for n, spec in HTTP_TOOLS.items()]

    @tool("check_candidate", "Run the whole lint bank (metre, form exists, dialect, attestation) on one Greek phrase "
          "for this poem's settings, without proposing it.", _schema(("greek",), greek=GREEK))
    async def check_candidate(args: dict) -> dict:
        await ctx.emit({"type": "tool", "name": "check_candidate", "summary": args.get("greek", "")[:200]})
        return text(await ctx.lint(norm(args.get("greek", ""))), ctx.settings.tool_result_chars)

    @tool("propose_candidates", "Offer candidates to the owner. Each is linted at once; those that pass are shown, the "
          "failures come back to you with reasons so the next batch avoids them. Batches of 6-12.",
          _schema(("candidates",), candidates={"type": "array", "items": CANDIDATE, "maxItems": 16}))
    async def propose_candidates(args: dict) -> dict:
        if ctx.stop.is_set():
            return text("Stop: the request is complete. Reply with the single word: done.")
        ctx.rounds += 1
        batch, dupes = [], 0
        for c in (args.get("candidates") or [])[:16]:
            g = norm(c.get("greek", "") if isinstance(c, dict) else "")
            if not g or g in ctx.seen:
                dupes += 1
                continue
            ctx.seen.add(g)
            batch.append({**c, "greek": g})
        await ctx.emit({"type": "tool", "name": "propose_candidates", "summary": f"round {ctx.rounds}: {len(batch)} candidates"})
        results = await asyncio.gather(*(ctx.lint(c["greek"]) for c in batch))
        lines = []
        for cand, res in zip(batch, results):
            if res["pass"] and not (ctx.target and ctx.passed >= ctx.target):
                ctx.passed += 1
                await ctx.emit({"type": "candidate", "greek": cand["greek"], "english_span": cand.get("english_span", ""),
                                "slots": cand.get("slots", ""), "evidence": list(cand.get("evidence") or []),
                                "checks": res["checks"], "scansion": res.get("scansion")})
            elif not res["pass"]:
                ctx.rejected_count += 1
                fails = _failures(res["checks"]) or [{"id": "fail", "detail": "lint did not pass"}]
                ctx.rejected.update(f["id"] for f in fails)
                lines.append(f"- {cand['greek']}: " + "; ".join(f"{f['id']} {f.get('detail', '')}".strip() for f in fails))
        accepted = sum(r["pass"] for r in results)
        msg = [f"Round {ctx.rounds}: {accepted} passed, {len(lines)} rejected" + (f", {dupes} duplicates skipped" if dupes else "")
               + (f"; {ctx.passed}/{ctx.target} wanted." if ctx.target else ".")]
        if lines:
            msg += ["Rejected (do not repeat these mistakes):", *lines]
        if ctx.target and (ctx.passed >= ctx.target or ctx.rounds >= ctx.max_rounds):
            ctx.stop.set()
            msg.append("Stop now: " + ("enough candidates." if ctx.passed >= ctx.target else "round limit reached.")
                       + " Reply with the single word: done.")
        return text("\n".join(msg))

    return [*tools, check_candidate, propose_candidates]


def server_for(ctx: Ctx):
    tools = build_tools(ctx)
    return create_sdk_mcp_server(SERVER, "1.0.0", tools), tools


def tool_names() -> list[str]:
    return [f"mcp__{SERVER}__{n}" for n in [*HTTP_TOOLS, "check_candidate", "propose_candidates"]]
