"""The Melos tools as one in-process SDK MCP server. Each tool is an HTTP call back to melos-api.

`propose_candidates` is the generate-then-discard gate: every candidate is linted by
POST /api/composer/check before anything leaves this service; failures go back to the model.
"""
from __future__ import annotations

import asyncio
import json
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

SERVER = "melos"
WORDS_MAX = 3            # a next-words candidate is one to three words
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
    "scan": ("POST", "/api/scan", "Scan verse: per-syllable quantity with rule and reason; metre= a template name "
             "(sapphic, alcaic, phalaecian, ...) or auto to fit; language grc (default) or la (Latin: elision candidates marked).",
             _schema(("text",), text=GREEK, metre=_s("string", "Template name or auto"),
                     dialect=_s("string", "none | aeolic | doric | ionic | attic"),
                     language=_s("string", "grc | la"))),
    "la_concordance": ("GET", "/api/la/concordance", "Latin: lines in which the corpus (Catullus, Horace, ...) prints a word, "
                       "u/v and i/j folded, with citations; author= to limit to the poet.",
                       _schema(("q",), q=_s("string", "A Latin word form"), author=AUTHOR, limit=LIMIT)),
    "la_forms": ("GET", "/api/la/forms", "Latin: for each spelling, whether it is printed in the corpus or known to the "
                 "paradigm lexicon, its tokens overall and in the poet, and one citation.",
                 _schema(("forms",), forms=_s("string", "Latin forms, comma or space separated"), author=AUTHOR)),
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
    "slot": _s("string", "The key of the slot this continues (from the task); required when there are several"),
    "greek": _s("string", "The continuation, Greek, accented, in the target dialect; a newline where it runs on "
                "into the next line"),
    "english_span": _s("string", "The words of the English source it carries"),
    "slots": _s("string", "Metrical slots it fills, e.g. '–⏑–– (positions 1-4 of line 2)'"),
    "evidence": _s("array", "Short evidence notes, e.g. 'σελάννα: Sappho 96, 154'; 'not in Sappho; Alcaeus 34a has πήλοθεν'",
                   items={"type": "string"})}}


def norm(greek: str) -> str:
    """NFC, spaces collapsed within a line; a line break (newline or ' / ') is kept as one newline (spill-over)."""
    text = unicodedata.normalize("NFC", greek or "").replace(" / ", "\n")
    return "\n".join(" ".join(line.split()) for line in text.split("\n") if line.strip())


def text(payload: Any, limit: int = 0, error: bool = False) -> dict:
    out = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if limit and len(out) > limit:
        out = out[:limit] + f"\n[truncated: {len(out) - limit} more characters; narrow the query]"
    return {"content": [{"type": "text", "text": out}], **({"is_error": True} if error else {})}


@dataclass
class Ctx:
    """State of one turn (one /pool, /warm or /chat request), shared by the tool handlers.

    ``slots``: slot_key -> {line_position, prefix, remaining_template, want}; empty for chat. ``seen``: slot_key ->
    every continuation already proposed for that slot in this session (kept across turns, so repeats are skipped)."""
    http: httpx.AsyncClient
    emit: Emit
    settings: Any
    poem: dict
    slots: dict = field(default_factory=dict)
    primary: str | None = None
    mode: str = "line"                                  # line: whole-line continuations | words: 1-3 words
    max_rounds: int = 4
    rounds: int = 0
    passed: Counter = field(default_factory=Counter)
    rejected: Counter = field(default_factory=Counter)
    rejected_count: int = 0
    seen: dict = field(default_factory=dict)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    stop_reason: str | None = None
    started: float = field(default_factory=time.monotonic)
    first_ms: dict = field(default_factory=dict)       # slot_key -> ms from the request to its first passing candidate
    lint_limit: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(8))

    @property
    def poem_settings(self) -> dict:
        return self.poem.get("settings") or {}

    @property
    def first_candidate_ms(self) -> int | None:
        return min(self.first_ms.values()) if self.first_ms else None

    @property
    def total_passed(self) -> int:
        return sum(self.passed.values())

    def satisfied(self) -> bool:
        return bool(self.slots) and all(self.passed[k] >= int(s.get("want") or 0) for k, s in self.slots.items())

    def halt(self, reason: str) -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            self.stop.set()

    async def call(self, method: str, path: str, args: dict) -> httpx.Response:
        args = {k: v for k, v in args.items() if v not in (None, "")}
        headers = {"X-Composer-Token": self.settings.token}
        url = self.settings.melos_api_url + path
        if method == "GET":
            return await self.http.get(url, params=args, headers=headers, timeout=self.settings.http_timeout)
        return await self.http.post(url, json=args, headers=headers, timeout=self.settings.http_timeout)

    async def lint(self, greek: str, slot: dict | None = None) -> dict:
        """POST /api/composer/check against the slot's own open slots. Any transport or HTTP failure counts as a
        blocking failure."""
        s, slot = self.poem_settings, slot or {}
        body = {"greek": greek, "metre": s.get("metre"), "dialect": s.get("dialect"), "author": s.get("author"),
                "remaining_template": slot.get("remaining_template"), "prefix": slot.get("prefix") or None,
                "line_index": slot.get("line_position") or 0, "language": s.get("language") or "grc"}
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


class Bound:
    """The session's tools are built once; each turn points them at its own Ctx."""
    ctx: Ctx | None = None


