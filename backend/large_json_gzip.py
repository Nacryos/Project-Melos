"""Negotiated gzip for single-body, large JSON responses only.

Unlike Starlette 0.46's general GZipMiddleware, this intentionally leaves
streaming JSON untouched. No request, route, cache policy or response body is
changed for clients that do not accept gzip. Register this *before* any
``@app.middleware('http')`` policy wrapper: later Starlette middleware is
outermost, and BaseHTTPMiddleware re-emits ordinary JSON as streaming frames.
"""
from __future__ import annotations

import gzip

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _accepts_gzip(header: str | None) -> bool:
    if not header:
        return False
    explicit = []
    wildcard = []
    for part in header.split(','):
        fields = [piece.strip().lower() for piece in part.split(';')]
        coding = fields[0]
        if coding not in {'gzip', '*'}:
            continue
        quality = 1.0
        for parameter in fields[1:]:
            if parameter.startswith('q='):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
                break
        if not 0 <= quality <= 1:
            quality = 0.0
        (explicit if coding == 'gzip' else wildcard).append(quality)
    # An explicit refusal wins over a wildcard. Conflicting duplicate codings
    # are malformed; fail closed instead of guessing which one a proxy honors.
    return all(quality > 0 for quality in explicit) if explicit else bool(wildcard) and all(
        quality > 0 for quality in wildcard)


class LargeJSONGZipMiddleware:
    """Compress one-frame JSON responses above ``minimum_size`` bytes.

    The first body frame decides eligibility. If ``more_body`` is true, that
    response is streamed through unchanged, without collecting later frames.
    """

    def __init__(self, app: ASGIApp, minimum_size: int = 4096, compresslevel: int = 1) -> None:
        if minimum_size < 1 or not 0 <= compresslevel <= 9:
            raise ValueError('Invalid gzip bounds.')
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        wants_gzip = _accepts_gzip(','.join(Headers(scope=scope).getlist('accept-encoding')))
        initial: Message | None = None
        started = False
        static_eligible = False

        async def send_response(message: Message) -> None:
            nonlocal initial, started, static_eligible
            if message['type'] == 'http.response.start':
                initial = message
                headers = Headers(raw=message['headers'])
                content_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
                cache_directives = {directive.strip().lower()
                                    for value in headers.getlist('cache-control')
                                    for directive in value.split(',')}
                static_eligible = (message['status'] == 200
                                   and content_type == 'application/json'
                                   and 'no-transform' not in cache_directives
                                   and not message.get('trailers', False)
                                   and not any(name in headers for name in (
                                       'content-encoding', 'content-range', 'content-md5',
                                       'digest', 'content-digest', 'repr-digest', 'etag',
                                       'trailer')))
                if not static_eligible:
                    # SSE and other known-ineligible responses must open before
                    # the first body arrives, which may be much later.
                    started = True
                    await send(message)
                return
            if message['type'] != 'http.response.body' and initial is not None and not started:
                # Extensions such as pathsend must never precede response.start.
                started = True
                await send(initial)
                await send(message)
                return
            if message['type'] != 'http.response.body' or initial is None or started:
                await send(message)
                return
            started = True
            body = message.get('body', b'')
            eligible = (static_eligible and not message.get('more_body', False)
                        and len(body) >= self.minimum_size)
            if eligible:
                headers = Headers(raw=initial['headers'])
                outgoing = MutableHeaders(raw=initial['headers'])
                vary = {item.strip().lower()
                        for value in headers.getlist('vary')
                        for item in value.split(',')}
                if '*' not in vary and 'accept-encoding' not in vary:
                    # Append a field instead of replacing one: servers may emit
                    # multiple Vary fields and each existing value must survive.
                    outgoing.append('vary', 'Accept-Encoding')
                if wants_gzip:
                    compressed = gzip.compress(body, compresslevel=self.compresslevel, mtime=0)
                else:
                    compressed = body
                if len(compressed) < len(body):
                    outgoing['content-encoding'] = 'gzip'
                    outgoing['content-length'] = str(len(compressed))
                    message = {**message, 'body': compressed}
            await send(initial)
            await send(message)

        await self.app(scope, receive, send_response)
        if initial is not None and not started:
            await send(initial)
