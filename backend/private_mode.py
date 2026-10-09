"""Private mode wiring (release T): owner routes, the signed-out response guard, the owner UI.

``install(app)`` must run before any other middleware is added so the guard sits innermost
(it reads uncompressed bodies). Server-side enforcement, in order:

1. ``/api/private/*`` answers 404 to any request without a verified owner session, before
   routing (unknown sub-paths included); 503 "not configured" when the box has no owner secrets;
2. every owner route also checks the session itself (``_owner_or_404``);
3. for signed-out requests the guard scans every ``/api`` response body for the private marker
   that tags all owner payloads; a match is replaced by 404 (or the stream is cut) and logged.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.requests import Request as StarletteRequest

from . import private_store
from .private_auth import load_config, not_configured, not_found, owner_from_request, router as auth_router

log = logging.getLogger("melos.private")
MARKER_BYTES = private_store.MARKER.encode()
UI_SCRIPT = Path(__file__).with_name("private_ui.js")


class PrivateGuard:
    """Pure ASGI middleware: 404 for signed-out private routes; marker scan on signed-out bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        request = StarletteRequest(scope)
        owner = owner_from_request(request)
        if owner is not None:
            return await self.app(scope, receive, send)
        if scope["path"].startswith("/api/private/") or scope["path"] == "/api/private":
            if load_config() is None:
                return await not_configured(request)(scope, receive, send)
            return await not_found()(scope, receive, send)

        held_start = None
        started = False
        blocked = False
        tail = b""

        async def guarded_send(message):
            nonlocal held_start, started, blocked, tail
            if blocked:
                return
            if message["type"] == "http.response.start":
                held_start = message
                return
            if message["type"] != "http.response.body":
                return await send(message)
            body = message.get("body", b"")
            window = tail + body
            if MARKER_BYTES in window:
                blocked = True
                log.error("private guard: blocked private marker in signed-out response %s", scope["path"])
                if not started:
                    started = True
                    return await not_found()(scope, receive, send)
                # Headers already went out: end the stream without the private bytes.
                return await send({"type": "http.response.body", "body": b"", "more_body": False})
            tail = window[-(len(MARKER_BYTES) - 1):]
            if not started:
                started = True
                await send(held_start)
            await send(message)

        await self.app(scope, receive, guarded_send)


def _owner_or_404(request: Request):
    owner = owner_from_request(request)
    return owner


router = APIRouter()


@router.get("/api/private/status", include_in_schema=False)
def private_status(request: Request):
    owner = _owner_or_404(request)
    return not_found() if owner is None else private_store.owner_status(owner)


@router.get("/api/private/documents", include_in_schema=False)
def private_documents(request: Request):
    owner = _owner_or_404(request)
    return not_found() if owner is None else private_store.owner_documents(owner)


@router.get("/api/private/page", include_in_schema=False)
def private_page(request: Request, doc: str = Query(..., max_length=64), page: int = Query(..., ge=0, le=100000)):
    owner = _owner_or_404(request)
    if owner is None:
        return not_found()
    payload = private_store.owner_page(owner, doc, page)
    return not_found() if payload is None else payload


@router.get("/api/private/passage", include_in_schema=False)
def private_passage(request: Request, id: str = Query(..., max_length=300)):
    owner = _owner_or_404(request)
    return not_found() if owner is None else private_store.owner_passage(owner, id)


@router.get("/api/private/lemma", include_in_schema=False)
def private_lemma(request: Request, lemma: str = Query(..., max_length=100)):
    owner = _owner_or_404(request)
    return not_found() if owner is None else private_store.owner_lemma(owner, lemma)


@router.get("/api/private/search", include_in_schema=False)
def private_search(request: Request, q: str = Query(..., max_length=300), limit: int = Query(20, ge=1, le=50)):
    owner = _owner_or_404(request)
    return not_found() if owner is None else private_store.owner_search(owner, q, limit)


@router.get("/api/private/ui.js", include_in_schema=False)
def private_ui(request: Request):
    owner = _owner_or_404(request)
    if owner is None:
        return not_found()
    return Response(UI_SCRIPT.read_text(encoding="utf-8"), media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@router.get("/owner", include_in_schema=False)
@router.get("/owner.html", include_in_schema=False)
def owner_page():
    """The sign-in page for a local server (the public site serves the same file from Vercel)."""
    path = Path(__file__).resolve().parents[1] / "owner.html"
    return FileResponse(path) if path.exists() else not_found()


def install(app: FastAPI) -> None:
    app.add_middleware(PrivateGuard)
    app.include_router(auth_router)
    app.include_router(router)
