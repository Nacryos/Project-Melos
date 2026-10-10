"""Unit tests with a fake melos-api and a scripted SDK client: no Anthropic calls."""
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
from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, SystemMessage, TextBlock  # noqa: E402
from composer_agent.fills import Gate  # noqa: E402
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
SESSION_ID = "11111111-2222-3333-4444-555555555555"


class FakeRunner:
    """One-shot runner (back-translation): returns fixed text and usage."""

    def __init__(self, text="", error=None):
        self.text, self.error, self.jobs = text, error, []

    async def run(self, job: Job) -> Outcome:
        self.jobs.append(job)
        return Outcome(usage=dict(USAGE), text=self.text, error=self.error, stop_reason="end_turn")


def research_prompt(p: str) -> bool:
    return "research only" in p


def fill_of(p: str) -> tuple | None:
    """(slot key, mode) of a fill prompt, else None."""
    if "Task: NEXT WORDS" in p or "Task: fill the autocomplete pool" in p:
        key = p.split("- slot ", 1)[1].split(":", 1)[0]
        return key, ("words" if "NEXT WORDS" in p else "line")
    return None


class FakeSDK:
    """Stands in for ClaudeSDKClient: one instance per session or fill. ``script`` maps a prompt to actions:
    a dict keyed "research", (slot, mode) or "chat" (chat prompts), a list consumed in order, or a callable.
    Actions: (tool, args) calls the real tool handler, ("sleep", s) waits (an interrupt cuts it short), ("text", s)
    streams text; then the turn ends with one assistant message and a result (session id SESSION_ID)."""

    def __init__(self, script=()):
        self.script, self.clients, self.running = script, [], 0
        self.max_running = 0

    def __call__(self, options, tools):
        client = _FakeClient(self, options, tools)
        self.clients.append(client)
        return client

    def actions(self, prompt):
        if callable(self.script):
            return self.script(prompt)
        if isinstance(self.script, dict):
            if research_prompt(prompt):
                return list(self.script.get("research", []))
            f = fill_of(prompt)
            return list(self.script.get(f if f else "chat", []))
        return self.script.pop(0) if self.script else []

    @property
    def prompts(self):
        return [p for c in self.clients for p in c.prompts]

    def fills(self):
        return [c for c in self.clients if c.options.resume or (c.prompts and fill_of(c.prompts[0]))]


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
        actions = self.owner.actions(self.prompts[-1])
        n = len(self.prompts)
        self.owner.running += 1
        self.owner.max_running = max(self.owner.max_running, self.owner.running)
        try:
            yield SystemMessage(subtype="init", data={"session_id": SESSION_ID})
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
                                session_id=SESSION_ID, stop_reason="end_turn", total_cost_usd=0.1, usage=dict(USAGE))
        finally:
            self.owner.running -= 1


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


def cands(evs):
    return [e for e in evs if e["type"] == "candidate"]


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


# ---------------------------------------------------------------------------------------------- effort per job kind

