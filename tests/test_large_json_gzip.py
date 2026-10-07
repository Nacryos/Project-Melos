"""Synthetic HTTP fixtures; no corpus, API server or network calls."""
import asyncio
import gzip
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from backend.large_json_gzip import LargeJSONGZipMiddleware


LARGE = {'rows': [{'id': i, 'source': 'literal ' + 'x' * 200} for i in range(200)]}
EXPECTED = JSONResponse(content=LARGE).body


def fixture_app():
    app = FastAPI()

    @app.get('/large')
    def large():
        response = JSONResponse(content=LARGE)
        response.headers['cache-control'] = 'no-store'
        response.headers['content-security-policy'] = "default-src 'none'"
        response.set_cookie('fixture', 'present', httponly=True)
        return response

    @app.get('/small')
    def small():
        return JSONResponse(content={'ok': True})

    @app.get('/stream')
    def stream():
        return StreamingResponse(iter([b'{"rows":', b'[1,2,3]}']), media_type='application/json')

    @app.get('/events')
    def events():
        return StreamingResponse(iter([b'data: first\n\n', b'data: second\n\n']),
                                 media_type='text/event-stream')

    @app.get('/etag')
    def etag():
        response = JSONResponse(content=LARGE)
        response.headers['etag'] = '"source-bytes"'
        return response

    @app.get('/no-transform')
    def no_transform():
        response = JSONResponse(content=LARGE)
        response.headers['cache-control'] = 'private, no-transform'
        return response

    @app.get('/preencoded')
    def preencoded():
        return Response(content=gzip.compress(EXPECTED, mtime=0),
                        media_type='application/json',
                        headers={'content-encoding': 'gzip'})

    # Register compression before BaseHTTPMiddleware. Starlette places later
    # middleware outside earlier entries; the policy wrapper presents ordinary
    # JSON as a stream to its outer neighbours.
    app.add_middleware(LargeJSONGZipMiddleware, minimum_size=512, compresslevel=1)
    app.add_middleware(CORSMiddleware, allow_origins=['https://reader.example'],
                       allow_methods=['GET'], allow_headers=['Accept'])
    @app.middleware('http')
    async def request_policy(request, call_next):
        response = await call_next(request)
        response.headers['x-policy'] = 'kept'
        return response
    return app


def test_large_json_negotiates_exact_decompressed_body_and_preserves_headers():
    with TestClient(fixture_app()) as client:
        response = client.get('/large', headers={'Accept-Encoding': 'gzip',
                                                 'Origin': 'https://reader.example'})
    assert response.status_code == 200
    assert response.headers['content-encoding'] == 'gzip'
    assert response.content == EXPECTED  # TestClient transparently decompresses.
    assert json.loads(response.content) == LARGE
    assert int(response.headers['content-length']) < len(EXPECTED)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-policy'] == 'kept'
    assert response.headers['content-security-policy'] == "default-src 'none'"
    assert 'fixture=present' in response.headers['set-cookie']
    assert response.headers['access-control-allow-origin'] == 'https://reader.example'
    assert {'origin', 'accept-encoding'} <= {
        value.strip().lower() for value in response.headers['vary'].split(',')}


def test_identity_and_explicit_gzip_refusal_keep_original_bytes_and_headers():
    with TestClient(fixture_app()) as client:
        for encoding in ('identity', 'gzip;q=0, *;q=1'):
            response = client.get('/large', headers={'Accept-Encoding': encoding})
            assert response.content == EXPECTED
            assert 'content-encoding' not in response.headers
            assert int(response.headers['content-length']) == len(EXPECTED)
            assert 'accept-encoding' in response.headers['vary'].lower()


def test_duplicate_accept_encoding_headers_respect_explicit_refusal():
    with TestClient(fixture_app()) as client:
        accepted = client.get('/large', headers=[('Accept-Encoding', 'identity'),
                                                 ('Accept-Encoding', 'gzip;q=0.5')])
        refused = client.get('/large', headers=[('Accept-Encoding', 'gzip;q=0'),
                                                ('Accept-Encoding', 'gzip;q=1')])
    assert accepted.headers['content-encoding'] == 'gzip'
    assert accepted.content == EXPECTED
    assert 'content-encoding' not in refused.headers
    assert refused.content == EXPECTED
    assert 'accept-encoding' in refused.headers['vary'].lower()


def test_small_json_streaming_json_sse_and_etag_are_not_compressed():
    with TestClient(fixture_app()) as client:
        for path, expected in [('/small', b'{"ok":true}'),
                               ('/stream', b'{"rows":[1,2,3]}'),
                               ('/events', b'data: first\n\ndata: second\n\n'),
                               ('/etag', EXPECTED),
                               ('/no-transform', EXPECTED)]:
            response = client.get(path, headers={'Accept-Encoding': 'gzip'})
            assert response.content == expected
            assert 'content-encoding' not in response.headers
            if path in {'/stream', '/events', '/etag', '/no-transform'}:
                assert 'accept-encoding' not in response.headers.get('vary', '').lower()
            if path == '/etag':
                assert response.headers['etag'] == '"source-bytes"'
        assert response.headers['cache-control'] == 'private, no-transform'


