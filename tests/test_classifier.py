"""Synthetic evaluation fixtures: no rows here are corpus evidence."""

import io
import json
from unittest.mock import patch

from backend.classifier import (JevProvider, build_evidence_packet, classify_context,
                                configured_provider, provider_status)


PASSAGE = {"id": "fixture:1", "text": "α β", "language": "grc", "kind": "text",
           "author": "Fixture poet", "source_url": "https://example.test/passage"}
CANDIDATES = [
    {"id": "parse_a", "lemma": "α", "analysis": "parse A", "matched_form": "α",
     "source_url": "https://example.test/lexicon/a", "claim_ids": ["claim:a"]},
    {"id": "parse_b", "lemma": "β", "analysis": "parse B", "matched_form": "β",
     "source_url": "https://example.test/lexicon/b", "claim_ids": ["claim:b"]},
]


def claim(identifier, object_value):
    return {"id": identifier, "subject": {"type": "form", "form": "α"},
            "predicate": "morphology", "object": object_value,
            "evidence": [{"source_url": f"https://example.test/{identifier}",
                          "quote": f"source quote for {identifier}",
                          "record_id": identifier}],
            "assertion_type": "quoted_source", "status": "source_claim",
            "source_family": "fixture source"}


class StubProvider:
    def __init__(self, choice):
        self.choice = choice
        self.called = False

    def decide(self, packet):
        self.called = True
        return {"choice": self.choice, "model": "fixture-provider-v1"}


def test_packet_retains_conflicting_claims_and_does_not_promote_model_inference():
    rows = [claim("claim:a", {"parse": "A"}), claim("claim:b", {"parse": "B"})]
    inference = claim("model:guess", {"parse": "C"})
    inference["assertion_type"] = "model_inference"
    inference["status"] = "machine_proposed"
    packet = build_evidence_packet("α", PASSAGE, CANDIDATES, rows + [inference],
                                   author_profile=[claim("author:profile", {"dialects": ["mixed"]})])
    assert {r["id"] for r in packet["claims"]} == {"claim:a", "claim:b"}
    assert packet["claims"][0]["object"] == {"parse": "A"}
    assert packet["claims"][1]["object"] == {"parse": "B"}
    assert packet["author_profile"][0]["id"] == "author:profile"
    assert "model:guess" not in json.dumps(packet)
    assert packet["passage"]["text"] == "α β"


def test_packet_preserves_feature_fields_without_author_dialect_shortcut():
    candidate = {**CANDIDATES[0], "features": {"mood": "indicative"},
                 "analysis_text": "verb, indicative", "dialect": ["unresolved"],
                 "matched_form_variants": ["α"]}
    packet = build_evidence_packet("α", PASSAGE, [candidate])
    assert packet["candidates"][0]["features"] == {"mood": "indicative"}
    assert packet["candidates"][0]["dialect"] == ["unresolved"]
    assert packet["author_profile"] == []
    assert "nearby spelling" in " ".join(packet["constraints"])


def test_model_can_only_propose_existing_sourced_candidate():
    provider = StubProvider("parse_b")
    result = classify_context("α", PASSAGE, CANDIDATES,
                              [claim("claim:a", "A"), claim("claim:b", "B")],
                              provider=provider)
    assert provider.called
    assert result["status"] == "proposed"
    assert result["candidate_id"] == "parse_b"
    assert result["model"] == "fixture-provider-v1"
    assert "claim:b" in result["evidence_ids"]
    assert "claim:a" not in result["evidence_ids"]
    assert result["packet"]["claims"][0]["id"] == "claim:a"


def test_accepted_claim_candidate_keeps_its_source_scope():
    candidate = {"id": "claim_candidate", "lemma": "α", "analysis": {"raw": "fixture"},
                 "matched_form": "α", "strength": "general_form_claim",
                 "match_reason": "form-level, not passage attestation",
                 "source_family": "fixture edition", "claim_ids": ["claim:a"],
                 "evidence_refs": ["record:a"]}
    result = classify_context("α", PASSAGE, [candidate], [claim("claim:a", "A")],
                              provider=StubProvider("claim_candidate"))
    assert result["status"] == "proposed"
    assert result["evidence_ids"] == ["claim:a", "record:a"]
    assert result["packet"]["candidates"][0]["strength"] == "general_form_claim"


