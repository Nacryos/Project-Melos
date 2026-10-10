"""HTTP service for melos-api: POST /chat and /pool (SSE), POST /backtranslate (JSON). Token-gated."""
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
from .melos import Ctx, server_for
from .runner import Job, Outcome, SdkRunner
from .settings import EFFORT, MODEL, Settings, cost_usd


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


class PoolRequest(BaseModel):
    poem: Poem
    slot: Slot
    n: int = Field(8, ge=1, le=40)


class BacktranslateRequest(BaseModel):
    greek: str = Field(min_length=1, max_length=5_000)
    dialect: str | None = None


def sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def create_app(settings: Settings | None = None, runner=None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    runner = runner or SdkRunner(settings)
    http: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        http["client"] = httpx.AsyncClient(transport=transport)
        try:
            yield
        finally:
            await http["client"].aclose()

    app = FastAPI(title="melos-composer-agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

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

    async def finish(endpoint: str, outcome: Outcome, t0: float, poem_id=None, **extra) -> dict:
        cost = cost_usd(outcome.usage)
        log_usage({"ts": datetime.now(timezone.utc).isoformat(), "endpoint": endpoint, "poem_id": poem_id,
                   "model": MODEL, "effort": EFFORT, "usage": outcome.usage, "cost_usd": cost,
                   "sdk_cost_usd": outcome.sdk_cost_usd, "ms": round((time.monotonic() - t0) * 1000),
                   "stop_reason": outcome.stop_reason, "terminal_reason": outcome.terminal_reason,
                   "error": outcome.error, **extra})
        return {"type": "done", "usage": outcome.usage, "cost_usd": cost}

    async def safe_run(job: Job) -> Outcome:
        try:
            return await runner.run(job)
        except Exception as exc:  # the CLI died, the key is missing, ...; never leak details beyond the type
            return Outcome(error=f"agent failed: {type(exc).__name__}")

    def stream(endpoint: str, poem: Poem, build) -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        ctx = Ctx(http=http["client"], emit=emit, settings=settings, poem=poem.model_dump())
        job = build(ctx)

        async def work():
            t0 = time.monotonic()
            outcome = await safe_run(job)
            if outcome.error:
                await emit({"type": "error", "message": outcome.error})
            extra = {}
            if ctx.target:
                await emit({"type": "rejected", "count": ctx.rejected_count, "reasons": dict(ctx.rejected)})
                extra = {"passed": ctx.passed, "rejected": ctx.rejected_count, "rounds": ctx.rounds}
            await emit(await finish(endpoint, outcome, t0, poem.poem_id, **extra))
            await queue.put(None)

        async def body():
            task = asyncio.create_task(work())
            try:
                while (event := await queue.get()) is not None:
                    yield sse(event)
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(body(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/chat", dependencies=[Depends(require_token)])
    async def chat(req: ChatRequest):
        def build(ctx: Ctx) -> Job:
            server, tools = server_for(ctx)
            return Job(system=prompts.SYSTEM, prompt=prompts.chat_prompt(ctx.poem, req.thread, req.message),
                       emit=ctx.emit, server=server, tools=tools, seconds=settings.chat_seconds, stream_text=True)
        return stream("chat", req.poem, build)

    @app.post("/pool", dependencies=[Depends(require_token)])
    async def pool(req: PoolRequest):
        def build(ctx: Ctx) -> Job:
            ctx.slot, ctx.target, ctx.max_rounds = req.slot.model_dump(), req.n, settings.pool_rounds
            server, tools = server_for(ctx)
            return Job(system=prompts.SYSTEM, prompt=prompts.pool_prompt(ctx.poem, ctx.slot, req.n), emit=ctx.emit,
                       server=server, tools=tools, stop=ctx.stop, seconds=settings.pool_seconds, max_turns=24)
        return stream("pool", req.poem, build)

    @app.post("/backtranslate", dependencies=[Depends(require_token)])
    async def backtranslate(req: BacktranslateRequest):
        async def ignore(_event: dict) -> None:
            return None
        t0 = time.monotonic()
        prompt = f"Dialect: {req.dialect or 'unspecified'}\nGreek:\n{req.greek}"
        outcome = await safe_run(Job(system=prompts.BACKTRANSLATE_SYSTEM, prompt=prompt, emit=ignore,
                                     seconds=settings.chat_seconds, max_turns=1))
        done = await finish("backtranslate", outcome, t0)
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
