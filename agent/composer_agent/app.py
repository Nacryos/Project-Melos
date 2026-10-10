"""HTTP service for melos-api: POST /chat, /pool and /warm (SSE; a persistent research session per poem, parallel
forked fills per slot), POST /backtranslate (JSON). Token-gated."""
from __future__ import annotations

import asyncio
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import prompts
from .fills import Fill, Fills
from .melos import Ctx
from .runner import Job, Outcome, SdkRunner
from .sessions import Busy, Session, Sessions, Turn, default_factory
from .settings import MODEL, MODES, Settings, cost_usd


class Poem(BaseModel):
    model_config = {"extra": "allow"}
    poem_id: str | int | None = None
    title: str = ""
    settings: dict = Field(default_factory=dict)
    english: str = Field("", max_length=50_000)
    lines: list[dict] = Field(default_factory=list, max_length=500)
    caret: dict = Field(default_factory=dict)


class ChatRequest(BaseModel):
    poem: Poem
    thread: list[dict] = Field(default_factory=list)
    message: str = Field(min_length=1, max_length=20_000)


class Slot(BaseModel):
    model_config = {"extra": "allow"}
    line_position: int | None = None
    caret: int | None = None
    prefix: str = ""
    remaining_template: str | None = None
    slot_key: str | None = Field(None, max_length=64)


class PoolRequest(BaseModel):
    poem: Poem
    slot: Slot
    ahead: list[Slot] = Field(default_factory=list, max_length=8)
    n: int = Field(8, ge=1, le=40)
    mode: str = Field("line", pattern="^(line|words)$")


class WarmRequest(BaseModel):
    poem: Poem
    slot: Slot | None = None
    ahead: list[Slot] = Field(default_factory=list, max_length=8)
    n: int = Field(8, ge=1, le=40)


class BacktranslateRequest(BaseModel):
    greek: str = Field(min_length=1, max_length=5_000)
    dialect: str | None = None


def sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def session_key(poem: Poem, kind: str) -> str:
    s = poem.settings or {}
    return f"{poem.poem_id}|{kind}|{s.get('author') or ''}/{s.get('metre') or ''}/{s.get('dialect') or ''}"


