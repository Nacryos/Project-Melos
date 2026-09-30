"""Durable, fail-closed budget and response cache for paid contextual decisions.

This is operational state, never philological evidence. Failed attempts consume
budget: an HTTP failure does not prove that the provider did not bill the call.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
# Bump whenever the provider prompt, answer schema, or interpretation changes.
CACHE_VERSION = "jev-contextual-parse-v1"
CACHE_TTL = 30 * 86400
CACHE_MAX_ENTRIES = 20000


class GatewayLimit(RuntimeError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class GatewayUnavailable(RuntimeError):
    pass


def public_enabled() -> bool:
    return os.environ.get("MELOS_PUBLIC_CLASSIFIER") == "1"


def _positive_setting(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        raise GatewayUnavailable("Classifier budget configuration is invalid.") from None
    if value < 1:
        raise GatewayUnavailable("Classifier budget configuration is invalid.")
    return value


class CachedJevProvider:
    """Wrap one provider, with per-request visitor identity already securely hashed.

    SQLite BEGIN IMMEDIATE makes reservations atomic across threads/processes.
    No network calls occur while a database transaction is held. Lease expiry is
    deliberately longer than the provider timeout; abandoned reservations still
    count against the daily budget, but cannot block service indefinitely.
    """

    def __init__(self, provider, visitor_id: str, *, state_path=None, clock=None):
        self.provider = provider
        self.model = getattr(provider, "model", None)
        if not isinstance(self.model, str) or not self.model:
            raise GatewayUnavailable("Classifier model is not configured.")
        if not isinstance(visitor_id, str) or not re.fullmatch(r"[0-9a-f]{64}", visitor_id):
            raise GatewayUnavailable("Classifier visitor identity is invalid.")
        self.visitor_id = visitor_id
        self.state_path = Path(state_path or os.environ.get(
            "MELOS_CLASSIFIER_STATE", str(ROOT / "runtime" / "classifier.sqlite")))
        self.clock = clock or time.time
        self.daily_limit = _positive_setting("MELOS_CLASSIFIER_DAILY_LIMIT", 500)
        self.minute_limit = _positive_setting("MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT", 10)
        self.visitor_daily_limit = _positive_setting("MELOS_CLASSIFIER_VISITOR_DAILY_LIMIT", 60)
        self.concurrency = _positive_setting("MELOS_CLASSIFIER_CONCURRENCY", 2)
        try:
            timeout = float(getattr(provider, "timeout", 8.0))
        except (TypeError, ValueError):
            raise GatewayUnavailable("Classifier timeout is invalid.") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise GatewayUnavailable("Classifier timeout is invalid.")
        self.lease_seconds = max(120.0, timeout * 4 + 30)

    def _connect(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.state_path, timeout=3, isolation_level=None)
        try:
            connection.executescript("""
                PRAGMA busy_timeout=3000;
                CREATE TABLE IF NOT EXISTS decision_cache (
                    cache_key TEXT PRIMARY KEY, answer TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS decision_expiry ON decision_cache(expires);
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, visitor TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS attempt_time ON attempts(created);
                CREATE INDEX IF NOT EXISTS visitor_time ON attempts(visitor, created);
                CREATE TABLE IF NOT EXISTS leases (
                    cache_key TEXT PRIMARY KEY, token TEXT NOT NULL, expires REAL NOT NULL);
            """)
            return connection
        except Exception:
            connection.close()
            raise

    def _key(self, packet):
        payload = json.dumps({"version": CACHE_VERSION, "model": self.model, "packet": packet},
                             sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _answer(answer: Mapping[str, Any], packet) -> dict[str, Any]:
        if not isinstance(answer, Mapping):
            raise GatewayUnavailable("Classifier returned an invalid decision.")
        choices = {str(row["id"]) for row in packet.get("candidates", [])} | {"abstain"}
        if (not isinstance(answer.get("choice"), str) or answer["choice"] not in choices
                or not isinstance(answer.get("model"), str) or not answer["model"].strip()):
            raise GatewayUnavailable("Classifier returned an invalid decision.")
        # Never store the raw HTTP response, request, credentials, or error text.
        safe = {key: answer[key] for key in (
            "choice", "model", "model_probabilities", "model_confidence", "usage") if key in answer}
        serialized = json.dumps(safe, allow_nan=False, ensure_ascii=False)
        if len(serialized) > 65536:
            raise GatewayUnavailable("Classifier returned an oversized decision.")
        return safe

    def _reserve(self, cache_key, token):
        now = float(self.clock())
        day_start = math.floor(now / 86400) * 86400
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Bounded maintenance; only expired historical records are discarded.
            connection.execute("DELETE FROM leases WHERE expires <= ?", (now,))
            connection.execute("DELETE FROM attempts WHERE id IN (SELECT id FROM attempts "
                               "WHERE created < ? ORDER BY created LIMIT 256)", (now - 2 * 86400,))
            connection.execute("DELETE FROM decision_cache WHERE cache_key IN (SELECT cache_key "
                               "FROM decision_cache WHERE expires <= ? ORDER BY expires LIMIT 128)", (now,))
            cached = connection.execute("SELECT answer FROM decision_cache WHERE cache_key=? "
                                        "AND expires>?", (cache_key, now)).fetchone()
            if cached:
                connection.commit()
                return json.loads(cached[0])
            duplicate = connection.execute("SELECT expires FROM leases WHERE cache_key=?", (cache_key,)).fetchone()
            if duplicate:
                raise GatewayLimit("This classification is already running. Please retry shortly.",
                                   min(10, math.ceil(duplicate[0] - now)))
            if connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0] >= self.concurrency:
                raise GatewayLimit("Contextual classification is busy. Please retry shortly.", 5)
            if connection.execute("SELECT COUNT(*) FROM attempts WHERE created>=?", (day_start,)).fetchone()[0] >= self.daily_limit:
                raise GatewayLimit("The site's daily classification allowance has been reached. Cached decisions remain available.",
                                   math.ceil(day_start + 86400 - now))
            if connection.execute("SELECT COUNT(*) FROM attempts WHERE visitor=? AND created>=?",
                                  (self.visitor_id, day_start)).fetchone()[0] >= self.visitor_daily_limit:
                raise GatewayLimit("Your daily classification allowance has been reached. Cached decisions remain available.",
                                   math.ceil(day_start + 86400 - now))
            recent = connection.execute("SELECT COUNT(*), MIN(created) FROM attempts WHERE visitor=? AND created>?",
                                        (self.visitor_id, now - 60)).fetchone()
            if recent[0] >= self.minute_limit:
                raise GatewayLimit("Please slow down new contextual classifications.", math.ceil(recent[1] + 60 - now))
            connection.execute("INSERT INTO attempts VALUES (?, ?, ?)", (token, self.visitor_id, now))
            connection.execute("INSERT INTO leases VALUES (?, ?, ?)", (cache_key, token, now + self.lease_seconds))
            connection.commit()
            return None
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def _finish(self, cache_key, token, answer=None):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if answer is not None:
                count = connection.execute("SELECT COUNT(*) FROM decision_cache").fetchone()[0]
                if count >= CACHE_MAX_ENTRIES:
                    connection.execute("DELETE FROM decision_cache WHERE cache_key IN (SELECT cache_key "
                                       "FROM decision_cache ORDER BY created LIMIT ?)", (count - CACHE_MAX_ENTRIES + 1,))
                now = float(self.clock())
                connection.execute("INSERT OR REPLACE INTO decision_cache VALUES (?, ?, ?, ?)",
                                   (cache_key, json.dumps(answer, ensure_ascii=False, allow_nan=False), now, now + CACHE_TTL))
            connection.execute("DELETE FROM leases WHERE cache_key=? AND token=?", (cache_key, token))
            connection.commit()
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            cache_key, token = self._key(packet), uuid.uuid4().hex
            cached = self._reserve(cache_key, token)
            if cached is not None:
                return {**self._answer(cached, packet), "cache_hit": True}
        except GatewayLimit:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            raise GatewayUnavailable("Classifier cache is unavailable; no paid request was made.") from None
        try:
            answer = self._answer(self.provider.decide(packet), packet)
        except Exception:
            try:
                self._finish(cache_key, token)
            except (sqlite3.Error, OSError):
                pass  # Durable lease expires; attempt remains charged either way.
            raise GatewayUnavailable("Contextual classification failed. Please try again later.") from None
        try:
            self._finish(cache_key, token, answer)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise GatewayUnavailable("Classifier could not save the decision. Please try again later.") from None
        return {**answer, "cache_hit": False}
