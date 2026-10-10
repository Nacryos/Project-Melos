"""Persistent agent sessions (docs/composer/agent.md, "Sessions").

One long-lived ClaudeSDKClient per (poem, kind, poem settings): kind "pool" serves /pool and /warm, kind "chat"
serves /chat, so chat and pool never interleave inside one conversation. The first turn of a pool session does the
research; later turns only name new slots and reuse it from context (prompt-cache reads). History is append-only:
every turn is a new query on the same client; nothing earlier is edited or re-sent.

A turn runs as a background task; HTTP responses subscribe to its events. Within a session turns are serialised
by a lock. A /pool or /warm for a slot the running pool turn already covers joins it (earlier candidates are
replayed, marked ``replay``); one for another slot preempts it (the owner moved on). Idle sessions are closed after
COMPOSER_SESSION_IDLE_MINUTES; at most COMPOSER_MAX_SESSIONS exist (the least recently used idle one is closed to
make room, else the request is refused with 503).
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from claude_agent_sdk import ClaudeSDKClient

from .melos import Bound, Ctx, server_for
from .runner import Outcome, drive, sdk_options


def default_factory(options, tools):
    return ClaudeSDKClient(options=options)


class Busy(Exception):
    """Every session slot is taken by a busy session."""


@dataclass
class Turn:
    kind: str                                   # pool | warm | chat
    ctx: Ctx
    events: list = field(default_factory=list)
    subscribers: list = field(default_factory=list)   # (queue, joined)
    finished: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def preemptible(self) -> bool:
        return self.kind in ("pool", "warm")

    async def emit(self, event: dict) -> None:
        self.events.append(event)
        for q, joined in self.subscribers:
            q.put_nowait(self._for(event, joined))

    @staticmethod
    def _for(event: dict, joined: bool) -> dict:
        if joined and event.get("type") == "done":        # the cost belongs to the request that started the turn
            return {**event, "cost_usd": 0, "shared": True, "turn_cost_usd": event.get("cost_usd")}
        return event

    def subscribe(self, joined: bool = False) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        if joined:
            for ev in self.events:
                if ev.get("type") == "candidate":
                    q.put_nowait({**ev, "replay": True})
        if self.finished.is_set():
            if joined:
                for ev in self.events:
                    if ev.get("type") in ("rejected", "done", "error"):
                        q.put_nowait(self._for(ev, joined))
            q.put_nowait(None)
        else:
            self.subscribers.append((q, joined))
        return q

    def unsubscribe(self, q) -> None:
        self.subscribers = [(x, j) for x, j in self.subscribers if x is not q]

    def close(self) -> None:
        self.finished.set()
        for q, _ in self.subscribers:
            q.put_nowait(None)


class Session:
    def __init__(self, key: str, kind: str, settings, factory, system: str):
        self.key, self.kind, self.settings = key, kind, settings
        self.bound = Bound()
        self.server, self.tools = server_for(self.bound)
        self.client = factory(sdk_options(settings, system, self.server, stream_text=kind == "chat"), self.tools)
        self.lock = asyncio.Lock()
        self.turns = 0
        self.connected = self.closed = False
        self.last_used = time.monotonic()
        self.turn: Turn | None = None
        self.seen: dict = {}                    # slot_key -> continuations proposed in this session
        self.passed: Counter = Counter()        # slot_key -> how many passed in this session
        self.english: str | None = None         # the English the model last saw

    @property
    def busy(self) -> bool:
        return self.lock.locked() or (self.turn is not None and not self.turn.finished.is_set())

    def running(self) -> Turn | None:
        return self.turn if self.turn and not self.turn.finished.is_set() else None

    async def close(self) -> None:
        self.closed = True
        if self.connected:
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001 - the CLI may already be gone
                pass


class Sessions:
    def __init__(self, settings, factory: Callable = default_factory):
        self.settings, self.factory = settings, factory
        self.by_key: dict[str, Session] = {}
        self.tasks: set = set()

    def get(self, key: str, kind: str, system: str) -> Session:
        s = self.by_key.get(key)
        if s and not s.closed:
            s.last_used = time.monotonic()
            return s
        if len(self.by_key) >= self.settings.max_sessions:
            idle = sorted((x for x in self.by_key.values() if not x.busy), key=lambda x: x.last_used)
            if not idle:
                raise Busy()
            victim = idle[0]
            self.by_key.pop(victim.key, None)
            self._spawn(victim.close())
        s = Session(key, kind, self.settings, self.factory, system)
        self.by_key[key] = s
        return s

    async def drop(self, s: Session) -> None:
        if self.by_key.get(s.key) is s:
            del self.by_key[s.key]
        await s.close()

    async def reap(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        stale = [s for s in self.by_key.values() if not s.busy and now - s.last_used > self.settings.session_idle_seconds]
        for s in stale:
            await self.drop(s)
        return len(stale)

    async def close_all(self) -> None:
        for s in list(self.by_key.values()):
            await self.drop(s)

    def _spawn(self, coro: Awaitable) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def start(self, s: Session, turn: Turn, prompt: Callable[[bool, bool], str], seconds: Callable[[bool], float],
              finish: Callable[[Turn, Outcome, dict], Awaitable[None]]) -> asyncio.Task:
        """Queue ``turn`` on ``s``. ``prompt(first, english_changed)`` is built when the turn gets the session, so
        it always reflects what the conversation already holds."""
        s.turn = turn

        async def run():
            info = {"session_turn": None, "first": False, "joined_skip": False}
            async with s.lock:
                t0 = time.monotonic()
                try:
                    if s.closed:                               # replaced after a failure while this turn waited
                        out = Outcome(error="agent failed: session closed, retry")
                    elif turn.ctx.stop.is_set():               # preempted while queued: never started
                        out = Outcome(terminal_reason=turn.ctx.stop_reason or "stop")
                    elif turn.kind == "warm" and turn.ctx.slots and all(
                            s.passed[k] >= int(v.get("want") or 0) for k, v in turn.ctx.slots.items()):
                        out = Outcome(terminal_reason="already_filled")
                    elif turn.kind == "warm" and not turn.ctx.slots and s.turns:
                        out = Outcome(terminal_reason="already_warm")
                    else:
                        if not s.connected:
                            await s.client.connect()
                            s.connected = True
                        first = s.turns == 0
                        english = turn.ctx.poem.get("english") or ""
                        changed = s.english is not None and s.english != english
                        s.english = english
                        s.turns += 1
                        info.update(session_turn=s.turns, first=first)
                        turn.ctx.seen = s.seen
                        s.bound.ctx = turn.ctx
                        out = await drive(s.client, prompt(first, changed), turn.ctx.emit, s.kind == "chat",
                                          turn.ctx.stop, seconds(first),
                                          lambda: 0.0 if turn.ctx.stop_reason == "preempted" else self.settings.stop_grace_seconds)
                        s.passed.update(turn.ctx.passed)
                except Exception as exc:  # noqa: BLE001 - the CLI died, the key is missing, ...
                    out = Outcome(error=f"agent failed: {type(exc).__name__}", broken=True)
                info["ms"] = round((time.monotonic() - t0) * 1000)
                s.last_used = time.monotonic()
                if out.broken:
                    await self.drop(s)
            try:
                await finish(turn, out, info)
            finally:
                turn.close()

        return self._spawn(run())
