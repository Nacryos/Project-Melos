"""Release W: the owner-only composer (docs/prd/composer-agent.md): store, owner gate, internal agent token, the
agent proxy (SSE relay, 503 when the agent is down) and the lint bank behind POST /api/composer/check.

Synthetic fixtures only: each run hashes a random owner password; the agent is a fake ASGI app.
"""
from __future__ import annotations

import json
import re
import secrets
import socket
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend import composer_access, composer_lint, composer_routes, composer_store as store, private_auth, server

ORIGIN = "https://testserver"
TOKEN = "t" * 20 + secrets.token_hex(16)
SAPPHIC = "ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    original = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("network disabled in composer tests")
        return original(self, address, *args, **kwargs)
    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    password = secrets.token_urlsafe(16)
    auth = tmp_path / "secrets" / "owner_auth.env"
    auth.parent.mkdir()
    auth.write_text(f"MELOS_OWNER_USERNAME=Owner\nMELOS_OWNER_PASSWORD_HASH={private_auth.hash_password(password)}\n"
                    f"MELOS_OWNER_SESSION_KEY={secrets.token_hex(32)}\n", encoding="utf-8")
    token_file = tmp_path / "secrets" / "composer_agent_token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("MELOS_OWNER_AUTH_FILE", str(auth))
    monkeypatch.setenv("MELOS_COMPOSER_DB", str(tmp_path / "runtime" / "composer.sqlite"))
    monkeypatch.setenv("MELOS_COMPOSER_AGENT_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("MELOS_COMPOSER_AGENT_TOKEN", raising=False)
    monkeypatch.delenv("MELOS_PUBLIC_DEPLOYMENT", raising=False)
    monkeypatch.setattr(server, "DB", tmp_path / "no-corpus.sqlite")
    monkeypatch.setattr(composer_routes, "_transport", None)
    private_auth.reset_state()
    yield {"password": password, "tmp": tmp_path, "token_file": token_file}
    private_auth.reset_state()


def client() -> TestClient:
    return TestClient(server.app, base_url=ORIGIN, raise_server_exceptions=False)


def signed_in(env) -> TestClient:
    c = client()
    token = c.get("/api/owner/login-token").json()["token"]
    r = c.post("/api/owner/login", json={"username": "Owner", "password": env["password"]},
               headers={"Origin": ORIGIN, "X-Melos-CSRF": token})
    assert r.status_code == 200, r.text
    return c


def owner_routes():
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if composer_access.owner_only_path(path):
            for method in sorted(route.methods or ()):
                yield method, path


# --------------------------------------------------------------------------- store

def test_store_schema_is_versioned_and_versions_chat_append_only(env):
    poem = store.create_poem("Ode", {"metre": "sapphic"}, "Deathless Aphrodite")
    with store._read() as con:
        assert [r[0] for r in con.execute("SELECT version FROM schema_migrations")] == [1]
    store._ready.clear()
    store.connect().close()                                      # migrating again is a no-op
    with store._read() as con:
        assert con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    line = store.insert_line(poem["id"])
    v1 = store.add_version(line["id"], "πρῶτον", source="owner")
    store.add_chat(poem["id"], "user", "hello")
    with store._read() as con:
        for sql in ("DELETE FROM versions", "UPDATE versions SET greek='x'", "DELETE FROM chat", "UPDATE chat SET content='x'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)
    assert store.update_version(v1["id"], back_translation="first")["back_translation"] == "first"
    with pytest.raises(store.StoreError):
        store.add_version(line["id"], "x", source="robot")
    with pytest.raises(store.StoreError):
        store.add_chat(poem["id"], "system", "x")


def test_store_lines_positions_versions_and_full(env):
    pid = store.create_poem("P")["id"]
    a = store.insert_line(pid)
    b = store.insert_line(pid)
    c = store.insert_line(pid, 0)                                 # insert at the top: a, b move down
    order = lambda: [line["id"] for line in store.full(pid)["lines"]]  # noqa: E731
    assert order() == [c["id"], a["id"], b["id"]]
    store.update_line(c["id"], position=2)
    assert order() == [a["id"], b["id"], c["id"]]
    store.update_line(c["id"], position=0)
    assert order() == [c["id"], a["id"], b["id"]]
    assert [line["position"] for line in store.full(pid)["lines"]] == [0, 1, 2]
    v1 = store.add_version(a["id"], "ἕν")
    v2 = store.add_version(a["id"], "δύο", source="agent", note="from the pool")
    assert store.get_line(a["id"])["current_version_id"] == v2["id"]
    store.update_line(a["id"], current_version_id=v1["id"])
    assert store.get_line(a["id"])["current_version_id"] == v1["id"]
    with pytest.raises(store.StoreError):
        store.update_line(b["id"], current_version_id=v1["id"])  # a version of another line
    store.update_version(v1["id"], archived=True)                 # current falls back to the newest live version
    assert store.get_line(a["id"])["current_version_id"] == v2["id"]
    for i in range(205):
        store.add_chat(pid, "user" if i % 2 else "assistant", f"m{i}", {"i": i} if i % 2 == 0 else None)
    full = store.full(pid)
    line_a = next(line for line in full["lines"] if line["id"] == a["id"])
    assert [v["greek"] for v in line_a["versions"]] == ["ἕν", "δύο"] and line_a["versions"][0]["archived"]
    assert line_a["current"]["greek"] == "δύο"
    assert len(full["chat"]) == 200 and full["chat"][-1]["content"] == "m204" and full["chat"][0]["content"] == "m5"
    ctx = store.agent_context(pid, {"line_position": 1, "char_offset": 2, "prefix": "δ"})
    assert ctx["lines"][1] == {"position": 1, "line_id": a["id"], "greek": "δύο", "back_translation": None}
    assert ctx["caret"]["prefix"] == "δ" and ctx["poem_id"] == pid


# --------------------------------------------------------------------------- owner gate

def test_every_composer_route_and_the_page_are_404_signed_out(env):
    c = client()
    routes = list(owner_routes())
    paths = {p for _, p in routes}
    for needed in ("/composer", "/composer.html", "/api/compose/suggest", "/api/compose/status", "/api/composer/check",
                   "/api/composer/poems", "/api/composer/poems/{poem_id}/full", "/api/composer/poems/{poem_id}/chat",
                   "/api/composer/poems/{poem_id}/pool", "/api/composer/backtranslate", "/api/composer/lines/{line_id}",
                   "/api/composer/lines/{line_id}/versions", "/api/composer/versions/{version_id}"):
        assert needed in paths, needed
    store.create_poem("secret poem title")
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = c.request(method, url, json={"greek": "x", "message": "x", "title": "x"}, headers={"Origin": ORIGIN})
        assert response.status_code == 404, (method, url, response.status_code)
        assert "secret poem" not in response.text and "<html" not in response.text.lower()
    for url in ("/api/composer", "/api/composer/", "/api/composer/nope", "/api/compose/nope", "/composer/"):
        assert c.get(url).status_code == 404, url
    # A forged session cookie is still signed out.
    c.cookies.set(private_auth.SESSION_COOKIE, "forged.cookie")
    assert c.get("/api/composer/poems").status_code == 404
    assert c.get("/composer").status_code == 404


def test_owner_reaches_the_page_and_the_api(env):
    c = signed_in(env)
    page = c.get("/composer")
    assert page.status_code == 200 and "<title>Composer" in page.text and page.headers["cache-control"] == "no-store"
    assert c.get("/composer.html").status_code == 200
    assert c.get("/api/compose/status").status_code == 200
    created = c.post("/api/composer/poems", json={"title": "Hymn", "settings": {"author": "Sappho"}}, headers={"Origin": ORIGIN})
    assert created.status_code == 200
    pid = created.json()["id"]
    assert c.get("/api/composer/poems").json()["poems"][0]["title"] == "Hymn"
    assert c.patch(f"/api/composer/poems/{pid}", json={"english": "Deathless"}, headers={"Origin": ORIGIN}).json()["english"] == "Deathless"
    # Changes must come from the site itself.
    assert c.post("/api/composer/poems", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/composer/poems/999").status_code == 404
    # Signing out closes it again.
    csrf = c.get("/api/owner/session").json()["csrf"]
    assert c.post("/api/owner/logout", headers={"Origin": ORIGIN, "X-Melos-CSRF": csrf}).status_code == 200
    assert c.get("/composer").status_code == 404 and c.get("/api/composer/poems").status_code == 404


def test_saved_version_is_scanned_and_linted(env):
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"settings": {"metre": "sapphic", "author": "Sappho"}},
                 headers={"Origin": ORIGIN}).json()["id"]
    line = c.post(f"/api/composer/poems/{pid}/lines", json={"greek": SAPPHIC}, headers={"Origin": ORIGIN}).json()
    version = line["version"]
    assert version["source"] == "owner" and version["scansion"]["lines"][0]["pattern"]
    l7 = next(ch for ch in version["checks"] if ch["id"] == "L7")
    assert l7["ok"] is True and l7["blocking"] is True
    # No corpus index here: L1 is reported as not run, never as passed.
    assert next(ch for ch in version["checks"] if ch["id"] == "L1")["ok"] is None
    second = c.post(f"/api/composer/lines/{line['id']}/versions", json={"greek": "λόγος", "source": "agent", "note": "try"},
                    headers={"Origin": ORIGIN}).json()
    assert next(ch for ch in second["checks"] if ch["id"] == "L7")["ok"] is False
    assert c.patch(f"/api/composer/versions/{version['id']}", json={"make_current": True}, headers={"Origin": ORIGIN}).status_code == 200
    full = c.get(f"/api/composer/poems/{pid}/full").json()
    assert full["lines"][0]["current_version_id"] == version["id"] and len(full["lines"][0]["versions"]) == 2
    assert c.post(f"/api/composer/lines/{line['id']}/versions", json={"greek": "x", "source": "robot"},
                  headers={"Origin": ORIGIN}).status_code == 422


# --------------------------------------------------------------------------- internal agent token

def test_internal_token_opens_only_the_lint_route(env):
    c = client()
    good = {"X-Composer-Token": TOKEN}
    r = c.post("/api/composer/check", json={"greek": SAPPHIC, "metre": "sapphic"}, headers=good)
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"pass", "scansion", "checks"}
    assert c.post("/api/composer/check", json={"greek": SAPPHIC}, headers={"X-Composer-Token": TOKEN[:-1] + "x"}).status_code == 404
    assert c.post("/api/composer/check", json={"greek": SAPPHIC}).status_code == 404
    # Through the public proxy chain (X-Forwarded-For) the token does not open it.
    assert c.post("/api/composer/check", json={"greek": SAPPHIC},
                  headers={**good, "X-Forwarded-For": "203.0.113.9"}).status_code == 404
    # Nothing else: owner, private and the rest of the composer stay closed.
    for method, url in (("GET", "/api/private/status"), ("GET", "/api/private/search?q=x"), ("POST", "/api/owner/logout"),
                        ("GET", "/api/composer/poems"), ("POST", "/api/composer/poems"), ("GET", "/composer"),
                        ("POST", "/api/composer/backtranslate"), ("POST", "/api/compose/suggest")):
        response = c.request(method, url, json={"greek": "x", "text": "x"}, headers=good)
        assert response.status_code == 404, (method, url, response.status_code)
    assert c.get("/api/owner/session", headers=good).json() == {"signed_in": False}


