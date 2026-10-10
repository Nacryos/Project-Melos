"""Pool fills: one short-lived session per (slot, mode), forked from the poem's research session.

A fill is a Claude Agent SDK client started with ``resume=<research session id>, fork_session=True`` at the pool
effort (settings.pool_effort): it begins with the whole research conversation (read from the prompt cache) and
proposes for one slot in one mode (``line``: whole-line continuations; ``words``: next words, 1-3 words each),
then disconnects. Fills of one poem run in parallel, at most COMPOSER_POOL_PARALLEL at once over the whole service
(each is a CLI process); waiting fills are served urgent first (the slot the owner is at), then in arrival order.
When no permit is free an urgent fill preempts the oldest running fill for a slot the request does not name.

A fill asked for while the research turn still runs (the owner is already typing) starts *cold* when
COMPOSER_COLD_FILLS is on: a fresh session with the poem context and no research, at the pool effort. Fills that
are not urgent (the rest of the stanza, warm-ups) wait for the research and fork from it.

Candidates stream the moment they pass the lint (melos.py, unchanged gate); each carries its slot key and mode.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from . import prompts
from .melos import Bound, Ctx, server_for
from .runner import Outcome, drive, sdk_options
from .sessions import Session, Turn


class Gate:
    """A counting permit with priority: ``acquire(urgent)`` waits until one of ``limit`` permits is free; urgent
    waiters go first, then arrival order."""

    def __init__(self, limit: int):
        self.limit, self.running, self.seq = max(1, int(limit)), 0, 0
        self.waiters: list[tuple[int, int, asyncio.Future]] = []

    @property
    def free(self) -> bool:
        return self.running < self.limit

    def _dispatch(self) -> None:
        while self.running < self.limit and self.waiters:
            self.waiters.sort(key=lambda w: (w[0], w[1]))
            _, _, fut = self.waiters.pop(0)
            if not fut.done():
                self.running += 1
                fut.set_result(None)

    async def acquire(self, urgent: bool = False) -> None:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.seq += 1
        self.waiters.append((0 if urgent else 1, self.seq, fut))
        self._dispatch()
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()
            else:
                self.waiters = [w for w in self.waiters if w[2] is not fut]
            raise

    def release(self) -> None:
        self.running = max(0, self.running - 1)
        self._dispatch()


class Fill:
    def __init__(self, session: Session, slot_key: str, mode: str, turn: Turn, urgent: bool):
        self.session, self.slot_key, self.mode, self.turn, self.urgent = session, slot_key, mode, turn, urgent
        self.created = time.monotonic()
        self.cold: bool | None = None
        self.started: float | None = None       # when it got its permit

    @property
    def key(self) -> tuple:
        return (self.session.key, self.slot_key, self.mode)

    def running(self) -> bool:
        return not self.turn.finished.is_set()


class Fills:
    def __init__(self, settings, factory: Callable, system: str, http: Callable[[], object]):
        self.settings, self.factory, self.system, self.http = settings, factory, system, http
        self.gate = Gate(settings.pool_parallel)
        self.active: dict[tuple, Fill] = {}
        self.tasks: set = set()

    def running_for(self, session: Session, slot_key: str, mode: str) -> Fill | None:
        f = self.active.get((session.key, slot_key, mode))
        return f if f and f.running() else None

    def for_session(self, session: Session) -> list[Fill]:
        return [f for f in self.active.values() if f.session is session and f.running()]

    def make_room(self, session: Session, keep: set) -> Fill | None:
        """No permit free: halt the oldest running fill of this session for a slot not in ``keep`` (the owner moved
        on). Returns the preempted fill, if any."""
        if self.gate.free:
            return None
        victims = sorted((f for f in self.for_session(session) if f.slot_key not in keep and f.started is not None),
                         key=lambda f: f.started)
        if not victims:
            return None
        victims[0].turn.ctx.halt("preempted")
        return victims[0]

    def start(self, session: Session, slot_key: str, slot: dict, mode: str, poem: dict, urgent: bool,
              keep: set, finish: Callable[[Turn, Outcome, dict], Awaitable[None]]) -> Fill:
        """Queue a fill for ``slot`` (a slot dict with ``want``) in ``mode``; events on its Turn."""
        settings = self.settings
        holder: list = []

        async def emit(event: dict) -> None:
            await holder[0].turn.emit(event)
        ctx = Ctx(http=self.http(), emit=emit, settings=settings, poem=dict(poem),
                  slots={slot_key: dict(slot)}, primary=slot_key, mode=mode,
                  max_rounds=settings.words_rounds if mode == "words" else settings.pool_rounds, seen=session.seen)
        turn = Turn(kind="fill", ctx=ctx)
        fill = Fill(session, slot_key, mode, turn, urgent)
        holder.append(fill)
        self.active[fill.key] = fill
        session.fills_active += 1
        session.last_used = time.monotonic()
        if urgent:
            self.make_room(session, keep)

        async def run():
            info: dict = {"mode": mode, "slot_key": slot_key, "urgent": urgent, "effort": settings.pool_effort}
            t0 = time.monotonic()
            out = Outcome()
            got_permit = False
            try:
                if not session.settled.is_set() and not (urgent and settings.cold_fills):
                    stop = asyncio.ensure_future(ctx.stop.wait())
                    settled = asyncio.ensure_future(session.settled.wait())
                    try:
                        await asyncio.wait({stop, settled}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        stop.cancel()
                        settled.cancel()
                fill.cold = not session.researched
                info["cold"] = fill.cold
                if ctx.stop.is_set():
                    out = Outcome(terminal_reason=ctx.stop_reason or "stop")
                else:
                    await self.gate.acquire(urgent)
                    got_permit = True
                    fill.started = time.monotonic()
                    info["wait_ms"] = round((fill.started - t0) * 1000)
                    if ctx.stop.is_set():
                        out = Outcome(terminal_reason=ctx.stop_reason or "stop")
                    else:
                        english = poem.get("english") or ""
                        changed = session.english is not None and session.english != english
                        bound = Bound()
                        bound.ctx = ctx
                        server, tools = server_for(bound)
                        resume = None if fill.cold else session.session_id
                        client = self.factory(sdk_options(settings, self.system, server, effort=settings.pool_effort,
                                                          resume=resume), tools)
                        await client.connect()
                        try:
                            prompt = prompts.fill_prompt(ctx.poem, ctx.slots, session.seen, mode, fill.cold, changed)
                            seconds = settings.words_seconds if mode == "words" else settings.pool_seconds
                            out = await drive(client, prompt, ctx.emit, False, ctx.stop, seconds,
                                              lambda: 0.0 if ctx.stop_reason == "preempted" else settings.stop_grace_seconds)
                        finally:
                            try:
                                await client.disconnect()
                            except Exception:  # noqa: BLE001 - the CLI may already be gone
                                pass
                        session.passed.update({(k, mode): v for k, v in ctx.passed.items()})
            except Exception as exc:  # noqa: BLE001 - the CLI died, the key is missing, ...
                out = Outcome(error=f"agent failed: {type(exc).__name__}")
            finally:
                if got_permit:
                    self.gate.release()
                session.fills_active -= 1
                session.last_used = time.monotonic()
                info["ms"] = round((time.monotonic() - t0) * 1000)
                if self.active.get(fill.key) is fill:
                    del self.active[fill.key]
            try:
                await finish(turn, out, info)
            finally:
                turn.close()

        task = asyncio.ensure_future(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return fill

    async def close_all(self) -> None:
        for f in list(self.active.values()):
            f.turn.ctx.halt("shutdown")
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=20)