def test_shared_source_with_distinct_senses_still_invokes_contextual_provider():
    alternatives = [
        {"id": "sense_a", "lemma": "α", "gloss": "sense A",
         "features": {"case": "nominative"}, "claim_ids": ["claim:a"]},
        {"id": "sense_b", "lemma": "α", "gloss": "sense B",
         "features": {"case": "accusative"}, "claim_ids": ["claim:a"]},
    ]
    provider = StubProvider("sense_a")
    result = classify_context("α", PASSAGE, alternatives, [claim("claim:a", "two readings")],
                              provider=provider)
    assert provider.called
    assert result["status"] == "proposed"
    assert result["candidate_id"] == "sense_a"
    uncertain = classify_context("α", PASSAGE, alternatives,
                                 [claim("claim:a", "two readings")],
                                 provider=StubProvider("abstain"))
    assert uncertain["status"] == "abstained"


def test_abstention_on_invalid_choice_unproven_candidate_and_non_greek_context():
    invalid = classify_context("α", PASSAGE, CANDIDATES, provider=StubProvider("invented"))
    assert invalid["status"] == "abstained"
    assert invalid["candidate_id"] is None
    weak = StubProvider("parse_a")
    bare = classify_context("α", PASSAGE, [{"id": "parse_a", "lemma": "α"}], provider=weak)
    assert bare["status"] == "abstained"
    assert not weak.called
    english = classify_context("α", {**PASSAGE, "language": "eng"}, CANDIDATES,
                               provider=StubProvider("parse_a"))
    assert english["status"] == "abstained"
    missing = StubProvider("parse_a")
    absent = classify_context("γ", PASSAGE, CANDIDATES, provider=missing)
    assert absent["status"] == "abstained"
    assert "does not occur" in absent["reason"]
    assert not missing.called


def test_model_abstain_and_unconfigured_provider_are_explicit():
    class UncertainProvider:
        def decide(self, packet):
            return {"choice": "abstain", "model": "fixture-provider-v1",
                    "model_probabilities": {"parse_a": 0.2, "parse_b": 0.1,
                                            "abstain": 0.7},
                    "model_confidence": 0.41,
                    "usage": {"input_tokens": 123, "output_tokens": 4}}

    abstained = classify_context("α", PASSAGE, CANDIDATES, provider=UncertainProvider())
    assert abstained["status"] == "abstained"
    assert abstained["model_probabilities_uncalibrated"]["abstain"] == 0.7
    assert abstained["model_confidence_uncalibrated"] == 0.41
    assert abstained["usage"]["input_tokens"] == 123
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "", "JEV_API_KEY": ""}):
        absent = classify_context("α", PASSAGE, CANDIDATES, provider=JevProvider(api_key=""))
    assert absent["status"] == "abstained"
    assert "not configured" in absent["reason"]


def test_jev_adapter_sends_official_systemone_choice_schema():
    packet = build_evidence_packet("α", PASSAGE, CANDIDATES, [claim("claim:a", "A")])
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(json.dumps({"model": "jev-version-fixture", "answers": {
            "contextual_parse": {"type": "choice", "choice": "parse_a",
                                 "confidence": 0.72,
                                 "probabilities": {"parse_a": 0.72, "parse_b": 0.18,
                                                   "abstain": 0.10}}},
            "usage": {"input_tokens": 100, "output_tokens": 3}}).encode())

    with patch("backend.classifier.urlopen", fake_urlopen):
        answer = JevProvider(api_key="fixture-secret", timeout=2).decide(packet)
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["headers"]["Authorization"] == "Bearer fixture-secret"
    assert captured["body"]["state"]["passage"]["text"] == "α β"
    criteria = captured["body"]["questions"]["contextual_parse"]["criteria"]
    assert set(criteria) == {"parse_a", "parse_b", "abstain"}
    assert answer["choice"] == "parse_a"
    assert answer["model"] == "jev-version-fixture"
    assert "fixture-secret" not in str(answer)
    assert answer["raw_response"]["usage"]["input_tokens"] == 100


def test_oversized_candidate_set_abstains_without_call():
    provider = StubProvider("parse_a")
    result = classify_context("α", PASSAGE, CANDIDATES * 7, provider=provider)
    assert result["status"] == "abstained"
    assert not provider.called


def test_fuzzy_choice_is_not_a_contextual_parse():
    provider = StubProvider("parse_a")
    result = classify_context("α", PASSAGE, [{**CANDIDATES[0], "edit_distance": 1}],
                              provider=provider)
    assert result["status"] == "abstained"
    assert "spelling suggestion" in result["reason"]


def test_provider_status_never_returns_key():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret"}):
        status = provider_status()
    assert status["configured"] is True
    assert "fixture-secret" not in str(status)


def test_installed_local_model_requires_validation_and_explicit_opt_in():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "", "JEV_API_KEY": "",
                                   "MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER": "1"}):
        with patch("backend.local_classifier.local_model_status",
                   return_value={"installed": True, "validated": False,
                                 "model": "fixture-local"}):
            assert configured_provider() is None
            status = provider_status()
    assert status["configured"] is False
    assert status["installed"] is True
    assert "disabled" in status["reason"]