def test_sdk_options_lock_model_and_tools_and_take_effort_and_fork(tmp_path, monkeypatch):
    key = tmp_path / "k"
    key.write_text("sk-test\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(key))
    s = Settings(state_dir=tmp_path, token=TOKEN)
    opts = sdk_options(s, "s", {"type": "sdk", "name": "melos"})
    assert (opts.model, opts.effort) == (MODEL, EFFORT) == ("claude-fable-5-1", "xhigh")
    assert opts.resume is None and opts.fork_session is False
    assert opts.tools == [] and opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert opts.thinking is None and opts.max_thinking_tokens is None    # Fable 5.1: never set a budget
    assert all(t.startswith("mcp__melos__") for t in opts.allowed_tools) and "mcp__melos__check_candidate" in opts.allowed_tools
    assert "Bash" in opts.disallowed_tools and opts.env["ANTHROPIC_API_KEY"] == "sk-test"
    fork = sdk_options(s, "s", {"type": "sdk", "name": "melos"}, effort="medium", resume=SESSION_ID)
    assert (fork.model, fork.effort, fork.resume, fork.fork_session) == (MODEL, "medium", SESSION_ID, True)
    assert fork.cwd == opts.cwd and fork.env["CLAUDE_CONFIG_DIR"] == opts.env["CLAUDE_CONFIG_DIR"]   # same transcript dir


def test_effort_settings_per_kind(monkeypatch):
    s = Settings(state_dir=Path("/tmp/x"), token=TOKEN)
    assert (s.pool_effort, s.chat_effort, s.warm_effort) == ("medium", "xhigh", "xhigh")
    assert (s.effort_for("pool"), s.effort_for("chat"), s.effort_for("warm"), s.effort_for("fill")) == ("medium", "xhigh", "xhigh", "medium")
    monkeypatch.setenv("COMPOSER_POOL_EFFORT", "high")
    monkeypatch.setenv("COMPOSER_CHAT_EFFORT", "xhigh")
    assert Settings(state_dir=Path("/tmp/x"), token=TOKEN).pool_effort == "high"
    monkeypatch.setenv("COMPOSER_POOL_EFFORT", "turbo")
    with pytest.raises(ValueError):
        Settings(state_dir=Path("/tmp/x"), token=TOKEN)


# ---------------------------------------------------------------------------------------------- research + fills

SLOT_A = {**SLOT, "slot_key": "A"}
NEXT = [{"line_position": 1, "prefix": "", "remaining_template": "-u-x-uu-u-F", "slot_key": "B"},
        {"line_position": 2, "prefix": "", "remaining_template": "-u-x-uu-u-F", "slot_key": "C"}]


def sc(slot, *greek):
    return {"candidates": [{"slot": slot, "greek": g, "english_span": "the moon", "evidence": ["Sappho 96"]} for g in greek]}


def pool_body(slot=SLOT_A, ahead=NEXT, n=2, poem=POEM, **kw):
    return {"poem": poem, "slot": slot, "ahead": ahead, "n": n, **kw}


def usage_log(settings):
    return [json.loads(l) for l in (settings.state_dir / "usage.jsonl").read_text().splitlines()]


def test_first_pool_request_runs_the_research_once_and_fills_each_slot_in_its_own_forked_session(tmp_path):
    sdk = FakeSDK({"research": [("lemma_search", {"q": "σελήνη", "author": "Sappho"})],
                   ("A", "line"): [("propose_candidates", sc("A", "πόντῳ πέρι", "bad one")), ("propose_candidates", sc("A", "late"))],
                   ("B", "line"): [("propose_candidates", sc("B", "ἄστερες μὲν"))],
                   ("C", "line"): [("propose_candidates", sc("C", "νύκτες\nἀμφὶ", "x"))]})
    client, melos, settings = make(tmp_path, sdk, pool_ahead_n=1)
    with client:
        evs = events(client.post("/pool", json=pool_body(), headers=H))
    got = cands(evs)
    assert {(c["slot_key"], c["greek"]) for c in got} == {("A", "πόντῳ πέρι"), ("B", "ἄστερες μὲν"), ("C", "νύκτες\nἀμφὶ"),
                                                         ("C", "x"), ("A", "late")}
    assert {c["slot_key"]: c["line_position"] for c in got} == {"A": 0, "B": 1, "C": 2}
    assert all(c["mode"] == "line" for c in got)
    bodies = {json.loads(r.content)["greek"]: json.loads(r.content) for r in melos.calls if r.url.path == "/api/composer/check"}
    assert bodies["πόντῳ πέρι"] == {"greek": "πόντῳ πέρι", "metre": "sapphic", "dialect": "aeolic", "author": "Sappho",
                                    "remaining_template": SLOT["remaining_template"], "prefix": "φαίνεται", "line_index": 0}
    assert bodies["ἄστερες μὲν"]["remaining_template"] == NEXT[0]["remaining_template"] and bodies["ἄστερες μὲν"]["line_index"] == 1
    # One research session (xhigh, research-only prompt) + three fills. The urgent one (A) ran cold while the
    # research was still running; B and C waited and forked from the research session at the pool effort.
    research = [c for c in sdk.clients if c.prompts and research_prompt(c.prompts[0])]
    assert len(research) == 1 and research[0].options.effort == "xhigh" and research[0].options.resume is None
    assert "first request for this poem" in research[0].prompts[0] and "The moon shows over the sea" in research[0].prompts[0]
    by_slot = {fill_of(c.prompts[0]): c for c in sdk.clients if c.prompts and fill_of(c.prompts[0])}
    assert set(by_slot) == {("A", "line"), ("B", "line"), ("C", "line")}
    a, b = by_slot[("A", "line")], by_slot[("B", "line")]
    assert a.options.resume is None and a.options.effort == "medium" and "research is still in progress" in a.prompts[0]
    assert "English source (whole)" in a.prompts[0]                        # cold: the whole poem context
    assert b.options.resume == SESSION_ID and b.options.fork_session is True and b.options.effort == "medium"
    assert b.prompts[0].startswith("Update to the poem") and "English source changed" not in b.prompts[0]
    assert all(c.disconnects == 1 for c in by_slot.values())             # fills are closed when done
    fills = [e for e in evs if e["type"] == "fill"]
    assert {(f["slot_key"], f["cold"]) for f in fills} == {("A", True), ("B", False), ("C", False)}
    assert evs[-1]["type"] == "done" and evs[-1]["fills"] == 3 and evs[-1]["cost_usd"] == pytest.approx(3 * cost_usd(USAGE))
    log = usage_log(settings)
    assert sorted(l["endpoint"] for l in log) == ["fill", "fill", "fill", "warm"]
    fa = next(l for l in log if l.get("slot_key") == "A")
    assert fa["effort"] == "medium" and fa["cold"] is True and fa["passed"] == {"A": 2} and fa["stop"] == "enough"
    assert next(l for l in log if l["endpoint"] == "warm")["effort"] == "xhigh"


def test_next_words_mode_proposes_short_continuations_only(tmp_path):
    sdk = FakeSDK({("A", "words"): [("propose_candidates", sc("A", "κῆνος", "ἴσος θέοισιν", "ὤνηρ ὄττις ἐνάντιός τοι", "bad")),
                                    ("propose_candidates", sc("A", "ἀ σελάννα"))]})
    client, _, settings = make(tmp_path, sdk, cold_fills=True)
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=3, mode="words"), headers=H))
    got = cands(evs)
    assert [c["greek"] for c in got] == ["κῆνος", "ἴσος θέοισιν", "ἀ σελάννα"] or sorted(c["greek"] for c in got) == ["ἀ σελάννα", "κῆνος", "ἴσος θέοισιν"]
    assert all(c["mode"] == "words" for c in got)
    fill = sdk.fills()[0]
    assert "Task: NEXT WORDS" in fill.prompts[0] and "one to three words" in fill.prompts[0]
    text = fill.results[0]["content"][0]["text"]
    assert "too long for next words" in text and "bad: L7" in text
    rejected = next(e for e in evs if e["type"] == "rejected")
    assert rejected["reasons"] == {"words_length": 1, "L7": 1} and rejected["mode"] == "words"
    assert "Stop now" in fill.results[1]["content"][0]["text"]            # n=3 reached
    log = next(l for l in usage_log(settings) if l["endpoint"] == "fill")
    assert log["mode"] == "words" and log["rounds"] == 2


