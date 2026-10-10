"""Live smoke test (costs real money, well under $1): one /backtranslate and one tiny /pool against a fake
melos-api, through a local recording proxy that shows what the CLI actually sends to Anthropic (model, effort,
thinking). Never prints headers or the key.

    env -i HOME=$HOME PATH=$PATH ANTHROPIC_API_KEY_FILE=/path/to/key .venv/bin/python smoke.py
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from composer_agent.app import create_app  # noqa: E402
from composer_agent.settings import Settings  # noqa: E402

TOKEN = "smoke-token"
SEEN: list[dict] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)


fake = FastAPI()


@fake.post("/api/composer/check")
async def check(req: Request):
    body = await req.json()
    ok = len(body["greek"].split()) <= 6 and any("Ͱ" <= ch <= "῿" for ch in body["greek"])
    return {"pass": ok, "scansion": "?", "checks": [{"id": "L7", "ok": ok, "blocking": True,
                                                     "detail": "fits (fake)" if ok else "too long or not Greek (fake)"}]}


@fake.api_route("/{path:path}", methods=["GET", "POST"])
async def stub(path: str):
    return JSONResponse({"note": f"smoke stub for /{path}: no data"})


proxy = FastAPI()
UPSTREAM = "https://api.anthropic.com"


@proxy.api_route("/{path:path}", methods=["GET", "POST"])
async def forward(path: str, req: Request):
    raw = await req.body()
    if path.endswith("messages"):
        try:
            b = json.loads(raw)
            SEEN.append({k: b.get(k) for k in ("model", "thinking", "output_config", "effort", "max_tokens", "tool_choice")
                         if k in b} | {"tools": len(b.get("tools") or [])})
        except ValueError:
            pass
    headers = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length", "accept-encoding")}
    client = httpx.AsyncClient(timeout=300)
    up = await client.send(client.build_request(req.method, f"{UPSTREAM}/{path}", params=req.query_params,
                                                headers=headers, content=raw), stream=True)

    async def body():
        try:
            if up.is_stream_consumed:
                yield up.content
                return
            async for chunk in up.aiter_bytes():
                yield chunk
        finally:
            await up.aclose()
            await client.aclose()
    if path.endswith("messages") and SEEN:
        SEEN[-1]["status"] = up.status_code
        if up.status_code >= 400:
            SEEN[-1]["error"] = (await up.aread()).decode("utf-8", "replace")[:600]
    keep = {k: v for k, v in up.headers.items() if k.lower() in ("content-type", "request-id", "anthropic-ratelimit-requests-remaining")}
    return StreamingResponse(body(), status_code=up.status_code, headers=keep)


def main():
    fport, pport = free_port(), free_port()
    serve(fake, fport)
    serve(proxy, pport)
    os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{pport}"
    state = Path(tempfile.mkdtemp(prefix="composer-smoke-"))
    settings = Settings(melos_api_url=f"http://127.0.0.1:{fport}", state_dir=state, token=TOKEN,
                        pool_rounds=1, pool_seconds=150)
    h = {"X-Composer-Token": TOKEN}
    total = 0.0
    with TestClient(create_app(settings)) as client:
        t = time.time()
        r = client.post("/backtranslate", json={"greek": "φαίνεταί μοι κῆνος ἴσος θέοισιν", "dialect": "aeolic"},
                        headers=h)
        print("backtranslate", r.status_code, f"{time.time() - t:.1f}s", r.json())
        total += (r.json().get("cost_usd") or 0) if r.status_code == 200 else 0
        if os.environ.get("SMOKE_SKIP_POOL"):
            return report(state, total)
        poem = {"poem_id": "smoke", "title": "smoke", "settings": {"author": "Sappho", "metre": "sapphic", "dialect": "aeolic"},
                "english": "The moon shows over the sea.", "lines": [], "caret": {"line_position": 0, "char_offset": 0, "prefix": ""}}
        t = time.time()
        r = client.post("/pool", json={"poem": poem, "slot": {"line_position": 0, "caret": 0, "prefix": ""}, "n": 2},
                        headers=h)
        print("pool", r.status_code, f"{time.time() - t:.1f}s")
        for line in r.text.splitlines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                print("  ", json.dumps(ev, ensure_ascii=False)[:300])
                if ev["type"] == "done":
                    total += ev["cost_usd"]
    report(state, total)


def report(state, total):
    print("requests seen by Anthropic:")
    for s in SEEN:
        print("  ", json.dumps(s, ensure_ascii=False))
    print("usage log:", (state / "usage.jsonl").read_text())
    print(f"TOTAL cost_usd (our pricing): {total:.4f}")


if __name__ == "__main__":
    main()
