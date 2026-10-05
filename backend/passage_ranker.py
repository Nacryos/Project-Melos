"""Occurrence-bound optional Jev ranking, separate from source evidence.

The injected classifier owns all existing source/receipt proof checks. This
adapter adds context only after those checks, before the durable gateway hashes
or charges the request. It neither adds candidates nor repairs source text.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import unicodedata
from typing import Mapping

from .classifier import MAX_STATE_CHARS
from .jev_gateway import GatewayLimit, GatewayUnavailable

MAX_TOKEN_OCCURRENCES = 3
MAX_TRANSLATIONS = 2
MAX_TRANSLATION_CHARACTERS = 1800
SCHEMA = "melos-occurrence-context-v1"


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _translations(passage):
    """Project only translation previews admitted by the corpus lookup."""
    rows = []
    for translation in passage.get("translation_previews") or []:
        if not isinstance(translation, Mapping) or not isinstance(translation.get("text"), str):
            continue
        if not translation.get("record_id") or translation.get("parent_id") != passage["id"]:
            continue
        if len(rows) >= MAX_TRANSLATIONS:
            break
        text = translation["text"]
        rows.append({**{key: deepcopy(translation[key]) for key in (
            "record_id", "parent_id", "source", "source_url", "language", "credit", "translator", "citation", "pairing_proof"
        ) if key in translation}, "text": text[:MAX_TRANSLATION_CHARACTERS],
            "excerpt_truncated": len(text) > MAX_TRANSLATION_CHARACTERS,
            "evidence_type": "published_translation", "scope": "whole_source_passage",
            "selection_aligned": False,
            "scope_note": "Published whole-passage context, not a token or selected-phrase alignment. A translation reflects an interpretation; it does not establish a grammatical parse."})
    return rows


def _syntax_context(result):
    syntax = result.get("syntax") or {}
    if syntax.get("state", syntax.get("status")) != "ready":
        return {"status": "unavailable", "evidence_type": "contextual_prediction"}
    source_rows = syntax.get("tokens") or []
    nonlexical = set()
    for row in source_rows:
        text = row.get("text") or ""
        if (row.get("token_kind") in {"whitespace", "editorial", "punctuation"}
                or row.get("prediction_status") == "not_applicable"
                or not any(unicodedata.category(char).startswith("L") for char in text)
                or any(char in "[]⟦⟧⟨⟩<>…†‡\u0323" for char in text)):
            nonlexical.add(row.get("id"))
    rows = []
    for row in source_rows:
        projected = {key: deepcopy(row[key]) for key in (
            "id", "text", "lemma", "upos", "xpos", "features", "head", "deprel",
            "start", "end", "absolute_start", "absolute_end", "selected", "sentence_id",
            "token_kind", "prediction_status", "attachment_status"
        ) if key in row}
        if row.get("id") in nonlexical:
            projected.update(lemma=None, upos=None, xpos=None, features={}, head=None, deprel=None,
                prediction_status="not_applicable", attachment_status="not_applicable",
                context_role="literal_nonlexical_or_editorial_boundary")
        elif row.get("head") is not None and row["head"] in nonlexical:
            projected.update(head=None, deprel=None, unresolved_head_id=row["head"],
                             attachment_status="unresolved_nonlexical_head")
        rows.append(projected)
    scope = syntax.get("scope", "unknown")
    return {"status": "ready", "evidence_type": "contextual_prediction",
        "scope": scope, "tokens": rows,
        **{key: deepcopy(syntax[key]) for key in (
            "context_start", "context_end", "offset_unit", "provider", "model", "model_version",
            "version", "annotation_scheme", "provenance", "excluded_components", "warnings", "limitations"
        ) if key in syntax},
        "scope_note": ("Fallible model predictions, not source annotations or independent proof. "
            "Context offsets identify the parsed corpus span; token start/end are local to that span and absolute_start/absolute_end are corpus offsets. "
            "Nonlexical/editorial rows retain literal boundaries but supply no grammatical prediction. "
            "A null head with unresolved attachment status is not a predicted root. "
            + ("Only the selected span was parsed; heads outside it cannot be resolved." if scope == "selected_span" else
               "The whole bounded source passage was parsed; this does not restore missing material." if scope == "whole_passage" else
               "The parsed context scope was not supplied; do not assume whole-passage coverage."))}


class OccurrenceProvider:
    """Enrich before the wrapped CachedJevProvider's cache key is computed."""
    def __init__(self, provider, passage, token, result):
        self.provider = provider
        self.passage = passage
        self.token = token
        self.result = result
        self.last_packet = None

    def decide(self, packet):
        text = self.passage["text"]
        start, end = self.token["start"], self.token["end"]
        supplied = packet.get("passage") or {}
        if (supplied.get("id") != self.passage["id"] or supplied.get("text") != text
                or packet.get("form") != text[start:end]):
            raise ValueError("Classifier context no longer matches the exact source occurrence; no paid request was made.")
        enriched = deepcopy(packet)
        enriched["occurrence_context_schema"] = SCHEMA
        enriched["target_occurrence"] = {
            "token_id": self.token["id"], "text": text[start:end],
            "start": start, "end": end, "offset_unit": "codepoint",
            "passage_text_sha256": _digest(text),
            "preceding_context": text[max(0, start - 180):start],
            "following_context": text[end:end + 180],
            "selected_span": deepcopy(self.result["selection"]),
        }
        enriched["published_translation_context"] = _translations(self.passage)
        enriched["predicted_syntax_context"] = _syntax_context(self.result)
        enriched["constraints"] = [*(enriched.get("constraints") or []),
            "Classify only target_occurrence at its exact offsets, not another occurrence of the same spelling elsewhere in the passage.",
            "Published translations are whole-passage contextual interpretations, not token-aligned grammatical evidence. Do not treat a translated word as a proved sense or parse.",
            "Predicted syntax is defeasible machine context. Do not turn model agreement into independent source corroboration; retained source alternatives and uncertainty take precedence.",
        ]
        if len(json.dumps(enriched, ensure_ascii=False, separators=(",", ":"), default=str)) > MAX_STATE_CHARS:
            raise ValueError(f"Enriched occurrence evidence exceeds {MAX_STATE_CHARS} characters; no candidates were dropped and no paid request was made.")
        self.last_packet = deepcopy(enriched)
        return self.provider.decide(enriched)