def test_internal_token_off_when_missing_or_short(env, monkeypatch):
    env["token_file"].write_text("short", encoding="utf-8")
    assert composer_access.internal_token() is None
    assert client().post("/api/composer/check", json={"greek": SAPPHIC}, headers={"X-Composer-Token": "short"}).status_code == 404
    monkeypatch.setenv("MELOS_COMPOSER_AGENT_TOKEN_FILE", str(env["tmp"] / "missing"))
    monkeypatch.setenv("MELOS_COMPOSER_AGENT_TOKEN", TOKEN)
    assert composer_access.internal_token() == TOKEN


def test_internal_token_lifts_tool_rate_limits_only(env, monkeypatch):
    from backend import rate_limit
    monkeypatch.setattr(rate_limit, "_LIMITER", rate_limit.RateLimiter(client_minute=2, client_day=5, connection_minute=5))
    c = client()
    body = {"text": "λόγος", "lexicon": False}
    xff = {"X-Forwarded-For": "198.51.100.7"}
    codes = [c.post("/api/scan", json=body, headers=xff).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    codes = [c.post("/api/scan", json=body, headers={**xff, "X-Composer-Token": TOKEN}).status_code for _ in range(5)]
    assert codes == [200] * 5
    assert c.post("/api/scan", json=body, headers={**xff, "X-Composer-Token": "wrong" * 10}).status_code == 429
    assert composer_access.internal_tool_path("/api/lemma/search") and not composer_access.internal_tool_path("/api/private/x")


# --------------------------------------------------------------------------- agent proxy

def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _data(event):
    return ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()


def fake_agent(seen: list):
    app = FastAPI()

    @app.post("/chat")
    async def chat(payload: dict):
        seen.append(("chat", payload))

        async def stream():   # the agent service's format (docs/composer/agent.md): data-only typed events
            yield b": keep-alive\n\n"
            yield _data({"type": "text", "delta": "Sappho "})
            yield _data({"type": "tool", "name": "lemma_search", "summary": "q=ἔρος"})
            yield _data({"type": "text", "delta": "uses it."})
            yield _data({"type": "done", "usage": {"input_tokens": 10, "output_tokens": 5}, "cost_usd": 0.01})
        return StreamingResponse(stream(), media_type="text/event-stream")

    async def pool_stream(payload: dict):
        for i in range(3):
            yield _data({"type": "candidate", "greek": f"λόγος {i}", "english_span": "word",
                         "checks": [{"id": "L7", "ok": True, "blocking": True}]})
        for a in payload.get("ahead") or []:      # the stanza batch: candidates for later slots carry their key
            yield _data({"type": "candidate", "greek": f"ἔπειτα {a['line_position']}", "slot_key": a["slot_key"],
                         "line_position": a["line_position"], "prefix": "", "checks": []})
            yield _data({"type": "candidate", "greek": "replayed", "slot_key": a["slot_key"], "replay": True})
        yield _data({"type": "candidate", "greek": "foreign", "slot_key": "not-a-requested-key", "checks": []})
        yield _data({"type": "rejected", "count": 1, "reasons": {"L7": 1}})
        yield _data({"type": "done", "usage": {}, "cost_usd": 0})

    @app.post("/pool")
    async def pool(payload: dict):
        seen.append(("pool", payload))
        return StreamingResponse(pool_stream(payload), media_type="text/event-stream")

    @app.post("/warm")
    async def warm(payload: dict):
        seen.append(("warm", payload))
        return StreamingResponse(pool_stream(payload), media_type="text/event-stream")

    @app.post("/backtranslate")
    async def back(payload: dict):
        seen.append(("backtranslate", payload))
        return {"english": "word", "dialect": payload.get("dialect")}

    @app.middleware("http")
    async def token_header(request, call_next):
        seen.append(("token", request.headers.get("x-composer-token")))
        return await call_next(request)

    return app


@pytest.fixture
def agent(monkeypatch):
    seen = []
    monkeypatch.setattr(composer_routes, "_transport", httpx.ASGITransport(app=fake_agent(seen)))
    return seen


def test_chat_relays_sse_unchanged_and_stores_the_exchange(env, agent):
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"title": "T", "english": "Eros again"}, headers={"Origin": ORIGIN}).json()["id"]
    c.post(f"/api/composer/poems/{pid}/lines", json={"greek": "Ἔρος δηὖτέ μ’ ὀ λυσιμέλης δόνει"}, headers={"Origin": ORIGIN})
    store.add_chat(pid, "assistant", "earlier answer")
    r = c.post(f"/api/composer/poems/{pid}/chat", json={"message": "How does Sappho use ἔρος?",
                                                       "caret": {"line_position": 0, "char_offset": 3, "prefix": "Ἔρ"}},
               headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.content.startswith(b": keep-alive\n\n") and _data({"type": "text", "delta": "uses it."}) in r.content
    kind, payload = next(x for x in agent if x[0] == "chat")
    assert payload["message"] == "How does Sappho use ἔρος?"
    assert payload["thread"] == [{"role": "assistant", "content": "earlier answer"}]
    ctx = payload["poem"]
    assert ctx["english"] == "Eros again" and ctx["lines"][0]["greek"].startswith("Ἔρος") and ctx["caret"]["prefix"] == "Ἔρ"
    assert ("token", TOKEN) in agent
    chat = c.get(f"/api/composer/poems/{pid}/full").json()["chat"]
    assert [m["role"] for m in chat] == ["assistant", "user", "assistant"]
    assert chat[-1]["content"] == "Sappho uses it."
    events = [t.get("event") for t in chat[-1]["trace"]]
    assert events == ["tool", "done"] and chat[-1]["trace"][1]["data"]["cost_usd"] == 0.01


def test_pool_relays_and_stores_candidates(env, agent):
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"settings": {"metre": "sapphic"}}, headers={"Origin": ORIGIN}).json()["id"]
    r = c.post(f"/api/composer/poems/{pid}/pool", json={"caret": {"line_position": 0, "char_offset": 4}, "prefix": "ποι",
                                                       "remaining_template": "-u-x-uu-u-F", "n": 3}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.content.count(b'"type": "candidate"') == 3 + 3 * 2 + 1
    key = composer_routes.slot_key(0, "ποι", {"metre": "sapphic"})
    stored = c.get(f"/api/composer/poems/{pid}/pool", params={"slot_key": key}).json()["pool"]
    # the current slot's candidates, plus one whose key was not asked for (filed under the current slot)
    assert [p["candidate"]["greek"] for p in stored] == ["λόγος 0", "λόγος 1", "λόγος 2", "foreign"]
    payload = next(p for k, p in agent if k == "pool")
    assert payload["n"] == 3 and set(payload) == {"poem", "slot", "ahead", "n"}
    assert payload["slot"] | {} == {"line_position": 0, "caret": 4, "prefix": "ποι", "remaining_template": "-u-x-uu-u-F",
                                   "line_id": None, "slot_key": key}
    # the rest of the Sapphic stanza: lines 1-3, the last an adonean
    assert [(a["line_position"], a["remaining_template"], a["prefix"]) for a in payload["ahead"]] == [
        (1, "-u-x-uu-u-F", ""), (2, "-u-x-uu-u-F", ""), (3, "-uu-F", "")]
    for a in payload["ahead"]:
        assert a["slot_key"] == composer_routes.slot_key(a["line_position"], "", {"metre": "sapphic"})
        later = c.get(f"/api/composer/poems/{pid}/pool", params={"slot_key": a["slot_key"]}).json()["pool"]
        assert [p["candidate"]["greek"] for p in later] == [f"ἔπειτα {a['line_position']}"]    # replays not stored twice
    assert stored[0]["checks"] == [{"id": "L7", "ok": True, "blocking": True}] and stored[0]["candidate"]["type"] == "candidate"
    assert c.get(f"/api/composer/poems/{pid}/pool", params={"slot_key": "other"}).json()["pool"] == []


def test_slot_key_formula_is_shared_with_the_page():
    # The same vectors are asserted in tests/composer-core.test.mjs (ComposerCore.slotKey).
    assert composer_routes.slot_key(0, "", {"author": "Sappho", "metre": "sapphic", "dialect": "aeolic"}) == "3e5d5780d5992aabffe8ed380744d64a"
    assert composer_routes.slot_key(2, "  ἄστερες  μὲν ", {"metre": "sapphic"}) == "ea66ae8e0ea3c660a5e7c0ef8dd45ecd"
    assert composer_routes.slot_key(2, "ἄστερες μὲν", {"metre": "sapphic", "author": None}) == "ea66ae8e0ea3c660a5e7c0ef8dd45ecd"


def test_ahead_slots_skip_written_lines_and_reach_into_the_next_stanza(env):
    ctx = {"settings": {"metre": "sapphic"}, "lines": [{"position": 2, "line_id": 7, "greek": "γέγραπται"},
                                                      {"position": 1, "line_id": 6, "greek": ""}]}
    assert [(a["line_position"], a["line_id"]) for a in composer_routes.ahead_slots(ctx, 0)] == [(1, 6), (3, None)]
    assert [a["line_position"] for a in composer_routes.ahead_slots(ctx, 3)] == [4, 5]      # stanza end: two more
    assert composer_routes.ahead_slots({"settings": {"metre": "auto"}, "lines": []}, 0) == []
    assert composer_routes.ahead_slots(ctx, 0, limit=0) == []


def test_warm_starts_in_the_background_and_stores_every_slot(env, agent):
    with signed_in(env) as c:
        pid = c.post("/api/composer/poems", json={"settings": {"metre": "sapphic", "author": "Sappho"}, "english": "Moon"},
                     headers={"Origin": ORIGIN}).json()["id"]
        c.post(f"/api/composer/poems/{pid}/lines", json={"greek": SAPPHIC}, headers={"Origin": ORIGIN})
        r = c.post(f"/api/composer/poems/{pid}/warm", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 202 and r.json()["started"] is True
        keys = r.json()["slot_keys"]
        payload = next(p for k, p in agent if k == "warm")
        assert payload["slot"]["line_position"] == 1 and payload["slot"]["remaining_template"] == "-u-x-uu-u-F"
        assert payload["slot"]["slot_key"] == keys[0] == composer_routes.slot_key(1, "", {"metre": "sapphic", "author": "Sappho"})
        assert [a["line_position"] for a in payload["ahead"]] == [2, 3] and payload["poem"]["english"] == "Moon"
        deadline = time.time() + 3
        while len(c.get(f"/api/composer/poems/{pid}/pool", params={"slot_key": keys[-1]}).json()["pool"]) < 1:
            assert time.time() < deadline
            time.sleep(0.02)
        assert len(c.get(f"/api/composer/poems/{pid}/pool", params={"slot_key": keys[0]}).json()["pool"]) == 4
        # already filled enough: nothing new is started
        for k in keys[1:]:
            for i in range(4):
                store.add_pool(pid, k, {"greek": f"x{i}"}, [])
        again = c.post(f"/api/composer/poems/{pid}/warm", json={}, headers={"Origin": ORIGIN})
        assert again.status_code == 200 and again.json() == {"started": False, "reason": "filled", "slot_keys": keys}
        assert len([k for k, _ in agent if k == "warm"]) == 1


def test_warm_needs_a_metre_and_the_owner(env, agent):
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"settings": {"metre": "auto"}}, headers={"Origin": ORIGIN}).json()["id"]
    r = c.post(f"/api/composer/poems/{pid}/warm", json={}, headers={"Origin": ORIGIN})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "template_required"
    assert client().post(f"/api/composer/poems/{pid}/warm", json={}, headers={"Origin": ORIGIN}).status_code == 404
    assert client().get(f"/api/composer/poems/{pid}/slot-key").status_code == 404
    assert not [k for k, _ in agent if k == "warm"]


