"""Owner-only private mode: sign-in, sessions, CSRF and brute-force limits (release T).

Rules: docs/private-mode.md. The owner's credentials never live in the repository:
the box holds an argon2id hash and a session key in a mode-600 secrets file
(``MELOS_OWNER_AUTH_FILE``, default ``/run/secrets/owner_auth.env``), written by
``scripts/owner_auth_setup.py``. Without that file private mode is off: every owner
and private route answers 503 "not configured" (no private material exists to protect).

Sessions are server-side (one uvicorn worker): the cookie carries a random id and
its HMAC, so a restart signs the owner out and a cookie never outlives logout.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

SESSION_COOKIE = "__Host-melos_owner"
LOGIN_COOKIE = "__Host-melos_login"
# Not a credential: tells the static pages that asking /api/owner/session is worthwhile,
# so public visitors never make that request.
UI_COOKIE = "melos_owner_ui"
CSRF_HEADER = "x-melos-csrf"
SESSION_TTL = 12 * 3600
LOGIN_TOKEN_TTL = 600
CLIENT_MAX_FAILURES, CLIENT_LOCK_SECONDS = 5, 15 * 60
GLOBAL_MAX_FAILURES, GLOBAL_WINDOW, GLOBAL_LOCK_SECONDS = 20, 3600, 3600
MAX_BODY = 1024


@dataclass(frozen=True)
class OwnerConfig:
    username: str
    password_hash: str
    key: bytes


@dataclass(frozen=True)
class OwnerContext:
    """Capability object: only a verified owner session yields one (see private_store)."""
    session_id: str
    username: str
    expires_at: float
    csrf: str


_config_cache: tuple = (None, None)
_lock = threading.Lock()
_sessions: dict[str, dict] = {}
_used_login_nonces: dict[str, float] = {}
_client_failures: dict[str, list[float]] = {}
_client_locked_until: dict[str, float] = {}
_global_failures: list[float] = []
_global_locked_until = 0.0
_verify_slots = threading.BoundedSemaphore(2)


def _now() -> float:
    return time.time()


def auth_file() -> Path:
    return Path(os.environ.get("MELOS_OWNER_AUTH_FILE", "/run/secrets/owner_auth.env"))


def parse_env_file(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def load_config() -> OwnerConfig | None:
    """The owner's hash and session key, or None (private mode off)."""
    global _config_cache
    path = auth_file()
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _config_cache[0] == stamp:
        return _config_cache[1]
    try:
        values = parse_env_file(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    username = values.get("MELOS_OWNER_USERNAME", "")
    password_hash = values.get("MELOS_OWNER_PASSWORD_HASH", "")
    key_hex = values.get("MELOS_OWNER_SESSION_KEY", "")
    config = None
    if username and password_hash.startswith("$argon2id$") and len(key_hex) >= 64:
        try:
            config = OwnerConfig(username, password_hash, bytes.fromhex(key_hex))
        except ValueError:
            config = None
    _config_cache = (stamp, config)
    return config


def hash_password(password: str) -> str:
    from argon2 import PasswordHasher
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2).hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import Argon2Error, InvalidHashError
    except ImportError:
        return False  # fail closed: no argon2 library, no sign-in
    with _verify_slots:
        try:
            return PasswordHasher().verify(password_hash, password)
        except (Argon2Error, InvalidHashError, ValueError):
            return False


