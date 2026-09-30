"""Evidence-bound contextual proposals; never a source of corpus facts.

The classifier accepts already retrieved candidates and independently accepted
claims.  Its optional Jev provider makes a real TypeSafe System One request.
No model is invoked when the passage, candidate provenance, or credentials are
missing.  The model can select an existing candidate ID or abstain, and cannot
create a lemma, Greek text, source claim, or dialect label.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .textutils import normalize, tokenize


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = 'jev-1.13.0'
MAX_CANDIDATES = 32
MAX_CLAIMS = 32
MAX_STATE_CHARS = 32000


def _state_json(value: Any) -> str:
    """The exact JSON encoding used on the wire (no insignificant whitespace)."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


class DecisionProvider(Protocol):
    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _source_claim(row: Any) -> bool:
    return (isinstance(row, Mapping) and row.get("status") == "source_claim"
            and row.get("assertion_type") != "model_inference"
            and bool(row.get("id")) and isinstance(row.get("evidence"), list)
            and any(isinstance(e, Mapping) and e.get("source_url") and e.get("quote")
                    for e in row["evidence"]))


def _claim_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only source-bearing fields, preserving alternatives in object."""
    return {"id": str(row["id"]), "subject": row.get("subject"),
            "predicate": row.get("predicate"), "object": row.get("object"),
            "source_family": row.get("source_family"),
            "strength": row.get("strength"),
            "evidence": [{k: e.get(k) for k in
                          ("record_id", "source_url", "quote", "locator") if e.get(k) is not None}
                         for e in row["evidence"] if isinstance(e, Mapping)],
            "status": "source_claim"}


def _compact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Factor repeated candidate provenance, without discarding evidence.

    Null optional candidate fields convey no supplied analysis. Everything
    nested inside an analysis or quoted claim is retained verbatim, including
    explicit nulls/empty values. Source-reference IDs remain candidate-specific;
    only their repeated URL/scope payload is shared in a lookup catalogue.
    """
    options = [{key: value for key, value in candidate.items() if value is not None}
               for candidate in packet['candidates']]
    compact = {**packet, 'candidates': options}
    catalog: dict[str, dict[str, Any]] = {}
    index: dict[str, str] = {}
    factored = []
    for candidate in options:
        refs = []
        for ref in candidate['source_references']:
            payload = {key: value for key, value in ref.items() if key != 'id'}
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if signature not in index:
                source_id = f's{len(catalog) + 1}'
                index[signature] = source_id
                catalog[source_id] = payload
            refs.append({'id': ref['id'], 'source_ref': index[signature]})
        factored.append({**candidate, 'source_references': refs})
    if not catalog:
        return compact
    shared = {**compact, 'candidates': factored, 'source_catalog': catalog,
              'source_reference_format':
              'Each candidate source_references item preserves its evidence id; '
              'source_ref resolves to the complete URL and scope in source_catalog. '
              'Sharing a URL does not merge claims, candidate IDs, or interpretations.'}
    # Small packets need not pay for the lookup-table explanation.
    size = lambda value: len(_state_json(value))
    return shared if size(shared) < size(compact) else compact


def _nearby_spelling(candidate: Mapping[str, Any]) -> bool:
    distance = candidate.get('edit_distance')
    return isinstance(distance, (int, float)) and distance > 0