def test_words_rounds_bound_the_fill(tmp_path):
    sdk = FakeSDK({("A", "words"): [("propose_candidates", sc("A", f"bad {i}")) for i in range(6)]})
    client, _, _ = make(tmp_path, sdk, words_rounds=2)
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=5, mode="words"), headers=H))
    texts = [r["content"][0]["text"] for r in sdk.fills()[0].results]
    assert "round limit" in texts[1] and all(t.startswith("Stop: this request is complete") for t in texts[2:])
    assert not cands(evs)


def test_candidates_stream_before_the_fill_ends(tmp_path, monkeypatch):
    # (TestClient buffers a whole response, so the timing is read where events enter the response queue.)
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "πρῶτον")), ("sleep", 0.6), ("propose_candidates", sc("A", "ὕστερον"))]})
    client, _, _ = make(tmp_path, sdk)
    seen, emit = {}, Turn.emit

    async def timed(self, event):
        seen.setdefault(event.get("greek") or event["type"], time.monotonic() - t0)
        await emit(self, event)
    monkeypatch.setattr(Turn, "emit", timed)
    with client:
        t0 = time.monotonic()
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
    assert seen["πρῶτον"] < 0.4 <= seen["ὕστερον"]


def test_research_runs_once_per_poem_and_later_fills_fork_from_it(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "α1", "α2"))], ("B", "line"): [("propose_candidates", sc("B", "β1", "β2"))]})
    client, _, settings = make(tmp_path, sdk, cold_fills=False)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        later = {**POEM, "lines": POEM["lines"] + [{"position": 1, "greek": "ἄστερες"}]}
        evs = events(client.post("/pool", json=pool_body(slot={**NEXT[0], "prefix": "ἄστερες"}, ahead=[], poem=later), headers=H))
    research = [c for c in sdk.clients if c.prompts and research_prompt(c.prompts[0])]
    assert len(research) == 1 and research[0].connects == 1
    a, b = sdk.fills()
    assert a.options.resume == b.options.resume == SESSION_ID             # cold fills off: both waited and forked
    assert b.prompts[0].startswith("Update to the poem") and "ἄστερες" in b.prompts[0]
    assert sorted(e["greek"] for e in cands(evs)) == ["β1", "β2"]
    assert [l["endpoint"] for l in usage_log(settings)] == ["warm", "fill", "fill"]


