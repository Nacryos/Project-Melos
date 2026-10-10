"""Release W: the owner's composer API (PRD docs/prd/composer-agent.md §6). Owner-only: signed out, every path is
404 (backend/composer_access.py; the release-T guard answers before routing, each route checks again).

Store (backend/composer_store.py):
  GET  /composer, /composer.html                    the page
  GET  /api/composer/poems                          poems (?archived=true to include archived)
  POST /api/composer/poems                          {title?, settings?, english?}
  GET  /api/composer/poems/{id}                     one poem
  PATCH /api/composer/poems/{id}                    {title?, settings?, english?, archived?}
  GET  /api/composer/poems/{id}/full                poem + lines + every version + last 200 chat rows
  POST /api/composer/poems/{id}/lines               {position?, greek?, source?, note?}: a line at position
  PATCH /api/composer/lines/{id}                    {position?, current_version_id?}
  POST /api/composer/lines/{id}/versions            {greek, source?, note?, make_current?}: scanned and linted now
  PATCH /api/composer/versions/{id}                 {archived?, make_current?, back_translation?}
  GET  /api/composer/poems/{id}/pool                stored pool candidates (?slot_key=)
Lint:
  POST /api/composer/check                          the lint bank (owner, or the agent with its internal token):
      {greek, metre?, dialect?, author?, remaining_template?, prefix?, line_index?} → {pass, scansion, checks[]}.
      The agent's shape (docs/composer/agent.md): greek = the candidate continuation alone (without the typed
      prefix), remaining_template = the metrical slots still open at the caret (template symbols - u x F D R X).
      The continuation must fill a prefix of those slots (all of them if it runs on into the next line; later
      lines are fitted to the metre's next templates). Without remaining_template a set metre fits whole lines.
      ``prefix`` (optional) is the line before the caret, scanned with the candidate for word-boundary
      quantities. metre "auto"/"none" counts as no metre; for the agent (internal token) a check with neither
      remaining_template nor a named metre fails L7 (template "missing"), since nothing could be rejected.
      Budget: MELOS_COMPOSER_CHECK_BUDGET_MS (default 1500); per-word lookups run concurrently, cached per
      (form, dialect); a word not resolved in time fails L1/L2 ("unresolved ... (timeout)"), never passes.
Agent service (MELOS_COMPOSER_AGENT_URL, header X-Composer-Token); unreachable → 503 {"agent": "unavailable"}:
  POST /api/composer/poems/{id}/chat                {message, caret?}: agent /chat {poem, thread, message}; SSE relayed unchanged; the final assistant
                                                    message and the tool trace are stored when the stream ends
  POST /api/composer/poems/{id}/pool                {line_id?, caret, prefix, remaining_template, n ≤ 40, ahead_lines?}:
                                                    agent /pool {poem, slot, ahead, n}: the slot plus the empty lines
                                                    after it (the rest of the stanza); SSE relayed; every `candidate`
                                                    stored under its own slot_key, read to the end even if the page
                                                    stops listening
  POST /api/composer/poems/{id}/warm                {line_position?, n?}: 202; agent /warm read in the background
                                                    (research once + a stanza batch), candidates stored per slot
  GET  /api/composer/poems/{id}/slot-key            ?line_position=&prefix= → the slot key (formula: slot_key())
  POST /api/composer/backtranslate                  {greek, dialect}: JSON
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import composer_store as store
from .composer_access import require_owner, require_owner_or_agent
from .composer_lint import TEMPLATE_SYMBOLS

log = logging.getLogger("melos.composer")
ROOT = Path(__file__).resolve().parents[1]
THREAD_ROWS = 40
MAX_LINE = 2000

router = APIRouter()
owner = [Depends(require_owner)]


def _store_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except store.StoreError as exc:
        raise HTTPException(exc.status, exc.message) from exc


# ------------------------------------------------------------------------------------------------ page

@router.get("/composer", include_in_schema=False, dependencies=owner)
@router.get("/composer.html", include_in_schema=False, dependencies=owner)
def composer_page():
    return FileResponse(ROOT / "composer.html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


# ------------------------------------------------------------------------------------------------ poems, lines, versions

class PoemIn(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field("", max_length=300)
    settings: dict = Field(default_factory=dict)
    english: str = Field("", max_length=50_000)


class PoemPatch(BaseModel):
    model_config = {"extra": "forbid"}
    title: str | None = Field(None, max_length=300)
    settings: dict | None = None
    english: str | None = Field(None, max_length=50_000)
    archived: bool | None = None


class LineIn(BaseModel):
    model_config = {"extra": "forbid"}
    position: int | None = Field(None, ge=0, le=100_000)
    greek: str | None = Field(None, max_length=MAX_LINE)
    source: str = "owner"
    note: str = Field("", max_length=2000)


class LinePatch(BaseModel):
    model_config = {"extra": "forbid"}
    position: int | None = Field(None, ge=0, le=100_000)
    current_version_id: int | None = None


class VersionIn(BaseModel):
    model_config = {"extra": "forbid"}
    greek: str = Field(..., min_length=1, max_length=MAX_LINE)
    source: str = "owner"
    note: str = Field("", max_length=2000)
    make_current: bool = True


class VersionPatch(BaseModel):
    model_config = {"extra": "forbid"}
    archived: bool | None = None
    make_current: bool = False
    back_translation: str | None = Field(None, max_length=MAX_LINE * 4)


@router.get("/api/composer/poems", dependencies=owner)
def poems(archived: bool = False):
    return {"poems": store.list_poems(include_archived=archived)}


@router.post("/api/composer/poems", dependencies=owner)
def create_poem(body: PoemIn):
    return store.create_poem(body.title, body.settings, body.english)


@router.get("/api/composer/poems/{poem_id}", dependencies=owner)
def poem(poem_id: int):
    return _store_call(store.get_poem, poem_id)


@router.patch("/api/composer/poems/{poem_id}", dependencies=owner)
def patch_poem(poem_id: int, body: PoemPatch):
    return _store_call(store.update_poem, poem_id, title=body.title, settings=body.settings, english=body.english,
                       archived=body.archived)


@router.get("/api/composer/poems/{poem_id}/full", dependencies=owner)
def poem_full(poem_id: int):
    return _store_call(store.full, poem_id)


def _lint_line(line_id: int, greek: str) -> tuple[dict | None, list | None]:
    """Scansion and checks for a saved line, with the poem's settings and the line's place in the metre."""
    from . import composer_lint
    line = store.get_line(line_id)
    settings = store.get_poem(line["poem_id"])["settings"] or {}
    metre = settings.get("metre") or None
    if metre in ("auto", "none", ""):
        metre = None
    try:
        result = composer_lint.check(greek, metre_name=metre, dialect=settings.get("dialect") or None,
                                     author=settings.get("author") or None, line_index=line["position"])
    except HTTPException as exc:
        return None, [{"id": "settings", "ok": None, "blocking": False, "detail": f"not checked: {exc.detail}"}]
    return {**result["scansion"], "pass": result["pass"], "ms": result["ms"]}, result["checks"]


def _new_version(line_id: int, greek: str, source: str, note: str, make_current: bool) -> dict:
    if source not in store.SOURCES:
        raise HTTPException(422, f"source must be one of {', '.join(store.SOURCES)}")
    _store_call(store.get_line, line_id)
    scansion, checks = _lint_line(line_id, greek)
    return _store_call(store.add_version, line_id, greek, source=source, note=note, scansion=scansion, checks=checks,
                       make_current=make_current)


@router.post("/api/composer/poems/{poem_id}/lines", dependencies=owner)
def add_line(poem_id: int, body: LineIn):
    line = _store_call(store.insert_line, poem_id, body.position)
    if body.greek and body.greek.strip():
        line["version"] = _new_version(line["id"], body.greek, body.source, body.note, True)
        line["current_version_id"] = line["version"]["id"]
    return line


@router.patch("/api/composer/lines/{line_id}", dependencies=owner)
def patch_line(line_id: int, body: LinePatch):
    return _store_call(store.update_line, line_id, position=body.position, current_version_id=body.current_version_id)


@router.post("/api/composer/lines/{line_id}/versions", dependencies=owner)
def add_version(line_id: int, body: VersionIn):
    return _new_version(line_id, body.greek, body.source, body.note, body.make_current)


@router.patch("/api/composer/versions/{version_id}", dependencies=owner)
def patch_version(version_id: int, body: VersionPatch):
    return _store_call(store.update_version, version_id, archived=body.archived, make_current=body.make_current,
                       back_translation=body.back_translation)


@router.get("/api/composer/poems/{poem_id}/pool", dependencies=owner)
def pool(poem_id: int, slot_key: str | None = Query(None, max_length=64)):
    return {"pool": _store_call(store.pool_for, poem_id, slot_key)}


# ------------------------------------------------------------------------------------------------ lint

class CheckIn(BaseModel):
    model_config = {"extra": "forbid"}
    greek: str = Field(..., min_length=1, max_length=MAX_LINE)
    metre: str | None = Field(None, max_length=40)
    dialect: str | None = Field(None, max_length=20)
    author: str | None = Field(None, max_length=80)
    remaining_template: str | None = Field(None, max_length=40)
    prefix: str | None = Field(None, max_length=MAX_LINE)
    line_index: int = Field(0, ge=0, le=10_000)


@router.post("/api/composer/check")
def check(body: CheckIn, caller=Depends(require_owner_or_agent)):
    from . import composer_lint
    metre = body.metre if body.metre not in (None, "", "auto", "none") else None   # poem settings may say auto/none
    # The agent's candidates (pool and chat) must be checked against a concrete template: with metre auto/none and
    # no remaining_template L7 fails for them (the owner's own lines are only scanned).
    return composer_lint.check(body.greek, metre_name=metre, dialect=body.dialect or None,
                               author=body.author, remaining_template=body.remaining_template, prefix=body.prefix,
                               line_index=body.line_index, require_template=caller == "agent")


# ------------------------------------------------------------------------------------------------ agent proxy

def agent_url() -> str:
    return os.environ.get("MELOS_COMPOSER_AGENT_URL", "http://melos-composer-agent:8800").rstrip("/")


# Tests replace this with an httpx transport to a fake agent; None = a real network connection.
_transport = None


def _client():
    import httpx
    from .composer_access import internal_token
    token = internal_token()
    headers = {"X-Composer-Token": token} if token else {}
    return httpx.AsyncClient(base_url=agent_url(), headers=headers, transport=_transport,
                             timeout=httpx.Timeout(connect=3.0, read=float(os.environ.get("MELOS_COMPOSER_AGENT_READ_TIMEOUT", 900)),
                                                   write=30.0, pool=5.0))


def _unavailable(detail: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"agent": "unavailable", "detail": detail},
                        headers={"Cache-Control": "no-store"})


async def _open_stream(path: str, payload: dict):
    """(client, response) of a streaming POST to the agent, or a 503/502 JSONResponse."""
    import httpx
    client = _client()
    try:
        response = await client.send(client.build_request("POST", path, json=payload,
                                                          headers={"Accept": "text/event-stream"}), stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("composer agent unreachable at %s%s: %s", agent_url(), path, exc)
        return _unavailable(f"the agent service is not reachable ({type(exc).__name__})")
    if response.status_code != 200:
        body = (await response.aread())[:2000].decode("utf-8", "replace")
        await response.aclose()
        await client.aclose()
        return JSONResponse(status_code=502, content={"agent": "error", "status": response.status_code, "detail": body})
    return client, response


class SSEParser:
    """Incremental server-sent-events parser: feed bytes, get (event, data) pairs (data JSON-decoded when it is)."""

    def __init__(self):
        self.buffer = b""

    def feed(self, chunk: bytes) -> list[tuple[str, object]]:
        self.buffer += chunk.replace(b"\r\n", b"\n")
        out = []
        while b"\n\n" in self.buffer:
            block, self.buffer = self.buffer.split(b"\n\n", 1)
            event, data = "message", []
            for line in block.decode("utf-8", "replace").split("\n"):
                if line.startswith(":"):
                    continue
                name, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if name == "event":
                    event = value
                elif name == "data":
                    data.append(value)
            if not data and event == "message":
                continue
            text = "\n".join(data)
            try:
                out.append((event, json.loads(text)))
            except ValueError:
                out.append((event, text))
        return out


_background: set = set()   # detached relays (pool, warm): kept referenced until they finish


def _relay(client, response, on_event, on_end, detach: bool = False):
    """Pass the agent's bytes through unchanged; parse a copy for storage. ``on_end(completed)`` always runs.
    ``detach``: a background task reads the agent stream to its end even after the page stops listening (caret
    moved, page closed), so every candidate the agent sends is stored; the page gets the bytes while it listens."""
    parser = SSEParser()

    async def chunks():
        completed = False
        try:
            async for chunk in response.aiter_raw():
                for event, data in parser.feed(chunk):
                    if isinstance(data, dict) and isinstance(data.get("type"), str):
                        event = data["type"]
                    try:
                        on_event(event, data)
                    except Exception:  # noqa: BLE001 - storage must not cut the owner's stream
                        log.exception("composer: could not store agent event %s", event)
                yield chunk
            completed = True
        finally:
            await response.aclose()
            await client.aclose()
            try:
                on_end(completed)
            except Exception:  # noqa: BLE001
                log.exception("composer: could not store the end of an agent stream")

    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    if not detach:
        return StreamingResponse(chunks(), media_type="text/event-stream", headers=headers)
    queue: asyncio.Queue = asyncio.Queue()
    listening = [True]

    async def pump():
        try:
            async for chunk in chunks():
                if listening[0]:
                    queue.put_nowait(chunk)
        except Exception:  # noqa: BLE001 - nobody may be listening: log it
            log.exception("composer: detached agent stream failed")
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(pump())
    _background.add(task)
    task.add_done_callback(_background.discard)

    async def forward():
        try:
            while (chunk := await queue.get()) is not None:
                yield chunk
        finally:
            listening[0] = False
    return StreamingResponse(forward(), media_type="text/event-stream", headers=headers)


class Caret(BaseModel):
    model_config = {"extra": "allow"}
    line_position: int | None = Field(None, ge=0)
    char_offset: int | None = Field(None, ge=0)
    prefix: str | None = Field(None, max_length=MAX_LINE)


class ChatIn(BaseModel):
    model_config = {"extra": "forbid"}
    message: str = Field(..., min_length=1, max_length=20_000)
    caret: Caret | None = None


# The agent service (agent/, docs/composer/agent.md) sends data-only events {"type": text|tool|candidate|rejected|
# error|done, ...}; a named SSE event is read the same way.
TEXT_EVENTS = ("text", "delta", "token")
FINAL_EVENTS = ("final", "assistant")


def _text_of(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for name in ("content", "text", "message", "delta"):
            if isinstance(data.get(name), str):
                return data[name]
    return ""


@router.post("/api/composer/poems/{poem_id}/chat", dependencies=owner)
async def chat(poem_id: int, body: ChatIn):
    context = _store_call(store.agent_context, poem_id, body.caret.model_dump() if body.caret else None)
    thread = [{"role": r["role"], "content": r["content"]} for r in store.recent_chat(poem_id, THREAD_ROWS)]
    opened = await _open_stream("/chat", {"poem": context, "thread": thread, "message": body.message})
    if isinstance(opened, JSONResponse):
        return opened
    store.add_chat(poem_id, "user", body.message)
    parts, final, trace = [], None, []

    def on_event(event, data):
        nonlocal final
        if event in TEXT_EVENTS:
            parts.append(_text_of(data))
        elif event in FINAL_EVENTS and _text_of(data):
            final = _text_of(data)
            if isinstance(data, dict) and data.get("trace"):
                trace.extend(data["trace"] if isinstance(data["trace"], list) else [data["trace"]])
        else:
            trace.append({"event": event, "data": data})

    def on_end(completed):
        content = final if final is not None else "".join(parts)
        if not completed:
            trace.append({"event": "interrupted", "data": "the stream ended before the agent finished"})
        if content or trace:
            store.add_chat(poem_id, "assistant", content, trace)

    return _relay(*opened, on_event, on_end)


class PoolIn(BaseModel):
    model_config = {"extra": "forbid"}
    line_id: int | None = None
    caret: Caret = Field(default_factory=Caret)
    prefix: str = Field("", max_length=MAX_LINE)
    remaining_template: str | None = Field(None, max_length=40)
    n: int = Field(8, ge=1, le=40)
    ahead_lines: int | None = Field(None, ge=0, le=8)


def slot_key(line_position, prefix: str, settings: dict | None) -> str:
    """The pool's slot key, computed the same way by js/composer-core.js ``slotKey`` (docs/composer/ui.md):
    sha256 of "v1|<line position>|<prefix>|<author>|<metre>|<dialect>" (UTF-8), first 32 hex digits. The prefix
    is the line before the slot, NFC, whitespace runs collapsed to one space, trimmed; a missing setting is ""."""
    s = settings or {}
    text = " ".join(unicodedata.normalize("NFC", prefix or "").split())
    raw = "|".join(["v1", str(int(line_position or 0)), text, *(str(s.get(k) or "") for k in ("author", "metre", "dialect"))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _templates(settings: dict | None) -> list[str]:
    from .scansion import metre
    return list(metre.TEMPLATES.get((settings or {}).get("metre") or "", []))


def ahead_slots(context: dict, line_position: int, limit: int | None = None) -> list[dict]:
    """The empty lines after ``line_position`` to fill in the same batch: the rest of the stanza, at least two lines,
    at most MELOS_COMPOSER_AHEAD_LINES (default 3). Lines that already hold Greek are skipped."""
    templates = _templates(context["settings"])
    if not templates:
        return []
    cap = int(os.environ.get("MELOS_COMPOSER_AHEAD_LINES", "3")) if limit is None else limit
    count = min(cap, max(len(templates) - 1 - line_position % len(templates), 2))
    written = {l["position"]: l for l in context.get("lines") or []}
    out = []
    for p in range(line_position + 1, line_position + 1 + count):
        line = written.get(p)
        if line and (line.get("greek") or "").strip():
            continue
        out.append({"line_position": p, "caret": 0, "prefix": "", "remaining_template": templates[p % len(templates)],
                    "line_id": line["line_id"] if line else None, "slot_key": slot_key(p, "", context["settings"])})
    return out


def _pool_store(poem_id: int, keys: set, primary: str):
    def on_event(event, data):
        if event == "candidate" and isinstance(data, dict) and not data.get("replay"):
            key = data.get("slot_key") if data.get("slot_key") in keys else primary
            store.add_pool(poem_id, key, data, data.get("checks"))
    return on_event


@router.post("/api/composer/poems/{poem_id}/pool", dependencies=owner)
async def fill_pool(poem_id: int, body: PoolIn):
    if not body.remaining_template or set(body.remaining_template) - TEMPLATE_SYMBOLS:
        # Without the open slots the lint's metre check cannot reject anything (metre "auto" names no template).
        raise HTTPException(422, {"code": "template_required",
                                  "message": "remaining_template is required: the metrical slots still open at the caret "
                                             "(symbols - u x F D R X); with metre auto or none the metre check cannot "
                                             "reject a candidate"})
    caret = body.caret.model_dump()
    context = _store_call(store.agent_context, poem_id, caret)
    position = caret.get("line_position") or 0
    key = slot_key(position, body.prefix, context["settings"])
    slot = {"line_position": caret.get("line_position"), "caret": caret.get("char_offset"), "prefix": body.prefix,
            "remaining_template": body.remaining_template, "line_id": body.line_id, "slot_key": key}
    ahead = ahead_slots(context, position, body.ahead_lines)
    opened = await _open_stream("/pool", {"poem": context, "slot": slot, "ahead": ahead, "n": body.n})
    if isinstance(opened, JSONResponse):
        return opened
    # Detached: the agent's candidates for every slot are stored even if the page stops listening (caret moved).
    return _relay(*opened, _pool_store(poem_id, {key, *(a["slot_key"] for a in ahead)}, key), lambda completed: None,
                  detach=True)


@router.get("/api/composer/poems/{poem_id}/slot-key", dependencies=owner)
def pool_slot_key(poem_id: int, line_position: int = Query(0, ge=0), prefix: str = Query("", max_length=MAX_LINE)):
    """The server's slot key for (line, prefix) with the poem's current settings (for checking the page's own)."""
    poem = _store_call(store.get_poem, poem_id)
    return {"slot_key": slot_key(line_position, prefix, poem["settings"])}


class WarmIn(BaseModel):
    model_config = {"extra": "forbid"}
    line_position: int | None = Field(None, ge=0, le=100_000)
    n: int = Field(8, ge=1, le=40)


@router.post("/api/composer/poems/{poem_id}/warm", dependencies=owner)
async def warm(poem_id: int, body: WarmIn | None = None):
    """Prefetch: start the agent's research for this poem and a stanza batch from the start of ``line_position``
    (default: the first line without Greek) in the background. Answers at once (202); the candidates land in the
    pool table as they pass the lint (GET .../pool?slot_key=). Nothing is started when every slot already has
    MELOS_COMPOSER_WARM_MIN (default 4) stored candidates."""
    body = body or WarmIn()
    context = _store_call(store.agent_context, poem_id, None)
    templates = _templates(context["settings"])
    if not templates:
        raise HTTPException(422, {"code": "template_required", "message": "warming needs a named metre"})
    written = sorted(l["position"] for l in context["lines"] if (l.get("greek") or "").strip())
    if body.line_position is not None:
        position = body.line_position
    else:
        position = next((p for p in range(len(written) + 1) if p not in set(written)), 0)
    line = next((l for l in context["lines"] if l["position"] == position), None)
    key = slot_key(position, "", context["settings"])
    slot = {"line_position": position, "caret": 0, "prefix": "", "remaining_template": templates[position % len(templates)],
            "line_id": line["line_id"] if line else None, "slot_key": key}
    ahead = ahead_slots(context, position)
    keys = [key, *(a["slot_key"] for a in ahead)]
    least = int(os.environ.get("MELOS_COMPOSER_WARM_MIN", "4"))
    if all(len(store.pool_for(poem_id, k, limit=least)) >= least for k in keys):
        return JSONResponse(status_code=200, content={"started": False, "reason": "filled", "slot_keys": keys})
    context["caret"] = {"line_position": position, "char_offset": 0, "prefix": ""}
    opened = await _open_stream("/warm", {"poem": context, "slot": slot, "ahead": ahead, "n": body.n})
    if isinstance(opened, JSONResponse):
        return opened
    _relay(*opened, _pool_store(poem_id, set(keys), key), lambda completed: None, detach=True)
    return JSONResponse(status_code=202, content={"started": True, "slot_keys": keys})


class BacktranslateIn(BaseModel):
    model_config = {"extra": "forbid"}
    greek: str = Field(..., min_length=1, max_length=MAX_LINE * 4)
    dialect: str | None = Field(None, max_length=20)


@router.post("/api/composer/backtranslate", dependencies=owner)
async def backtranslate(body: BacktranslateIn):
    import httpx
    async with _client() as client:
        try:
            response = await client.post("/backtranslate", json=body.model_dump())
        except httpx.HTTPError as exc:
            log.warning("composer agent unreachable for backtranslate: %s", exc)
            return _unavailable(f"the agent service is not reachable ({type(exc).__name__})")
    if response.status_code != 200:
        return JSONResponse(status_code=502, content={"agent": "error", "status": response.status_code,
                                                      "detail": response.text[:2000]})
    try:
        return response.json()
    except ValueError:
        return JSONResponse(status_code=502, content={"agent": "error", "detail": "the agent did not answer JSON"})