def build_evidence_packet(
    form: str, passage: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] = (),
    author_profile: Sequence[Mapping[str, Any]] = (),
    dialect_rules: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a bounded, inspectable decision state from supplied evidence.

    Unaccepted or model-inferred claims are never promoted into the packet.
    Author profile and dialect rules must be source claims too; merely knowing
    an author's name never turns a word into an exclusive dialect form.
    """
    context = passage or {}
    warnings: list[str] = []
    if len(candidates) > MAX_CANDIDATES:
        warnings.append(f"More than {MAX_CANDIDATES} candidates; no subset was silently chosen.")
    if sum(map(len, (claims, author_profile, dialect_rules))) > MAX_CLAIMS:
        warnings.append(f"More than {MAX_CLAIMS} claims; no subset was silently chosen.")
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, rows in (("claims", claims), ("author_profile", author_profile),
                       ("dialect_rules", dialect_rules)):
        groups[name] = [_claim_record(row) for row in rows if _source_claim(row)]
        dropped = len(rows) - len(groups[name])
        if dropped:
            warnings.append(f"{dropped} {name} record(s) excluded: not source-bearing accepted claims.")
    known_claim_ids = {row["id"] for rows in groups.values() for row in rows}
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(candidates, 1):
        if not isinstance(row, Mapping):
            warnings.append(f"Candidate {index} is not an object.")
            continue
        cid = str(row.get("id") or f"candidate_{index}")
        if cid == "abstain" or cid in seen:
            warnings.append(f"Duplicate or reserved candidate ID: {cid}.")
            continue
        seen.add(cid)
        source_refs: list[dict[str, str]] = []
        for field in ("source_url", "gloss_source_url"):
            url = row.get(field)
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                source_refs.append({"id": f"{cid}:{field}", "url": url,
                                    "scope": "candidate metadata; verify source scope"})
        for source in row.get("supporting_sources") or ():
            if isinstance(source, Mapping) and isinstance(source.get("source_url"), str):
                url = source["source_url"]
                if url.startswith(("https://", "http://")) and not any(
                        ref["url"] == url for ref in source_refs):
                    source_refs.append({"id": f"{cid}:support:{len(source_refs)}",
                                        "url": url, "scope": "candidate metadata; verify source scope"})
        linked = [str(claim_id) for claim_id in row.get("claim_ids") or ()
                  if str(claim_id) in known_claim_ids]
        options.append({"id": cid, "lemma": row.get("lemma"),
                        "analysis": row.get("analysis"),
                        "analysis_text": row.get("analysis_text"),
                        "features": row.get("features"),
                        "dialect": row.get("dialect"),
                        "gloss": row.get("gloss"),
                        "matched_form": row.get("matched_form"),
                        "matched_form_variants": row.get("matched_form_variants"),
                        "matched_object_form": row.get("matched_object_form"),
                        "match_kind": row.get("match_kind"),
                        "edit_distance": row.get("edit_distance"),
                        "strength": row.get("strength"),
                        "match_reason": row.get("match_reason"),
                        "source_family": row.get("source_family"),
                        "comparison_scope": row.get("comparison_scope"),
                        "source_passage_id": row.get("source_passage_id"),
                        "comparison_context": row.get("comparison_context"),
                        "evidence_refs": row.get("evidence_refs"),
                        "source_references": source_refs, "claim_ids": linked})
    packet = {
        "form": form,
        "passage": {k: context.get(k) for k in
                    ("id", "text", "author", "author_id", "work", "citation",
                     "language", "kind", "source_url") if context.get(k) is not None},
        "candidates": options,
        **groups,
        "constraints": [
            "Choose only an existing candidate ID or abstain.",
            "Source claims and lexical candidates have distinct scopes; do not infer attestation from a dictionary listing.",
            "Author context and literary dialect rules are defeasible, not exclusive dialect assignments.",
            "A nearby spelling is a correction suggestion, not a parse of the queried form.",
            "An equivalent form or listed entry is an alternative relation, not an attested parse in this passage.",
            "A computationally matching context in another edition is a comparison only: its source claim belongs to the original source passage, not proof of edition identity or direct target-passage attestation.",
            "Preserve conflicting interpretations; abstain if evidence does not resolve them.",
        ],
        "warnings": warnings,
    }
    return _compact_packet(packet)


class JevProvider:
    """Official TypeSafe Jev System One HTTP adapter (no account creation)."""

    def __init__(self, api_key: str | None = None, *, model: str = "jev-latest",
                 timeout: float = 8.0):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        self.model = model
        self.timeout = timeout

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.api_key:
            raise RuntimeError("TypeSafe Jev API key is not configured")
        # Full hypotheses/evidence occur once, in state. Repeating them in the
        # choice criteria needlessly doubled much of the provider's input.
        choices = {str(item["id"]):
            "Select the candidate with this exact ID in state.candidates, using its complete evidence and scope."
            for item in packet["candidates"]}
        choices["abstain"] = "The supplied context and source evidence do not support a responsible selection."
        body = {"model": self.model, "state": packet,
                "questions": {"contextual_parse": {
                    "type": "choice",
                    "instructions": "Which supplied candidate best fits this exact Greek passage? Select abstain for unresolved ambiguity, conflicts, missing evidence, or inadequate context. Never create a new reading or assume the author's literary dialect makes every form exclusive.",
                    "criteria": choices}}}
        request = Request(JEV_ENDPOINT, data=_state_json(body).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"TypeSafe Jev HTTP {exc.code}") from None
        except URLError as exc:
            raise RuntimeError(f"TypeSafe Jev transport error: {exc.reason}") from None
        answer = payload.get("answers", {}).get("contextual_parse", {})
        if answer.get("type") != "choice" or not isinstance(answer.get("choice"), str):
            raise RuntimeError("TypeSafe Jev returned no valid choice answer")
        return {"choice": answer["choice"], "model": payload.get("model"),
                "model_probabilities": answer.get("probabilities"),
                "model_confidence": answer.get("confidence"),
                "usage": payload.get("usage"),
                "raw_response": {"model": payload.get("model"),
                                 "answers": payload.get("answers"),
                                 "usage": payload.get("usage")}}


def configured_provider() -> DecisionProvider | None:
    """Use Jev if configured; local inference needs validation and opt-in."""
    if os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY"):
        return JevProvider(model=os.environ.get('MELOS_JEV_MODEL', JEV_MODEL))
    try:
        from .local_classifier import LocalModelProvider, local_model_status
        status = local_model_status()
        if (status.get("installed") and status.get("validated")
                and os.environ.get("MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER") == "1"):
            return LocalModelProvider()
    except (ImportError, RuntimeError, OSError):
        pass
    return None


def provider_status() -> dict[str, Any]:
    """Describe capability without exposing credentials or calling a model."""
    if os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY"):
        return {"configured": True, "provider": "TypeSafe Jev",
                "model": os.environ.get('MELOS_JEV_MODEL', JEV_MODEL), "reason": "Jev is configured; each comparison is an evidence-bound model proposal."}
    try:
        from .local_classifier import local_model_status
        status = local_model_status()
        if status.get("installed"):
            enabled = bool(status.get("validated") and
                           os.environ.get("MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER") == "1")
            reason = ("Validated local model is explicitly enabled; no request made."
                      if enabled else
                      "Validated local model requires MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER=1; inference is disabled."
                      if status.get("validated") else
                      "TypeSafe Jev is preferred, but TYPESAFE_API_KEY is not configured. The installed local diagnostic model remains disabled because its contextual accuracy is unverified.")
            return {"configured": enabled, "provider": "local", "model": status.get("model"),
                    "installed": True, "validated": bool(status.get("validated")),
                    "reason": reason}
    except (ImportError, RuntimeError, OSError):
        pass
    return {"configured": False, "provider": None, "model": None,
            "reason": "No TypeSafe Jev key or local classifier is configured."}


def classify_context(
    form: str, passage: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] = (),
    author_profile: Sequence[Mapping[str, Any]] = (),
    dialect_rules: Sequence[Mapping[str, Any]] = (),
    provider: DecisionProvider | None = None,
) -> dict[str, Any]:
    """Return a model proposal or a reasoned abstention, never a corpus claim."""
    packet = build_evidence_packet(form, passage, candidates, claims,
                                   author_profile, dialect_rules)
    result: dict[str, Any] = {"status": "abstained", "decision_stage": "preflight", "candidate_id": None,
                              "reason": "", "model": None, "evidence_ids": [],
                              "packet": packet, "warnings": list(packet["warnings"])}
    if packet["warnings"] and any("silently chosen" in w or "candidate ID" in w
                                   for w in packet["warnings"]):
        result["reason"] = "Input exceeds safe bounds or has ambiguous candidate IDs."
        return result
    context = packet["passage"]
    if not context.get("text") or context.get("language", "grc") != "grc" or context.get("kind", "text") != "text":
        result["reason"] = "An original Greek text passage is required."
        return result
    if normalize(form) not in {normalize(token) for token in tokenize(str(context["text"]))}:
        result["reason"] = "The queried form does not occur as a token in the supplied Greek passage."
        return result
    if not packet["candidates"]:
        result["reason"] = "No existing candidate is available."
        return result
    if all(_nearby_spelling(candidate) for candidate in packet['candidates']):
        result['reason'] = ('Only nearby-spelling suggestions are available, not parses of this form. '
                            'No model request was made; source-supported candidates for the exact form are needed.')
        return result
    if not any(c["source_references"] or c["claim_ids"] for c in packet["candidates"]):
        result["reason"] = "Candidates have no source references or accepted claim links."
        return result
    state_chars = len(_state_json(packet))
    if state_chars > MAX_STATE_CHARS:
        result["reason"] = f"Evidence packet exceeds {MAX_STATE_CHARS} characters."
        return result
    provider = provider or configured_provider()
    if provider is None:
        result["reason"] = provider_status()["reason"]
        return result
    from .jev_gateway import GatewayLimit, GatewayUnavailable
    result['decision_stage'] = 'provider_request'
    try:
        answer = provider.decide(packet)
    except (GatewayLimit, GatewayUnavailable):
        raise
    except (RuntimeError, ValueError, TypeError, TimeoutError) as exc:
        result["reason"] = str(exc)
        return result
    choice = answer.get("choice")
    if 'cache_hit' in answer:
        result['cache_hit'] = bool(answer['cache_hit'])
    result["model"] = answer.get("model")
    if not isinstance(result["model"], str) or not result["model"]:
        result["reason"] = "Provider did not identify the model used."
        return result
    # Preserve the provider's uncertainty even when it chooses abstention.
    # These are raw model signals, not philological calibration.
    if answer.get("model_probabilities") is not None:
        result["model_probabilities_uncalibrated"] = answer["model_probabilities"]
    if answer.get("model_confidence") is not None:
        result["model_confidence_uncalibrated"] = answer["model_confidence"]
    if answer.get("usage") is not None:
        result["usage"] = answer["usage"]
    if choice == "abstain":
        result['decision_stage'] = 'model_abstained'
        result["reason"] = "The model abstained on the supplied evidence."
        return result
    selected = next((c for c in packet["candidates"] if c["id"] == choice), None)
    if selected is None:
        result["reason"] = "Provider returned a choice outside the supplied candidate IDs."
        return result
    if _nearby_spelling(selected):
        result["reason"] = "Selected candidate is a nearby-spelling suggestion, not a parse of this form."
        return result
    evidence_ids = list(dict.fromkeys(
        selected["claim_ids"] +
        [str(ref) for ref in selected.get("evidence_refs") or () if ref] +
        [r["id"] for r in selected["source_references"]]))
    if not evidence_ids:
        result["reason"] = "Selected candidate has no linked evidence."
        return result
    result.update(status="proposed", decision_stage="model_proposed", candidate_id=choice,
                  reason="Model-ranked existing candidate; interpretive proposal only.",
                  evidence_ids=evidence_ids)
    return result


__all__ = ["DecisionProvider", "JevProvider", "build_evidence_packet",
           "classify_context", "configured_provider", "provider_status"]