def test_backtranslate_returns_agent_json(env, agent):
    c = signed_in(env)
    r = c.post("/api/composer/backtranslate", json={"greek": "λόγος", "dialect": "aeolic"}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.json() == {"english": "word", "dialect": "aeolic"}


def test_agent_down_is_503_with_no_fallback(env, monkeypatch):
    monkeypatch.setenv("MELOS_COMPOSER_AGENT_URL", "http://127.0.0.1:9")   # nothing listens on the discard port
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"settings": {"metre": "sapphic"}}, headers={"Origin": ORIGIN}).json()["id"]
    for url, body in ((f"/api/composer/poems/{pid}/chat", {"message": "hi"}),
                      (f"/api/composer/poems/{pid}/pool", {"prefix": "", "n": 2, "remaining_template": "-uu-F"}),
                      (f"/api/composer/poems/{pid}/warm", {}),
                      ("/api/composer/backtranslate", {"greek": "λόγος"})):
        r = c.post(url, json=body, headers={"Origin": ORIGIN})
        assert r.status_code == 503 and r.json()["agent"] == "unavailable", (url, r.text)
    assert c.get(f"/api/composer/poems/{pid}/full").json()["chat"] == []      # nothing stored for a failed call


def test_sse_parser_handles_split_chunks():
    p = composer_routes.SSEParser()
    raw = _sse("candidate", {"greek": "α"}) + b"event: text\r\ndata: plain\r\n\r\n" + b": comment\n\n"
    out = []
    for i in range(0, len(raw), 7):
        out += p.feed(raw[i:i + 7])
    assert out == [("candidate", {"greek": "α"}), ("text", "plain")]