def _sign(key: bytes, purpose: str, value: str) -> str:
    return hmac.new(key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def public_deployment() -> bool:
    return os.environ.get("MELOS_PUBLIC_DEPLOYMENT") == "1"


def _loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_https(request: Request) -> bool:
    """Only TLS requests count. On the box the API listens on 127.0.0.1 behind the Tailscale
    Funnel (TLS) and Vercel (TLS); both set X-Forwarded-Proto. Locally, loopback only."""
    if public_deployment():
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return request.url.scheme == "https" or _loopback(request)


def allowed_origins() -> set[str]:
    raw = os.environ.get("MELOS_OWNER_ORIGINS", "https://greeklyric.com")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def origin_ok(request: Request) -> bool:
    """State-changing requests must come from the site itself (login/logout CSRF)."""
    if request.headers.get("sec-fetch-site", "") in ("cross-site", "same-site"):
        return False
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        return not public_deployment()  # browsers always send Origin on a POST fetch
    if origin in allowed_origins():
        return True
    if not public_deployment():
        return origin.startswith(("http://localhost:", "http://127.0.0.1:", "https://testserver")) or origin in (
            "http://localhost", "http://127.0.0.1", "https://testserver")
    return False


def owner_from_request(request: Request) -> OwnerContext | None:
    """The verified owner session of this request, else None. Never raises."""
    cached = getattr(request.state, "melos_owner", False)
    if cached is not False:
        return cached
    owner = None
    config = load_config()
    raw = request.cookies.get(SESSION_COOKIE, "")
    if config and raw and is_https(request):
        sid, _, signature = raw.partition(".")
        if sid and signature and hmac.compare_digest(signature, _sign(config.key, "session", sid)):
            with _lock:
                record = _sessions.get(sid)
                if record and record["expires_at"] > _now():
                    owner = OwnerContext(sid, config.username, record["expires_at"], record["csrf"])
                elif record:
                    _sessions.pop(sid, None)
    request.state.melos_owner = owner
    return owner


def _client_key(request: Request) -> str:
    # Spoofable, so only the per-client tier uses it; the global tier is authoritative.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _locked(client: str) -> float:
    """Seconds until sign-in is allowed again for this client (0 when allowed)."""
    now = _now()
    with _lock:
        wait = max(_global_locked_until - now, _client_locked_until.get(client, 0.0) - now, 0.0)
    return wait


def _record_failure(client: str) -> None:
    global _global_locked_until
    now = _now()
    with _lock:
        recent = [t for t in _client_failures.get(client, []) if now - t < CLIENT_LOCK_SECONDS] + [now]
        _client_failures[client] = recent
        if len(recent) >= CLIENT_MAX_FAILURES:
            _client_locked_until[client] = now + CLIENT_LOCK_SECONDS
            _client_failures[client] = []
        _global_failures[:] = [t for t in _global_failures if now - t < GLOBAL_WINDOW] + [now]
        if len(_global_failures) >= GLOBAL_MAX_FAILURES:
            _global_locked_until = now + GLOBAL_LOCK_SECONDS
            _global_failures.clear()


def _record_success(client: str) -> None:
    with _lock:
        _client_failures.pop(client, None)


def reset_state() -> None:
    """Tests only: forget sessions and failure counters."""
    global _global_locked_until, _config_cache
    with _lock:
        _sessions.clear()
        _used_login_nonces.clear()
        _client_failures.clear()
        _client_locked_until.clear()
        _global_failures.clear()
        _global_locked_until = 0.0
        _config_cache = (None, None)


def not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


def not_configured(request: Request) -> JSONResponse:
    """Private mode off (no owner secrets file): say so plainly. ``https`` reports whether this
    request reached the API as HTTPS (X-Forwarded-Proto on the public deployment), so the proxy
    chain can be checked before a password exists."""
    return JSONResponse(status_code=503, headers={"Cache-Control": "no-store"}, content={
        "configured": False, "signed_in": False, "https": is_https(request),
        "detail": "Owner sign-in is not configured on this server."})


def _cookie(response: Response, name: str, value: str, max_age: int, httponly: bool = True) -> None:
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=httponly, samesite="strict")


def _clear(response: Response, name: str, httponly: bool = True) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=httponly, samesite="strict")


def _json_body(request: Request, raw: bytes) -> dict | None:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return None
    if len(raw) > MAX_BODY:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


router = APIRouter()


@router.get("/api/owner/session", include_in_schema=False)
def owner_session(request: Request):
    config = load_config()
    if config is None:
        return not_configured(request)
    if not is_https(request):
        return not_found()
    owner = owner_from_request(request)
    if owner is None:
        response = JSONResponse({"signed_in": False})
        if request.cookies.get(UI_COOKIE):
            _clear(response, UI_COOKIE, httponly=False)
        return response
    return JSONResponse({"signed_in": True, "username": owner.username, "expires_at": int(owner.expires_at),
                         "csrf": owner.csrf, "ui_script": "/api/private/ui.js"})