def test_changed_english_is_sent_to_fills_and_settings_open_a_new_session(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "α1", "α2"))]})
    client, _, _ = make(tmp_path, sdk, cold_fills=False)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        events(client.post("/pool", json=pool_body(ahead=[], poem={**POEM, "english": "The moon has set"}), headers=H))
        events(client.post("/pool", json=pool_body(ahead=[], poem={**POEM, "settings": {**POEM["settings"], "metre": "alcaic"}}), headers=H))
    fills = sdk.fills()
    assert "English source changed" not in fills[0].prompts[0] and "now reads (whole):\nThe moon has set" in fills[1].prompts[0]
    research = [c for c in sdk.clients if c.prompts and research_prompt(c.prompts[0])]
    assert len(research) == 2                                            # alcaic: a new research session


def test_chat_has_its_own_session_at_xhigh_and_sends_the_thread_once(tmp_path):
    sdk = FakeSDK({"chat": [("lemma_search", {"q": "σελήνη", "author": "Sappho"}), ("text", "Sappho has σελάννα.")]})
    client, melos, _ = make(tmp_path, sdk)
    with client:
        evs = events(client.post("/chat", json={"poem": POEM, "thread": [{"role": "user", "content": "earlier"}],
                                                "message": "Which word for moon?"}, headers=H))
        events(client.post("/chat", json={"poem": POEM, "thread": [{"role": "user", "content": "earlier"}],
                                          "message": "Attested?"}, headers=H))
    assert len(sdk.clients) == 1 and sdk.clients[0].options.include_partial_messages is True
    assert sdk.clients[0].options.effort == "xhigh" and sdk.clients[0].options.resume is None
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "tool" and evs[0]["name"] == "lemma_search" and kinds[-1] == "done" and "rejected" not in kinds
    assert "".join(e["delta"] for e in evs if e["type"] == "text").strip() == "Sappho has σελάννα."
    c1, c2 = sdk.clients[0].prompts
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


def test_request_for_a_slot_whose_fill_runs_joins_it(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "α1")), ("sleep", 0.5), ("propose_candidates", sc("A", "α2"))]})
    client, _, settings = make(tmp_path, sdk)
    with client:
        t, out = _in_thread(lambda: events(client.post("/pool", json=pool_body(n=2, ahead=[]), headers=H)))
        _wait_for(lambda: sdk.fills() and sdk.fills()[0].results)
        joined = events(client.post("/pool", json=pool_body(n=2, ahead=[]), headers=H))
        t.join()
    assert len(sdk.fills()) == 1                                           # no second fill
    got = cands(joined)
    assert got[0] == {**got[0], "greek": "α1", "replay": True} and got[1]["greek"] == "α2" and "replay" not in got[1]
    assert joined[-1]["type"] == "done" and joined[-1]["cost_usd"] == 0
    assert next(e for e in joined if e["type"] == "fill")["shared"] is True
    assert out["v"][-1]["cost_usd"] == pytest.approx(cost_usd(USAGE))
    assert len([l for l in usage_log(settings) if l["endpoint"] == "fill"]) == 1


def test_fills_run_in_parallel_up_to_the_bound_and_an_urgent_fill_preempts_a_left_behind_one(tmp_path):
    script = {"research": [], ("Z", "line"): [("propose_candidates", sc("Z", "ζ1", "ζ2"))]}
    for k in "ABCD":
        script[(k, "line")] = [("propose_candidates", sc(k, "bad " + k)), ("sleep", 5)]      # not satisfied: keeps running
    sdk = FakeSDK(script)
    client, _, settings = make(tmp_path, sdk, pool_parallel=2, pool_ahead_n=1)
    ahead = [{"line_position": i + 1, "prefix": "", "remaining_template": "-u-x-uu-u-F", "slot_key": k} for i, k in enumerate("BCD")]
    with client:
        t0 = time.monotonic()
        t, _ = _in_thread(lambda: events(client.post("/warm", json=pool_body(n=1, ahead=ahead), headers=H)))
        _wait_for(lambda: sdk.running == 2 and len(sdk.fills()) == 2)
        time.sleep(0.2)
        assert sdk.running == 2 and sdk.max_running == 2                   # A and B run; C and D wait (plus words for A, queued)
        # The owner moves to a new slot Z: no permit is free, so the oldest running fill for a slot Z's request does
        # not name (A) is preempted, Z gets the permit first (urgent), the queued ones follow.
        z = events(client.post("/pool", json={"poem": POEM, "slot": {**NEXT[0], "slot_key": "Z"}, "ahead": [], "n": 2}, headers=H))
        assert time.monotonic() - t0 < 3
        assert [e["greek"] for e in cands(z)] == ["ζ1", "ζ2"]
        fills = client.app.state.fills
        for f in list(fills.active.values()):
            f.turn.ctx.halt("test")
        t.join()
    assert sdk.max_running == 2
    a = next(c for c in sdk.fills() if fill_of(c.prompts[0]) == ("A", "line"))
    assert a.interrupts == 1
    logs = {(l.get("slot_key"), l.get("mode")): l for l in usage_log(settings) if l["endpoint"] == "fill"}
    assert logs[("A", "line")]["stop"] == "preempted" and logs[("Z", "line")]["stop"] == "enough" and logs[("Z", "line")]["urgent"] is True