# --------------------------------------------------------------------------- lint bank

def test_agent_lint_shape_continuation_without_prefix(env):
    """The agent service's exact request (docs/composer/agent.md): the continuation alone + the open slots."""
    body = {"greek": "ἀθανάτ’ Ἀφρόδιτα", "metre": "sapphic", "dialect": "aeolic", "author": "Sappho",
            "remaining_template": "-uu-u-F"}
    r = client().post("/api/composer/check", json=body, headers={"X-Composer-Token": TOKEN})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["pass"] is True and out["scansion"]["fit"][0]["remaining_template"] == ""
    assert {"id", "ok", "blocking", "detail"} <= set(out["checks"][0])
    # The same words at the start of the line do not fit: the slots matter.
    wrong = client().post("/api/composer/check", json={**body, "remaining_template": "-u-x-uu-u-F"},
                          headers={"X-Composer-Token": TOKEN}).json()
    assert wrong["pass"] is False and wrong["checks"][0]["id"] == "L7" and wrong["checks"][0]["blocking"]
    # A shorter continuation may fill only the first slots of a longer remainder.
    short = client().post("/api/composer/check", json={**body, "greek": "ποικιλόθρον’", "remaining_template": "-u-x-uu-u-F"},
                          headers={"X-Composer-Token": TOKEN}).json()
    assert short["pass"] is True and short["scansion"]["fit"][0]["remaining_template"] == "-uu-u-F"
    assert client().post("/api/composer/check", json={**body, "metre": "auto"}, headers={"X-Composer-Token": TOKEN}).status_code == 200


