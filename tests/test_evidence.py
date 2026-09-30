"""Synthetic fixtures test evidence plumbing, never historical content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.evidence import EvidenceIndex
from scripts.build_evidence import build


def _claim(claim_id: str, subject: dict, predicate: str, obj: dict,
           status: str = "source_claim") -> dict:
    return {
        "id": claim_id,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "evidence": [{
            "record_id": "fixture:record",
            "source_url": "https://example.org/synthetic-fixture",
            "raw_path": "data/raw/synthetic-fixture.txt",
            "raw_sha256": "a" * 64,
            "quote": "SYNTHETIC TEST FIXTURE",
        }],
        "assertion_type": "extracted_annotation",
        "status": status,
        "method": "synthetic-test",
        "source_family": "synthetic-fixture",
        "metadata": {"fixture": True},
    }


def _stage(root: Path, claims: list[dict], digest_override: str | None = None) -> Path:
    claims_dir = root / "data/claims"
    reports_dir = root / "data/reports"
    claims_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    path = claims_dir / "synthetic.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in claims), encoding="utf-8")
    digest = digest_override or hashlib.sha256(path.read_bytes()).hexdigest()
    (reports_dir / "p2-claim-acceptance.json").write_text(json.dumps({
        "files": {"synthetic.jsonl": {
            "verdict": "PASS", "sha256": digest, "records": len(claims),
        }},
    }), encoding="utf-8")
    return path


def test_lookup_preserves_scope_alternatives_and_provenance(tmp_path: Path) -> None:
    _stage(tmp_path, [
        _claim("fixture:general", {"type": "form", "form": "λόγος"}, "lemma",
               {"form": "λόγος", "alternatives": ["A", "B"]}),
        _claim("fixture:linked", {"type": "token", "form": "λόγος", "passage_id": "fixture:passage", "start": 2, "end": 7},
               "morphology", {"raw_label": "fixture tag", "features": {"case": "fixture-case"}}),
        _claim("fixture:review", {"type": "token", "form": "λόγος", "passage_id": "fixture:passage"},
               "morphology", {"raw_label": "other fixture tag"}, status="needs_review"),
    ])
    output = tmp_path / "data/evidence.sqlite"
    report = build(tmp_path, output)
    assert report["claims"] == 3
    index = EvidenceIndex(output)
    found = index.lookup("λόγος", passage_id="fixture:passage")
    assert [row["id"] for row in found["claims"]] == ["fixture:linked", "fixture:review", "fixture:general"]
    assert [row["strength"] for row in found["claims"]] == [
        "explicit_passage_span", "explicit_passage_link", "general_form_claim",
    ]
    assert found["claims"][2]["object"]["alternatives"] == ["A", "B"]
    assert found["claims"][0]["evidence"][0]["record_id"] == "fixture:record"
    assert index.lookup("λόγος")["total"] == 1
    assert index.get_passage_claims("fixture:passage")["total"] == 2
    assert index.related_claims("fixture:linked")["total"] == 2
    candidates = index.candidate_analyses("λόγος", passage_id="fixture:passage")
    assert candidates["candidates"][0]["features"] == {"case": "fixture-case"}
    assert index.provenance()["files"][0]["name"] == "synthetic.jsonl"


def test_listed_form_is_not_passage_attestation(tmp_path: Path) -> None:
    _stage(tmp_path, [
        _claim("fixture:entry", {"type": "entry", "id": "fixture:entry", "form": "λύω"},
               "morphology", {"lemma": "λύω", "forms": [
                   {"form": "λύεις", "tags": ["synthetic tag"], "table": "fixture table"},
                   {"form": "λύει", "tags": ["other synthetic tag"]},
                   {"form": "aorist", "tags": ["synthetic table heading"]},
               ]}),
        _claim("fixture:gloss", {"type": "form", "form": "λύεις"},
               "sense_gloss", {"text": "synthetic gloss"}),
    ])
    output = tmp_path / "data/evidence.sqlite"
    report = build(tmp_path, output)
    assert report["listed_form_edges"] == 2
    index = EvidenceIndex(output)
    found = index.lookup("λύεις", passage_id="fixture:passage")
    assert [claim["id"] for claim in found["claims"]] == ["fixture:entry", "fixture:gloss"]
    hit = found["claims"][0]
    assert hit["strength"] == "listed_entry_form"
    assert hit["matched_object_forms"] == [
        {"form": "λύεις", "tags": ["synthetic tag"], "table": "fixture table"},
    ]
    assert hit["object_omitted_fields"] == ["forms"]
    assert hit["object"]["listed_form_count"] == 3
    assert len(index.get_claim("fixture:entry")["object"]["forms"]) == 3
    assert len(index.get_claim("fixture:entry#form:0")["object"]["forms"]) == 3
    candidate = index.candidate_analyses("λύεις")["candidates"][0]
    assert candidate["id"] == "fixture:entry#form:0"
    assert candidate["lemma"] == "λύω"
    assert candidate["analysis"] == ["synthetic tag"]
    assert index.forms_for_lemma("λύω") == ["λύει", "λύεις"]
    assert index.lookup("aorist")["total"] == 0
    assert index.get_passage_claims("fixture:passage")["total"] == 0


def test_equivalent_form_candidate_keeps_source_relation(tmp_path: Path) -> None:
    _stage(tmp_path, [_claim(
        "fixture:equivalent", {"type": "form", "form": "α"},
        "equivalent_form", {"form": "β", "relation_raw": "fixture relation"},
    )])
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    candidate = EvidenceIndex(output).candidate_analyses("α")["candidates"][0]
    assert candidate["id"] == "fixture:equivalent"
    assert candidate["equivalent_form"] == "β"
    assert candidate["relation_raw"] == "fixture relation"


def test_form_of_candidate_uses_only_explicit_unique_target(tmp_path: Path) -> None:
    _stage(tmp_path, [
        _claim("fixture:form-of", {"type": "form", "form": "λύεις"}, "lemma", {
            "relation": "form_of", "targets": [{"word": "λύω", "extra": "fixture"}],
            "source_tags": ["synthetic-person-tag"], "source_raw_tags": ["raw fixture"],
        }),
        _claim("fixture:ambiguous", {"type": "form", "form": "λύεις"}, "lemma", {
            "relation": "form_of", "targets": [{"word": "λύω"}, {"word": "ἄλλος"}],
        }),
    ])
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    candidates = EvidenceIndex(output).candidate_analyses("λύεις")["candidates"]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    assert by_id["fixture:form-of"]["lemma"] == "λύω"
    assert by_id["fixture:form-of"]["analysis"] == ["synthetic-person-tag"]
    assert by_id["fixture:form-of"]["source_raw_tags"] == ["raw fixture"]
    assert by_id["fixture:ambiguous"]["lemma"] is None
    assert len(by_id["fixture:ambiguous"]["lemma_targets"]) == 2


def test_hash_mismatch_cannot_replace_existing_db(tmp_path: Path) -> None:
    rows = [_claim("fixture:one", {"type": "form", "form": "α"}, "lemma", {"form": "α"})]
    _stage(tmp_path, rows)
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    original = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = tmp_path / "data/reports/p2-claim-acceptance.json"
    manifest.write_text(json.dumps({"files": {"synthetic.jsonl": {
        "verdict": "PASS", "sha256": "0" * 64, "records": 1,
    }}}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build(tmp_path, output)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == original


def test_unaccepted_file_is_excluded(tmp_path: Path) -> None:
    _stage(tmp_path, [_claim("fixture:one", {"type": "form", "form": "α"}, "lemma", {"form": "α"})])
    (tmp_path / "data/claims/pending.jsonl").write_text(json.dumps(
        _claim("fixture:pending", {"type": "form", "form": "β"}, "lemma", {"form": "β"})
    ) + "\n", encoding="utf-8")
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    assert EvidenceIndex(output).lookup("β")["total"] == 0


def test_known_metadata_entry_is_verified_but_not_ingested(tmp_path: Path) -> None:
    _stage(tmp_path, [_claim("fixture:one", {"type": "form", "form": "α"}, "lemma", {"form": "α"})])
    metadata_dir = tmp_path / "data/metadata"
    metadata_dir.mkdir()
    metadata_path = metadata_dir / "p2-author-profiles.json"
    metadata_path.write_text('{"fixture":true}', encoding="utf-8")
    manifest_path = tmp_path / "data/reports/p2-claim-acceptance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][metadata_path.name] = {
        "kind": "metadata", "verdict": "PASS",
        "sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        "records": 1,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "data/evidence.sqlite"
    report = build(tmp_path, output)
    assert report["claims"] == 1
    assert len(report["files"]) == 1
    metadata_path.write_text('{"fixture":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build(tmp_path, output)