def test_gate_serves_urgent_waiters_first():
    async def go():
        g = Gate(1)
        order = []
        await g.acquire()

        async def waiter(name, urgent):
            await g.acquire(urgent)
            order.append(name)
            g.release()
        tasks = [asyncio.ensure_future(waiter("slow", False)), asyncio.ensure_future(waiter("slow2", False))]
        await asyncio.sleep(0)
        tasks.append(asyncio.ensure_future(waiter("urgent", True)))
        await asyncio.sleep(0)
        g.release()
        await asyncio.gather(*tasks)
        assert order == ["urgent", "slow", "slow2"] and g.running == 0
    asyncio.run(go())


def test_warm_fills_the_stanza_in_line_mode_plus_next_words_and_skips_what_is_filled(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "α1", "α2"))], ("A", "words"): [("propose_candidates", sc("A", "ἀ", "ἀλλ’"))],
                   ("B", "line"): [("propose_candidates", sc("B", "β1"))]})
    client, _, settings = make(tmp_path, sdk, pool_ahead_n=1, words_n=2)
    with client:
        evs = events(client.post("/warm", json=pool_body(n=2, ahead=NEXT[:1]), headers=H))
        assert {(f["slot_key"], f["mode"]) for f in evs if f["type"] == "fill"} == {("A", "line"), ("A", "words"), ("B", "line")}
        assert {c["mode"] for c in cands(evs)} == {"line", "words"}
        again = events(client.post("/warm", json=pool_body(n=2, ahead=NEXT[:1]), headers=H))   # already filled: no fill
    assert again == [{"type": "done", "usage": {}, "cost_usd": 0, "terminal_reason": "already_filled",
                      "skipped": [{"slot_key": "A", "mode": "line"}, {"slot_key": "B", "mode": "line"}, {"slot_key": "A", "mode": "words"}]}]
    assert len(sdk.fills()) == 3
    research = [c for c in sdk.clients if c.prompts and research_prompt(c.prompts[0])]
    assert len(research) == 1 and all(c.options.resume == SESSION_ID for c in sdk.fills())   # warm fills wait for the research


def test_warm_research_only_then_already_warm(tmp_path):
    sdk = FakeSDK({"research": [("lemma_search", {"q": "σελήνη"})]})
    client, _, settings = make(tmp_path, sdk)
    with client:
        evs = events(client.post("/warm", json={"poem": POEM}, headers=H))
        assert evs[0]["type"] == "tool" and evs[-1]["type"] == "done" and evs[-1]["cost_usd"] == pytest.approx(cost_usd(USAGE))
        assert "research only" in sdk.prompts[0] and "first request for this poem" in sdk.prompts[0]
        again = events(client.post("/warm", json={"poem": POEM}, headers=H))           # already warm: no model call
    assert len(sdk.prompts) == 1 and again[-1]["terminal_reason"] == "already_warm" and again[-1]["cost_usd"] == 0
    assert [l["endpoint"] for l in usage_log(settings)] == ["warm"]


def test_idle_sessions_are_closed_and_the_next_request_starts_fresh(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "α1", "α2"))]})
    client, _, _ = make(tmp_path, sdk, session_idle_seconds=60, cold_fills=False)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
        sessions = client.app.state.sessions
        assert client.portal.call(sessions.reap) == 0                          # not idle long enough
        assert client.portal.call(sessions.reap, time.monotonic() + 61) == 1
        assert sdk.clients[0].disconnects == 1 and not sessions.by_key
        events(client.post("/pool", json=pool_body(ahead=[]), headers=H))
    research = [c for c in sdk.clients if c.prompts and research_prompt(c.prompts[0])]
    assert len(research) == 2


