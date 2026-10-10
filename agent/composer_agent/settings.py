"""Configuration from the environment, secret files and pricing. Nothing here logs a secret."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "claude-fable-5-1"   # owner ruling (PRD §1): always this model ...
EFFORT = "xhigh"             # ... at this effort for chat and the research (warm-up) turn; pool fills may run lower
EFFORTS = ("low", "medium", "high", "xhigh", "max")   # ClaudeAgentOptions.effort -> CLI --effort
MODES = ("line", "words")    # pool fill modes: whole-line continuations | next words (1-3 words)

# Fable 5.1, USD per million tokens. Cache writes are not in the brief; 1.25x input (5-minute writes).
PRICE_PER_MTOK = {"input_tokens": 10.0, "output_tokens": 50.0,
                  "cache_read_input_tokens": 0.25, "cache_creation_input_tokens": 12.5}


def read_secret(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def cost_usd(usage: dict | None) -> float:
    usage = usage or {}
    return round(sum(float(usage.get(k) or 0) * p for k, p in PRICE_PER_MTOK.items()) / 1e6, 6)


def _effort(env_name: str, default: str) -> str:
    value = os.environ.get(env_name, default).strip().lower() or default
    if value not in EFFORTS:
        raise ValueError(f"{env_name}={value!r}: effort must be one of {', '.join(EFFORTS)}")
    return value


@dataclass
class Settings:
    melos_api_url: str = field(default_factory=lambda: os.environ.get("MELOS_API_URL", "http://melos-api:8791").rstrip("/"))
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get("COMPOSER_AGENT_STATE", "/state")))
    token: str = field(default_factory=lambda: read_secret("COMPOSER_AGENT_TOKEN_FILE"))
    # Effort per job kind (owner ruling 2026-10-10: the pool may run below xhigh; chat and the research turn stay xhigh).
    pool_effort: str = field(default_factory=lambda: _effort("COMPOSER_POOL_EFFORT", "medium"))
    chat_effort: str = field(default_factory=lambda: _effort("COMPOSER_CHAT_EFFORT", EFFORT))
    warm_effort: str = field(default_factory=lambda: _effort("COMPOSER_WARM_EFFORT", EFFORT))
    # Pool fills: one forked session per (slot, mode), at most this many running at once (each is a CLI process).
    pool_parallel: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_POOL_PARALLEL", "4")))
    pool_rounds: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_POOL_ROUNDS", "8")))
    pool_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_POOL_SECONDS", "240")))
    # Next-words fills: short continuations, small batches, a shorter deadline.
    words_rounds: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_WORDS_ROUNDS", "5")))
    words_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_WORDS_SECONDS", "120")))
    words_n: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_WORDS_N", "8")))
    # A fill asked for while the poem's research turn still runs starts cold (no research in its context) instead
    # of waiting; 0 = always wait for the research and fork from it.
    cold_fills: bool = field(default_factory=lambda: os.environ.get("COMPOSER_COLD_FILLS", "1") not in ("0", "false", ""))
    # The research turn (a session's first turn, effort warm_effort) is bounded by this.
    warm_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_WARM_SECONDS", "600")))
    pool_ahead_n: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_POOL_AHEAD_N", "6")))
    stop_grace_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_STOP_GRACE_SECONDS", "8")))
    # Persistent sessions: one SDK client per (poem, kind, settings); closed after this idle time; at most this many.
    session_idle_seconds: float = field(default_factory=lambda: 60 * float(os.environ.get("COMPOSER_SESSION_IDLE_MINUTES", "30")))
    max_sessions: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_MAX_SESSIONS", "4")))
    chat_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_CHAT_SECONDS", "600")))
    tool_result_chars: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_TOOL_RESULT_CHARS", "10000")))
    http_timeout: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_HTTP_TIMEOUT", "30")))

    def effort_for(self, kind: str) -> str:
        """The effort of a job kind: chat | warm (the research turn) | pool (fills, any mode)."""
        return {"chat": self.chat_effort, "warm": self.warm_effort}.get(kind, self.pool_effort)

    def anthropic_key(self) -> str:
        """Read on demand so the key lives only in the CLI subprocess environment."""
        return read_secret("ANTHROPIC_API_KEY_FILE")