def test_existing_content_encoding_is_not_double_compressed():
    with TestClient(fixture_app()) as client:
        response = client.get('/preencoded', headers={'Accept-Encoding': 'gzip'})
    assert response.content == EXPECTED  # HTTP client decodes the one existing layer.
    assert response.headers['content-encoding'] == 'gzip'
    assert int(response.headers['content-length']) == len(gzip.compress(EXPECTED, mtime=0))
    assert 'accept-encoding' not in response.headers.get('vary', '').lower()


def test_raw_asgi_frame_decompresses_to_exact_original_json_bytes():
    async def source(_scope, _receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'application/json'),
                                (b'content-length', str(len(EXPECTED)).encode())]})
        await send({'type': 'http.response.body', 'body': EXPECTED})

    async def capture():
        events = []
        scope = {'type': 'http', 'method': 'GET', 'path': '/fixture',
                 'headers': [(b'accept-encoding', b'gzip')]}
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(message):
            events.append(message)
        await LargeJSONGZipMiddleware(source, minimum_size=512)(scope, receive, send)
        return events

    start, body = asyncio.run(capture())
    assert gzip.decompress(body['body']) == EXPECTED
    headers = dict(start['headers'])
    assert headers[b'content-encoding'] == b'gzip'
    assert int(headers[b'content-length']) == len(body['body'])


def test_raw_duplicate_cache_control_and_vary_headers_preserve_all_values():
    async def exchange(extra_headers, accept=b'gzip'):
        async def source(_scope, _receive, send):
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'content-length', str(len(EXPECTED)).encode()),
                                    *extra_headers]})
            await send({'type': 'http.response.body', 'body': EXPECTED})
        events = []
        scope = {'type': 'http', 'method': 'GET', 'path': '/fixture',
                 'headers': [(b'accept-encoding', accept)]}
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(message):
            events.append(message)
        await LargeJSONGZipMiddleware(source, minimum_size=512)(scope, receive, send)
        return events

    start, body = asyncio.run(exchange([
        (b'cache-control', b'private'), (b'cache-control', b'no-transform')]))
    assert body['body'] == EXPECTED
    assert (b'content-encoding', b'gzip') not in start['headers']
    assert [value for name, value in start['headers'] if name == b'cache-control'] == [
        b'private', b'no-transform']

    start, body = asyncio.run(exchange([
        (b'vary', b'Origin'), (b'vary', b'Authorization')]))
    assert gzip.decompress(body['body']) == EXPECTED
    assert [value for name, value in start['headers'] if name == b'vary'] == [
        b'Origin', b'Authorization', b'Accept-Encoding']
    assert int(dict(start['headers'])[b'content-length']) == len(body['body'])

    start, body = asyncio.run(exchange([(b'vary', b'*')]))
    assert gzip.decompress(body['body']) == EXPECTED
    assert [value for name, value in start['headers'] if name == b'vary'] == [b'*']


def test_response_extension_never_precedes_start_and_trailers_exclude_compression():
    async def exchange(start_extra, extension):
        async def source(_scope, _receive, send):
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'content-type', b'application/json'), *start_extra]})
            await send(extension)
        events = []
        scope = {'type': 'http', 'method': 'GET', 'path': '/fixture',
                 'headers': [(b'accept-encoding', b'gzip')]}
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(message):
            events.append(message)
        await LargeJSONGZipMiddleware(source, minimum_size=512)(scope, receive, send)
        return events

    events = asyncio.run(exchange([], {'type': 'http.response.pathsend', 'path': '/fixture'}))
    assert [event['type'] for event in events] == [
        'http.response.start', 'http.response.pathsend']

    async def source(_scope, _receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'trailers': True,
                    'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': EXPECTED})
        await send({'type': 'http.response.trailers', 'headers': [(b'digest', b'test')]})
    events = []
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        events.append(message)
    asyncio.run(LargeJSONGZipMiddleware(source, minimum_size=512)(
        {'type': 'http', 'method': 'GET', 'path': '/fixture',
         'headers': [(b'accept-encoding', b'gzip')]}, receive, send))
    assert [event['type'] for event in events] == [
        'http.response.start', 'http.response.body', 'http.response.trailers']
    assert events[1]['body'] == EXPECTED
    assert not any(name == b'content-encoding' for name, _ in events[0]['headers'])


def test_sse_start_is_forwarded_before_delayed_first_event():
    async def check():
        started = asyncio.Event()
        release_body = asyncio.Event()
        events = []

        async def source(_scope, _receive, send):
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'content-type', b'text/event-stream')]})
            await release_body.wait()
            await send({'type': 'http.response.body', 'body': b'data: first\n\n'})

        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            events.append(message)
            if message['type'] == 'http.response.start':
                started.set()

        task = asyncio.create_task(LargeJSONGZipMiddleware(source, minimum_size=512)(
            {'type': 'http', 'method': 'GET', 'path': '/events',
             'headers': [(b'accept-encoding', b'gzip')]}, receive, send))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            assert [event['type'] for event in events] == ['http.response.start']
        finally:
            release_body.set()
            await task
        assert [event['type'] for event in events] == [
            'http.response.start', 'http.response.body']
        assert events[1]['body'] == b'data: first\n\n'

    asyncio.run(check())