def test_check_continuation_against_remaining_template():
    first = composer_lint.check("ποικιλόθρον’", metre_name="sapphic", remaining_template="-u-x-uu-u-F")
    l7 = first["checks"][0]
    assert first["pass"] and l7["ok"] and first["scansion"]["fit"][0]["remaining_template"] == "-uu-u-F"
    rest = composer_lint.check("ἀθανάτ’ Ἀφρόδιτα", metre_name="sapphic", remaining_template="-uu-u-F",
                               prefix="ποικιλόθρον’")
    assert rest["pass"] and rest["scansion"]["fit"][0]["remaining_template"] == ""
    bad = composer_lint.check("ἀθανάτ’ Ἀφρόδιτα", remaining_template="uu-")
    assert not bad["pass"] and bad["checks"][0]["blocking"]
    with pytest.raises(Exception):
        composer_lint.check("λόγος", remaining_template="-q-")


def test_dialect_check_blocks_a_word_with_an_attested_dialect_spelling(monkeypatch):
    monkeypatch.setattr(composer_lint, "_dialect_spellings",
                        lambda form, d, a: (("σελάννα", "Sappho 34"),) if form == "σελήνη" else ())
    rows = [{"form": "σελήνη", "tokens": 40, "dialect_tokens": 0, "other_dialects": {}},
            {"form": "κάλα", "tokens": 3, "dialect_tokens": 2, "other_dialects": {"lesbian": 2}},
            {"form": "ἄγνωστον", "tokens": 5, "dialect_tokens": 0, "other_dialects": {}}]
    c = composer_lint.dialect_check(rows, "aeolic", "Sappho")
    assert c["ok"] is False and c["blocking"] and "σελάννα" in c["detail"]
    assert c["evidence"][0]["form"] == "σελήνη" and len(c["evidence"]) == 1
    ionic = composer_lint.dialect_check([{"form": "σελάννα", "tokens": 4, "other_dialects": {"lesbian": 4}}], "ionic", "")
    assert ionic["ok"] is False and ionic["blocking"] is False
    assert composer_lint.dialect_check(rows, "none", "")["ok"] is True


