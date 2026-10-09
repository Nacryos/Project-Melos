"""Release T private mode: sign-in, sessions, CSRF, brute-force limits, and no private text
reaching a signed-out visitor through any endpoint.

All fixtures are synthetic. The owner's real password is never used or stored here: each test
run hashes a random password of its own.
"""
from __future__ import annotations

import ast
import json
import re
import secrets
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import private_auth, private_gate, private_store, server
from scripts import build_corpus, private_ingest

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "ZQXOWNERSENTINEL"
GREEK_SENTINEL = "ξυζυγοκρυπτόν"
ORIGIN = "https://testserver"
FILLER = " ".join(f"word{i}" for i in range(60))
PRIVATE_PAGE = (f"Commentary on the Muse. The line μοῦσα φωνή καλὴ μοῖρα is discussed here. {FILLER} "
                f"{SENTINEL} {GREEK_SENTINEL} private licensed note on μοῦσα.")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Endpoints under test must not reach any outside service."""
    original = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("network disabled in private-mode tests")
        return original(self, address, *args, **kwargs)
    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    raw = root / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("SYNTHETIC TEST FIXTURE", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    processed = root / "data/processed"
    processed.mkdir(parents=True)
    common = {"source": "synthetic-test-source", "source_url": "https://example.org/synthetic", "raw_path": "data/raw/synthetic.txt",
              "raw_sha256": digest, "edition": "Synthetic test edition", "language": "grc", "kind": "text",
              "quality": "source_text", "license": "test-only"}
    rows = [dict(common, id="p1", author="Alpha", work="Song", citation="1", text="μοῦσα φωνή καλὴ μοῖρα"),
            dict(common, id="p2", author="Alpha", work="Song", citation="2", text="μοῦσα κόσμος"),
            dict(common, id="p3", author="Beta", work="Song", citation="3", text="ἄνθος μοῦσα"),
            dict(common, id="t1", author="Alpha", work="Song", citation="1", text="Muse voice", language="eng",
                 kind="translation", parent_id="p1")]
    fixture_file = processed / "synthetic.jsonl"
    fixture_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {fixture_file.name: {
        "verdict": "PASS", "sha256": hashlib.sha256(fixture_file.read_bytes()).hexdigest(), "records": len(rows)}}}), encoding="utf-8")
    (reports / "collector.json").write_text(json.dumps({"raw_file": str(raw)}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "DB", root / "data/corpus.sqlite")
    build_corpus.build(server.DB)

    # Private store through the real ingestion pipeline.
    private = root / "melos-private"
    (private / "inbox").mkdir(parents=True)
    (private / "inbox" / "notes.txt").write_text(PRIVATE_PAGE + "\f" + "Second page about something else entirely.",
                                                 encoding="utf-8")
    (private / "inbox" / "notes.txt.json").write_text(json.dumps({
        "title": "Synthetic Commentary", "author": "Test Author", "year": 2001, "kind": "commentary", "language": "eng",
        "rights_basis": "synthetic test fixture", "owner_attestation": True, "citation": "Test, Synthetic Commentary (2001)",
        "passage_links": [{"passage_id": "p3", "page": 2}]}), encoding="utf-8")
    assert private_ingest.ingest(private, private / "originals") == 1
    assert private_ingest.link(private, server.DB, min_shared=1) >= 1
    monkeypatch.setenv("MELOS_PRIVATE_STORE", str(private / "store" / "private.sqlite"))

    password = secrets.token_urlsafe(16)
    auth = root / "secrets" / "owner_auth.env"
    auth.parent.mkdir()
    auth.write_text(f"MELOS_OWNER_USERNAME=Owner\nMELOS_OWNER_PASSWORD_HASH={private_auth.hash_password(password)}\n"
                    f"MELOS_OWNER_SESSION_KEY={secrets.token_hex(32)}\n", encoding="utf-8")
    monkeypatch.setenv("MELOS_OWNER_AUTH_FILE", str(auth))
    monkeypatch.delenv("MELOS_PUBLIC_DEPLOYMENT", raising=False)
    monkeypatch.delenv("MELOS_PRIVATE_PUBLIC_EXCERPTS", raising=False)
    private_auth.reset_state()
    yield {"password": password, "private": private, "root": root}
    private_auth.reset_state()


def client() -> TestClient:
    return TestClient(server.app, base_url=ORIGIN, raise_server_exceptions=False)


def login(c: TestClient, password: str, username: str = "Owner", headers: dict | None = None):
    token = c.get("/api/owner/login-token").json()["token"]
    base = {"Origin": ORIGIN, "X-Melos-CSRF": token}
    return c.post("/api/owner/login", json={"username": username, "password": password}, headers={**base, **(headers or {})})


def signed_in(env) -> TestClient:
    c = client()
    assert login(c, env["password"]).status_code == 200
    return c


# --------------------------------------------------------------------------- sign-in flow

def test_login_flow_cookie_attributes_and_logout(env):
    c = client()
    assert c.get("/api/owner/session").json() == {"signed_in": False}
    assert c.get("/api/private/search", params={"q": SENTINEL}).status_code == 404
    response = login(c, env["password"], username="owner")  # name is case-insensitive
    assert response.status_code == 200, response.text
    cookies = "\n".join(response.headers.get_list("set-cookie"))
    session_cookie = next(line for line in response.headers.get_list("set-cookie") if line.startswith(private_auth.SESSION_COOKIE))
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=43200"):
        assert attribute.lower() in session_cookie.lower()
    assert "Domain" not in session_cookie
    assert env["password"] not in cookies
    session = c.get("/api/owner/session").json()
    assert session["signed_in"] and session["username"] == "Owner" and session["csrf"]
    found = c.get("/api/private/search", params={"q": SENTINEL}).json()
    assert found["visibility"] == private_store.MARKER and SENTINEL in found["results"][0]["text"]
    assert found["results"][0]["label"] == "Private — owner only" and found["results"][0]["page"] == "1"
    assert "Test, Synthetic Commentary (2001), p. 1" == found["results"][0]["source"]
    assert c.get("/api/private/ui.js").status_code == 200
    old_cookie = c.cookies.get(private_auth.SESSION_COOKIE)
    out = c.post("/api/owner/logout", headers={"Origin": ORIGIN, "X-Melos-CSRF": session["csrf"]})
    assert out.status_code == 200
    assert c.get("/api/private/search", params={"q": SENTINEL}).status_code == 404
    replay = client()
    replay.cookies.set(private_auth.SESSION_COOKIE, old_cookie, domain="testserver.local")
    assert replay.get("/api/private/documents").status_code == 404


def test_owner_displays_passage_lemma_and_page(env):
    c = signed_in(env)
    passage = c.get("/api/private/passage", params={"id": "p1"}).json()
    assert passage["results"] and SENTINEL in passage["results"][0]["text"]
    manual = c.get("/api/private/passage", params={"id": "p3"}).json()
    assert [r["page"] for r in manual["results"]] == ["2"]
    lemma = c.get("/api/private/lemma", params={"lemma": "μοῦσα"}).json()
    assert lemma["results"] and lemma["results"][0]["visibility"] == private_store.MARKER
    docs = c.get("/api/private/documents").json()["results"]
    assert docs[0]["rights_basis"] == "synthetic test fixture" and docs[0]["pages"] == 2
    page = c.get("/api/private/page", params={"doc": docs[0]["doc_id"], "page": 2}).json()
    assert page["results"][0]["text"].startswith("Second page")
    assert all(str(env["private"]) not in json.dumps(x) for x in (passage, lemma, docs, page))


def test_wrong_credentials_and_lockout(env):
    c = client()
    for _ in range(private_auth.CLIENT_MAX_FAILURES):
        assert login(c, "wrong-password").status_code == 401
    locked = login(c, env["password"])
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert c.get("/api/owner/session").json() == {"signed_in": False}
    assert login(c, env["password"], headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200


def test_global_brute_force_limit_across_clients(env):
    c = client()
    for i in range(private_auth.GLOBAL_MAX_FAILURES):
        assert login(c, "nope", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code == 401
    assert login(c, env["password"], headers={"X-Forwarded-For": "192.0.2.77"}).status_code == 429


def test_wrong_username_rejected(env):
    assert login(client(), env["password"], username="Mallory").status_code == 401


# --------------------------------------------------------------------------- CSRF and fixation

def test_login_csrf(env):
    c = client()
    body = {"username": "Owner", "password": env["password"]}
    token = c.get("/api/owner/login-token").json()["token"]
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN}).status_code == 403  # no token
    assert c.post("/api/owner/login", json=body, headers={"Origin": "https://evil.example", "X-Melos-CSRF": token}).status_code == 403
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": token,
                                                         "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.post("/api/owner/login", content=json.dumps(body), headers={
        "Origin": ORIGIN, "X-Melos-CSRF": token, "Content-Type": "text/plain"}).status_code == 400
    other = client()
    foreign = other.get("/api/owner/login-token").json()["token"]  # a token for someone else's cookie
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": foreign}).status_code == 403
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": token}).status_code == 200
    # A token is single-use.
    again = client()
    again.cookies.set(private_auth.LOGIN_COOKIE, c.cookies.get(private_auth.LOGIN_COOKIE) or "x", domain="testserver.local")
    assert again.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": token}).status_code == 403


def test_login_token_cannot_be_replayed(env):
    c = client()
    token = c.get("/api/owner/login-token").json()["token"]
    cookie = c.cookies.get(private_auth.LOGIN_COOKIE)
    body = {"username": "Owner", "password": "wrong"}
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": token}).status_code == 401
    c.cookies.set(private_auth.LOGIN_COOKIE, cookie, domain="testserver.local")
    body["password"] = env["password"]
    assert c.post("/api/owner/login", json=body, headers={"Origin": ORIGIN, "X-Melos-CSRF": token}).status_code == 403


def test_logout_csrf(env):
    c = signed_in(env)
    csrf = c.get("/api/owner/session").json()["csrf"]
    assert c.post("/api/owner/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert c.post("/api/owner/logout", headers={"Origin": ORIGIN, "X-Melos-CSRF": "forged"}).status_code == 403
    assert c.post("/api/owner/logout", headers={"Origin": "https://evil.example", "X-Melos-CSRF": csrf}).status_code == 403
    assert c.get("/api/private/status").status_code == 200  # still signed in
    assert client().post("/api/owner/logout", headers={"Origin": ORIGIN, "X-Melos-CSRF": csrf}).status_code == 404


def test_session_fixation(env):
    # A cookie planted before sign-in is never adopted: sign-in mints a new id.
    c = client()
    c.cookies.set(private_auth.SESSION_COOKIE, "attacker-chosen-id.0000", domain="testserver.local")
    assert login(c, env["password"]).status_code == 200
    issued = c.cookies.get(private_auth.SESSION_COOKIE)
    assert not issued.startswith("attacker-chosen-id")
    # Signing in again from a valid session replaces it; the old id stops working.
    first = issued
    assert login(c, env["password"]).status_code == 200
    second = c.cookies.get(private_auth.SESSION_COOKIE)
    assert second != first
    stale = client()
    stale.cookies.set(private_auth.SESSION_COOKIE, first, domain="testserver.local")
    assert stale.get("/api/private/status").status_code == 404
    forged = client()
    forged.cookies.set(private_auth.SESSION_COOKIE, second.partition(".")[0] + "." + "0" * 64, domain="testserver.local")
    assert forged.get("/api/private/status").status_code == 404


def test_session_expiry(env, monkeypatch):
    c = signed_in(env)
    now = private_auth._now()
    monkeypatch.setattr(private_auth, "_now", lambda: now + private_auth.SESSION_TTL + 1)
    assert c.get("/api/private/status").status_code == 404


def test_https_only_on_public_deployment(env, monkeypatch):
    monkeypatch.setenv("MELOS_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.setenv("MELOS_OWNER_ORIGINS", ORIGIN)
    plain = TestClient(server.app, base_url="http://testserver", raise_server_exceptions=False)
    assert plain.get("/api/owner/login-token").status_code == 404
    c = client()
    assert c.get("/api/owner/login-token").status_code == 404  # TLS must be stated by the proxy
    c.headers["X-Forwarded-Proto"] = "https"
    assert login(c, env["password"]).status_code == 200
    assert c.get("/api/private/status").status_code == 200
    del c.headers["X-Forwarded-Proto"]
    assert c.get("/api/private/status").status_code == 404
    c.headers["X-Forwarded-Proto"] = "http"
    assert c.get("/api/private/status").status_code == 404
    # On the public deployment a POST without Origin is refused.
    c.headers["X-Forwarded-Proto"] = "https"
    token = c.get("/api/owner/login-token").json()["token"]
    assert c.post("/api/owner/login", json={"username": "Owner", "password": env["password"]},
                  headers={"X-Melos-CSRF": token}).status_code == 403


def test_private_mode_off_without_secrets(env, monkeypatch, tmp_path):
    monkeypatch.setenv("MELOS_OWNER_AUTH_FILE", str(tmp_path / "missing.env"))
    private_auth.reset_state()
    c = client()
    for path in ("/api/owner/session", "/api/owner/login-token", "/api/private/status"):
        assert c.get(path).status_code == 404
    assert c.post("/api/owner/login", json={}, headers={"Origin": ORIGIN}).status_code == 404


# --------------------------------------------------------------------------- no private text leaks

GUESSES = {"q": "μοῦσα private licensed note commentary", "id": "p1", "lemma": "μοῦσα", "word": "μοῦσα", "form": "μοῦσα", "doc": "x",
           "page": "1", "author": "Alpha", "work_id": "x", "query": "μοῦσα", "text": "μοῦσα", "passage_id": "p1",
           "lemmas": "μοῦσα", "concept": "μοῦσα", "term": "μοῦσα", "citation": "Alpha 1", "urn": "x", "ref": "x"}


def _api_routes():
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/"):
            yield route


def _leaks(text: str) -> list[str]:
    return [s for s in (SENTINEL, GREEK_SENTINEL, private_store.MARKER, "Synthetic Commentary", "melos-private")
            if s in text]


def test_every_endpoint_signed_out_returns_no_private_text(env):
    c = client()
    routes = list(_api_routes())
    assert len(routes) > 40
    checked = 0
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "p1", route.path)
        for method in sorted(route.methods or ()):
            if method == "GET":
                response = c.get(path, params=GUESSES)
            elif method == "POST":
                response = c.post(path, json={**GUESSES, "words": ["μοῦσα", "licensed"], "tokens": ["μοῦσα"],
                                              "passage": {"id": "p1", "text": "μοῦσα"}}, headers={"Origin": ORIGIN})
            else:
                continue
            checked += 1
            assert not _leaks(response.text), (method, path, response.status_code, response.text[:300])
            if path.startswith("/api/private/"):
                assert response.status_code == 404, path
    assert checked >= len(routes)


def test_signed_out_private_paths_are_404_even_unknown(env):
    c = client()
    for path in ("/api/private", "/api/private/", "/api/private/nope", "/api/private/../private/status",
                 "/api/private/search?q=x", "/api/private/ui.js"):
        assert c.get(path).status_code == 404, path
    c.cookies.set(private_auth.SESSION_COOKIE, "garbage", domain="testserver.local")
    assert c.get("/api/private/status").status_code == 404


def test_public_search_uses_private_signals_without_private_text(env):
    c = client()
    public = c.get("/api/search", params={"q": "μοῦσα", "match": "exact"})
    assert public.status_code == 200
    assert not _leaks(public.text)
    assert "reference_excerpt" not in public.text
    ids = [r["id"] for r in public.json()["results"]]
    assert ids and ids[0] == "p1"  # the passage the private commentary quotes ranks first
    scores, _ = private_gate.rank_signals("μοῦσα")
    assert "p1" in scores


def test_public_excerpt_is_short_and_cited(env, monkeypatch):
    monkeypatch.setenv("MELOS_PRIVATE_PUBLIC_EXCERPTS", "1")
    body = client().get("/api/search", params={"q": "μοῦσα", "match": "exact"}).json()
    excerpts = [r["reference_excerpt"] for r in body["results"] if "reference_excerpt" in r]
    assert excerpts
    for excerpt in excerpts:
        words = excerpt["text"].replace("…", " ").split()
        assert len(words) <= private_gate.MAX_EXCERPT_WORDS
        assert excerpt["source"] == "Test, Synthetic Commentary (2001)" and excerpt["page"]
        assert excerpt["visibility"] == private_gate.PUBLIC_EXCERPT
    assert private_gate.cited_excerpt("a " * 500, ["a"], "S", "1", max_words=400)["words"] == 30
    assert private_gate.cited_excerpt("text", ["t"], "", "1") is None


def test_guard_blocks_marker_in_any_signed_out_response(env):
    from fastapi.responses import JSONResponse
    path = "/api/__test_leaky"

    @server.app.get(path)
    def leaky():
        return JSONResponse({"oops": private_store.MARKER, "text": SENTINEL})

    try:
        response = client().get(path)
        assert response.status_code == 404 and SENTINEL not in response.text
        assert signed_in(env).get(path).status_code == 200
    finally:
        server.app.router.routes[:] = [r for r in server.app.router.routes if getattr(r, "path", "") != path]


def test_private_store_reached_only_through_the_gate():
    allowed = {"private_store.py", "private_gate.py", "private_mode.py", "private_schema.py"}
    for module in (ROOT / "backend").glob("*.py"):
        if module.name in allowed:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            assert not any(n.endswith("private_store") for n in names), module.name


def test_static_files_name_no_private_paths():
    static = [*ROOT.glob("*.html"), *(ROOT / "js").glob("*.js"), *(ROOT / "css").glob("*.css"), ROOT / "vercel.json"]
    for path in static:
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("melos-private", "storagebox", "/api/private", "private.sqlite", "owner_auth", "argon2"):
            assert needle not in text, (path.name, needle)


def test_ingest_rejects_files_without_valid_provenance(tmp_path):
    root = tmp_path / "p"
    (root / "inbox").mkdir(parents=True)
    (root / "inbox" / "a.txt").write_text("text", encoding="utf-8")
    (root / "inbox" / "b.txt").write_text("text", encoding="utf-8")
    (root / "inbox" / "b.txt.json").write_text(json.dumps({
        "title": "B", "kind": "edition", "rights_basis": "x", "citation": "B", "owner_attestation": True,
        "acquired_from": "downloaded from Library Genesis"}), encoding="utf-8")
    (root / "inbox" / "c.txt").write_text("text", encoding="utf-8")
    (root / "inbox" / "c.txt.json").write_text(json.dumps({"title": "C", "kind": "edition", "citation": "C"}), encoding="utf-8")
    assert private_ingest.ingest(root, root / "originals") == 0
    reasons = {p.name: p.read_text(encoding="utf-8") for p in (root / "rejected").glob("*.reason.txt")}
    assert "no provenance manifest" in reasons["a.txt.reason.txt"]
    assert "shadow library" in reasons["b.txt.reason.txt"]
    assert "owner_attestation" in reasons["c.txt.reason.txt"] and "rights_basis" in reasons["c.txt.reason.txt"]
    assert not list((root / "inbox").iterdir())
