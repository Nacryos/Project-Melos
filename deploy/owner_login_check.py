"""End-to-end owner sign-in check against a running API (local server or the T canary).

    printf '%s\n' "$PASSWORD" | python3 owner_login_check.py http://127.0.0.1:8792 --username Alvin \
        --origin https://greeklyric.com --forwarded-https [--probe "word in a private page"]

The password is read from standard input only. Checks: signed-out 404s, sign-in token, CSRF
refusals, wrong password, sign-in, cookie attributes, owner routes, session fixation, sign-out,
replayed cookie, and (``--probe``) that a signed-out public search for private words returns no
private text. Prints one line per check and exits non-zero on any failure. Never prints secrets.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

MARKER = "private-owner-only"


class Client:
    def __init__(self, base: str, headers: dict):
        self.base, self.headers, self.cookies = base.rstrip("/"), headers, {}

    def call(self, method: str, path: str, body=None, headers=None, raw_body: bytes | None = None):
        data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
        h = {**self.headers, **(headers or {})}
        if body is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        set_cookies = response.headers.get_all("Set-Cookie") or []
        for line in set_cookies:
            name, _, rest = line.partition("=")
            value = rest.split(";", 1)[0]
            if "max-age=0" in line.lower() or value in ('""', ""):
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        text = response.read().decode("utf-8", "replace")
        return response.status, text, set_cookies


failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + label + (f" ({detail})" if detail and not ok else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--username", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--forwarded-https", action="store_true")
    parser.add_argument("--probe", default="")
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    headers = {"X-Forwarded-Proto": "https"} if args.forwarded_https else {}
    origin = {"Origin": args.origin}

    anon = Client(args.base, headers)
    check("signed-out session says signed_in false", anon.call("GET", "/api/owner/session")[1] == '{"signed_in":false}')
    for path in ("/api/private/status", "/api/private/documents", "/api/private/search?q=a", "/api/private/ui.js",
                 "/api/private/unknown"):
        check(f"signed-out {path} is 404", anon.call("GET", path)[0] == 404)
    if args.forwarded_https:
        plain = Client(args.base, {"X-Forwarded-Proto": "http"})
        check("plain-HTTP sign-in token refused (404)", plain.call("GET", "/api/owner/login-token")[0] == 404)

    c = Client(args.base, headers)
    token = json.loads(c.call("GET", "/api/owner/login-token")[1])["token"]
    creds = {"username": args.username, "password": password}
    check("sign-in without CSRF token refused", c.call("POST", "/api/owner/login", creds, origin)[0] == 403)
    check("sign-in from another origin refused",
          c.call("POST", "/api/owner/login", creds, {"Origin": "https://evil.example", "X-Melos-CSRF": token})[0] == 403)
    check("sign-in as text/plain refused", c.call("POST", "/api/owner/login", None, {
        **origin, "X-Melos-CSRF": token, "Content-Type": "text/plain"}, raw_body=json.dumps(creds).encode())[0] == 400)
    status, _, _ = c.call("POST", "/api/owner/login", {"username": args.username, "password": password + "x"},
                          {**origin, "X-Melos-CSRF": token})
    check("wrong password refused (401)", status == 401)
    token = json.loads(c.call("GET", "/api/owner/login-token")[1])["token"]
    c.cookies["__Host-melos_owner"] = "planted-by-attacker.00"
    status, text, cookies = c.call("POST", "/api/owner/login", creds, {**origin, "X-Melos-CSRF": token})
    check("sign-in succeeds", status == 200, text[:120])
    session_line = next((line for line in cookies if line.startswith("__Host-melos_owner=")), "")
    for attribute in ("httponly", "secure", "samesite=strict", "path=/", "max-age=43200"):
        check(f"session cookie has {attribute}", attribute in session_line.lower())
    check("planted session id not adopted", not c.cookies.get("__Host-melos_owner", "").startswith("planted"))
    check("password not echoed", password not in text and all(password not in line for line in cookies))
    session = json.loads(c.call("GET", "/api/owner/session")[1])
    check("session says signed in", session.get("signed_in") is True)
    status, text, _ = c.call("GET", "/api/private/status")
    check("owner /api/private/status 200 and tagged", status == 200 and MARKER in text, text[:120])
    check("owner panels script 200", c.call("GET", "/api/private/ui.js")[0] == 200)
    if args.probe:
        status, text, _ = c.call("GET", "/api/private/search?q=" + urllib.parse.quote(args.probe))
        check("owner private search finds the probe", status == 200 and MARKER in text)
        status, text, _ = anon.call("GET", "/api/search?q=" + urllib.parse.quote(args.probe))
        check("signed-out public search: no private tag", MARKER not in text)
        status, text, _ = c.call("GET", "/api/search?q=" + urllib.parse.quote(args.probe))
        check("signed-in public search: still no private tag (private text only via /api/private)", MARKER not in text)
    first = c.cookies["__Host-melos_owner"]
    token = json.loads(c.call("GET", "/api/owner/login-token")[1])["token"]
    c.call("POST", "/api/owner/login", creds, {**origin, "X-Melos-CSRF": token})
    old = Client(args.base, headers)
    old.cookies["__Host-melos_owner"] = first
    check("signing in again ends the previous session", old.call("GET", "/api/private/status")[0] == 404)
    csrf = json.loads(c.call("GET", "/api/owner/session")[1])["csrf"]
    check("sign-out without CSRF refused", c.call("POST", "/api/owner/logout", {}, origin)[0] == 403)
    check("sign-out from another origin refused",
          c.call("POST", "/api/owner/logout", {}, {"Origin": "https://evil.example", "X-Melos-CSRF": csrf})[0] == 403)
    second = c.cookies["__Host-melos_owner"]
    check("sign-out succeeds", c.call("POST", "/api/owner/logout", {}, {**origin, "X-Melos-CSRF": csrf})[0] == 200)
    replay = Client(args.base, headers)
    replay.cookies["__Host-melos_owner"] = second
    check("signed-out cookie replay is 404", replay.call("GET", "/api/private/status")[0] == 404)
    # Lockout last, from a throwaway client address (the per-client limit, below the global one).
    lock = Client(args.base, {**headers, "X-Forwarded-For": "192.0.2.123", "X-Forwarded-Proto": "https"})
    codes = []
    for _ in range(6):
        t = json.loads(lock.call("GET", "/api/owner/login-token")[1])["token"]
        codes.append(lock.call("POST", "/api/owner/login", {"username": args.username, "password": "wrong"},
                               {**origin, "X-Melos-CSRF": t})[0])
    check("5 failures then lockout (429)", codes == [401] * 5 + [429], str(codes))
    t = json.loads(lock.call("GET", "/api/owner/login-token")[1])["token"]
    check("locked client refused even with the right password",
          lock.call("POST", "/api/owner/login", creds, {**origin, "X-Melos-CSRF": t})[0] == 429)
    print("failures:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
