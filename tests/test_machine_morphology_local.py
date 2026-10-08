"""Local Morpheus transport: same receipt format, own provenance, no courtesy quotas."""
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.parse

import pytest

from backend import machine_morphology as mm
FIXTURES = Path(__file__).parent / "fixtures/machine_morphology"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_bytes())


def fixture(index=0):
    row = MANIFEST["samples"][index]
    return row, (FIXTURES / row["file"]).read_bytes()

ENDPOINT = "http://melos-morpheus:8080/api/v1/analysis/word"
HEALTH = json.dumps({"morpheus_commit": "2f1a30d65ed7ae9c6120dbf64d730b863be412e4",
                     "morphsvc_commit": "264ad78feae7efcb23255736f7ed624f673db1e4"}).encode()
REVISION = ("alpheios-project/morpheus@2f1a30d65ed7ae9c6120dbf64d730b863be412e4 (dist/stemlib); "
            "alpheios-project/morphsvc@264ad78feae7efcb23255736f7ed624f673db1e4")


def local_service(tmp_path, raw, calls=None, status=201, health=HEALTH):
    def transport(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("/health"):
            return 200, health, {}
        return status, raw, {"Content-Type": "application/json"}
    remote = lambda url: pytest.fail("remote Alpheios must not be called when the local engine is configured")
    return mm.MachineMorphologyService(tmp_path / "cache.sqlite", transport=remote, local_transport=transport)


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("MELOS_MORPHEUS_LOCAL", ENDPOINT)
    # Courtesy caps at zero: a local request must not consult them.
    for name in ("MELOS_MACHINE_GLOBAL_DAILY", "MELOS_MACHINE_GLOBAL_MINUTE",
                 "MELOS_MACHINE_VISITOR_DAILY", "MELOS_MACHINE_VISITOR_MINUTE"):
        monkeypatch.setenv(name, "0")


def test_local_receipt_projection_matches_remote_and_is_labelled_local(tmp_path, local_env):
    row, raw = fixture()
    calls = []
    service = local_service(tmp_path, raw, calls)
    result = service.analyze(row["word"], visitor_id=None, fetch=False)
    assert result["status"] == "ok"
    receipt = result["receipt"]
    assert receipt["parser_version"] == mm.LOCAL_PARSER_VERSION
    assert receipt["engine_revision"] == REVISION
    assert receipt["endpoint"] == ENDPOINT and receipt["url"].startswith(ENDPOINT + "?")
    assert "Alpheios service" in result["warnings"][1] and "Local Morpheus build" in result["warnings"][1]
    # Same candidates as the remote projection of the same raw body.
    expected = mm.project(raw, row["word"], {"id": "0" * 64, "raw_sha256": hashlib.sha256(raw).hexdigest()})
    assert expected["machine_candidates"]
    assert [(c["lemma"], c["features"]) for c in result["machine_candidates"]] == \
           [(c["lemma"], c["features"]) for c in expected["machine_candidates"]]
    # Cached: no second engine call; reloadable by receipt id.
    service.analyze(row["word"], visitor_id=None)
    assert len([c for c in calls if not c.endswith("/health")]) == 1
    assert service.load_receipt(receipt["id"], form=row["word"])["machine_candidates"] == result["machine_candidates"]


def test_local_engine_ignores_courtesy_caps(tmp_path, local_env):
    row, raw = fixture()
    service = local_service(tmp_path, raw)
    for word in [row["word"]] * 3:
        assert service.analyze(word, visitor_id=None)["status"] == "ok"
    with sqlite3.connect(tmp_path / "cache.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_cached_alpheios_receipt_keeps_precedence(tmp_path, monkeypatch):
    row, raw = fixture()
    remote = mm.MachineMorphologyService(tmp_path / "cache.sqlite", transport=lambda _: (201, raw, {}))
    first = remote.analyze(row["word"], "a" * 64)
    monkeypatch.setenv("MELOS_MORPHEUS_LOCAL", ENDPOINT)
    service = local_service(tmp_path, b"never used")
    again = service.analyze(row["word"], visitor_id=None)
    assert again["receipt"]["parser_version"] == mm.PARSER_VERSION and again["receipt"]["id"] == first["receipt"]["id"]


def test_negative_envelope_is_cached_no_analyses(tmp_path, local_env):
    sample = MANIFEST["negative_control"]
    raw = (FIXTURES / sample["file"]).read_bytes()
    service = local_service(tmp_path, raw)
    result = service.analyze(sample["word"], visitor_id=None)
    assert result["status"] == "no_analyses" and result["receipt"]["parser_version"] == mm.LOCAL_PARSER_VERSION


@pytest.mark.parametrize("health", [b"{}", b"not json",
                                    json.dumps({"morpheus_commit": "main", "morphsvc_commit": "x"}).encode()])
def test_unreported_build_refuses_to_store(tmp_path, local_env, health):
    row, raw = fixture()
    result = local_service(tmp_path, raw, health=health).analyze(row["word"], visitor_id=None)
    assert result["status"] == "upstream_error" and not result["machine_candidates"]


def test_error_status_and_backoff(tmp_path, local_env):
    row, raw = fixture()
    calls = []
    service = local_service(tmp_path, raw, calls, status=500)
    assert service.analyze(row["word"], visitor_id=None)["status"] == "upstream_error"
    assert service.analyze(row["word"], visitor_id=None)["status"] == "upstream_error"
    assert len([c for c in calls if not c.endswith("/health")]) == 1
    with sqlite3.connect(tmp_path / "cache.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_forged_local_provenance_rejected(tmp_path, local_env):
    row, raw = fixture()
    service = local_service(tmp_path, raw)
    receipt = service.analyze(row["word"], visitor_id=None)["receipt"]
    with sqlite3.connect(tmp_path / "cache.sqlite") as con:
        metadata = json.loads(con.execute("SELECT metadata FROM receipts WHERE id=?", (receipt["id"],)).fetchone()[0])
    for field, value in [("engine_revision", "Alpheios"), ("endpoint", "file:///etc"),
                         ("url", mm.request_url(row["word"]))]:
        forged = dict(metadata, **{field: value})
        encoded = mm._json(forged)
        forged_id = hashlib.sha256(encoded.encode()).hexdigest()
        with sqlite3.connect(tmp_path / "cache.sqlite") as con:
            con.execute("INSERT INTO receipts VALUES (?,?,?)", (forged_id, encoded, raw))
        assert service.load_receipt(forged_id, form=row["word"])["status"] == "invalid_receipt"


@pytest.mark.parametrize("value", ["ftp://host/x", "melos-morpheus:8080", "http://h/api?word=x"])
def test_bad_local_configuration_disables_without_remote_call(tmp_path, monkeypatch, value):
    row, raw = fixture()
    monkeypatch.setenv("MELOS_MORPHEUS_LOCAL", value)
    assert local_service(tmp_path, raw).analyze(row["word"], visitor_id=None)["status"] == "disabled"


def test_no_local_configuration_keeps_remote_cache_miss(tmp_path, monkeypatch):
    monkeypatch.delenv("MELOS_MORPHEUS_LOCAL", raising=False)
    row, raw = fixture()
    service = mm.MachineMorphologyService(tmp_path / "cache.sqlite", transport=lambda _: pytest.fail("fetched"))
    assert service.analyze(row["word"], "a" * 64, fetch=False)["status"] == "cache_miss"
