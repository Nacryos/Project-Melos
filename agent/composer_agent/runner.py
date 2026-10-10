"""Drives Claude Agent SDK turns (model claude-fable-5-1, effort xhigh): one-shot clients and session turns."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent,
                              TextBlock)

from .melos import tool_names
from .settings import EFFORT, MODEL

# Belt and braces: tools=[] already removes every built-in; these must never run even if a default changes.
BUILTINS_DENIED = ["Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob",
                   "Grep", "LS", "WebFetch", "WebSearch", "Task", "Agent", "Skill", "SlashCommand", "TodoWrite",
                   "ExitPlanMode", "Monitor"]
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


@dataclass
class Job:
    system: str
    prompt: str
    emit: Callable[[dict], Awaitable[None]]
    server: Any = None                  # in-process MCP server config (None: no tools)
    tools: list = field(default_factory=list)   # the SdkMcpTool objects (used by test fakes)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    seconds: float = 600
    max_turns: int = 30
    stream_text: bool = False


@dataclass
class Outcome:
    usage: dict = field(default_factory=dict)
    sdk_cost_usd: float | None = None
    text: str = ""
    error: str | None = None
    stop_reason: str | None = None
    terminal_reason: str | None = None
    sdk_usage: dict | None = None
    session_id: str | None = None
    broken: bool = False                # the turn did not end after an interrupt: the session must be replaced


def sdk_options(settings, system: str, server=None, stream_text: bool = False, max_turns: int | None = None) -> ClaudeAgentOptions:
    state = Path(settings.state_dir)
    scratch = state / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    env = {"ANTHROPIC_API_KEY": settings.anthropic_key(),
           "CLAUDE_CONFIG_DIR": str(state / "claude-config"),
           "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    return ClaudeAgentOptions(
        model=MODEL, effort=EFFORT, system_prompt=system,
        tools=[], allowed_tools=tool_names() if server else [], disallowed_tools=BUILTINS_DENIED,
        mcp_servers={"melos": server} if server else {}, strict_mcp_config=True,
        permission_mode="dontAsk", setting_sources=[], max_turns=max_turns,
        include_partial_messages=stream_text, cwd=str(scratch), env=env)


async def consume(client, prompt: str, emit, stream_text: bool, out: Outcome) -> None:
    """One query and its response. Usage = the result message's usage, which is per query even in a long-lived
    session (measured 2026-10-10; its total_cost_usd is cumulative over the session, so it is only logged). Without
    a result (interrupted, failed) usage is summed over the assistant messages, each counted once at its largest
    figure; those carry message-start figures, so output tokens are undercounted then."""
    per_message: dict = {}              # message id -> usage (a message arrives once per content block)
    usage = out.usage = {k: 0 for k in USAGE_KEYS}
    await client.query(prompt)
    async for msg in client.receive_response():
        if isinstance(msg, StreamEvent):
            ev = msg.event
            if (stream_text and msg.parent_tool_use_id is None and ev.get("type") == "content_block_delta"
                    and (ev.get("delta") or {}).get("type") == "text_delta"):
                await emit({"type": "text", "delta": ev["delta"].get("text", "")})
        elif isinstance(msg, AssistantMessage):
            if msg.usage:
                prev = per_message.setdefault(msg.message_id, {k: 0 for k in USAGE_KEYS})
                for k in USAGE_KEYS:                       # keep the largest figure seen for this message
                    new = int(msg.usage.get(k) or 0)
                    if new > prev[k]:
                        usage[k] += new - prev[k]
                        prev[k] = new
            if msg.stop_reason == "refusal":
                out.error = "The model declined this request (refusal)."
            if msg.error:
                out.error = f"model error: {msg.error}"
            for block in msg.content:
                if isinstance(block, TextBlock) and msg.parent_tool_use_id is None:
                    out.text += block.text
        elif isinstance(msg, ResultMessage):
            out.sdk_cost_usd = msg.total_cost_usd
            out.session_id = msg.session_id
            out.stop_reason, out.terminal_reason = msg.stop_reason, msg.terminal_reason
            if msg.usage:   # this turn's usage (measured live: per query, also in a long session)
                out.sdk_usage = {k: int(msg.usage.get(k) or 0) for k in USAGE_KEYS}
                out.usage = dict(out.sdk_usage)
            if msg.stop_reason == "refusal":
                out.error = "The model declined this request (refusal)."
            elif msg.is_error and not out.error and msg.terminal_reason not in ("aborted_streaming", "aborted_tools"):
                out.error = f"agent error: {msg.subtype}" + (f" (HTTP {msg.api_error_status})" if msg.api_error_status else "")


async def drive(client, prompt: str, emit, stream_text: bool, stop: asyncio.Event, seconds: float,
                grace: Callable[[], float] = lambda: 0.0) -> Outcome:
    """Run one turn on a connected client. On ``stop`` the model gets ``grace`` seconds to finish on its own (it
    was told to reply 'done'), then the turn is interrupted; on the deadline it is interrupted at once."""
    out = Outcome()
    deadline = time.monotonic() + seconds
    task = asyncio.create_task(consume(client, prompt, emit, stream_text, out))
    stopper = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({task, stopper}, timeout=max(0.0, deadline - time.monotonic()),
                                     return_when=asyncio.FIRST_COMPLETED)
        if task not in done and stop.is_set() and grace() > 0:
            done, _ = await asyncio.wait({task}, timeout=min(grace(), max(0.0, deadline - time.monotonic())))
        if task not in done:   # stop requested or out of time: interrupt, then let the result arrive
            stopped_early = "stop" if stop.is_set() else "deadline"
            await client.interrupt()
            try:
                await asyncio.wait_for(asyncio.shield(task), 15)
            except asyncio.TimeoutError:
                task.cancel()
                out.broken = True
            out.terminal_reason = stopped_early
        else:
            task.result()
    finally:
        stopper.cancel()
    return out


class SdkRunner:
    """One-shot requests (back-translation): a fresh client per call."""

    def __init__(self, settings):
        self.settings = settings

    def options(self, job: Job) -> ClaudeAgentOptions:
        return sdk_options(self.settings, job.system, job.server, job.stream_text, job.max_turns)

    async def run(self, job: Job) -> Outcome:
        async with ClaudeSDKClient(options=self.options(job)) as client:
            return await drive(client, job.prompt, job.emit, job.stream_text, job.stop, job.seconds)
