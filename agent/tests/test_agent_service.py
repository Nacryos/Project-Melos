"""Unit tests with a fake melos-api and a scripted runner: no Anthropic calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from composer_agent.app import create_app  # noqa: E402
from composer_agent.runner import Outcome, SdkRunner, Job  # noqa: E402
from composer_agent.settings import EFFORT, MODEL, Settings, cost_usd  # noqa: E402

TOKEN = "t0ken-for-tests"
H = {"X-Composer-Token": TOKEN}
POEM = {"poem_id": "p1", "title": "Moon", "settings": {"author": "Sappho", "metre": "sapphic", "dialect": "aeolic"},
        "english": "The moon shows over the sea", "lines": [{"position": 0, "greek": "φαίνεται", "back_translation": "appears"}],
        "caret": {"line_position": 0, "char_offset": 8, "prefix": "φαίνεται"}}
SLOT = {"line_position": 0, "caret": 8, "prefix": "φαίνεται", "remaining_template": "–⏑–⏑⏑–⏑––"}
USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}


class FakeRunner:
    """Plays a script of tool calls against the real tool handlers, then returns fixed usage."""

    def __init__(self, script=(), text="", error=None):
        self.script, self.text, self.error, self.results, self.jobs = list(script), text, error, [], []

    async def run(self, job: Job) -> Outcome:
        self.jobs.append(job)
        tools = {t.name: t for t in job.tools}
        for name, args in self.script:
            if job.stop.is_set():
                break
            self.results.append(await tools[name].handler(args))
        if job.stream_text and self.text:
            for word in self.text.split(" "):
                await job.emit({"type": "text", "delta": word + " "})
        return Outcome(usage=dict(USAGE), text=self.text, error=self.error, stop_reason="end_turn")


class FakeMelos:
    def __init__(self, check_status=200):
        self.calls, self.check_status = [], check_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Composer-Token") == TOKEN
        self.calls.append(request)
        if request.url.path == "/api/composer/check":
            if self.check_status != 200:
                return httpx.Response(self.check_status, json={"detail": "boom"})
            body = json.loads(request.content)
            bad = "bad" in body["greek"]
            checks = [{"id": "L7", "ok": not bad, "blocking": True, "detail": "position 3 must be long" if bad else "fits"},
                      {"id": "L4", "ok": False, "blocking": False, "detail": "not in Sappho"}]
            return httpx.Response(200, json={"pass": not bad, "scansion": "–⏑–", "checks": checks})
        if request.url.path == "/api/lemma/search":
            return httpx.Response(200, json={"q": request.url.params.get("q"), "forms_found": {"σελάννα": 4}})
        return httpx.Response(404, json={"detail": "not found"})


def make(tmp_path, runner, melos=None, **kw):
    tok = tmp_path / "token"
    tok.write_text(TOKEN + "\n")
    settings = Settings(melos_api_url="http://melos-api:8791", state_dir=tmp_path / "state", token=TOKEN, **kw)
    melos = melos or FakeMelos()
    return TestClient(create_app(settings, runner, httpx.MockTransport(melos))), melos, settings


def events(resp) -> list[dict]:
    assert resp.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def cands(*greek, span="the moon"):
    return {"candidates": [{"greek": g, "english_span": span, "slots": "–⏑–", "evidence": ["Sappho 96"]} for g in greek]}


def test_token_required(tmp_path):
    client, _, _ = make(tmp_path, FakeRunner())
    with client:
        for path, body in [("/chat", {"poem": POEM, "message": "hi"}), ("/pool", {"poem": POEM, "slot": SLOT}),
                           ("/backtranslate", {"greek": "νῦν"})]:
            assert client.post(path, json=body).status_code == 401
            assert client.post(path, json=body, headers={"X-Composer-Token": "wrong"}).status_code == 401


def test_unconfigured_token_rejects_everything(tmp_path):
    settings = Settings(state_dir=tmp_path, token="")
    with TestClient(create_app(settings, FakeRunner())) as client:
        assert client.post("/backtranslate", json={"greek": "νῦν"}, headers={"X-Composer-Token": ""}).status_code == 401


def test_pool_streams_only_linted_candidates_and_stops_at_n(tmp_path):
    runner = FakeRunner([("propose_candidates", cands("πόντῳ πέρι", "bad one", "νῦν σελάννα")),
                         ("propose_candidates", cands("πόντῳ πέρι", "ἄψ σελάννα", "more")),
                         ("propose_candidates", cands("never reached"))])
    client, melos, settings = make(tmp_path, runner)
    with client:
        evs = events(client.post("/pool", json={"poem": POEM, "slot": SLOT, "n": 3}, headers=H))
    got = [e for e in evs if e["type"] == "candidate"]
    assert [c["greek"] for c in got] == ["πόντῳ πέρι", "νῦν σελάννα", "ἄψ σελάννα"]
    assert all(c["checks"] and c["english_span"] == "the moon" and c["evidence"] == ["Sappho 96"] for c in got)
    rejected = next(e for e in evs if e["type"] == "rejected")
    assert rejected == {"type": "rejected", "count": 1, "reasons": {"L7": 1}}
    assert evs[-1]["type"] == "done" and evs[-1]["cost_usd"] == cost_usd(USAGE)
    # failures go back to the model with reasons; the stop instruction follows the target
    first, second = (r["content"][0]["text"] for r in runner.results)
    assert "bad one: L7 position 3 must be long" in first
    assert "duplicates skipped" in second and "Stop now" in second
    assert len(runner.results) == 2 and runner.jobs[0].stop.is_set()
    body = json.loads(next(c for c in melos.calls if c.url.path == "/api/composer/check").content)
    assert body == {"greek": "πόντῳ πέρι", "metre": "sapphic", "dialect": "aeolic", "author": "Sappho",
                    "remaining_template": SLOT["remaining_template"]}
    log = [json.loads(l) for l in (settings.state_dir / "usage.jsonl").read_text().splitlines()]
    assert log[-1]["endpoint"] == "pool" and log[-1]["model"] == MODEL and log[-1]["passed"] == 3


def test_pool_round_limit(tmp_path):
    runner = FakeRunner([("propose_candidates", cands(f"bad {i}")) for i in range(6)])
    client, _, _ = make(tmp_path, runner, pool_rounds=4)
    with client:
        evs = events(client.post("/pool", json={"poem": POEM, "slot": SLOT, "n": 5}, headers=H))
    assert not [e for e in evs if e["type"] == "candidate"]
    assert len(runner.results) == 4 and "round limit" in runner.results[-1]["content"][0]["text"]
    assert next(e for e in evs if e["type"] == "rejected")["count"] == 4


def test_lint_outage_never_emits_unlinted(tmp_path):
    runner = FakeRunner([("propose_candidates", cands("πόντῳ πέρι"))])
    client, _, _ = make(tmp_path, runner, melos=FakeMelos(check_status=503))
    with client:
        evs = events(client.post("/pool", json={"poem": POEM, "slot": SLOT, "n": 1}, headers=H))
    assert not [e for e in evs if e["type"] == "candidate"]
    assert next(e for e in evs if e["type"] == "rejected")["reasons"] == {"lint_unavailable": 1}


def test_chat_streams_text_tool_and_candidates(tmp_path):
    runner = FakeRunner([("lemma_search", {"q": "σελήνη", "author": "Sappho", "limit": 5}),
                         ("propose_candidates", cands("σελάννα"))], text="Sappho has σελάννα (96, 154).")
    client, melos, _ = make(tmp_path, runner)
    with client:
        evs = events(client.post("/chat", json={"poem": POEM, "thread": [{"role": "user", "content": "x"}],
                                                "message": "Which word for moon?"}, headers=H))
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "tool" and evs[0]["name"] == "lemma_search" and "σελήνη" in evs[0]["summary"]
    assert "candidate" in kinds and "rejected" not in kinds and kinds[-1] == "done"
    assert "".join(e["delta"] for e in evs if e["type"] == "text").strip() == "Sappho has σελάννα (96, 154)."
    req = next(c for c in melos.calls if c.url.path == "/api/lemma/search")
    assert req.method == "GET" and req.url.params["author"] == "Sappho"
    assert "σελάννα" in runner.results[0]["content"][0]["text"]
    assert "Which word for moon?" in runner.jobs[0].prompt and "The moon shows over the sea" in runner.jobs[0].prompt


def test_runner_error_becomes_error_event(tmp_path):
    client, _, _ = make(tmp_path, FakeRunner(error="The model declined this request (refusal)."))
    with client:
        evs = events(client.post("/chat", json={"poem": POEM, "message": "?"}, headers=H))
    assert [e["type"] for e in evs] == ["error", "done"] and "refusal" in evs[0]["message"]


def test_backtranslate(tmp_path):
    client, _, _ = make(tmp_path, FakeRunner(text=" The moon appears. "))
    with client:
        r = client.post("/backtranslate", json={"greek": "φαίνεται σελάννα", "dialect": "aeolic"}, headers=H)
    assert r.status_code == 200 and r.json()["english"] == "The moon appears."
    client, _, _ = make(tmp_path, FakeRunner(error="agent failed: CLIConnectionError"))
    with client:
        assert client.post("/backtranslate", json={"greek": "νῦν"}, headers=H).status_code == 502


def test_cost():
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}) == 60.25


def test_sdk_options_lock_model_effort_and_tools(tmp_path, monkeypatch):
    key = tmp_path / "k"
    key.write_text("sk-test\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(key))
    runner = SdkRunner(Settings(state_dir=tmp_path, token=TOKEN))

    async def emit(_):
        return None
    opts = runner.options(Job(system="s", prompt="p", emit=emit, server={"type": "sdk", "name": "melos"}))
    assert (opts.model, opts.effort) == (MODEL, EFFORT) == ("claude-fable-5-1", "xhigh")
    assert opts.tools == [] and opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert opts.thinking is None and opts.max_thinking_tokens is None    # Fable 5.1: never set a budget
    assert all(t.startswith("mcp__melos__") for t in opts.allowed_tools) and "mcp__melos__check_candidate" in opts.allowed_tools
    assert "Bash" in opts.disallowed_tools and opts.env["ANTHROPIC_API_KEY"] == "sk-test"