def _ranked_candidates(decision):
    probabilities = decision.get("model_probabilities_uncalibrated")
    probabilities = probabilities if isinstance(probabilities, Mapping) else {}
    rows = []
    for candidate in (decision.get("packet") or {}).get("candidates") or []:
        identifier = candidate.get("id")
        score = probabilities.get(identifier)
        if not isinstance(score, (float, int)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            score = None
        rows.append({"candidate_id": identifier, "score_uncalibrated": score})
    return sorted(rows, key=lambda row: (row["score_uncalibrated"] is None,
                                        -(row["score_uncalibrated"] or 0)))


class PassageRanker:
    """Bounded callback for PassageAnalysisService.

    provider_factory(visitor_id) must return the existing durable cached Jev
    gateway. classify_callback(form, passage_id, *, provider, candidate_basis,
    machine_receipt_id) must reuse the server's protected proof assembly.
    Both are trusted application callbacks, never HTTP request parameters.
    """
    def __init__(self, passage_lookup, classify_callback, provider_factory):
        self.passage_lookup = passage_lookup
        self.classify_callback = classify_callback
        self.provider_factory = provider_factory

    def __call__(self, result, *, visitor_id=None):
        output = {"status": "unavailable", "provider": "TypeSafe Jev",
            "max_token_occurrences": MAX_TOKEN_OCCURRENCES, "attempted_occurrences": 0, "items": [],
            "warnings": ["Model scores are uncalibrated contextual proposals, not verified grammatical or scholarly confidence. All original source alternatives remain available."]}
        passage_id = (result.get("passage") or {}).get("id")
        try:
            passage = self.passage_lookup(passage_id)
            text = passage["text"]
            selection = result["selection"]
            start, end = selection["start"], selection["end"]
            valid = (passage["id"] == passage_id and isinstance(text, str)
                and _digest(text) == result["passage"].get("text_sha256")
                and type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and text[start:end] == selection["text"])
        except (KeyError, TypeError, ValueError, OSError):
            valid = False
        if not valid:
            output["warnings"].append("The source passage or exact selection changed; no ranking was requested.")
            return output
        words = [token for token in result.get("tokens") or [] if token.get("kind") == "word"]
        # Validate every occurrence before any paid work, including later tokens.
        for token in words:
            a, b = token.get("start"), token.get("end")
            if (type(a) is not int or type(b) is not int or not start <= a < b <= end
                    or text[a:b] != token.get("text")):
                output["warnings"].append("A token no longer matches its source offsets; no ranking was requested.")
                return output
        try:
            provider = self.provider_factory(visitor_id)
            if provider is None:
                raise GatewayUnavailable("Jev is not configured.")
        except (GatewayUnavailable, OSError, ValueError, TypeError):
            output["warnings"].append("Jev or its durable budget gateway is unavailable; no ranking was requested.")
            return output
        blocked = None
        for token in words:
            item = {"token_id": token["id"], "form": token["text"], "start": token["start"],
                    "end": token["end"], "status": "not_available", "ranked_candidates": []}
            output["items"].append(item)
            if token.get("editorial_fragment"):
                item.update(status="editorial_fragment", reason="Editorial boundaries split this word; no reconstructed form was ranked.")
                continue
            if token.get("partial_word"):
                item.update(status="partial_word", reason="Select the complete source word to rank its analyses.")
                continue
            source = [*(token.get("contextual_candidates") or []), *(token.get("source_candidates") or []),
                      *[candidate for parallel in token.get("parallel_contexts") or [] for candidate in parallel.get("candidates") or []]]
            # Nearby spellings are lookup suggestions, never parses of the
            # literal target. Keep them untouched in the reader and in the
            # classifier's original source safety inventory, but they must not
            # prevent use of a receipt for the exact computational form.
            exact_source = [candidate for candidate in source
                if not (isinstance(candidate.get("edit_distance"), (int, float))
                        and candidate["edit_distance"] > 0)]
            machine = token.get("machine") or {}
            receipt = machine.get("receipt") or {}
            basis, receipt_id = "source", None
            if not exact_source:
                if machine.get("machine_candidates") and receipt.get("id"):
                    basis, receipt_id = "machine", receipt["id"]
                else:
                    item["reason"] = "No exact-form source candidates or cached computational receipt are available; nearby spellings are not parses, and no model call was made."
                    continue
            if blocked:
                item.update(status=blocked, reason="Further rankings stopped because the contextual classifier is unavailable or limited.")
                continue
            if output["attempted_occurrences"] >= MAX_TOKEN_OCCURRENCES:
                item.update(status="request_limit", reason="At most three token occurrences are compared per explicit selection; select a narrower span to compare another occurrence.")
                continue
            output["attempted_occurrences"] += 1
            wrapper = OccurrenceProvider(provider, passage, token, result)
            try:
                decision = self.classify_callback(token["text"], passage_id, provider=wrapper,
                    candidate_basis=basis, machine_receipt_id=receipt_id)
                if not isinstance(decision, Mapping):
                    raise GatewayUnavailable("Classifier did not return a decision.")
                decision = deepcopy(dict(decision))
                if wrapper.last_packet is not None:
                    decision["packet"] = wrapper.last_packet
                item.update(status=decision.get("status", "abstained"), decision=decision,
                            ranked_candidates=_ranked_candidates(decision))
            except GatewayLimit as exc:
                blocked = "rate_limited"
                item.update(status=blocked, reason="The contextual classification allowance or concurrency limit has been reached.", retry_after=exc.retry_after)
            except GatewayUnavailable:
                blocked = "unavailable"
                item.update(status=blocked, reason="Jev or its durable gateway is unavailable; source alternatives are unchanged.")
            except Exception as exc:
                # HTTP callback errors may include provider/transport details;
                # expose only safe status information, never raw exception text.
                blocked = "rate_limited" if getattr(exc, "status_code", None) == 429 else "unavailable"
                item.update(status=blocked, reason="Contextual comparison could not complete; source alternatives are unchanged.")
        completed = sum("decision" in item for item in output["items"])
        if completed:
            output["status"] = "complete" if all("decision" in item for item in output["items"]) else "partial"
        elif not output["attempted_occurrences"]:
            output["status"] = "not_available"
        if any(item["status"] == "request_limit" for item in output["items"]):
            output["warnings"].append("Only the first three eligible occurrences were compared. Narrow the selection to inspect later tokens.")
        return output
