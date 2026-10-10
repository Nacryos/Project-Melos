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
  POST /api/composer/poems/{id}/pool                {line_id?, caret, prefix, remaining_template, n ≤ 40}: agent
                                                    /pool {poem, slot, n}; SSE relayed; each `candidate` stored
  POST /api/composer/backtranslate                  {greek, dialect}: JSON
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
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


def _relay(client, response, on_event, on_end):
    """Pass the agent's bytes through unchanged; parse a copy for storage. ``on_end(completed)`` always runs."""
    parser = SSEParser()

    async def body():
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

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


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


def slot_key(poem: dict, line_id, caret: dict, prefix: str) -> str:
    """Pool key: (poem, line, caret context, settings), PRD §4."""
    raw = json.dumps([poem["poem_id"], line_id, caret, prefix, poem["settings"]], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


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
    key = slot_key(context, body.line_id, caret, body.prefix + "|" + (body.remaining_template or ""))
    slot = {"line_position": caret.get("line_position"), "caret": caret.get("char_offset"), "prefix": body.prefix,
            "remaining_template": body.remaining_template, "line_id": body.line_id, "slot_key": key}
    opened = await _open_stream("/pool", {"poem": context, "slot": slot, "n": body.n})
    if isinstance(opened, JSONResponse):
        return opened

    def on_event(event, data):
        if event == "candidate":
            checks = data.get("checks") if isinstance(data, dict) else None
            store.add_pool(poem_id, key, data, checks)

    return _relay(*opened, on_event, lambda completed: None)


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