@router.get("/api/owner/login-token", include_in_schema=False)
def login_token(request: Request):
    """A one-use pre-login token bound to an HttpOnly cookie (login CSRF protection)."""
    config = load_config()
    if config is None:
        return not_configured(request)
    if not is_https(request):
        return not_found()
    nonce = secrets.token_urlsafe(24)
    expires = int(_now()) + LOGIN_TOKEN_TTL
    payload = f"{nonce}.{expires}"
    response = JSONResponse({"token": _sign(config.key, "login", payload)})
    _cookie(response, LOGIN_COOKIE, payload + "." + _sign(config.key, "login-cookie", payload), LOGIN_TOKEN_TTL)
    return response


def _login_token_ok(config: OwnerConfig, request: Request) -> str | None:
    raw = request.cookies.get(LOGIN_COOKIE, "")
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    nonce, expires, signature = parts
    payload = f"{nonce}.{expires}"
    if not hmac.compare_digest(signature, _sign(config.key, "login-cookie", payload)):
        return None
    try:
        if int(expires) < _now():
            return None
    except ValueError:
        return None
    token = request.headers.get(CSRF_HEADER, "")
    if not token or not hmac.compare_digest(token, _sign(config.key, "login", payload)):
        return None
    with _lock:
        now = _now()
        for old in [n for n, exp in _used_login_nonces.items() if exp < now]:
            _used_login_nonces.pop(old, None)
        if nonce in _used_login_nonces:
            return None
        _used_login_nonces[nonce] = float(expires)
    return nonce


@router.post("/api/owner/login", include_in_schema=False)
async def login(request: Request):
    config = load_config()
    if config is None:
        return not_configured(request)
    if not is_https(request):
        return not_found()
    if not origin_ok(request):
        return JSONResponse(status_code=403, content={"detail": "Sign-in must come from the site itself."})
    client = _client_key(request)
    wait = _locked(client)
    if wait > 0:
        return JSONResponse(status_code=429, content={"detail": "Too many attempts. Try again later."},
                            headers={"Retry-After": str(int(wait) + 1)})
    body = _json_body(request, await request.body())
    if body is None:
        return JSONResponse(status_code=400, content={"detail": "Send a small JSON body."})
    if _login_token_ok(config, request) is None:
        return JSONResponse(status_code=403, content={"detail": "The sign-in form expired. Reload the page."})
    username = str(body.get("username", ""))[:64]
    password = str(body.get("password", ""))[:256]
    # Always run the hash check so a wrong name costs the same time as a wrong password.
    password_ok = await run_in_threadpool(verify_password, config.password_hash, password)
    name_ok = hmac.compare_digest(username.casefold().encode(), config.username.casefold().encode())
    if not (password_ok and name_ok):
        _record_failure(client)
        return JSONResponse(status_code=401, content={"detail": "Wrong name or password."})
    _record_success(client)
    # Session fixation: whatever session cookie came in is ignored and a fresh id is minted.
    old = request.cookies.get(SESSION_COOKIE, "").partition(".")[0]
    sid = secrets.token_urlsafe(32)
    expires_at = _now() + SESSION_TTL
    with _lock:
        if old:
            _sessions.pop(old, None)
        _sessions[sid] = {"expires_at": expires_at, "csrf": secrets.token_urlsafe(24)}
    response = JSONResponse({"signed_in": True, "username": config.username, "expires_at": int(expires_at)})
    _cookie(response, SESSION_COOKIE, sid + "." + _sign(config.key, "session", sid), SESSION_TTL)
    _cookie(response, UI_COOKIE, "1", SESSION_TTL, httponly=False)
    _clear(response, LOGIN_COOKIE)
    return response


@router.post("/api/owner/logout", include_in_schema=False)
def logout(request: Request):
    config = load_config()
    if config is None:
        return not_configured(request)
    if not is_https(request):
        return not_found()
    owner = owner_from_request(request)
    if owner is None:
        return not_found()
    if not origin_ok(request) or not hmac.compare_digest(request.headers.get(CSRF_HEADER, ""), owner.csrf):
        return JSONResponse(status_code=403, content={"detail": "Sign-out must come from the site itself."})
    with _lock:
        _sessions.pop(owner.session_id, None)
    response = JSONResponse({"signed_in": False})
    _clear(response, SESSION_COOKIE)
    _clear(response, UI_COOKIE, httponly=False)
    return response
