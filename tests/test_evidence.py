"""Synthetic fixtures test evidence plumbing, never historical content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.evidence import EvidenceIndex
from backend.classifier import build_evidence_packet
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


def test_equivalent_form_relation_remains_raw_not_a_grammatical_candidate(tmp_path: Path) -> None:
    _stage(tmp_path, [_claim(
        "fixture:equivalent", {"type": "form", "form": "α"},
        "equivalent_form", {"form": "β", "relation_raw": "fixture relation"},
    )])
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    index = EvidenceIndex(output)
    assert index.candidate_analyses("α")["candidates"] == []
    assert index.equivalent_forms_for_form("α") == ["β"]
    raw = index.lookup("α")["claims"][0]
    assert raw["predicate"] == "equivalent_form"
    assert raw["object"] == {"form": "β", "relation_raw": "fixture relation"}


def test_equivalent_target_array_is_retrieval_only_and_unaccepted_claims_do_not_expand(tmp_path: Path) -> None:
    rows = [
        _claim("fixture:accepted", {"type": "form", "form": "α"},
               "equivalent_form", {"targets": [{"word": "β"}, {"word": "γ"}]}),
        _claim("fixture:review", {"type": "form", "form": "α"},
               "equivalent_form", {"form": "δ"}, status="needs_review"),
    ]
    _stage(tmp_path, rows)
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    index = EvidenceIndex(output)
    assert index.equivalent_forms_for_form("α") == ["β", "γ"]
    assert index.candidate_analyses("α")["candidates"] == []
    assert {claim["id"] for claim in index.lookup("α")["claims"]} == {
        "fixture:accepted", "fixture:review",
    }


def _kaikki_fixture(claim_id: str, headword: str, predicate: str, obj: dict) -> dict:
    """Synthetic Kaikki-shaped source claim, never corpus or dictionary data."""
    record_id = ":".join(claim_id.split(":", 4)[:4])
    row = _claim(claim_id, {"type": "form", "form": headword}, predicate, obj)
    row["source_family"] = "enwiktionary-kaikki-synthetic-fixture"
    row["metadata"] = {"source_record_id": record_id, "fixture": True}
    return row


def test_inflected_entry_metadata_is_not_a_parse_but_form_of_and_table_are(tmp_path: Path) -> None:
    # The first page is an inflected entry; its word and canonical display form
    # are not lemmas/grammar. The second page is an ordinary paradigm entry.
    claims = [
        _kaikki_fixture("wiktionary:kaikki:line:1:lemma:entry", "αβ", "lemma", {
            "lemma": "αβ", "head_templates": [{"name": "grc-noun form"}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:1:morphology:entry", "αβ", "morphology", {
            "lemma": "αβ", "forms": [{"form": "αβ", "tags": ["canonical"]}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:1:form_of:0", "αβ", "lemma", {
            "relation": "form_of", "targets": [{"word": "γᾱ"}],
            "source_tags": ["dative", "form-of", "plural"],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:2:lemma:entry", "γ", "lemma", {
            "lemma": "γ", "head_templates": [{"name": "grc-noun"}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:2:morphology:entry", "γ", "morphology", {
            "lemma": "γ", "forms": [{"form": "αβ", "tags": ["dative", "plural"]}],
        }),
    ]
    _stage(tmp_path, claims)
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    index = EvidenceIndex(output)
    assert len(index.lookup("αβ", limit=100)["claims"]) == 4
    result = index.candidate_analyses("αβ", limit=2)
    assert result["total_claims"] == 4
    assert len(result["candidates"]) == 2  # Filter before the candidate limit.
    by_kind = {row["candidate_kind"]: row for row in result["candidates"]}
    assert by_kind["explicit_form_of"]["lemma"] == "γᾱ"
    assert by_kind["explicit_form_of"]["analysis"] == ["dative", "plural"]
    assert by_kind["explicit_form_of"]["source_tags"] == ["dative", "form-of", "plural"]
    assert by_kind["grammatical_analysis"]["lemma"] == "γ"
    assert by_kind["grammatical_analysis"]["strength"] == "listed_entry_form"
    assert index.candidate_analyses("αβ", limit=1)["candidates"][0]["candidate_kind"] in by_kind
    assert index.get_claim("wiktionary:kaikki:line:1:morphology:entry")["object"]["forms"][0]["tags"] == ["canonical"]


def test_inflected_entry_listed_grammar_uses_only_sourced_form_of_target(tmp_path: Path) -> None:
    claims = [
        _kaikki_fixture("wiktionary:kaikki:line:3:lemma:entry", "αβ", "lemma", {
            "lemma": "αβ", "head_templates": [{"name": "grc-noun form"}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:3:morphology:entry", "αβ", "morphology", {
            "lemma": "αβ", "forms": [{"form": "αβγ", "tags": ["canonical", "dative", "plural"]}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:3:form_of:0", "αβ", "lemma", {
            "relation": "form_of", "targets": [{"word": "γ"}],
            "source_tags": ["dative", "form-of", "plural"],
        }),
    ]
    _stage(tmp_path, claims)
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    index = EvidenceIndex(output)
    raw = index.lookup("αβγ")
    assert [claim["id"] for claim in raw["claims"]] == ["wiktionary:kaikki:line:3:morphology:entry"]
    projected = index.candidate_analyses("αβγ")
    candidates = projected["candidates"]
    listed = next(row for row in candidates if row["candidate_kind"] == "grammatical_analysis")
    assert listed["entry_headword"] == "αβ"
    assert listed["lemma"] == "γ"
    assert listed["analysis"] == ["dative", "plural"]
    assert listed["matched_object_form"]["tags"] == ["canonical", "dative", "plural"]
    assert listed["claim_ids"] == [
        "wiktionary:kaikki:line:3:morphology:entry", "wiktionary:kaikki:line:3:form_of:0",
    ]
    assert [claim["id"] for claim in projected["supporting_claims"]] == [
        "wiktionary:kaikki:line:3:form_of:0",
    ]
    sibling = projected["supporting_claims"][0]
    assert sibling["subject"]["form"] == "αβ"
    assert sibling["strength"] == "general_entry_relation"
    assert sibling["object"]["targets"] == [{"word": "γ"}]
    packet = build_evidence_packet("αβγ", {"id": "fixture:passage", "text": "αβγ",
                                              "language": "grc", "kind": "text"},
                                   candidates, [*raw["claims"], *projected["supporting_claims"]])
    assert {claim["id"] for claim in packet["claims"]} == set(listed["claim_ids"])
    assert packet["candidates"][0]["claim_ids"] == listed["claim_ids"]


def test_model_inference_cannot_supply_a_sibling_form_of_target(tmp_path: Path) -> None:
    inferred = _kaikki_fixture("wiktionary:kaikki:line:5:form_of:0", "αβ", "lemma", {
        "relation": "form_of", "targets": [{"word": "δ"}], "source_tags": ["dative"],
    })
    inferred["assertion_type"] = "model_inference"
    _stage(tmp_path, [
        _kaikki_fixture("wiktionary:kaikki:line:5:lemma:entry", "αβ", "lemma", {
            "lemma": "αβ", "head_templates": [{"name": "grc-noun form"}],
        }),
        _kaikki_fixture("wiktionary:kaikki:line:5:morphology:entry", "αβ", "morphology", {
            "lemma": "αβ", "forms": [{"form": "αβγ", "tags": ["dative", "plural"]}],
        }),
        inferred,
    ])
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    result = EvidenceIndex(output).candidate_analyses("αβγ")
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["lemma"] is None
    assert result["candidates"][0]["claim_ids"] == ["wiktionary:kaikki:line:5:morphology:entry"]
    assert result["supporting_claims"] == []


def test_multiple_form_of_targets_do_not_create_a_lemma(tmp_path: Path) -> None:
    _stage(tmp_path, [
        _kaikki_fixture("wiktionary:kaikki:line:4:form_of:0", "αβ", "lemma", {
            "relation": "form_of", "targets": [{"word": "γ"}, {"word": "δ"}],
            "source_tags": ["dative", "form-of", "plural"],
        }),
    ])
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    candidate = EvidenceIndex(output).candidate_analyses("αβ")["candidates"][0]
    assert candidate["lemma"] is None
    assert candidate["lemma_targets"] == [{"word": "γ"}, {"word": "δ"}]
    assert candidate["analysis"] == ["dative", "plural"]


def test_metadata_over_100_claim_preview_limit_does_not_hide_later_parse(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claims = [
        _kaikki_fixture(f"wiktionary:kaikki:line:{number}:morphology:entry", "αβ", "morphology", {
            "lemma": "αβ", "forms": [{"form": "αβ", "tags": ["canonical"]}],
        })
        for number in range(100, 211)
    ]
    claims.append(_kaikki_fixture("wiktionary:kaikki:line:999:form_of:0", "αβ", "lemma", {
        "relation": "form_of", "targets": [{"word": "γ"}], "source_tags": ["dative", "plural"],
    }))
    _stage(tmp_path, claims)
    output = tmp_path / "data/evidence.sqlite"
    build(tmp_path, output)
    index = EvidenceIndex(output)
    assert index.lookup("αβ", limit=100)["total"] == 112
    assert len(index.lookup("αβ", limit=100)["claims"]) == 100
    projected = index.candidate_analyses("αβ", limit=1)
    assert projected["total_claims"] == 112
    assert [(row["candidate_kind"], row["lemma"]) for row in projected["candidates"]] == [
        ("explicit_form_of", "γ")
    ]
    from backend import server

    class NoMorphology:
        def analyze(self, form, **kwargs):
            return {"candidates": [], "warnings": []}

    monkeypatch.setattr(server, "morph_service", lambda: NoMorphology())
    monkeypatch.setattr(server, "occurrences", lambda *args, **kwargs: [])
    monkeypatch.setattr(server, "evidence_service", lambda: index)
    monkeypatch.setattr(server, "evidence_lookup", lambda form, passage_id, limit: {
        "ready": True, **index.lookup(form, passage_id=passage_id or None, limit=limit),
    })
    word = server.word("αβ")
    assert len(word["structured_evidence"]["claims"]) == 100
    assert [claim["id"] for claim in word["contextual_supporting_claims"]] == [
        "wiktionary:kaikki:line:999:form_of:0",
    ]
    assert word["contextual_unresolved_claim_ids"] == []
    packet = build_evidence_packet("αβ", {"id": "fixture:passage", "text": "αβ",
                                           "language": "grc", "kind": "text"},
                                   word["contextual_candidates"],
                                   [*word["structured_evidence"]["claims"],
                                    *word["contextual_supporting_claims"]])
    assert packet["candidates"][0]["claim_ids"] == ["wiktionary:kaikki:line:999:form_of:0"]
    assert any(claim["id"] == "wiktionary:kaikki:line:999:form_of:0"
               for claim in packet["claims"])


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
