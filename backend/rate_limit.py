"""Release U: per-client request rate limits for the unmetered local parser routes.

The local Morpheus engine has no external cost, so it has no per-visitor daily allowance (the courtesy
allowances in backend.machine_morphology apply to the remote Alpheios service only). Abuse protection is a
sliding-window limit per client on the routes that can make it parse many new forms (analysis, draft
analysis, dialect spellings, machine analysis, batch headlines).

Client identity: requests reach the API through Vercel and Tailscale Funnel. Funnel appends the connecting
address to X-Forwarded-For, and Vercel overwrites the header with the visitor's address, so a request via
the site carries "visitor, Vercel edge". The key is the last two entries; a direct caller can forge the
first, so the connecting address (last entry) has its own, larger limit as the backstop. In-memory and per
process (one uvicorn worker), not a security boundary.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

LIMITED_PATHS = ("/api/machine-analysis", "/api/analyze-text", "/api/dialectize", "/api/analyze-passage",
                 "/api/passage-analysis", "/api/words/headlines", "/api/passage-morphology/warm",
                 # release V: the scanner (cheap, but up to 20,000 characters a call) and the composer's
                 # suggestions (which also have their own, lower limit in backend/compose_routes.py)
                 "/api/scan", "/api/scan/rules/validate", "/api/compose/suggest")


def _env(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RateLimiter:
    def __init__(self, *, client_minute=None, client_day=None, connection_minute=None, clock=time.monotonic):
        self.client_minute = client_minute or _env("MELOS_RATE_CLIENT_MINUTE", 300)
        self.client_day = client_day or _env("MELOS_RATE_CLIENT_DAY", 20000)
        self.connection_minute = connection_minute or _env("MELOS_RATE_CONNECTION_MINUTE", 1200)
        self.clock = clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._sweep = 0.0

    @staticmethod
    def keys(headers, client_host):
        chain = [part.strip() for part in (headers.get("x-forwarded-for") or "").split(",") if part.strip()]
        if not chain:
            chain = [client_host or "unknown"]
        return "client:" + ",".join(chain[-2:]), "conn:" + chain[-1]

    def _allow(self, key, limit, window, now):
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(hits[0] + window - now) + 1)
        return 0

    def check(self, headers, client_host):
        """0 when allowed (and counted), else the seconds to wait. A request without X-Forwarded-For is
        not limited: it comes from the host itself (check scripts; inside the container it arrives from the
        Docker gateway), since public traffic reaches the API only through Tailscale Funnel, whose reverse
        proxy always appends the header."""
        if not (headers.get("x-forwarded-for") or "").strip():
            return 0
        client, conn = self.keys(headers, client_host)
        now = self.clock()
        with self._lock:
            if now - self._sweep > 300:
                self._sweep = now
                for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - 86400]:
                    del self._hits[key]
            for key, limit, window in ((client, self.client_minute, 60), (client + "#day", self.client_day, 86400),
                                       (conn, self.connection_minute, 60)):
                wait = self._allow(key, limit, window, now)
                if wait:
                    return wait
            for key in (client, client + "#day", conn):
                self._hits[key].append(now)
        return 0


_LIMITER = None


def limiter():
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter()
    return _LIMITER
