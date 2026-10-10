"""Drives one Claude Agent SDK session per request (model claude-fable-5-1, effort xhigh)."""
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


class SdkRunner:
    def __init__(self, settings):
        self.settings = settings

    def options(self, job: Job) -> ClaudeAgentOptions:
        state = Path(self.settings.state_dir)
        scratch = state / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        env = {"ANTHROPIC_API_KEY": self.settings.anthropic_key(),
               "CLAUDE_CONFIG_DIR": str(state / "claude-config"),
               "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
               "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        return ClaudeAgentOptions(
            model=MODEL, effort=EFFORT, system_prompt=job.system,
            tools=[], allowed_tools=tool_names() if job.server else [], disallowed_tools=BUILTINS_DENIED,
            mcp_servers={"melos": job.server} if job.server else {}, strict_mcp_config=True,
            permission_mode="dontAsk", setting_sources=[], max_turns=job.max_turns,
            include_partial_messages=job.stream_text, cwd=str(scratch), env=env)

    async def run(self, job: Job) -> Outcome:
        out, seen_ids, usage = Outcome(), set(), {k: 0 for k in USAGE_KEYS}
        deadline = time.monotonic() + job.seconds

        async def consume(client: ClaudeSDKClient):
            await client.query(job.prompt)
            async for msg in client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev = msg.event
                    if (job.stream_text and msg.parent_tool_use_id is None and ev.get("type") == "content_block_delta"
                            and (ev.get("delta") or {}).get("type") == "text_delta"):
                        await job.emit({"type": "text", "delta": ev["delta"].get("text", "")})
                elif isinstance(msg, AssistantMessage):
                    if msg.message_id not in seen_ids and msg.usage:
                        seen_ids.add(msg.message_id)
                        for k in USAGE_KEYS:
                            usage[k] += int(msg.usage.get(k) or 0)
                    if msg.stop_reason == "refusal":
                        out.error = "The model declined this request (refusal)."
                    if msg.error:
                        out.error = f"model error: {msg.error}"
                    for block in msg.content:
                        if isinstance(block, TextBlock) and msg.parent_tool_use_id is None:
                            out.text += block.text
                elif isinstance(msg, ResultMessage):
                    out.sdk_cost_usd = msg.total_cost_usd
                    out.stop_reason, out.terminal_reason = msg.stop_reason, msg.terminal_reason
                    if msg.usage:
                        out.usage = {k: int(msg.usage.get(k) or 0) for k in USAGE_KEYS}
                    if msg.stop_reason == "refusal":
                        out.error = "The model declined this request (refusal)."
                    elif msg.is_error and not out.error and msg.terminal_reason not in ("aborted_streaming", "aborted_tools"):
                        out.error = f"agent error: {msg.subtype}" + (f" (HTTP {msg.api_error_status})" if msg.api_error_status else "")

        async with ClaudeSDKClient(options=self.options(job)) as client:
            task = asyncio.create_task(consume(client))
            stopper = asyncio.create_task(job.stop.wait())
            try:
                done, _ = await asyncio.wait({task, stopper}, timeout=max(0.0, deadline - time.monotonic()),
                                             return_when=asyncio.FIRST_COMPLETED)
                if task not in done:   # stop requested or out of time: interrupt, then let the result arrive
                    stopped_early = "stop" if job.stop.is_set() else "deadline"
                    await client.interrupt()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), 15)
                    except asyncio.TimeoutError:
                        task.cancel()
                    out.terminal_reason = stopped_early
                else:
                    task.result()
            finally:
                stopper.cancel()
        if not out.usage or not any(out.usage.values()):
            out.usage = usage
        return out