def test_verbatim_runs_found_in_the_corpus(monkeypatch):
    from backend.textutils import normalize
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE passages (id TEXT, author TEXT, citation TEXT)")
    con.execute("CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized)")
    text = "δέδυκε μὲν ἀ σελάννα καὶ Πληΐαδες"
    con.execute("INSERT INTO passages VALUES ('s168b','Sappho','168B')")
    con.execute("INSERT INTO passage_fts VALUES ('s168b', ?)", (normalize(text),))

    class Keep:
        def __enter__(self):
            return con

        def __exit__(self, *_):
            return False
    monkeypatch.setattr(server, "connect", lambda: Keep())
    composer_lint._phrase_in_corpus.cache_clear()
    found = composer_lint.verbatim_check("ἐγὼ δέδυκε μὲν ἀ σελάννα νῦν".split())
    assert found["ok"] is False and found["blocking"] is False
    assert found["evidence"] == [{"words": "δέδυκε μὲν ἀ σελάννα", "passage_id": "s168b", "author": "Sappho", "citation": "168B"}]
    assert composer_lint.verbatim_check("ἐγὼ δέδυκε μὲν νῦν".split())["ok"] is True
    composer_lint._phrase_in_corpus.cache_clear()


def test_check_is_fast_without_the_corpus():
    composer_lint.check(SAPPHIC, metre_name="sapphic")             # warm the grammar
    t0 = time.perf_counter()
    for _ in range(10):
        composer_lint.check(SAPPHIC, metre_name="sapphic", author="Sappho")
    assert (time.perf_counter() - t0) / 10 < 0.3


