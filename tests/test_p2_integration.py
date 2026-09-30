"""Phase 2 integration contracts using synthetic, test-only evidence.

These fixtures are never historical claims and never enter the project corpus.
Production coverage is checked separately against the independent manifests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from backend import server
from backend.classifier import classify_context
from backend.evidence import EvidenceIndex
from scripts import build_corpus
from scripts.build_evidence import build as build_evidence
from scripts.merge_p2_acceptance import merge as merge_text_acceptance


def _claim(identifier: str, subject: dict, *, status: str = "source_claim",
           assertion_type: str = "quoted_source") -> dict:
    return {
        "id": identifier,
        "subject": subject,
        "predicate": "lemma",
        "object": {"lemma": "synthetic-lemma", "alternatives": ["synthetic-alternative"]},
        "evidence": [{
            "source_url": "https://example.org/synthetic-fixture",
            "raw_path": "data/raw/synthetic.txt",
            "raw_sha256": "a" * 64,
            "quote": "Synthetic source quote",
            "locator": "fixture 1",
        }],
        "assertion_type": assertion_type,
        "status": status,
        "method": "synthetic-test-only",
        "source_family": "synthetic-test-source",
    }


@pytest.fixture
def evidence_fixture(tmp_path: Path) -> tuple[EvidenceIndex, Path]:
    claims_dir = tmp_path / "data/claims"
    reports_dir = tmp_path / "data/reports"
    claims_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    rows = [
        _claim("span", {"type": "token", "passage_id": "p1",
                        "form": "μοῦσα", "start": 0, "end": 5}),
        _claim("general", {"type": "dictionary_entry", "id": "entry-1",
                           "form": "μοῦσα"}),
        _claim("other-passage", {"type": "token", "passage_id": "p2",
                                 "form": "μοῦσα"}),
        _claim("model", {"type": "dictionary_entry", "id": "entry-2",
                         "form": "μοῦσα"}, status="machine_proposed",
               assertion_type="model_inference"),
    ]
    listed = _claim("listed", {"type": "dictionary_entry", "id": "entry-3",
                                "form": "δοκιμή"})
    listed["object"] = {"forms": [{"form": "μορφή", "tags": ["test-only-tag"]}]}
    rows.append(listed)
    source = claims_dir / "synthetic.jsonl"
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                              for row in rows), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (reports_dir / "p2-claim-acceptance.json").write_text(json.dumps({"files": {
        source.name: {"verdict": "PASS", "sha256": digest, "records": len(rows)}
    }}), encoding="utf-8")
    output = tmp_path / "data/evidence.sqlite"
    result = build_evidence(tmp_path, output)
    assert result["claims"] == len(rows)
    return EvidenceIndex(output), source


def test_clicked_form_preserves_occurrence_scope_and_api_shape(
        evidence_fixture: tuple[EvidenceIndex, Path], monkeypatch: pytest.MonkeyPatch):
    index, _ = evidence_fixture
    monkeypatch.setattr(server, "evidence_service", lambda: index)
    response = TestClient(server.app).get(
        "/api/evidence", params={"form": "ΜΟΥΣΑ", "passage_id": "p1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["total"] == 3
    assert [row["id"] for row in payload["claims"]] == ["span", "general", "model"]
    assert payload["claims"][0]["strength"] == "explicit_passage_span"
    assert payload["claims"][0]["subject"]["start"] == 0
    assert payload["claims"][1]["strength"] == "general_form_claim"
    assert "no occurrence" in payload["claims"][1]["match_reason"]
    assert payload["claims"][2]["status"] == "machine_proposed"
    assert payload["claims"][2]["assertion_type"] == "model_inference"
    assert "other-passage" not in {row["id"] for row in payload["claims"]}

    passage = TestClient(server.app).get("/api/evidence", params={"passage_id": "p1"}).json()
    assert [row["id"] for row in passage["claims"]] == ["span"]
    unbound = TestClient(server.app).get("/api/evidence", params={"form": "μοῦσα"}).json()
    assert {row["id"] for row in unbound["claims"]} == {"general", "model"}


def test_evidence_index_is_bound_to_independently_accepted_hash(
        evidence_fixture: tuple[EvidenceIndex, Path]):
    index, source = evidence_fixture
    before = index.db_path.read_bytes()
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_evidence(source.parents[2], index.db_path)
    assert index.db_path.read_bytes() == before


def test_api_fails_closed_when_accepted_claim_bytes_change(
        evidence_fixture: tuple[EvidenceIndex, Path],
        monkeypatch: pytest.MonkeyPatch):
    index, source = evidence_fixture
    monkeypatch.setattr(server, "ROOT", source.parents[2])
    before = TestClient(server.app).get("/api/evidence", params={"form": "μοῦσα"}).json()
    assert before["ready"] is True
    assert before["total"] == 2
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    after = TestClient(server.app).get("/api/evidence", params={"form": "μοῦσα"}).json()
    assert after["ready"] is False
    assert after["claims"] == []
    assert "revalidation" in after["warnings"][0]
    assert index.db_path.is_file()


def test_reverse_indexed_entry_form_is_not_a_passage_attestation(
        evidence_fixture: tuple[EvidenceIndex, Path]):
    index, _ = evidence_fixture
    result = index.lookup("μορφή", passage_id="p1")
    assert result["total"] == 1
    claim = result["claims"][0]
    assert claim["id"] == "listed"
    assert claim["strength"] == "listed_entry_form"
    assert claim["matched_object_forms"] == [{"form": "μορφή", "tags": ["test-only-tag"]}]
    assert "no passage attestation" in claim["match_reason"]
    assert index.get_passage_claims("p1")["total"] == 1


def test_contextual_decision_keeps_source_claims_and_model_proposal_separate(
        evidence_fixture: tuple[EvidenceIndex, Path]):
    index, _ = evidence_fixture
    claims = index.lookup("μοῦσα", passage_id="p1")["claims"]

    class Provider:
        def decide(self, packet):
            assert [row["id"] for row in packet["claims"]] == ["span", "general"]
            assert not packet["author_profile"]
            assert packet["candidates"][0]["claim_ids"] == ["span"]
            return {"choice": "candidate-1", "model": "synthetic-test-provider",
                    "model_confidence": 0.9}

    result = classify_context(
        "μοῦσα", {"id": "p1", "language": "grc", "kind": "text",
                  "text": "μοῦσα synthetic passage"},
        [{"id": "candidate-1", "lemma": "synthetic-lemma", "claim_ids": ["span", "model"]}],
        claims=claims, provider=Provider(),
    )
    assert result["status"] == "proposed"
    assert result["candidate_id"] == "candidate-1"
    assert result["model"] == "synthetic-test-provider"
    assert result["evidence_ids"] == ["span"]
    assert "model_confidence_uncalibrated" in result
    assert "confidence" not in result


def test_contextual_decision_abstains_without_sourced_candidate():
    class Provider:
        def decide(self, packet):
            raise AssertionError("provider should not be called")

    result = classify_context(
        "μοῦσα", {"id": "p1", "language": "grc", "kind": "text", "text": "μοῦσα"},
        [{"id": "unsupported", "lemma": "synthetic-lemma"}], provider=Provider(),
    )
    assert result["status"] == "abstained"
    assert result["candidate_id"] is None
    assert result["evidence_ids"] == []


@pytest.fixture
def corpus_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                  evidence_fixture: tuple[EvidenceIndex, Path]) -> TestClient:
    root = tmp_path / "corpus"
    raw = root / "data/raw/synthetic.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("Synthetic test-only source", encoding="utf-8")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    common = {
        "source": "synthetic-test-source", "source_url": "https://example.org/synthetic",
        "raw_path": "data/raw/synthetic.txt", "raw_sha256": digest,
        "author": "Fixture Poet", "work": "Fixture Work", "edition": "Fixture Edition",
        "license": "test-only", "quality": "source_text",
    }
    rows = [
        dict(common, id="p1", citation="1", language="grc", kind="text",
             text="μοῦσα synthetic Greek fixture"),
        dict(common, id="p2", citation="2", language="grc", kind="text",
             text="ἄλλος synthetic Greek fixture"),
        dict(common, id="c1", citation="1", language="eng", kind="commentary",
             parent_id="p1", author="Fixture Commentator", text="echo from a linked note"),
        dict(common, id="c2", citation="2", language="eng", kind="commentary",
             text="echo from an unrelated note"),
    ]
    processed = root / "data/processed/synthetic.jsonl"
    processed.parent.mkdir(parents=True)
    processed.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                         for row in rows), encoding="utf-8")
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {
        processed.name: {"verdict": "PASS", "sha256":
                         hashlib.sha256(processed.read_bytes()).hexdigest(), "records": len(rows)}
    }}), encoding="utf-8")
    monkeypatch.setattr(build_corpus, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "DB", root / "data/corpus.sqlite")
    monkeypatch.setattr(server, "evidence_service", lambda: evidence_fixture[0])
    build_corpus.build(server.DB)

    class DenseFixture:
        status = {"ready": False}

        def search(self, query, limit, **filters):
            return [{"id": "c1", "score": 0.8, "match_reason": "Synthetic linked note"},
                    {"id": "c2", "score": 0.7, "match_reason": "Synthetic unrelated note"}][:limit]

    monkeypatch.setattr(server, "semantic_service", lambda: DenseFixture())
    return TestClient(server.app)


def test_clicked_word_carries_evidence_without_promoting_generic_claims(
        corpus_client: TestClient):
    result = corpus_client.get("/api/word", params={
        "form": "μοῦσα", "passage_id": "p1"}).json()
    assert result["context"]["id"] == "p1"
    assert {row["id"] for row in result["occurrences"]} == {"p1"}
    evidence = result["structured_evidence"]
    assert evidence["ready"] is True
    assert evidence["claims"][0]["strength"] == "explicit_passage_span"
    assert any(row["strength"] == "general_form_claim" for row in evidence["claims"])
    assert all(row["id"] != "other-passage" for row in evidence["claims"])
    candidates = result["contextual_candidates"]
    assert candidates[0]["strength"] == "explicit_passage_span"
    assert candidates[0]["claim_ids"] == ["span"]
    assert any(row["status"] == "machine_proposed" for row in candidates)


def test_classifier_api_returns_model_judgment_without_writing_evidence(
        corpus_client: TestClient, evidence_fixture: tuple[EvidenceIndex, Path],
        monkeypatch: pytest.MonkeyPatch):
    from backend import classifier

    class Provider:
        def decide(self, packet):
            assert packet["passage"]["id"] == "p1"
            assert [row["id"] for row in packet["claims"]] == ["span", "general"]
            return {"choice": packet["candidates"][0]["id"],
                    "model": "synthetic-test-provider"}

    monkeypatch.setattr(classifier, "configured_provider", Provider)
    index, _ = evidence_fixture
    before = index.db_path.read_bytes()
    response = corpus_client.post("/api/classify-context", json={
        "form": "μοῦσα", "passage_id": "p1"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "proposed"
    assert result["model"] == "synthetic-test-provider"
    assert "span" in result["evidence_ids"]
    assert "model" not in result["evidence_ids"]
    assert result["candidate_origin"] == "structured_source_claims"
    assert index.db_path.read_bytes() == before


def test_hybrid_api_groups_only_explicit_parent_and_keeps_support_visible(
        corpus_client: TestClient):
    assisted = corpus_client.get("/api/search", params={
        "q": "echo", "mode": "hybrid", "language": "grc", "limit": 5}).json()
    assert assisted["mode"] == "hybrid"
    assert assisted["commentary_assisted"] is True
    assert [row["id"] for row in assisted["results"]] == ["p1"]
    assert {hit["id"] for hit in assisted["results"][0]["matched_evidence"]} == {"c1"}
    assert assisted["results"][0]["retrieval_score_kind"] == "reciprocal_rank_fusion"
    assert any(hit["signal"] == "semantic" and hit["raw_score"] == 0.8
               for hit in assisted["results"][0]["matched_evidence"])
    assert assisted["results"][0]["score"] != 0.8

    greek_only = corpus_client.get("/api/search", params={
        "q": "echo", "mode": "hybrid", "language": "grc",
        "commentary_assisted": "false"}).json()
    assert greek_only["results"] == []


def test_corpus_status_statistics_match_indexed_rows(corpus_client: TestClient):
    status = corpus_client.get("/api/status").json()
    with server.connect() as con:
        count = con.execute("SELECT count(*) FROM passages").fetchone()[0]
        sources = {row["source"]: row["count"] for row in con.execute(
            "SELECT source,count(*) count FROM passages GROUP BY source")}
        quality = {row["quality"]: row["count"] for row in con.execute(
            "SELECT quality,count(*) count FROM passages GROUP BY quality")}
        languages = {row["language"]: row["count"] for row in con.execute(
            "SELECT language,count(*) count FROM passages GROUP BY language")}
        authors = con.execute(
            "SELECT count(DISTINCT author_key(author)) FROM passages").fetchone()[0]
    assert status["passages"] == count == 4
    assert {row["source"]: row["count"] for row in status["sources"]} == sources
    assert {row["quality"]: row["count"] for row in status["quality"]} == quality
    assert {row["language"]: row["count"] for row in status["languages"]} == languages
    assert status["authors"] == authors


def test_corpus_rebuild_rejects_accepted_record_count_mismatch(
        corpus_client: TestClient):
    acceptance = server.ROOT / "data/reports/audit-acceptance.json"
    manifest = json.loads(acceptance.read_text(encoding="utf-8"))
    manifest["files"]["synthetic.jsonl"]["records"] = 5
    acceptance.write_text(json.dumps(manifest), encoding="utf-8")
    before = server.DB.read_bytes()
    with pytest.raises((ValueError, RuntimeError), match="count"):
        build_corpus.build(server.DB)
    assert server.DB.read_bytes() == before


def test_merge_withdraws_prior_p2_acceptance_when_auditor_revokes_it(
        tmp_path: Path):
    reports = tmp_path / "data/reports"
    processed = tmp_path / "data/processed"
    reports.mkdir(parents=True)
    processed.mkdir(parents=True)
    fresh = processed / "p2_current.jsonl"
    fresh.write_text('{"id":"synthetic-test-only"}\n', encoding="utf-8")
    digest = hashlib.sha256(fresh.read_bytes()).hexdigest()
    (reports / "audit-acceptance.json").write_text(json.dumps({"files": {
        "original.jsonl": {"verdict": "PASS", "sha256": "a" * 64, "records": 1},
        "p2_revoked.jsonl": {"verdict": "PASS", "sha256": "b" * 64, "records": 1,
                             "acceptance_origin": "data/reports/p2-text-acceptance.json"},
    }}), encoding="utf-8")
    (reports / "p2-text-acceptance.json").write_text(json.dumps({"files": {
        "p2_revoked.jsonl": {"verdict": "FAIL", "sha256": "b" * 64, "records": 1},
        "p2_current.jsonl": {"verdict": "PASS", "sha256": digest, "records": 1},
    }}), encoding="utf-8")
    assert merge_text_acceptance(tmp_path) == {"p2_current.jsonl": 1}
    merged = json.loads((reports / "audit-acceptance.json").read_text(encoding="utf-8"))["files"]
    assert "original.jsonl" in merged
    assert "p2_current.jsonl" in merged
    assert "p2_revoked.jsonl" not in merged
    (reports / "p2-text-acceptance.json").write_text(json.dumps({"files": {
        "p2_current.jsonl": {"verdict": "FAIL", "sha256": digest, "records": 1},
    }}), encoding="utf-8")
    assert merge_text_acceptance(tmp_path) == {}
    merged_again = json.loads((reports / "audit-acceptance.json").read_text(
        encoding="utf-8"))["files"]
    assert set(merged_again) == {"original.jsonl"}


def test_hashed_painting_is_immutable_but_source_files_are_not_served():
    painting_dir = server.ROOT / "assets/paintings"
    asset = next(path for path in painting_dir.glob("*-thumb.*.webp")
                 if re.fullmatch(r"[^/]+\.[0-9a-f]{8}\.webp", path.name))
    client = TestClient(server.app)
    response = client.get(f"/assets/paintings/{asset.name}")
    assert response.status_code == 200
    assert response.content == asset.read_bytes()
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/assets/source/foo").status_code == 404


def test_classifier_refuses_remote_and_public_deployment_before_model_call(
        monkeypatch: pytest.MonkeyPatch):
    from backend import classifier

    def forbidden_provider():
        raise AssertionError("a refused request must not reach the paid provider")

    monkeypatch.setattr(classifier, "configured_provider", forbidden_provider)
    body = {"form": "synthetic", "passage_id": "synthetic"}
    monkeypatch.delenv("MELOS_PUBLIC_DEPLOYMENT", raising=False)
    remote = TestClient(server.app, client=("198.51.100.1", 1234))
    refused_remote = remote.post("/api/classify-context", json=body)
    assert refused_remote.status_code == 403
    assert "local-only" in refused_remote.json()["detail"]

    monkeypatch.setenv("MELOS_PUBLIC_DEPLOYMENT", "1")
    local = TestClient(server.app)
    refused_public = local.post("/api/classify-context", json=body)
    assert refused_public.status_code == 403
    assert "local-only" in refused_public.json()["detail"]
