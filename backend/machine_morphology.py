"""Explicit, bounded Alpheios machine analyses; never corpus attestations.

Endpoint: Alpheios' official client config at alpheios-core a27dc27a,
packages/client-adapters/src/adapters/tufts/config.json. Service revision unknown.
SQLite holds immutable raw receipts and cross-process miss reservations/quotas.
No retries, redirects, accent folding, feature inference, or dictionary joins.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone

PARSER_VERSION = "alpheios-literal-v1"
ENDPOINT = "https://morph.alpheios.net/api/v1/analysis/word"
CLIENT = "project-melos-explicit-morphology"
MAX_RESPONSE = 262144
TIMEOUT = 8
FAILURE_BACKOFF = 300
WARNINGS = ["Machine-generated alternatives, not occurrence-attested or contextually adjudicated morphology.",
            "The deployed engine and stem-library revisions are unknown; dialect labels are not exhaustive."]
ELISION_MARKS = "\u2019\u1fbd"
ELISION_CONVENTION = ("https://github.com/alpheios-project/alpheios-core/blob/"
                     "a27dc27afa166998c15335295a63233219a16741/"
                     "packages/data-models/src/greek_language_model.js#L153-L158")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def validate_form(value):
    """One Greek word with an optional final elision mark; no letter repairs."""
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise ValueError("Expected one Greek word (maximum 80 characters)")
    value = unicodedata.normalize("NFC", value)
    has_letter = False
    letters = value[:-1] if value[-1] in ELISION_MARKS else value
    for char in letters:
        category = unicodedata.category(char)
        if category.startswith("L") and "GREEK" in unicodedata.name(char, ""):
            has_letter = True
        elif category.startswith("M") and has_letter and char in "\u0300\u0301\u0304\u0306\u0308\u0313\u0314\u0342\u0345":
            continue
        else:
            raise ValueError("Only Greek letters, accent marks, and one final elision mark are accepted")
    if not has_letter:
        raise ValueError("Expected Greek letters")
    return value


def transport_form(form):
    """Documented Alpheios spelling, kept separate from the source spelling.

    GreekLanguageModel.normalizeText at ELISION_CONVENTION maps final U+2019
    to U+1FBD. No ASCII apostrophe, accent folding, or restored letters.
    """
    return form[:-1] + "\u1fbd" if form.endswith("\u2019") else form


def request_url(form):
    parameters = {"word": transport_form(form), "engine": "morpheusgrc",
                  "lang": "grc", "clientId": CLIENT}
    if form.endswith(tuple(ELISION_MARKS)):
        # Disable the documented service-side apostrophe-stripping retry:
        # morphsvc 264ad78feae7efcb23255736f7ed624f673db1e4,
        # morphsvc/lib/engines/MorpheusLocalEngine.py lines 123-132.
        parameters["noAposRetry"] = "1"
    return ENDPOINT + "?" + urllib.parse.urlencode(parameters)


def _items(value, pointer):
    if value is None:
        return []
    rows = [(v, f"{pointer}/{i}") for i, v in enumerate(value)] if isinstance(value, list) else [(value, pointer)]
    if any(not isinstance(v, dict) for v, _ in rows):
        raise ValueError("Unexpected upstream object shape")
    return rows


def _object(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("Missing or malformed upstream object")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def project(raw, form, receipt):
    """Lossless objects plus literal display fields. No missing features filled."""
    if len(raw) > MAX_RESPONSE or _sha(raw) != receipt["raw_sha256"]:
        raise ValueError("Raw response integrity failure")
    data = json.loads(raw, object_pairs_hook=_unique_object)
    annotations = _items(_object(_object(data)["RDF"])["Annotation"], "/RDF/Annotation")
    if not annotations:
        raise ValueError("Missing response target")
    candidates, entries = [], []
    query_form = transport_form(form)
    for annotation, ap in annotations:
        target = _object(_object(annotation["hasTarget"])["Description"])["about"]
        if not isinstance(target, str) or unicodedata.normalize("NFC", target) != "urn:word:" + unicodedata.normalize("NFC", query_form):
            raise ValueError("Response target mismatch")
        if "Body" not in annotation and "hasBody" not in annotation:
            # Audited QA23 negative control: complete service annotation with
            # both body fields ABSENT. Null/empty/mismatched present fields are
            # not this envelope and must not silently become "no analyses".
            expected = "urn:TuftsMorphologyService:" + unicodedata.normalize("NFC", query_form) + ":morpheusgrc"
            about = annotation["about"]
            creator = _object(_object(annotation["creator"])["Agent"])["about"]
            created = _object(annotation["created"])["$"]
            rights = _object(annotation["rights"])["$"]
            if (not isinstance(about, str) or unicodedata.normalize("NFC", about) != expected
                    or creator != "org.perseus:tools:morpheus.v1"
                    or not isinstance(created, str) or not created
                    or not isinstance(rights, str) or not rights
                    or not isinstance(annotation["title"], dict)):
                raise ValueError("Unrecognised empty-result envelope")
            continue
        bodies = _items(annotation["Body"], ap + "/Body")
        declared = _items(annotation["hasBody"], ap + "/hasBody")
        body_ids = [b["about"] for b, _ in bodies]
        reference_ids = [b["resource"] for b, _ in declared]
        if (not bodies or not declared or any(not isinstance(v, str) or not v for v in body_ids + reference_ids)
                or len(set(body_ids)) != len(body_ids) or len(set(reference_ids)) != len(reference_ids)
                or set(body_ids) != set(reference_ids)):
            raise ValueError("Missing or inconsistent alternative bodies")
        for body, bp in bodies:
            entry_rows = _items(_object(body["rest"])["entry"], bp + "/rest/entry")
            if not entry_rows:
                raise ValueError("Missing upstream entries")
            for entry, ep in entry_rows:
                dictionary = _object(entry["dict"])
                entries.append({"entry_pointer": ep, "entry": entry})
                headword = _object(dictionary["hdwd"])
                lemma = headword["$"]
                if not isinstance(lemma, str) or not lemma:
                    raise ValueError("Malformed headword")
                infl_rows = _items(entry["infl"], ep + "/infl")
                if not infl_rows:
                    raise ValueError("Missing upstream inflections")
                for inflection, ip in infl_rows:
                    part = _object(inflection["pofs"])["$"]
                    _object(inflection["term"])
                    if not isinstance(part, str) or not part:
                        raise ValueError("Unusable inflection")
                    if any(not isinstance(v["$"], str) for v in inflection.values() if isinstance(v, dict) and "$" in v):
                        raise ValueError("Malformed literal feature")
                    candidates.append({
                        "id": "machine:" + _sha((receipt["id"] + "\n" + ip).encode()),
                        "candidate_kind": "machine_analysis", "basis": "machine_analysis",
                        "receipt_id": receipt["id"], "lemma": lemma,
                        "dictionary_fields": dictionary, "inflection": inflection,
                        "features": {k: v["$"] for k, v in inflection.items()
                                     if isinstance(v, dict) and "$" in v},
                        "entry_pointer": ep, "inflection_pointer": ip,
                    })
    return {"status": "ok" if candidates else "no_analyses", "form": form,
            "machine_candidates": candidates, "machine_entries": entries,
            "receipt": receipt, "warnings": list(WARNINGS)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _fetch(url):
    """One fixed-origin request; bounded reads and deadline, no retry/redirect."""
    request = urllib.request.Request(url, headers={"User-Agent": "Project-Melos/QA23 (explicit morphology lookup)",
                                                   "Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    started = time.monotonic()
    try:
        response = opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        response = exc  # Preserve bounded error bodies, not retry them.
    with response:
        if response.geturl() != url:
            raise ValueError("Unexpected response URL")
        chunks, size = [], 0
        while True:
            if time.monotonic() - started > TIMEOUT:
                raise TimeoutError("Morphology response deadline exceeded")
            chunk = response.read1(min(16384, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError("Morphology response too large")
        return response.status, b"".join(chunks), {k: response.headers[k] for k in
                                                   ("Content-Type", "Date", "Age", "X-Cache") if k in response.headers}


def _limit(name, default, maximum):
    try:
        return max(0, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def default_cache_path():
    if os.getenv("MELOS_MACHINE_STATE"):
        return Path(os.environ["MELOS_MACHINE_STATE"])
    if os.getenv("MELOS_CLASSIFIER_STATE"):
        return Path(os.environ["MELOS_CLASSIFIER_STATE"]).with_name("machine_morphology.sqlite")
    return Path(__file__).resolve().parents[1] / "runtime" / "machine_morphology.sqlite"


class MachineMorphologyService:
    def __init__(self, cache_path=None, *, transport=None, clock=None):
        self.path = Path(cache_path) if cache_path is not None else default_cache_path()
        self.transport = transport or _fetch
        self.clock = clock or time.time
        self.max_bytes = _limit("MELOS_MACHINE_MAX_BYTES", 64 * 1024 * 1024, 256 * 1024 * 1024)
        self.global_day = _limit("MELOS_MACHINE_GLOBAL_DAILY", 200, 1000)
        self.global_minute = _limit("MELOS_MACHINE_GLOBAL_MINUTE", 10, 30)
        self.visitor_day = _limit("MELOS_MACHINE_VISITOR_DAILY", 20, 100)
        self.visitor_minute = _limit("MELOS_MACHINE_VISITOR_MINUTE", 3, 10)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, raw BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, expires REAL);
          CREATE TABLE IF NOT EXISTS inflight(key TEXT PRIMARY KEY, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS failures(key TEXT PRIMARY KEY, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(visitor TEXT NOT NULL, at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS attempts_at ON attempts(at);
          CREATE TRIGGER IF NOT EXISTS receipt_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
          CREATE TRIGGER IF NOT EXISTS receipt_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
        """)
        if "expires" not in {r[1] for r in conn.execute("PRAGMA table_info(cache)")}:
            conn.execute("ALTER TABLE cache ADD COLUMN expires REAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _result(status, form=None, warning=None):
        return {"status": status, "form": form, "machine_candidates": [], "machine_entries": [],
                "receipt": None, "warnings": list(WARNINGS) + ([warning] if warning else [])}

    def load_receipt(self, receipt_id, *, form):
        """Cache-only trusted reconstruction; no network or client candidate trust."""
        try:
            form = validate_form(form)
            if not isinstance(receipt_id, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_id):
                raise ValueError("Invalid receipt identifier")
            with self._connect() as conn:
                row = conn.execute("SELECT metadata,raw FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if row is None:
                raise ValueError("Receipt unavailable")
            metadata = json.loads(row["metadata"])
            if _sha(row["metadata"].encode()) != receipt_id:
                raise ValueError("Receipt metadata integrity failure")
            source_form = metadata.get("source_form", metadata["request_form"])
            if (source_form != form or metadata["request_form"] != transport_form(form)
                    or metadata["url"] != request_url(form) or metadata["parser_version"] != PARSER_VERSION):
                raise ValueError("Receipt request/parser mismatch")
            if form.endswith(tuple(ELISION_MARKS)):
                if (validate_form(metadata["input_form"]) != form
                        or metadata["input_transformation"] != "NFC; final U+2019 to U+1FBD for transport only"
                        or metadata["input_convention"] != ELISION_CONVENTION):
                    raise ValueError("Receipt elision provenance mismatch")
            receipt = {"id": receipt_id, **metadata}
            if _sha(row["raw"]) != metadata["raw_sha256"]:
                raise ValueError("Receipt raw integrity failure")
            if metadata["http_status"] not in (200, 201):
                result = self._result("upstream_error", form, "Morphology service returned an unsuccessful HTTP status.")
                result["receipt"] = receipt
                return result
            return project(row["raw"], form, receipt)
        except (ValueError, KeyError, TypeError, RecursionError, sqlite3.Error, OSError):
            return self._result("invalid_receipt", form, "Cached response could not be verified; no analysis was used.")

    def analyze(self, form, visitor_id, fetch=True):
        input_form = form
        try:
            form = validate_form(form)
        except ValueError as exc:
            return self._result("invalid_form", warning=str(exc))
        key = _sha((PARSER_VERSION + "\n" + form).encode())
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT receipt_id FROM cache WHERE key=? AND (expires IS NULL OR expires>?)", (key, self.clock())).fetchone()
            if row:
                return self.load_receipt(row[0], form=form)
            if not fetch:
                return self._result("cache_miss", form)
            if os.getenv("MELOS_MACHINE_ENABLED", "1").lower() in ("0", "false", "no"):
                return self._result("disabled", form)
            if not isinstance(visitor_id, str) or not re.fullmatch(r"[0-9a-f]{64}", visitor_id):
                return self._result("rate_limited", form, "A valid server-derived visitor identifier is required.")
            now = self.clock()
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM attempts WHERE at<?", (now - 86400,))
                conn.execute("DELETE FROM inflight WHERE expires<?", (now,))
                conn.execute("DELETE FROM failures WHERE expires<=?", (now,))
                conn.execute("DELETE FROM cache WHERE expires IS NOT NULL AND expires<=?", (now,))
                row = conn.execute("SELECT receipt_id FROM cache WHERE key=?", (key,)).fetchone()
                if row:
                    cached_id = row[0]
                else:
                    cached_id = None
                    if conn.execute("SELECT 1 FROM failures WHERE key IN (?,?)", (key, "upstream-rate-limit")).fetchone():
                        return self._result("upstream_error", form, "A recent request failed; no automatic retry was made. Try again later.")
                    active = conn.execute("SELECT COUNT(*) FROM inflight").fetchone()[0]
                    if active >= 2 or conn.execute("SELECT 1 FROM inflight WHERE key=?", (key,)).fetchone():
                        return self._result("busy", form, "An analysis is already in flight; no duplicate request was sent.")
                    size, receipt_count = conn.execute("SELECT COALESCE(SUM(length(raw)+length(CAST(metadata AS BLOB))),0),COUNT(*) FROM receipts").fetchone()
                    if receipt_count + active >= 10000 or size + (active + 1) * (MAX_RESPONSE + 4096) > self.max_bytes:
                        return self._result("cache_full", form, "Raw-response cache capacity reached; no request was sent.")
                    for visitor, since, limit in [(None, now-86400, self.global_day), (None, now-60, self.global_minute),
                                                   (visitor_id, now-86400, self.visitor_day), (visitor_id, now-60, self.visitor_minute)]:
                        sql, args = "SELECT COUNT(*) FROM attempts WHERE at>=?", [since]
                        if visitor is not None:
                            sql += " AND visitor=?"
                            args.append(visitor)
                        if conn.execute(sql, args).fetchone()[0] >= limit:
                            return self._result("rate_limited", form, "Morphology request allowance reached; cached analyses remain available.")
                    conn.execute("INSERT INTO attempts VALUES (?,?)", (visitor_id, now))
                    conn.execute("INSERT INTO inflight VALUES (?,?)", (key, now + 60))
            if cached_id:
                return self.load_receipt(cached_id, form=form)
            try:
                url = request_url(form)
                status, raw, headers = self.transport(url)
                if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
                    raise ValueError("Invalid or oversized response")
                metadata = {"request_form": transport_form(form), "url": url, "http_status": status,
                            "received_utc": datetime.now(timezone.utc).isoformat(), "raw_sha256": _sha(raw),
                            "parser_version": PARSER_VERSION, "engine_revision": None, "response_headers": headers}
                if form.endswith(tuple(ELISION_MARKS)):
                    metadata.update(input_form=input_form, source_form=form,
                                    input_transformation="NFC; final U+2019 to U+1FBD for transport only",
                                    input_convention=ELISION_CONVENTION)
                encoded = _json(metadata)
                if len(encoded.encode()) > 4096:
                    raise ValueError("Oversized response metadata")
                receipt_id = _sha(encoded.encode())
                with self._connect() as conn:
                    conn.execute("INSERT INTO receipts VALUES (?,?,?)", (receipt_id, encoded, raw))
                    conn.execute("INSERT INTO cache VALUES (?,?,?)", (key, receipt_id, self.clock() + FAILURE_BACKOFF))
                    if status == 429:
                        conn.execute("INSERT OR REPLACE INTO failures VALUES (?,?)", ("upstream-rate-limit", self.clock() + FAILURE_BACKOFF))
                result = self.load_receipt(receipt_id, form=form)
                if result["status"] in ("ok", "no_analyses"):
                    with self._connect() as conn:
                        conn.execute("UPDATE cache SET expires=NULL WHERE key=? AND receipt_id=?", (key, receipt_id))
                if result["status"] == "invalid_receipt":
                    result["status"] = "invalid_response"
                return result
            except (OSError, ValueError, sqlite3.Error, urllib.error.URLError, TimeoutError):
                with self._connect() as conn:
                    conn.execute("INSERT OR REPLACE INTO failures VALUES (?,?)", (key, self.clock() + FAILURE_BACKOFF))
                return self._result("upstream_error", form, "Morphology request failed; no retry or fallback was made.")
            finally:
                with self._connect() as conn:
                    conn.execute("DELETE FROM inflight WHERE key=?", (key,))
        except (sqlite3.Error, OSError):
            return self._result("upstream_error", form, "Morphology runtime cache unavailable.")


def get_service():
    return MachineMorphologyService()


def validate_receipt_projection(receipt_id, candidates, form):
    result = get_service().load_receipt(receipt_id, form=form)
    if result["status"] == "ok" and isinstance(candidates, list) and candidates == result["machine_candidates"]:
        return result
    return None
