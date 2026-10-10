"""Release W: who may reach the composer (docs/prd/composer-agent.md §6).

Two kinds of caller:

1. **The owner** (a verified release-T session, ``private_auth.owner_from_request``). The composer page
   (``/composer``, ``/composer.html``), ``/api/compose/*`` and ``/api/composer/*`` answer 404 to anyone else,
   before routing (``private_mode.PrivateGuard`` calls ``owner_only_path``) and again in each route
   (``require_owner``).
2. **The composer agent service** (container ``melos-composer-agent`` on the box's internal Docker network). It
   sends the shared internal token in ``X-Composer-Token``. The token (file ``MELOS_COMPOSER_AGENT_TOKEN_FILE``,
   else env ``MELOS_COMPOSER_AGENT_TOKEN``; at least 32 characters, else the internal path is off) does two things:
     - opens ``POST /api/composer/check`` (the lint bank), the one owner-only route the agent calls, and only on
       a request without ``X-Forwarded-For``: public traffic always arrives through Tailscale Funnel, which
       appends that header, so a token leaked to the internet still cannot reach it;
     - exempts the read-only tool routes (search, word, analyze-text, dialectize, scan, lemma/*, …) from the
       per-visitor rate limits (``rate_limit.LIMITED_PATHS``), with or without a forwarding header.
   It never makes a request the owner: ``/api/private/*``, ``/api/owner/*`` and every other composer route stay 404.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import HTTPException, Request

from .private_auth import origin_ok, owner_from_request

TOKEN_HEADER = "x-composer-token"
MIN_TOKEN = 32
OWNER_ONLY_PREFIXES = ("/api/compose/", "/api/composer/")
OWNER_ONLY_EXACT = frozenset({"/api/compose", "/api/composer", "/composer", "/composer.html", "/composer/"})
# Owner-only routes the agent service may call with the internal token.
INTERNAL_OWNER_ROUTES = frozenset({("POST", "/api/composer/check")})
# Read-only tool routes the agent calls; the token lifts only their per-visitor rate limits.
INTERNAL_TOOL_PREFIXES = ("/api/search", "/api/word", "/api/words/headlines", "/api/analyze-text", "/api/dialectize",
                          "/api/scan", "/api/lemma/", "/api/concept/diachrony", "/api/cite", "/api/commentary/",
                          "/api/machine-analysis")

_token_cache: tuple = (None, None)


def internal_token() -> str | None:
    """The shared agent token, or None (internal access off). The file is re-read when it changes."""
    global _token_cache
    path = os.environ.get("MELOS_COMPOSER_AGENT_TOKEN_FILE", "")
    value = None
    if path:
        try:
            stat = Path(path).stat()
            stamp = (path, stat.st_mtime_ns, stat.st_size)
            if _token_cache[0] == stamp:
                value = _token_cache[1]
            else:
                text = Path(path).read_text(encoding="utf-8").strip()
                value = text.partition("=")[2].strip() if text.startswith("MELOS_COMPOSER_AGENT_TOKEN=") else text
                _token_cache = (stamp, value)
        except OSError:
            value = None
    if not value:
        value = os.environ.get("MELOS_COMPOSER_AGENT_TOKEN", "").strip()
    return value if value and len(value) >= MIN_TOKEN else None


def internal_request(request, *, direct: bool = True) -> bool:
    """True for a request carrying the agent service's token; with ``direct`` (the default) it must also not have
    come through the public proxy chain (no X-Forwarded-For)."""
    given = request.headers.get(TOKEN_HEADER, "")
    if not given or (direct and (request.headers.get("x-forwarded-for") or "").strip()):
        return False
    expected = internal_token()
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def owner_only_path(path: str) -> bool:
    return path in OWNER_ONLY_EXACT or path.startswith(OWNER_ONLY_PREFIXES)


def internal_tool_path(path: str) -> bool:
    return path.startswith(INTERNAL_TOOL_PREFIXES)


def internal_may_call(method: str, path: str) -> bool:
    return (method.upper(), path) in INTERNAL_OWNER_ROUTES


def require_owner(request: Request):
    """Route dependency: the owner session, else 404 (the composer does not exist for anyone else). State-changing
    requests must also come from the site itself (same Origin rule as sign-out)."""
    owner = owner_from_request(request)
    if owner is None:
        raise HTTPException(404, "Not Found")
    if request.method not in ("GET", "HEAD") and not origin_ok(request):
        raise HTTPException(403, "Composer changes must come from the site itself.")
    return owner


def require_owner_or_agent(request: Request):
    """Route dependency for POST /api/composer/check: the owner, or the agent service with the internal token."""
    if internal_request(request) and internal_may_call(request.method, request.url.path):
        return "agent"
    return require_owner(request)