def test_pool_requires_a_concrete_template(env, agent):
    c = signed_in(env)
    pid = c.post("/api/composer/poems", json={"settings": {"metre": "auto"}}, headers={"Origin": ORIGIN}).json()["id"]
    for bad in ({}, {"remaining_template": ""}, {"remaining_template": "-q-"}):
        r = c.post(f"/api/composer/poems/{pid}/pool", json={"prefix": "", "n": 2, **bad}, headers={"Origin": ORIGIN})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "template_required"
    assert not [k for k, _ in agent if k == "pool"]                      # nothing reached the agent


def test_agent_check_without_template_fails_l7(env):
    out = client().post("/api/composer/check", json={"greek": SAPPHIC, "metre": "auto"},
                        headers={"X-Composer-Token": TOKEN}).json()
    l7 = out["checks"][0]
    assert out["pass"] is False and l7["ok"] is False and l7["blocking"] and l7["template"] == "missing"
    assert "remaining_template" in l7["detail"] and out["scansion"]["template"] == "missing"
    # The owner's own check of the same line only scans it.
    assert composer_lint.check(SAPPHIC, metre_name=None)["pass"] is True


def test_budget_unresolved_words_fail_l1_l2_and_caches_make_repeats_instant(monkeypatch):
    calls = []

    def slow_lemma(spelling, author):
        calls.append(spelling)
        time.sleep(0.5 if spelling.startswith("βραδ") else 0)
        return "λόγος"

    def row(printed, target, author):
        time.sleep(0.5 if printed.startswith("βραδ") else 0)
        return {"form": printed, "tokens": 3, "headwords": [], "dialect_tokens": 2, "author_tokens": 1,
                "example": None, "other_dialects": {"lesbian": 2}}
    composer_lint._headline_lemma.cache_clear()
    monkeypatch.setattr(composer_lint, "_headline_lemma", composer_lint.lru_cache(maxsize=64)(slow_lemma))
    monkeypatch.setattr(composer_lint, "attestation_row", row)
    monkeypatch.setattr(composer_lint, "verbatim_check", lambda words: {"id": "L11", "name": "verbatim", "ok": True,
                                                                        "blocking": False, "detail": "", "evidence": []})
    monkeypatch.setenv("MELOS_COMPOSER_CHECK_BUDGET_MS", "200")
    t0 = time.perf_counter()
    out = composer_lint.check("λόγος βραδύς", dialect="aeolic", author="Sappho")
    assert time.perf_counter() - t0 < 0.45                                # the budget, not the slow lookup
    by = {c["id"]: c for c in out["checks"]}
    for cid in ("L1", "L2"):
        assert by[cid]["ok"] is False and by[cid]["blocking"] and "timeout" in by[cid]["detail"] and "βραδύς" in by[cid]["detail"]
    assert out["pass"] is False and out["budget_ms"] == 200
    time.sleep(0.6)                                                      # the lookup finishes in the background
    composer_lint._headline_lemma("βραδύς", "Sappho")                     # ... and is cached (no second call)
    assert calls.count("βραδύς") == 1


