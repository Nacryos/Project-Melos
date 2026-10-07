"""Transfer controls use archived source-response fixtures, never the network."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from backend.machine_morphology import MachineMorphologyService, PARSER_VERSION
from deploy.sync_morphology_receipts import export_bundle, import_bundle, read_bundle

FIXTURES = Path(__file__).parent / "fixtures/machine_morphology"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_bytes())


def seed(path, index):
    sample = MANIFEST["samples"][index]
    raw = (FIXTURES / sample["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample["response"]["raw_sha256"]
    service = MachineMorphologyService(path, transport=lambda url: (201, raw, {}))
    result = service.analyze(sample["word"], "a" * 64)
    assert result["status"] == "ok"
    return result


def snapshot(path):
    with sqlite3.connect(path) as connection:
        return {table: connection.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                for table in ("attempts", "inflight", "failures", "receipts", "cache")}


def test_preview_insert_preservation_and_idempotence(tmp_path):
    source, target, bundle = [tmp_path / name for name in ("source.sqlite", "target.sqlite", "bundle.json")]
    added = seed(source, 0)
    seed(target, 1)
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO failures VALUES('existing-failure',123)")
        connection.execute("INSERT INTO inflight VALUES('unrelated-inflight',123)")
    before = snapshot(target)
    assert export_bundle(source, bundle)["exported"] == 1
    assert import_bundle(target, bundle)["missing"] == 1
    assert snapshot(target) == before
    assert import_bundle(target, bundle, True)["missing"] == 1
    after = snapshot(target)
    for table in ("attempts", "inflight", "failures"):
        assert before[table] == after[table]
    for table in ("receipts", "cache"):
        assert all(row in after[table] for row in before[table])
        assert len(after[table]) == len(before[table]) + 1
    assert MachineMorphologyService(target).analyze(added["form"], "", fetch=False)["machine_candidates"] == added["machine_candidates"]
    assert import_bundle(target, bundle, True)["missing"] == 0
    assert snapshot(target) == after


@pytest.mark.parametrize("field", ["raw", "metadata", "key", "url", "parser_version", "request_form"])
def test_tampered_bundle_rejected_before_target_write(tmp_path, field):
    source, target, bundle = [tmp_path / name for name in ("source.sqlite", "target.sqlite", "bundle.json")]
    seed(source, 0)
    seed(target, 1)
    export_bundle(source, bundle)
    data = json.loads(bundle.read_bytes())
    row = data["entries"][0]
    if field == "raw":
        row["raw_base64"] = base64.b64encode(b"{}").decode()
    elif field == "key":
        row["key"] = "0" * 64
    elif field == "metadata":
        row["metadata"] += " "
    else:
        metadata = json.loads(row["metadata"])
        metadata[field] = "bad"
        row["metadata"] = json.dumps(metadata)
        row["receipt_id"] = hashlib.sha256(row["metadata"].encode()).hexdigest()
    bundle.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(target)
    with pytest.raises(ValueError):
        import_bundle(target, bundle, True)
    assert snapshot(target) == before


def test_inflight_key_and_existing_key_are_never_replaced(tmp_path):
    source, target, bundle = [tmp_path / name for name in ("source.sqlite", "target.sqlite", "bundle.json")]
    seed(source, 0)
    seed(target, 1)
    export_bundle(source, bundle)
    key = read_bundle(bundle)[0][0]
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO inflight VALUES(?,9999999999)", (key,))
    before = snapshot(target)
    assert import_bundle(target, bundle, True)["skipped"][0]["reason"] == "inflight_key"
    assert snapshot(target) == before


@pytest.mark.parametrize("index", [0, 1, 2])
def test_elision_transfer_preserves_original_source_and_transport_binding(tmp_path, index):
    source, target, bundle = [tmp_path / name for name in ("source.sqlite", "target.sqlite", "bundle.json")]
    sample = json.loads((FIXTURES / "elision/manifest.json").read_bytes())["samples"][index]
    raw = (FIXTURES / "elision" / sample["raw_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample["receipt"]["raw_sha256"]
    service = MachineMorphologyService(source, transport=lambda _: (201, raw, {}))
    original = service.analyze(sample["text"], "a" * 64)
    assert original["status"] == "ok"
    seed(target, 0)  # Keep a legacy intact receipt alongside the new one.
    before = snapshot(target)
    assert export_bundle(source, bundle)["exported"] == 1
    preview = import_bundle(target, bundle)
    assert preview["entries"] == [{"form": sample["text"], "candidates": sample["candidate_count"], "status": "ok"}]
    assert snapshot(target) == before
    assert import_bundle(target, bundle, True)["missing"] == 1
    restored = MachineMorphologyService(target).analyze(sample["text"], "", fetch=False)
    assert restored == original
    after = snapshot(target)
    assert all(row in after["receipts"] for row in before["receipts"])
    for table in ("attempts", "inflight", "failures"):
        assert after[table] == before[table]
    assert import_bundle(target, bundle, True)["missing"] == 0
    assert snapshot(target) == after


def test_elision_bundle_cannot_substitute_transport_as_source(tmp_path):
    source, target, bundle = [tmp_path / name for name in ("source.sqlite", "target.sqlite", "bundle.json")]
    sample = json.loads((FIXTURES / "elision/manifest.json").read_bytes())["samples"][0]
    raw = (FIXTURES / "elision" / sample["raw_file"]).read_bytes()
    MachineMorphologyService(source, transport=lambda _: (201, raw, {})).analyze(sample["text"], "a" * 64)
    seed(target, 0)
    export_bundle(source, bundle)
    data = json.loads(bundle.read_bytes())
    row = data["entries"][0]
    metadata = json.loads(row["metadata"])
    metadata["source_form"] = metadata["request_form"]  # Synthetic provenance corruption.
    row["metadata"] = json.dumps(metadata)
    row["receipt_id"] = hashlib.sha256(row["metadata"].encode()).hexdigest()
    row["key"] = hashlib.sha256((PARSER_VERSION + "\n" + metadata["source_form"]).encode()).hexdigest()
    bundle.write_text(json.dumps(data), encoding="utf8")
    before = snapshot(target)
    with pytest.raises(ValueError):
        import_bundle(target, bundle, True)
    assert snapshot(target) == before