def test_session_count_is_bounded(tmp_path):
    settings = Settings(state_dir=tmp_path, token=TOKEN, max_sessions=1)
    sdk = FakeSDK()

    async def go():
        sessions = Sessions(settings, sdk)
        a = sessions.get("a", "pool", "s")
        b = sessions.get("b", "pool", "s")                                    # a is idle: closed to make room
        await asyncio.sleep(0)
        assert list(sessions.by_key) == ["b"] and a.closed
        b.fills_active = 1                                                    # b has a fill running: busy
        with pytest.raises(Busy):
            sessions.get("c", "pool", "s")
        assert sessions.get("b", "pool", "s") is b
        assert a.effort == "xhigh"                                            # pool sessions hold the research at the warm effort
    asyncio.run(go())


def test_busy_answers_503(tmp_path):
    sdk = FakeSDK({("A", "line"): [("sleep", 0.5)]})
    client, _, _ = make(tmp_path, sdk, max_sessions=1)
    with client:
        t, _ = _in_thread(lambda: client.post("/pool", json=pool_body(ahead=[]), headers=H))
        _wait_for(lambda: sdk.prompts)
        r = client.post("/chat", json={"poem": POEM, "message": "?"}, headers=H)
        t.join()
    assert r.status_code == 503


def test_round_limit_and_lint_outage(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", f"bad {i}")) for i in range(6)]})
    client, _, _ = make(tmp_path, sdk, pool_rounds=4)
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=5), headers=H))
    assert not cands(evs)
    texts = [r["content"][0]["text"] for r in sdk.fills()[0].results]
    assert "round limit" in texts[3] and all(t.startswith("Stop: this request is complete") for t in texts[4:])
    assert next(e for e in evs if e["type"] == "rejected")["count"] == 4
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("A", "πόντῳ πέρι"))]})
    client, _, _ = make(tmp_path, sdk, melos=FakeMelos(check_status=503))
    with client:
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=1), headers=H))
    assert not cands(evs)
    assert next(e for e in evs if e["type"] == "rejected")["reasons"] == {"lint_unavailable": 1}


def test_unknown_slot_and_duplicates_across_fills_are_refused(tmp_path):
    sdk = FakeSDK({("A", "line"): [("propose_candidates", sc("Z", "α1")), ("propose_candidates", sc("A", "α1"))],
                   ("A", "words"): [("propose_candidates", sc("A", "α1", "α2"))]})
    client, _, _ = make(tmp_path, sdk)
    with client:
        events(client.post("/pool", json=pool_body(ahead=[], n=3), headers=H))
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=3, mode="words"), headers=H))
    line, words = sdk.fills()
    r = [x["content"][0]["text"] for x in line.results]
    assert "unknown slot 'Z'" in r[0]
    assert "duplicates skipped" in words.results[0]["content"][0]["text"]  # α1 was offered by the line fill
    assert [e["greek"] for e in cands(evs)] == ["α2"]
    assert "already offered (do not repeat): α1" in words.prompts[0]


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
        evs = events(client.post("/pool", json=pool_body(ahead=[], n=1), headers=H))
        assert [e["type"] for e in evs][:2] == ["error", "rejected"] and evs[-1]["type"] == "done"
        assert not client.app.state.fills.active


def test_norm_keeps_line_breaks():
    assert norm("  φαίνεταί  μοι \n κῆνος / ἴσος ") == "φαίνεταί μοι\nκῆνος\nἴσος"


def test_usage_is_the_results_else_each_message_once_at_its_largest_figure():
    from composer_agent.runner import consume

    class Client:
        async def query(self, prompt, session_id="default"):
            pass

        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "init-id"})
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
                if not isinstance(m, ResultMessage):
                    yield m
    out = Outcome()
    asyncio.run(consume(NoResult(), "p", emit, False, out))
    assert out.usage == {"input_tokens": 2, "output_tokens": 623, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0}
    assert out.session_id == "init-id"                                     # known from the init message
    out = Outcome()
    asyncio.run(consume(Client(), "p", emit, False, out))       # the result's per-query usage wins
    assert out.usage == out.sdk_usage == {"input_tokens": 0, "output_tokens": 9999, "cache_read_input_tokens": 0,
                                          "cache_creation_input_tokens": 0} and out.session_id == "s"
