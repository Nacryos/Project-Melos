"""Unit tests with a fake melos-api and a scripted runner: no Anthropic calls."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from composer_agent.app import create_app  # noqa: E402
from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock  # noqa: E402
from composer_agent.melos import norm  # noqa: E402
from composer_agent.runner import Job, Outcome, sdk_options  # noqa: E402
from composer_agent.sessions import Busy, Sessions, Turn  # noqa: E402
from composer_agent.settings import EFFORT, MODEL, Settings, cost_usd  # noqa: E402

TOKEN = "t0ken-for-tests"
H = {"X-Composer-Token": TOKEN}
POEM = {"poem_id": "p1", "title": "Moon", "settings": {"author": "Sappho", "metre": "sapphic", "dialect": "aeolic"},
        "english": "The moon shows over the sea", "lines": [{"position": 0, "greek": "φαίνεται", "back_translation": "appears"}],
        "caret": {"line_position": 0, "char_offset": 8, "prefix": "φαίνεται"}}
SLOT = {"line_position": 0, "caret": 8, "prefix": "φαίνεται", "remaining_template": "–⏑–⏑⏑–⏑––"}
USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}


class FakeRunner:
    """One-shot runner (back-translation): returns fixed text and usage."""

    def __init__(self, text="", error=None):
        self.text, self.error, self.jobs = text, error, []

    async def run(self, job: Job) -> Outcome:
        self.jobs.append(job)
        return Outcome(usage=dict(USAGE), text=self.text, error=self.error, stop_reason="end_turn")


class FakeSDK:
    """Stands in for ClaudeSDKClient: one instance per session. ``turns`` is a shared script: each query pops the
    next list of actions — (tool, args) calls the real tool handler, ("sleep", s) waits (an interrupt cuts it
    short), ("text", s) streams text — then the turn ends with one assistant message and a result."""

    def __init__(self, turns=()):
        self.turns, self.clients = list(turns), []

    def __call__(self, options, tools):
        client = _FakeClient(self, options, tools)
        self.clients.append(client)
        return client

    @property
    def prompts(self):
        return [p for c in self.clients for p in c.prompts]


class _FakeClient:
    def __init__(self, owner, options, tools):
        self.owner, self.options, self.tools = owner, options, {t.name: t for t in tools}
        self.prompts, self.connects, self.disconnects, self.interrupts, self.results = [], 0, 0, 0, []
        self._cut = None

    async def connect(self, prompt=None):
        self.connects += 1

    async def disconnect(self):
        self.disconnects += 1

    async def query(self, prompt, session_id="default"):
        self.prompts.append(prompt)

    async def interrupt(self):
        self.interrupts += 1
        if self._cut:
            self._cut.set()

    async def receive_response(self):
        self._cut = asyncio.Event()
        actions = self.owner.turns.pop(0) if self.owner.turns else []
        n = len(self.prompts)
        for name, arg in actions:
            if self._cut.is_set():
                break
            if name == "sleep":
                try:
                    await asyncio.wait_for(self._cut.wait(), arg)
                except asyncio.TimeoutError:
                    pass
            elif name == "text":
                for word in arg.split(" "):
                    yield StreamEvent(uuid="u", session_id="s", event={"type": "content_block_delta",
                                                                       "delta": {"type": "text_delta", "text": word + " "}})
            else:
                self.results.append(await self.tools[name].handler(arg))
        yield AssistantMessage(content=[TextBlock(text="done")], model=MODEL, usage=dict(USAGE), message_id=f"m{n}")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="s", stop_reason="end_turn", total_cost_usd=0.1, usage=dict(USAGE))


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


def make(tmp_path, sdk=None, melos=None, runner=None, **kw):
    kw.setdefault("stop_grace_seconds", 0.05)
    settings = Settings(melos_api_url="http://melos-api:8791", state_dir=tmp_path / "state", token=TOKEN, **kw)
    melos = melos or FakeMelos()
    app = create_app(settings, runner or FakeRunner(), httpx.MockTransport(melos), client_factory=sdk or FakeSDK())
    return TestClient(app), melos, settings


def events(resp) -> list[dict]:
    assert resp.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def cands(*greek, span="the moon"):
    return {"candidates": [{"greek": g, "english_span": span, "slots": "–⏑–", "evidence": ["Sappho 96"]} for g in greek]}


def test_token_required(tmp_path):
    client, _, _ = make(tmp_path)
    with client:
        for path, body in [("/chat", {"poem": POEM, "message": "hi"}), ("/pool", {"poem": POEM, "slot": SLOT}), ("/warm", {"poem": POEM}),
                           ("/backtranslate", {"greek": "νῦν"})]:
            assert client.post(path, json=body).status_code == 401
            assert client.post(path, json=body, headers={"X-Composer-Token": "wrong"}).status_code == 401


def test_unconfigured_token_rejects_everything(tmp_path):
    settings = Settings(state_dir=tmp_path, token="")
    with TestClient(create_app(settings, FakeRunner())) as client:
        assert client.post("/backtranslate", json={"greek": "νῦν"}, headers={"X-Composer-Token": ""}).status_code == 401


def test_backtranslate(tmp_path):
    client, _, _ = make(tmp_path, runner=FakeRunner(text=" The moon appears. "))
    with client:
        r = client.post("/backtranslate", json={"greek": "φαίνεται σελάννα", "dialect": "aeolic"}, headers=H)
    assert r.status_code == 200 and r.json()["english"] == "The moon appears."
    client, _, _ = make(tmp_path, runner=FakeRunner(error="agent failed: CLIConnectionError"))
    with client:
        assert client.post("/backtranslate", json={"greek": "νῦν"}, headers=H).status_code == 502


def test_cost():
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}) == 60.25


def test_sdk_options_lock_model_effort_and_tools(tmp_path, monkeypatch):
    key = tmp_path / "k"
    key.write_text("sk-test\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(key))
    opts = sdk_options(Settings(state_dir=tmp_path, token=TOKEN), "s", {"type": "sdk", "name": "melos"})
    assert (opts.model, opts.effort) == (MODEL, EFFORT) == ("claude-fable-5-1", "xhigh")
    assert opts.tools == [] and opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert opts.thinking is None and opts.max_thinking_tokens is None    # Fable 5.1: never set a budget
    assert all(t.startswith("mcp__melos__") for t in opts.allowed_tools) and "mcp__melos__check_candidate" in opts.allowed_tools
    assert "Bash" in opts.disallowed_tools and opts.env["ANTHROPIC_API_KEY"] == "sk-test"


# ---------------------------------------------------------------------------------------------- sessions, slots, warm

SLOT_A = {**SLOT, "slot_key": "A"}
NEXT = [{"line_position": 1, "prefix": "", "remaining_template": "-u-x-uu-u-F", "slot_key": "B"},
        {"line_position": 2, "prefix": "", "remaining_template": "-u-x-uu-u-F", "slot_key": "C"}]


def sc(slot, *greek):
    return {"candidates": [{"slot": slot, "greek": g, "english_span": "the moon", "evidence": ["Sappho 96"]} for g in greek]}


def pool_body(slot=SLOT_A, ahead=NEXT, n=2, poem=POEM):
    return {"poem": poem, "slot": slot, "ahead": ahead, "n": n}


def usage_log(settings):
    return [json.loads(l) for l in (settings.state_dir / "usage.jsonl").read_text().splitlines()]


def test_stanza_batch_lints_each_slot_against_its_own_template_and_streams(tmp_path):
    sdk = FakeSDK([[("propose_candidates", {"candidates": [*sc("A", "πόντῳ πέρι", "bad one")["candidates"],
                                                           *sc("B", "ἄστερες μὲν")["candidates"]]}),
                    ("propose_candidates", sc("C", "νύκτες\nἀμφὶ", "x")), ("propose_candidates", sc("A", "late"))]])
    client, melos, settings = make(tmp_path, sdk, pool_ahead_n=1)
    with client:
        evs = events(client.post("/pool", json=pool_body(), headers=H))
    got = [e for e in evs if e["type"] == "candidate"]
    assert {(c["slot_key"], c["greek"]) for c in got} == {("A", "πόντῳ πέρι"), ("B", "ἄστερες μὲν"), ("C", "νύκτες\nἀμφὶ"),
                                                         ("C", "x"), ("A", "late")}
    assert {c["slot_key"]: c["line_position"] for c in got} == {"A": 0, "B": 1, "C": 2}
    bodies = {json.loads(r.content)["greek"]: json.loads(r.content) for r in melos.calls if r.url.path == "/api/composer/check"}
    assert bodies["πόντῳ πέρι"] == {"greek": "πόντῳ πέρι", "metre": "sapphic", "dialect": "aeolic", "author": "Sappho",
                                    "remaining_template": SLOT["remaining_template"], "prefix": "φαίνεται", "line_index": 0}
    assert bodies["ἄστερες μὲν"]["remaining_template"] == NEXT[0]["remaining_template"] and bodies["ἄστερες μὲν"]["line_index"] == 1
    assert "prefix" not in bodies["ἄστερες μὲν"]
    # A wants 2 (n), B and C want 1: A is still short after round 2, so round 3 runs; then all are satisfied
    texts = [r["content"][0]["text"] for r in sdk.clients[0].results]
    assert "[A] bad one: L7" in texts[0] and "A 1/2, B 1/1, C 0/1" in texts[0] and "Stop now" in texts[2]
    assert next(e for e in evs if e["type"] == "rejected") == {"type": "rejected", "count": 1, "reasons": {"L7": 1}}
    log = usage_log(settings)[-1]
    assert log["passed"] == {"A": 2, "B": 1, "C": 2} and log["stop"] == "enough" and log["first_turn"] is True
    assert set(log["first_ms_by_slot"]) == {"A", "B", "C"}


def test_candidates_stream_before_the_turn_ends(tmp_path, monkeypatch):
    # (TestClient buffers a whole response, so the timing is read where events enter the response queue.)
    sdk = FakeSDK([[("propose_candidates", sc("A", "πρῶτον")), ("sleep", 0.6), ("propose_candidates", sc("A", "ὕστερον"))]])
    client, _, _ = make(tmp_path, sdk)
    seen, emit = {}, Turn.emit

    async def timed(self, event):
        seen.setdefault(event.get("greek") or event["type"], time.monotonic() - t0)
        await emit(self, event)
    monkeypatch.setattr(Turn, "emit", timed)
    with client:
        t0 = time.monotonic()
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
    assert seen["πρῶτον"] < 0.4 <= seen["ὕστερον"] <= seen["done"]


def test_session_is_reused_per_poem_and_history_is_append_only(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1", "α2"))], [("propose_candidates", sc("B", "β1", "β2"))]])
    client, _, settings = make(tmp_path, sdk)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        later = {**POEM, "lines": POEM["lines"] + [{"position": 1, "greek": "ἄστερες"}]}
        events(client.post("/pool", json=pool_body(slot={**NEXT[0], "prefix": "ἄστερες"}, ahead=[], poem=later), headers=H))
    assert len(sdk.clients) == 1 and sdk.clients[0].connects == 1           # one client, one connection, two turns
    first, second = sdk.clients[0].prompts
    assert "first request for this poem" in first and "The moon shows over the sea" in first
    assert "first request" not in second and second.startswith("Update to the poem") and "ἄστερες" in second
    assert "English source changed" not in second                            # unchanged English is not re-sent
    assert [l["session_turn"] for l in usage_log(settings)] == [1, 2]


def test_changed_english_is_sent_again_and_settings_open_a_new_session(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1", "α2"))]] * 3)
    client, _, _ = make(tmp_path, sdk)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        events(client.post("/pool", json=pool_body(ahead=[], poem={**POEM, "english": "The moon has set"}), headers=H))
        events(client.post("/pool", json=pool_body(ahead=[], poem={**POEM, "settings": {**POEM["settings"], "metre": "alcaic"}}), headers=H))
    assert "now reads (whole):\nThe moon has set" in sdk.clients[0].prompts[1]
    assert len(sdk.clients) == 2 and "first request" in sdk.clients[1].prompts[0]


def test_chat_has_its_own_session_and_sends_the_thread_once(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1", "α2"))],
                   [("lemma_search", {"q": "σελήνη", "author": "Sappho"}), ("text", "Sappho has σελάννα.")],
                   [("text", "Yes.")]])
    client, melos, _ = make(tmp_path, sdk)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        evs = events(client.post("/chat", json={"poem": POEM, "thread": [{"role": "user", "content": "earlier"}],
                                                "message": "Which word for moon?"}, headers=H))
        events(client.post("/chat", json={"poem": POEM, "thread": [{"role": "user", "content": "earlier"}],
                                          "message": "Attested?"}, headers=H))
    assert len(sdk.clients) == 2 and sdk.clients[1].options.include_partial_messages is True
    assert sdk.clients[0].options.include_partial_messages is False
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "tool" and evs[0]["name"] == "lemma_search" and kinds[-1] == "done" and "rejected" not in kinds
    assert "".join(e["delta"] for e in evs if e["type"] == "text").strip() == "Sappho has σελάννα."
    c1, c2 = sdk.clients[1].prompts
    assert "earlier" in c1 and "Which word for moon?" in c1 and "earlier" not in c2 and "Attested?" in c2


def _in_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn()))
    t.start()
    return t, out


def _wait_for(cond, seconds=3.0):
    t0 = time.monotonic()
    while not cond():
        assert time.monotonic() - t0 < seconds, "timed out"
        time.sleep(0.01)


def test_request_for_a_slot_the_running_turn_covers_joins_it(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1")), ("sleep", 0.5), ("propose_candidates", sc("B", "β1"))]])
    client, _, settings = make(tmp_path, sdk, pool_ahead_n=1)
    with client:
        t, out = _in_thread(lambda: events(client.post("/warm", json=pool_body(n=1, ahead=NEXT[:1]), headers=H)))
        _wait_for(lambda: sdk.clients and sdk.clients[0].results)
        joined = events(client.post("/pool", json=pool_body(n=1, ahead=[]), headers=H))
        t.join()
    assert len(sdk.prompts) == 1                                            # no second turn
    cands = [e for e in joined if e["type"] == "candidate"]
    assert cands[0] == {**cands[0], "greek": "α1", "replay": True} and cands[1]["greek"] == "β1" and "replay" not in cands[1]
    assert joined[-1]["type"] == "done" and joined[-1]["shared"] is True and joined[-1]["cost_usd"] == 0
    assert out["v"][-1]["cost_usd"] == cost_usd(USAGE)
    assert len(usage_log(settings)) == 1


def test_request_for_another_slot_preempts_the_running_turn(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1")), ("sleep", 5)], [("propose_candidates", sc("B", "β1", "β2"))]])
    client, _, settings = make(tmp_path, sdk)
    with client:
        t0 = time.monotonic()
        t, out = _in_thread(lambda: events(client.post("/pool", json=pool_body(ahead=[]), headers=H)))
        _wait_for(lambda: sdk.clients and sdk.clients[0].results)
        second = events(client.post("/pool", json=pool_body(slot=NEXT[0], ahead=[]), headers=H))
        t.join()
    assert time.monotonic() - t0 < 3 and sdk.clients[0].interrupts == 1 and len(sdk.clients) == 1
    assert sorted(e["greek"] for e in second if e["type"] == "candidate") == ["β1", "β2"]
    logs = usage_log(settings)
    assert logs[0]["stop"] == "preempted" and logs[0]["terminal_reason"] == "stop" and logs[1]["stop"] == "enough"


def test_warm_research_only_then_skips_when_already_filled(tmp_path):
    sdk = FakeSDK([[("lemma_search", {"q": "σελήνη"})], [("propose_candidates", sc("A", "α1", "α2"))]])
    client, _, settings = make(tmp_path, sdk)
    with client:
        evs = events(client.post("/warm", json={"poem": POEM}, headers=H))
        assert evs[0]["type"] == "tool" and evs[-1]["type"] == "done"
        assert "research only" in sdk.prompts[0] and "first request for this poem" in sdk.prompts[0]
        events(client.post("/warm", json={"poem": POEM}, headers=H))           # already warm: no model call
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        again = events(client.post("/warm", json=pool_body(ahead=[]), headers=H))
    assert len(sdk.prompts) == 2 and "Update to the poem" in sdk.prompts[1]
    assert [l["terminal_reason"] for l in usage_log(settings)][1::2] == ["already_warm", "already_filled"]
    assert again[-1]["cost_usd"] == 0


def test_idle_sessions_are_closed_and_the_next_request_starts_fresh(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", "α1", "α2"))]] * 2)
    client, _, _ = make(tmp_path, sdk, session_idle_seconds=60)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        sessions = client.app.state.sessions
        assert client.portal.call(sessions.reap) == 0                          # not idle long enough
        assert client.portal.call(sessions.reap, time.monotonic() + 61) == 1
        assert sdk.clients[0].disconnects == 1 and not sessions.by_key
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
    assert len(sdk.clients) == 2 and "first request" in sdk.clients[1].prompts[0]


def test_session_count_is_bounded(tmp_path):
    settings = Settings(state_dir=tmp_path, token=TOKEN, max_sessions=1)
    sdk = FakeSDK()

    async def go():
        sessions = Sessions(settings, sdk)
        a = sessions.get("a", "pool", "s")
        b = sessions.get("b", "pool", "s")                                    # a is idle: closed to make room
        await asyncio.sleep(0)
        assert list(sessions.by_key) == ["b"] and a.closed
        b.turn = Turn(kind="pool", ctx=None)                                  # b is busy
        with pytest.raises(Busy):
            sessions.get("c", "pool", "s")
        assert sessions.get("b", "pool", "s") is b
    asyncio.run(go())


def test_busy_answers_503(tmp_path):
    sdk = FakeSDK([[("sleep", 0.5)]])
    client, _, _ = make(tmp_path, sdk, max_sessions=1)
    with client:
        t, _ = _in_thread(lambda: client.post("/pool", json=pool_body(ahead=[]), headers=H))
        _wait_for(lambda: sdk.prompts)
        r = client.post("/chat", json={"poem": POEM, "message": "?"}, headers=H)
        t.join()
    assert r.status_code == 503


def test_round_limit_and_lint_outage(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("A", f"bad {i}")) for i in range(6)]])
    client, _, _ = make(tmp_path, sdk, pool_rounds=4)
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=5), headers=H))
    assert not [e for e in evs if e["type"] == "candidate"]
    texts = [r["content"][0]["text"] for r in sdk.clients[0].results]
    assert "round limit" in texts[3] and all(t.startswith("Stop: this request is complete") for t in texts[4:])
    assert next(e for e in evs if e["type"] == "rejected")["count"] == 4
    sdk = FakeSDK([[("propose_candidates", sc("A", "πόντῳ πέρι"))]])
    client, _, _ = make(tmp_path, sdk, melos=FakeMelos(check_status=503))
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=1), headers=H))
    assert not [e for e in evs if e["type"] == "candidate"]
    assert next(e for e in evs if e["type"] == "rejected")["reasons"] == {"lint_unavailable": 1}


def test_unknown_slot_and_cross_turn_duplicates_are_refused(tmp_path):
    sdk = FakeSDK([[("propose_candidates", sc("Z", "α1")), ("propose_candidates", sc("A", "α1"))],
                   [("propose_candidates", sc("A", "α1", "α2"))]])
    client, _, _ = make(tmp_path, sdk)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[], n=3), headers=H))
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=3, slot={**SLOT_A, "prefix": "φαίνεται "}), headers=H))
    r = [x["content"][0]["text"] for x in sdk.clients[0].results]
    assert "unknown slot 'Z'" in r[0] and "duplicates skipped" in r[2]
    assert [e["greek"] for e in evs if e["type"] == "candidate"] == ["α2"]
    assert "already offered (do not repeat): α1" in sdk.prompts[1]


def test_runner_error_becomes_error_event(tmp_path):
    class Broken(FakeSDK):
        def __call__(self, options, tools):
            client = super().__call__(options, tools)

            async def boom(prompt=None):
                raise RuntimeError("cli died")
            client.connect = boom
            return client
    sdk = Broken()
    client, _, _ = make(tmp_path, sdk)
    with client:
        evs = events(client.post("/chat", json={"poem": POEM, "message": "?"}, headers=H))
        assert [e["type"] for e in evs] == ["error", "done"] and "RuntimeError" in evs[0]["message"]
        assert not client.app.state.sessions.by_key                           # the broken session was dropped


def test_norm_keeps_line_breaks():
    assert norm("  φαίνεταί  μοι \n κῆνος / ἴσος ") == "φαίνεταί μοι\nκῆνος\nἴσος"


def test_usage_is_the_results_else_each_message_once_at_its_largest_figure():
    from composer_agent.runner import consume

    class Client:
        async def query(self, prompt, session_id="default"):
            pass

        async def receive_response(self):
            for mid, out in (("m1", 2), ("m1", 583), ("m1", 583), ("m2", 40)):
                yield AssistantMessage(content=[], model=MODEL, message_id=mid,
                                       usage={"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": 100})
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                session_id="s", usage={"output_tokens": 9999}, total_cost_usd=1.0)

    async def emit(_):
        return None
    class NoResult(Client):
        async def receive_response(self):
            async for m in super().receive_response():
                if isinstance(m, AssistantMessage):
                    yield m
    out = Outcome()
    asyncio.run(consume(NoResult(), "p", emit, False, out))
    assert out.usage == {"input_tokens": 2, "output_tokens": 623, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0}
    out = Outcome()
    asyncio.run(consume(Client(), "p", emit, False, out))       # the result's per-query usage wins
    assert out.usage == out.sdk_usage == {"input_tokens": 0, "output_tokens": 9999, "cache_read_input_tokens": 0,
                                          "cache_creation_input_tokens": 0} and out.session_id == "s"
