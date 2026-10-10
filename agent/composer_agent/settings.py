"""Configuration from the environment, secret files and pricing. Nothing here logs a secret."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "claude-fable-5-1"   # owner ruling (PRD §1): always this model ...
EFFORT = "xhigh"             # ... at this effort; ClaudeAgentOptions.effort -> CLI --effort

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


@dataclass
class Settings:
    melos_api_url: str = field(default_factory=lambda: os.environ.get("MELOS_API_URL", "http://melos-api:8791").rstrip("/"))
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get("COMPOSER_AGENT_STATE", "/state")))
    token: str = field(default_factory=lambda: read_secret("COMPOSER_AGENT_TOKEN_FILE"))
    pool_rounds: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_POOL_ROUNDS", "4")))
    pool_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_POOL_SECONDS", "120")))
    chat_seconds: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_CHAT_SECONDS", "600")))
    tool_result_chars: int = field(default_factory=lambda: int(os.environ.get("COMPOSER_TOOL_RESULT_CHARS", "20000")))
    http_timeout: float = field(default_factory=lambda: float(os.environ.get("COMPOSER_HTTP_TIMEOUT", "30")))

    def anthropic_key(self) -> str:
        """Read on demand so the key lives only in the CLI subprocess environment."""
        return read_secret("ANTHROPIC_API_KEY_FILE")
