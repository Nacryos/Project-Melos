"""Synthetic operational tests; these fixtures are not corpus assertions."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import threading

import pytest

from backend import jev_gateway as gateway


VISITOR = hashlib.sha256(b"synthetic visitor").hexdigest()
OTHER_VISITOR = hashlib.sha256(b"different synthetic visitor").hexdigest()


def packet(identifier="a", evidence="source version one"):
    return {"candidates": [{"id": identifier}], "evidence": evidence}


class Provider:
    model = "synthetic-jev-model"
    timeout = 8

    def __init__(self, *, choice=None, failure=False):
        self.calls = 0
        self.choice = choice
        self.failure = failure

    def decide(self, state):
        self.calls += 1
        if self.failure:
            raise RuntimeError("PRIVATE PROVIDER ERROR APIKEY")
        return {"choice": self.choice or state["candidates"][0]["id"], "model": self.model,
                "model_confidence": .7, "raw_response": {"private": "not persisted"}}


@pytest.fixture(autouse=True)
def clear_config(monkeypatch):
    for name in ("MELOS_CLASSIFIER_DAILY_LIMIT", "MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT",
                 "MELOS_CLASSIFIER_VISITOR_DAILY_LIMIT", "MELOS_CLASSIFIER_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)


def wrapper(tmp_path, provider=None, visitor=VISITOR, clock=lambda: 100000):
    return gateway.CachedJevProvider(provider or Provider(), visitor,
                                     state_path=tmp_path / "classifier.sqlite", clock=clock)


def test_cache_survives_new_instances_and_is_free_after_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_CLASSIFIER_DAILY_LIMIT", "1")
    provider = Provider()
    first = wrapper(tmp_path, provider).decide(packet())
    second = wrapper(tmp_path, provider, visitor=OTHER_VISITOR).decide(packet())
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["model_confidence"] == .7
    assert provider.calls == 1
    with pytest.raises(gateway.GatewayLimit, match="site's daily"):
        wrapper(tmp_path, provider).decide(packet("b"))


def test_cache_key_includes_evidence_model_and_schema_version(tmp_path, monkeypatch):
    provider = Provider()
    cache = wrapper(tmp_path, provider)
    cache.decide(packet())
    cache.decide(packet(evidence="source version two"))
    provider.model = "synthetic-new-model"
    wrapper(tmp_path, provider).decide(packet())
    monkeypatch.setattr(gateway, "CACHE_VERSION", "new-schema-version")
    wrapper(tmp_path, provider).decide(packet())
    assert provider.calls == 4


def test_canonical_key_is_independent_of_object_key_order(tmp_path):
    provider = Provider()
    cache = wrapper(tmp_path, provider)
    cache.decide(packet())
    assert cache.decide(dict(reversed(list(packet().items()))))["cache_hit"] is True
    assert provider.calls == 1


def test_abstention_cached_but_raw_payload_never_saved(tmp_path):
    provider = Provider(choice="abstain")
    cache = wrapper(tmp_path, provider)
    assert cache.decide(packet())["choice"] == "abstain"
    assert cache.decide(packet())["cache_hit"] is True
    with sqlite3.connect(cache.state_path) as db:
        serialized = db.execute("SELECT answer FROM decision_cache").fetchone()[0]
    assert "raw_response" not in serialized
    assert "private" not in serialized


def test_failures_are_charged_and_secret_error_is_not_returned_or_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_CLASSIFIER_DAILY_LIMIT", "1")
    provider = Provider(failure=True)
    cache = wrapper(tmp_path, provider)
    with pytest.raises(gateway.GatewayUnavailable) as error:
        cache.decide(packet())
    assert "APIKEY" not in str(error.value)
    with pytest.raises(gateway.GatewayLimit):
        wrapper(tmp_path, provider).decide(packet())
    assert provider.calls == 1
    with sqlite3.connect(cache.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM decision_cache").fetchone()[0] == 0


@pytest.mark.parametrize("choice", ["invented-candidate", 17])
def test_invalid_choice_not_cached(tmp_path, choice):
    cache = wrapper(tmp_path, Provider(choice=choice))
    with pytest.raises(gateway.GatewayUnavailable):
        cache.decide(packet())
    with sqlite3.connect(cache.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM decision_cache").fetchone()[0] == 0


def test_unidentified_response_model_not_cached(tmp_path):
    class NoModel(Provider):
        def decide(self, state):
            return {"choice": "a", "model": None}
    with pytest.raises(gateway.GatewayUnavailable):
        wrapper(tmp_path, NoModel()).decide(packet())


def test_visitor_minute_limit_does_not_block_other_visitors(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT", "1")
    wrapper(tmp_path).decide(packet())
    with pytest.raises(gateway.GatewayLimit, match="slow down") as error:
        wrapper(tmp_path).decide(packet("b"))
    assert error.value.retry_after == 60
    assert wrapper(tmp_path, visitor=OTHER_VISITOR).decide(packet("b"))["cache_hit"] is False
    assert wrapper(tmp_path, clock=lambda: 100061).decide(packet("c"))["cache_hit"] is False


def test_visitor_daily_limit_and_utc_day_rollover(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_CLASSIFIER_VISITOR_DAILY_LIMIT", "1")
    wrapper(tmp_path).decide(packet())
    with pytest.raises(gateway.GatewayLimit, match="Your daily"):
        wrapper(tmp_path, clock=lambda: 100061).decide(packet("b"))
    assert wrapper(tmp_path, clock=lambda: 172801).decide(packet("b"))["cache_hit"] is False


def test_concurrency_and_duplicate_packets_do_not_consume_budget(tmp_path):
    started = [threading.Event(), threading.Event()]
    release = threading.Event()

    class BlockingProvider(Provider):
        def __init__(self, event):
            super().__init__()
            self.event = event

        def decide(self, state):
            self.event.set()
            assert release.wait(10)
            return super().decide(state)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(wrapper(tmp_path, BlockingProvider(started[0])).decide, packet("a"))
        assert started[0].wait(5)
        with pytest.raises(gateway.GatewayLimit, match="already running"):
            wrapper(tmp_path).decide(packet("a"))
        second = pool.submit(wrapper(tmp_path, BlockingProvider(started[1])).decide, packet("b"))
        assert started[1].wait(5)
        try:
            with pytest.raises(gateway.GatewayLimit, match="busy"):
                wrapper(tmp_path).decide(packet("c"))
        finally:
            release.set()
        assert first.result()["cache_hit"] is False
        assert second.result()["cache_hit"] is False
    with sqlite3.connect(tmp_path / "classifier.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2


def test_simultaneous_requests_reserve_only_one_daily_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_CLASSIFIER_DAILY_LIMIT", "1")
    barrier = threading.Barrier(6)

    def run(index):
        barrier.wait(timeout=10)
        try:
            return wrapper(tmp_path).decide(packet(str(index)))
        except gateway.GatewayLimit:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, range(6)))
    assert sum(result is not None for result in results) == 1


def test_stale_lease_expires_but_does_not_refund_budget(tmp_path):
    cache = wrapper(tmp_path)
    state = packet()
    assert cache._reserve(cache._key(state), "synthetic-crash") is None
    assert wrapper(tmp_path, clock=lambda: 100121).decide(state)["cache_hit"] is False
    with sqlite3.connect(cache.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2


def test_cache_expiry_and_entry_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "CACHE_MAX_ENTRIES", 2)
    provider = Provider()
    cache = wrapper(tmp_path, provider)
    cache.decide(packet("a"))
    wrapper(tmp_path, provider, clock=lambda: 100001).decide(packet("b"))
    wrapper(tmp_path, provider, clock=lambda: 100002).decide(packet("c"))
    with sqlite3.connect(cache.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM decision_cache").fetchone()[0] == 2
    assert wrapper(tmp_path, provider, clock=lambda: 100003 + gateway.CACHE_TTL).decide(packet("c"))["cache_hit"] is False


def test_database_failure_is_closed_without_provider_request(tmp_path):
    provider = Provider()
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("fixture")
    cache = gateway.CachedJevProvider(provider, VISITOR, state_path=blocked_parent / "cache.db")
    with pytest.raises(gateway.GatewayUnavailable, match="no paid request"):
        cache.decide(packet())
    assert provider.calls == 0


def test_invalid_configuration_and_raw_ip_rejected(tmp_path, monkeypatch):
    with pytest.raises(gateway.GatewayUnavailable, match="identity"):
        wrapper(tmp_path, visitor="127.0.0.1")
    monkeypatch.setenv("MELOS_CLASSIFIER_DAILY_LIMIT", "unlimited")
    with pytest.raises(gateway.GatewayUnavailable, match="configuration"):
        wrapper(tmp_path)


def test_public_enable_requires_explicit_value(monkeypatch):
    monkeypatch.delenv("MELOS_PUBLIC_CLASSIFIER", raising=False)
    assert not gateway.public_enabled()
    monkeypatch.setenv("MELOS_PUBLIC_CLASSIFIER", "true")
    assert not gateway.public_enabled()
    monkeypatch.setenv("MELOS_PUBLIC_CLASSIFIER", "1")
    assert gateway.public_enabled()