def test_elision_marks_fold_to_the_corpus_spelling():
    for typed in ("ἀθανάτ'", "ἀθανάτ᾽", "ἀθανάτʼ", "ἀθανάτ’", "ἀθανάτ’,"):
        assert composer_lint.corpus_spelling(typed) == "ἀθανάτ’"
    assert composer_lint.corpus_spelling("μ᾿") == "μ᾿"                   # psili is a distinct sign


def test_verbatim_flags_a_short_whole_colon(monkeypatch):
    from backend.textutils import normalize
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE passages (id TEXT, author TEXT, citation TEXT)")
    con.execute("CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized)")
    con.execute("INSERT INTO passages VALUES ('fr1','Sappho','1')")
    con.execute("INSERT INTO passage_fts VALUES ('fr1', ?)", (normalize("ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα, παῖ Δίος δολόπλοκε"),))

    class Keep:
        def __enter__(self):
            return con

        def __exit__(self, *_):
            return False
    monkeypatch.setattr(server, "connect", lambda: Keep())
    composer_lint._phrase_in_corpus.cache_clear()
    out = composer_lint.verbatim_check("ποικιλόθρον' ἀθανάτ' Ἀφρόδιτα".split())    # 3 words, ASCII apostrophes
    assert out["ok"] is False and out["evidence"][0]["citation"] == "1"
    assert composer_lint.verbatim_check("Δίος δολόπλοκε".split())["ok"] is True       # 2 words: not flagged
    assert composer_lint._qualifies("παῖ Δίος ἄγε".split()) is False                 # 3 short words
    assert composer_lint._qualifies("παῖ Δίος δολόπλοκε".split()) is True
    composer_lint._phrase_in_corpus.cache_clear()