def _http_tool(bound: Bound, name: str, method: str, path: str, desc: str, schema: dict):
    @tool(name, desc, schema, annotations=None)
    async def handler(args: dict) -> dict:
        ctx = bound.ctx
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


async def _propose(ctx: Ctx, args: dict) -> dict:
    if ctx.stop.is_set():
        return text("Stop: this request is complete. Reply with the single word: done.")
    ctx.rounds += 1
    batch, dupes, unknown = [], 0, []
    for c in (args.get("candidates") or [])[:16]:
        if not isinstance(c, dict):
            continue
        g = norm(c.get("greek", ""))
        key = c.get("slot") or (ctx.primary if ctx.slots else None)
        if ctx.slots and key not in ctx.slots:
            unknown.append(f"- {g}: unknown slot {key!r}; use one of {', '.join(ctx.slots)}")
            continue
        if ctx.mode == "words" and (len(g.split()) > WORDS_MAX or "\n" in g):   # next words: short, one line
            ctx.rejected_count += 1
            ctx.rejected["words_length"] += 1
            unknown.append(f"- [{key}] {g}: too long for next words (one to three words, no line break)")
            continue
        seen = ctx.seen.setdefault(key, set())
        if not g or g in seen:
            dupes += 1
            continue
        seen.add(g)
        batch.append((key, {**c, "greek": g}))
    await ctx.emit({"type": "tool", "name": "propose_candidates", "summary": f"round {ctx.rounds}: {len(batch)} candidates"})

    async def one(key, cand):
        return key, cand, await ctx.lint(cand["greek"], ctx.slots.get(key))

    lines, accepted = list(unknown), 0
    for job in asyncio.as_completed([one(k, c) for k, c in batch]):    # each passing candidate goes out at once
        key, cand, res = await job
        if res["pass"]:
            accepted += 1
            ctx.passed[key] += 1
            ctx.first_ms.setdefault(key, round((time.monotonic() - ctx.started) * 1000))
            slot = ctx.slots.get(key) or {}
            await ctx.emit({"type": "candidate", "greek": cand["greek"], "english_span": cand.get("english_span", ""),
                            "slots": cand.get("slots", ""), "evidence": list(cand.get("evidence") or []),
                            "checks": res["checks"], "scansion": res.get("scansion"), "mode": ctx.mode,
                            **({"slot_key": key, "line_position": slot.get("line_position"),
                                "prefix": slot.get("prefix", "")} if key else {})})
        else:
            ctx.rejected_count += 1
            fails = _failures(res["checks"]) or [{"id": "fail", "detail": "lint did not pass"}]
            ctx.rejected.update(f["id"] for f in fails)
            lines.append(f"- [{key}] {cand['greek']}: " if key else f"- {cand['greek']}: ")
            lines[-1] += "; ".join(f"{f['id']} {f.get('detail', '')}".strip() for f in fails)
    msg = [f"Round {ctx.rounds}: {accepted} passed, {len(lines)} rejected" + (f", {dupes} duplicates skipped" if dupes else "") + "."]
    if ctx.slots:
        msg.append("Passed so far: " + ", ".join(f"{k} {ctx.passed[k]}/{s.get('want')}" for k, s in ctx.slots.items()) + ".")
    if lines:
        msg += ["Rejected (do not repeat these mistakes):", *lines]
    if ctx.slots and (ctx.satisfied() or ctx.rounds >= ctx.max_rounds):
        ctx.halt("enough" if ctx.satisfied() else "rounds")
        msg.append("Stop now: " + ("enough candidates." if ctx.stop_reason == "enough" else "round limit reached.")
                   + " Reply with the single word: done.")
    elif ctx.slots:
        msg.append("Continue: research briefly if needed, then propose again for the slots still short.")
    return text("\n".join(msg))


def build_tools(bound: Bound) -> list:
    tools = [_http_tool(bound, n, *spec) for n, spec in HTTP_TOOLS.items()]

    @tool("check_candidate", "Run the whole lint bank (metre, form exists, dialect, attestation) on one Greek phrase "
          "for this poem's settings, without proposing it. slot: the slot key to check against (default: the first).",
          _schema(("greek",), greek=GREEK, slot=_s("string", "Slot key")))
    async def check_candidate(args: dict) -> dict:
        ctx = bound.ctx
        await ctx.emit({"type": "tool", "name": "check_candidate", "summary": args.get("greek", "")[:200]})
        slot = ctx.slots.get(args.get("slot") or ctx.primary or "")
        return text(await ctx.lint(norm(args.get("greek", "")), slot), ctx.settings.tool_result_chars)

    @tool("propose_candidates", "Offer candidates to the owner. Each is linted at once against its own slot; those "
          "that pass are shown immediately, the failures come back to you with reasons. Call it early and often, "
          "in small batches (4-8), rather than once at the end.",
          _schema(("candidates",), candidates={"type": "array", "items": CANDIDATE, "maxItems": 16}))
    async def propose_candidates(args: dict) -> dict:
        return await _propose(bound.ctx, args)

    return [*tools, check_candidate, propose_candidates]


def server_for(bound: Bound):
    tools = build_tools(bound)
    return create_sdk_mcp_server(SERVER, "1.0.0", tools), tools


def tool_names() -> list[str]:
    return [f"mcp__{SERVER}__{n}" for n in [*HTTP_TOOLS, "check_candidate", "propose_candidates"]]
