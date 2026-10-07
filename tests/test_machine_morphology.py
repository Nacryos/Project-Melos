"""Audited source-response replay plus explicitly synthetic failure schemas."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import unicodedata
import urllib.parse

import pytest

from backend import machine_morphology as mm

FIXTURES = Path(__file__).parent / "fixtures/machine_morphology"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_bytes())
ELISION_FIXTURES = FIXTURES / "elision"
ELISION_MANIFEST = json.loads((ELISION_FIXTURES / "manifest.json").read_bytes())
VISITOR = "a" * 64


def fixture(index=0):
    row = MANIFEST["samples"][index]
    raw = (FIXTURES / row["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["response"]["raw_sha256"]
    return row, raw


def replay(tmp_path, index=0, **kwargs):
    row, raw = fixture(index)
    calls = []
    def transport(url):
        calls.append(url)
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["word"] == [unicodedata.normalize("NFC", row["word"])]
        return 201, raw, {"Content-Type": "application/json"}
    return mm.MachineMorphologyService(tmp_path / "cache.sqlite", transport=transport, **kwargs), row, calls


@pytest.mark.parametrize("index,count", list(enumerate([5, 2, 2, 1, 5, 1, 2, 1])))
def test_audited_raw_fixtures_lossless_cached_reprojection(tmp_path, index, count):
    service, sample, calls = replay(tmp_path, index)
    result = service.analyze(sample["word"], VISITOR)
    assert result["status"] == "ok"
    assert len(result["machine_candidates"]) == count
    assert result["receipt"]["engine_revision"] is None
    assert result["receipt"]["raw_sha256"] == sample["response"]["raw_sha256"]
    source = json.loads((FIXTURES / sample["file"]).read_bytes())
    def resolve(pointer):
        value = source
        for key in pointer.split("/")[1:]:
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    for entry in result["machine_entries"]:
        assert entry["entry"] == resolve(entry["entry_pointer"])
    for candidate in result["machine_candidates"]:
        assert candidate["inflection"] == resolve(candidate["inflection_pointer"])
        assert candidate["dictionary_fields"] == resolve(candidate["entry_pointer"])["dict"]
        assert candidate["basis"] == candidate["candidate_kind"] == "machine_analysis"
        assert candidate["features"] == {k: v["$"] for k, v in candidate["inflection"].items() if isinstance(v, dict) and "$" in v}
        assert "gloss" not in candidate and "attestations" not in candidate
    assert result == service.load_receipt(result["receipt"]["id"], form=sample["word"])
    assert result == service.analyze(sample["word"], VISITOR, fetch=False)
    assert len(calls) == 1


@pytest.mark.parametrize("word", ["word", "ἄνθρωπος λόγος", "[λόγος]", "λόγος†", "λόγ̣ος", "λόγος…", "<λόγος>", "λ\nόγος", "", "α"*81, "\u0301α",
                                 "᾽", "’", "’δ", "δ’δ", "δ’’", "δ᾽’", "δ’\u0301", "δ'", "δʼ", "δ‘"])
def test_reject_unsafe_or_nonword_input_without_network(tmp_path, word):
    service = mm.MachineMorphologyService(tmp_path / "x.sqlite", transport=lambda _: pytest.fail("Network forbidden"))
    assert service.analyze(word, VISITOR)["status"] == "invalid_form"


def test_nfc_preserves_accents_and_case():
    assert mm.validate_form("Μοισάων") == "Μοισάων"
    assert mm.validate_form(unicodedata.normalize("NFD", "θέοισιν")) == unicodedata.normalize("NFC", "θέοισιν")
    assert mm.validate_form("ἴσος") != mm.validate_form("ἰσός")


@pytest.mark.parametrize("mark", ["\u2019", "\u1fbd"])
def test_elision_input_and_documented_transport_are_separate(mark):
    # Synthetic spelling for protocol behavior, not an authored analysis.
    word = "Δ" + mark
    assert mm.validate_form(word) == word
    assert mm.transport_form(word) == "Δ\u1fbd"
    parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(mm.request_url(word)).query)
    assert parameters["word"] == ["Δ\u1fbd"]
    assert parameters["noAposRetry"] == ["1"]
    assert "noAposRetry" not in urllib.parse.parse_qs(urllib.parse.urlsplit(mm.request_url("λόγος")).query)


def test_elision_keeps_nfc_accents_and_letter_sequence():
    word = "ἔρχεσθ’"
    assert mm.validate_form(unicodedata.normalize("NFD", word)) == word
    assert mm.transport_form(word)[:-1] == word[:-1]


@pytest.mark.parametrize("target", ["δ’", "δ", "δ'", "δʼ"])
def test_elision_does_not_relax_response_target_binding(tmp_path, target):
    # Synthetic alteration of an audited negative envelope tests target guards;
    # it is not a lexical fixture or an assertion that delta is an unknown word.
    sample = MANIFEST["negative_control"]
    data = json.loads((FIXTURES / sample["file"]).read_bytes())
    annotation = data["RDF"]["Annotation"]
    annotation["hasTarget"]["Description"]["about"] = "urn:word:" + target
    annotation["about"] = "urn:TuftsMorphologyService:δ᾽:morpheusgrc"
    raw = json.dumps(data).encode()
    service = mm.MachineMorphologyService(tmp_path / "wrong-elision.sqlite", transport=lambda _: (201, raw, {}))
    assert service.analyze("δ’", VISITOR)["status"] == "invalid_response"


@pytest.mark.parametrize("index,count", [(0, 4), (1, 1), (2, 1)])
def test_audited_elision_raw_replay_keeps_source_and_request_spelling(tmp_path, index, count):
    sample = ELISION_MANIFEST["samples"][index]
    raw = (ELISION_FIXTURES / sample["raw_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample["receipt"]["raw_sha256"]
    calls = []
    def transport(url):
        calls.append(url)
        assert url == sample["receipt"]["url"]
        return sample["receipt"]["http_status"], raw, sample["receipt"]["response_headers"]
    service = mm.MachineMorphologyService(tmp_path / "elision.sqlite", transport=transport)
    result = service.analyze(sample["text"], VISITOR)
    assert result["status"] == "ok" and len(result["machine_candidates"]) == count
    assert result["form"] == sample["text"]
    assert result["receipt"]["input_form"] == sample["text"]
    assert result["receipt"]["source_form"] == sample["text"]
    assert result["receipt"]["request_form"] == sample["receipt"]["request_form"]
    assert result["receipt"]["input_convention"] == mm.ELISION_CONVENTION
    data = json.loads(raw)
    for candidate in result["machine_candidates"]:
        value = data
        for key in candidate["inflection_pointer"].split("/")[1:]:
            value = value[int(key)] if isinstance(value, list) else value[key]
        assert candidate["inflection"] == value
        assert candidate["features"] == {k: v["$"] for k, v in value.items() if isinstance(v, dict) and "$" in v}
        assert candidate["basis"] == "machine_analysis"
    rid = result["receipt"]["id"]
    assert service.analyze(sample["text"], VISITOR, fetch=False) == result
    assert service.load_receipt(rid, form=sample["text"]) == result
    different_mark = sample["text"][:-1] + ("᾽" if sample["text"].endswith("’") else "’")
    assert service.load_receipt(rid, form=different_mark)["status"] == "invalid_receipt"
    assert len(calls) == 1


def test_elision_receipt_retains_original_decomposed_input(tmp_path):
    sample = ELISION_MANIFEST["samples"][0]
    raw = (ELISION_FIXTURES / sample["raw_file"]).read_bytes()
    word = unicodedata.normalize("NFD", sample["text"])
    service = mm.MachineMorphologyService(tmp_path / "nfd-elision.sqlite", transport=lambda _: (201, raw, {}))
    result = service.analyze(word, VISITOR)
    assert result["status"] == "ok"
    assert result["receipt"]["input_form"] == word
    assert result["receipt"]["source_form"] == sample["text"]
    assert result["receipt"]["request_form"] == sample["receipt"]["request_form"]


@pytest.mark.parametrize("field", ["source_form", "input_form", "input_transformation", "input_convention", "request_form", "url"])
def test_elision_receipt_forged_provenance_rejected(tmp_path, field):
    sample = ELISION_MANIFEST["samples"][0]
    raw = (ELISION_FIXTURES / sample["raw_file"]).read_bytes()
    metadata = {k: v for k, v in sample["receipt"].items() if k != "id"}
    metadata[field] = "SYNTHETIC invalid binding"
    encoded = mm._json(metadata)
    rid = hashlib.sha256(encoded.encode()).hexdigest()
    service = mm.MachineMorphologyService(tmp_path / "forged-elision.sqlite", transport=lambda _: pytest.fail("No fetch"))
    with service._connect() as conn:
        conn.execute("INSERT INTO receipts VALUES (?,?,?)", (rid, encoded, raw))
    assert service.load_receipt(rid, form=sample["text"])["status"] == "invalid_receipt"


def test_receipt_wrong_form_and_tamper_fail_closed(tmp_path):
    service, row, _ = replay(tmp_path)
    result = service.analyze(row["word"], VISITOR)
    rid = result["receipt"]["id"]
    assert service.load_receipt(rid, form="λόγος")["status"] == "invalid_receipt"
    assert service.load_receipt("../private", form=row["word"])["status"] == "invalid_receipt"
    with sqlite3.connect(service.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE receipts SET raw=? WHERE id=?", (b"{}", rid))
        conn.execute("DROP TRIGGER receipt_no_update")  # Synthetic corruption of isolated test cache.
        conn.execute("UPDATE receipts SET raw=? WHERE id=?", (b"{}", rid))
    assert service.load_receipt(rid, form=row["word"])["status"] == "invalid_receipt"


def test_cached_only_validator_rejects_forged_candidates(tmp_path, monkeypatch):
    service, row, calls = replay(tmp_path)
    result = service.analyze(row["word"], VISITOR)
    monkeypatch.setattr(mm, "get_service", lambda: service)
    rid = result["receipt"]["id"]
    assert mm.validate_receipt_projection(rid, result["machine_candidates"], row["word"]) == result
    assert mm.validate_receipt_projection(rid, result["machine_candidates"][:-1], row["word"]) is None
    altered = json.loads(json.dumps(result["machine_candidates"]))
    altered[0]["features"]["case"] = "SYNTHETIC FALSE VALUE"
    assert mm.validate_receipt_projection(rid, altered, row["word"]) is None
    assert len(calls) == 1


def test_cache_miss_disable_capacity_and_visitor_bounds(tmp_path, monkeypatch):
    service, row, calls = replay(tmp_path)
    assert service.analyze(row["word"], VISITOR, fetch=False)["status"] == "cache_miss"
    monkeypatch.setenv("MELOS_MACHINE_ENABLED", "0")
    assert service.analyze(row["word"], VISITOR)["status"] == "disabled"
    monkeypatch.setenv("MELOS_MACHINE_ENABLED", "1")
    assert service.analyze(row["word"], "untrusted-ip")["status"] == "rate_limited"
    service.max_bytes = 0
    assert service.analyze(row["word"], VISITOR)["status"] == "cache_full"
    assert calls == []


def test_persistent_quotas_and_failed_attempt_counting(tmp_path):
    def unavailable(url):
        raise TimeoutError("SYNTHETIC private transport error")
    service = mm.MachineMorphologyService(tmp_path / "quota.sqlite", transport=unavailable, clock=lambda: 100000)
    service.visitor_minute = 1
    first = service.analyze("λόγος", VISITOR)
    assert first["status"] == "upstream_error"
    assert "private" not in json.dumps(first)
    assert service.analyze("θεός", VISITOR)["status"] == "rate_limited"
    other = mm.MachineMorphologyService(service.path, transport=unavailable, clock=lambda: 100000)
    other.global_minute = 1
    assert other.analyze("θεός", "b"*64)["status"] == "rate_limited"


def test_cross_instance_singleflight(tmp_path):
    row, raw = fixture()
    entered, release = threading.Event(), threading.Event()
    def slow(url):
        entered.set()
        assert release.wait(5)
        return 201, raw, {}
    service = mm.MachineMorphologyService(tmp_path / "flight.sqlite", transport=slow)
    with ThreadPoolExecutor(2) as pool:
        pending = pool.submit(service.analyze, row["word"], VISITOR)
        assert entered.wait(5)
        other = mm.MachineMorphologyService(service.path, transport=lambda _: pytest.fail("Duplicate fetch"))
        assert other.analyze(row["word"], "b"*64)["status"] == "busy"
        release.set()
        assert pending.result()["status"] == "ok"


@pytest.mark.parametrize("status,raw,expected", [(503,b"unavailable","upstream_error"), (201,b"{}","invalid_response"),
                                                    (201,b"x"*(mm.MAX_RESPONSE+1),"upstream_error")], ids=["http-error","malformed","oversized"])
def test_bad_responses_never_produce_candidates(tmp_path, status, raw, expected):
    service = mm.MachineMorphologyService(tmp_path / "bad.sqlite", transport=lambda _: (status,raw,{}))
    result = service.analyze("λόγος", VISITOR)
    assert result["status"] == expected and result["machine_candidates"] == []


def test_synthetic_empty_body_not_successful_parse(tmp_path):
    # Synthetic schema solely for absence handling, not scholarly data.
    raw = json.dumps({"RDF":{"Annotation":{"hasTarget":{"Description":{"about":"urn:word:λόγος"}}}}}).encode()
    service = mm.MachineMorphologyService(tmp_path / "empty.sqlite", transport=lambda _: (201,raw,{}))
    result = service.analyze("λόγος", VISITOR)
    # No legitimate empty-result envelope has yet been source-verified. Fail
    # closed instead of mistaking a truncated body for an unknown word.
    assert result["status"] == "invalid_response" and result["machine_candidates"] == []


def test_audited_negative_envelope_is_no_analyses(tmp_path):
    sample = MANIFEST["negative_control"]
    raw = (FIXTURES / sample["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample["raw_sha256"]
    service = mm.MachineMorphologyService(tmp_path / "negative.sqlite", transport=lambda _: (201, raw, {}))
    result = service.analyze(sample["word"], VISITOR)
    assert result["status"] == "no_analyses" and not result["machine_candidates"]
    assert service.load_receipt(result["receipt"]["id"], form=sample["word"]) == result


@pytest.mark.parametrize("field", ["about", "creator", "created", "rights", "title"])
def test_incomplete_negative_envelope_not_silent_no_analysis(tmp_path, field):
    sample = MANIFEST["negative_control"]
    data = json.loads((FIXTURES / sample["file"]).read_bytes())
    del data["RDF"]["Annotation"][field]  # Explicitly synthetic corruption.
    raw = json.dumps(data).encode()
    service = mm.MachineMorphologyService(tmp_path / "negative-bad.sqlite", transport=lambda _: (201, raw, {}))
    assert service.analyze(sample["word"], VISITOR)["status"] == "invalid_response"


@pytest.mark.parametrize("mutation", ["missing-body", "rest-list", "missing-entry", "missing-infl", "empty-infl", "null-infl", "empty-one-infl", "missing-declared-body", "duplicate-body", "wrong-target"])
def test_synthetic_corrupted_shapes_fail_closed_without_partial_alternatives(tmp_path, mutation):
    sample, raw = fixture()
    data = json.loads(raw)
    annotation = data["RDF"]["Annotation"]
    body = annotation["Body"]
    entry = body["rest"]["entry"]
    if mutation == "missing-body": del annotation["Body"]
    elif mutation == "rest-list": body["rest"] = []
    elif mutation == "missing-entry": del body["rest"]["entry"]
    elif mutation == "missing-infl": del entry["infl"]
    elif mutation == "empty-infl": entry["infl"] = []
    elif mutation == "null-infl": entry["infl"] = None
    elif mutation == "empty-one-infl": entry["infl"].append({})
    elif mutation == "missing-declared-body": annotation["hasBody"] = [annotation["hasBody"], {"resource":"urn:synthetic:missing"}]
    elif mutation == "duplicate-body": annotation["Body"] = [body, body]
    elif mutation == "wrong-target": annotation["hasTarget"]["Description"]["about"] = "urn:word:λόγος"
    changed = json.dumps(data).encode()
    service = mm.MachineMorphologyService(tmp_path / "malformed.sqlite", transport=lambda _: (201, changed, {}))
    result = service.analyze(sample["word"], VISITOR)
    assert result["status"] == "invalid_response" and not result["machine_candidates"]


def test_runtime_path_env_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("MELOS_MACHINE_STATE", raising=False)
    monkeypatch.setenv("MELOS_CLASSIFIER_STATE", str(tmp_path / "classifier.sqlite"))
    assert mm.get_service().path == tmp_path / "machine_morphology.sqlite"
    monkeypatch.setenv("MELOS_MACHINE_STATE", str(tmp_path / "explicit.sqlite"))
    assert mm.get_service().path == tmp_path / "explicit.sqlite"


def test_failure_backoff_then_explicit_recovery_preserves_old_receipt(tmp_path):
    sample, raw = fixture()
    now, calls = [100000], []
    def transport(url):
        calls.append(url)
        return (503, b"synthetic unavailable", {}) if len(calls) == 1 else (201, raw, {})
    service = mm.MachineMorphologyService(tmp_path / "recover.sqlite", transport=transport, clock=lambda: now[0])
    first = service.analyze(sample["word"], VISITOR)
    assert first["status"] == "upstream_error"
    assert service.analyze(sample["word"], VISITOR) == first
    assert len(calls) == 1
    now[0] += mm.FAILURE_BACKOFF + 1
    assert service.analyze(sample["word"], VISITOR, fetch=False)["status"] == "cache_miss"
    assert len(calls) == 1
    second = service.analyze(sample["word"], VISITOR)
    assert second["status"] == "ok" and len(calls) == 2
    assert service.load_receipt(first["receipt"]["id"], form=sample["word"]) == first
    with sqlite3.connect(service.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 2


def test_transport_failure_backoff_and_upstream_rate_limit(tmp_path):
    calls = []
    def unavailable(url):
        calls.append(url)
        raise TimeoutError("synthetic timeout")
    service = mm.MachineMorphologyService(tmp_path / "timeout.sqlite", transport=unavailable)
    assert service.analyze("λόγος", VISITOR)["status"] == "upstream_error"
    assert service.analyze("λόγος", VISITOR)["status"] == "upstream_error"
    assert len(calls) == 1
    rate_calls = []
    def limited(url):
        rate_calls.append(url)
        return 429, b"synthetic rate limit", {}
    rate = mm.MachineMorphologyService(tmp_path / "rate.sqlite", transport=limited)
    assert rate.analyze("λόγος", VISITOR)["status"] == "upstream_error"
    assert rate.analyze("θεός", VISITOR)["status"] == "upstream_error"
    assert len(rate_calls) == 1