def create_app(settings: Settings | None = None, runner=None, transport: httpx.AsyncBaseTransport | None = None,
               client_factory=None) -> FastAPI:
    settings = settings or Settings()
    runner = runner or SdkRunner(settings)
    factory = client_factory or default_factory
    sessions = Sessions(settings, factory)
    http: dict = {}
    fills = Fills(settings, factory, prompts.SYSTEM, lambda: http["client"])

    async def reaper():
        while True:
            await asyncio.sleep(max(5.0, min(60.0, settings.session_idle_seconds / 4)))
            await sessions.reap()

    @asynccontextmanager
    async def lifespan(_app):
        http["client"] = httpx.AsyncClient(transport=transport)
        reap_task = asyncio.create_task(reaper())
        try:
            yield
        finally:
            reap_task.cancel()
            await fills.close_all()
            await sessions.close_all()
            await http["client"].aclose()

    app = FastAPI(title="melos-composer-agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions, app.state.fills = sessions, fills

    def require_token(x_composer_token: str = Header("")):
        if not settings.token or not hmac.compare_digest(x_composer_token.encode(), settings.token.encode()):
            raise HTTPException(401, "unauthorized")

    def log_usage(record: dict) -> None:
        try:
            settings.state_dir.mkdir(parents=True, exist_ok=True)
            with open(settings.state_dir / "usage.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def finish_record(endpoint: str, outcome: Outcome, ms: int, poem_id=None, effort: str | None = None, **extra) -> dict:
        cost = cost_usd(outcome.usage)
        log_usage({"ts": datetime.now(timezone.utc).isoformat(), "endpoint": endpoint, "poem_id": poem_id,
                   "model": MODEL, "effort": effort or settings.effort_for(endpoint), "usage": outcome.usage, "cost_usd": cost,
                   "sdk_usage": outcome.sdk_usage, "sdk_cost_usd": outcome.sdk_cost_usd, "ms": ms,
                   "stop_reason": outcome.stop_reason, "terminal_reason": outcome.terminal_reason,
                   "error": outcome.error, **extra})
        return {"type": "done", "usage": outcome.usage, "cost_usd": cost}

    async def safe_run(job: Job) -> Outcome:
        try:
            return await runner.run(job)
        except Exception as exc:  # the CLI died, the key is missing, ...; never leak details beyond the type
            return Outcome(error=f"agent failed: {type(exc).__name__}")

    def stream(body):
        return StreamingResponse(body, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def respond(turn: Turn, joined: bool = False) -> StreamingResponse:
        q = turn.subscribe(joined)

        async def body():
            try:
                while (event := await q.get()) is not None:
                    yield sse(event)
            finally:
                turn.unsubscribe(q)      # the turn itself runs on (bounded): its candidates still reach melos-api's store

        return stream(body())

    def respond_fills(members: list[tuple[Fill, bool]], t0: float, skipped: list) -> StreamingResponse:
        """One SSE stream over several fills: every event of each (replayed candidates for joined ones), each
        fill's end as a ``fill`` event, then one ``done`` with the cost of the fills this request started."""
        subs = [(f, joined, f.turn.subscribe(joined)) for f, joined in members]   # subscribed now, not when read

        async def body():
            if not members:
                yield sse({"type": "done", "usage": {}, "cost_usd": 0, "terminal_reason": "already_filled",
                           "skipped": skipped})
                return
            q: asyncio.Queue = asyncio.Queue()

            async def pump(f, fq, joined):
                while (ev := await fq.get()) is not None:
                    if ev.get("type") == "done":
                        ev = {**ev, "type": "fill", "slot_key": f.slot_key, "mode": f.mode, "cold": f.cold}
                        if joined:
                            ev["shared"] = True
                    elif ev.get("type") in ("rejected", "error"):
                        ev = {**ev, "slot_key": f.slot_key, "mode": f.mode}
                    q.put_nowait(ev)
                q.put_nowait({"type": "_end"})
            tasks = [asyncio.ensure_future(pump(f, fq, joined)) for f, joined, fq in subs]
            pending, cost, usage = len(members), 0.0, {}
            try:
                while pending:
                    ev = await q.get()
                    if ev.get("type") == "_end":
                        pending -= 1
                        continue
                    if ev.get("type") == "fill" and not ev.get("shared"):
                        cost += float(ev.get("cost_usd") or 0)
                        for k, v in (ev.get("usage") or {}).items():
                            usage[k] = usage.get(k, 0) + int(v or 0)
                    yield sse(ev)
                yield sse({"type": "done", "usage": usage, "cost_usd": round(cost, 6), "fills": len(members),
                           "skipped": skipped, "ms": round((time.monotonic() - t0) * 1000)})
            finally:
                for f, _, fq in subs:
                    f.turn.unsubscribe(fq)
                for t in tasks:
                    t.cancel()

        return stream(body())

    def finisher(endpoint: str, poem: Poem, t0: float):
        async def finish(turn: Turn, outcome: Outcome, info: dict) -> None:
            ctx = turn.ctx
            if outcome.error:
                await turn.emit({"type": "error", "message": outcome.error})
            extra = {"session_turn": info.get("session_turn"), "first_turn": info.get("first"),
                     "turn_ms": info.get("ms"), "wait_ms": info.get("wait_ms", round((time.monotonic() - t0) * 1000) - (info.get("ms") or 0))}
            effort = info.get("effort")
            if ctx.slots:
                await turn.emit({"type": "rejected", "count": ctx.rejected_count, "reasons": dict(ctx.rejected)})
                extra.update(passed=dict(ctx.passed), rejected=ctx.rejected_count, rounds=ctx.rounds,
                             stop=ctx.stop_reason, first_candidate_ms=ctx.first_candidate_ms,
                             first_ms_by_slot=dict(ctx.first_ms), mode=ctx.mode,
                             **{k: info[k] for k in ("slot_key", "cold", "urgent") if k in info})
            await turn.emit(finish_record(endpoint, outcome, round((time.monotonic() - t0) * 1000), poem.poem_id,
                                          effort, **extra))
        return finish

    def new_ctx(poem: Poem, turn_holder: list) -> Ctx:
        async def emit(event: dict) -> None:
            await turn_holder[0].emit(event)
        return Ctx(http=http["client"], emit=emit, settings=settings, poem=poem.model_dump())

    def slot_map(slot: Slot | None, ahead: list[Slot], n: int) -> tuple[dict, str | None]:
        slots: dict = {}
        for i, sl in enumerate(([slot] if slot else []) + list(ahead)):
            key = sl.slot_key or f"s{i}"
            if key in slots:
                continue
            slots[key] = {**sl.model_dump(exclude={"slot_key"}), "want": n if (slot and i == 0) else settings.pool_ahead_n}
        return slots, (next(iter(slots)) if slot and slots else None)

    def research(s: Session, poem: Poem, t0: float) -> tuple[Turn | None, bool]:
        """The poem's research turn (the session's first and only turn, warm effort): (the turn, started now).
        The running one if it runs; None when it is over."""
        running = s.running()
        if running:
            return running, False
        if s.turns or s.settled.is_set():
            return None, False
        holder: list = []
        ctx = new_ctx(poem, holder)
        turn = Turn(kind="warm", ctx=ctx)
        holder.append(turn)
        sessions.start(s, turn, lambda first, changed: prompts.pool_prompt(ctx.poem, {}, s.seen, first, changed),
                       lambda first: settings.warm_seconds, finisher("warm", poem, t0))
        return turn, True

    def pool_turn(endpoint: str, poem: Poem, slot: Slot | None, ahead: list[Slot], n: int, mode: str = "line"):
        t0 = time.monotonic()
        try:
            s = sessions.get(session_key(poem, "pool"), "pool", prompts.SYSTEM)
        except Busy:
            raise HTTPException(503, "agent busy: too many open sessions")
        slots, primary = slot_map(slot, ahead, n)
        turn, started = research(s, poem, t0)
        if not slots:                                    # /warm without a slot: research only
            if turn:
                return respond(turn, joined=not started)
            done = Turn(kind="warm", ctx=new_ctx(poem, [None]))
            done.events.append({"type": "done", "usage": {}, "cost_usd": 0, "terminal_reason": "already_warm"})
            done.close()
            return respond(done, joined=True)
        poem_dict = poem.model_dump()
        wanted = [(key, mode if key == primary else "line", sl) for key, sl in slots.items()]
        if endpoint == "warm" and primary and mode == "line":       # a warm-up also readies next words for the slot
            wanted.append((primary, "words", {**slots[primary], "want": settings.words_n}))
        members, skipped = [], []
        keep = set(slots)
        for key, fill_mode, sl in wanted:
            if endpoint == "warm" and s.passed[(key, fill_mode)] >= int(sl.get("want") or 0):
                skipped.append({"slot_key": key, "mode": fill_mode})
                continue
            f = fills.running_for(s, key, fill_mode)
            joined = f is not None
            if not f:
                f = fills.start(s, key, sl, fill_mode, poem_dict, endpoint == "pool" and key == primary, keep,
                                finisher("fill", poem, t0))
            members.append((f, joined))
        return respond_fills(members, t0, skipped)

    @app.post("/chat", dependencies=[Depends(require_token)])
    async def chat(req: ChatRequest):
        t0 = time.monotonic()
        try:
            s = sessions.get(session_key(req.poem, "chat"), "chat", prompts.SYSTEM)
        except Busy:
            raise HTTPException(503, "agent busy: too many open sessions")
        holder: list = []
        ctx = new_ctx(req.poem, holder)
        turn = Turn(kind="chat", ctx=ctx)
        holder.append(turn)
        resp = respond(turn)
        sessions.start(s, turn, lambda first, changed: prompts.chat_prompt(ctx.poem, req.thread, req.message, first, changed),
                       lambda first: settings.chat_seconds, finisher("chat", req.poem, t0))
        return resp

    @app.post("/pool", dependencies=[Depends(require_token)])
    async def pool(req: PoolRequest):
        return pool_turn("pool", req.poem, req.slot, req.ahead, req.n, req.mode)

    @app.post("/warm", dependencies=[Depends(require_token)])
    async def warm(req: WarmRequest):
        """Start (or join) the poem's research and fill the stanza (line mode, plus next words for the slot)."""
        return pool_turn("warm", req.poem, req.slot, req.ahead, req.n)

    @app.post("/backtranslate", dependencies=[Depends(require_token)])
    async def backtranslate(req: BacktranslateRequest):
        async def ignore(_event: dict) -> None:
            return None
        t0 = time.monotonic()
        prompt = f"Dialect: {req.dialect or 'unspecified'}\nGreek:\n{req.greek}"
        outcome = await safe_run(Job(system=prompts.BACKTRANSLATE_SYSTEM, prompt=prompt, emit=ignore,
                                     seconds=settings.chat_seconds, max_turns=1))
        done = finish_record("backtranslate", outcome, round((time.monotonic() - t0) * 1000), effort=settings.chat_effort)
        if outcome.error or not outcome.text.strip():
            raise HTTPException(502, outcome.error or "empty translation")
        return {"english": outcome.text.strip(), "usage": done["usage"], "cost_usd": done["cost_usd"]}

    return app


def main() -> None:
    import os
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("COMPOSER_AGENT_HOST", "0.0.0.0"),
                port=int(os.environ.get("COMPOSER_AGENT_PORT", "8800")), log_level="info", access_log=False)


if __name__ == "__main__":
    main()
