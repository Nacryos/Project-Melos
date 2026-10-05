"""Bounded corpus-bound span analysis. Predictions never become source rows.

Offsets are over the unchanged stored text. The HTTP boundary accepts UTF-16
offsets for browser selections; every result also carries Python codepoints.
Source lookups are intentionally supplied by the application so publication
checks and evidence receipts remain the same as the existing word reader.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from threading import BoundedSemaphore
import unicodedata

VERSION = 1
MAX_CHARACTERS = 2000
MAX_WORDS = 80
MAX_MACHINE_FETCHES = 3
APOSTROPHES = "'’ʼ᾽"
EDITORIAL = frozenset("[]⟦⟧⟨⟩<>…†‡̣")


class PassageAnalysisError(ValueError):
    def __init__(self, code, message, status_code=422):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def utf16_offset(text, position):
    return len(text[:position].encode("utf-16-le")) // 2


def codepoint_offset(text, position, unit):
    if type(position) is not int or position < 0:
        raise PassageAnalysisError("invalid_offset", "Offsets must be nonnegative integers.")
    if unit == "codepoint":
        if position <= len(text):
            return position
    elif unit == "utf16":
        current = 0
        for index, char in enumerate(text):
            if current == position:
                return index
            current += 2 if ord(char) > 0xFFFF else 1
        if current == position:
            return len(text)
    else:
        raise PassageAnalysisError("invalid_offset_unit", "Use utf16 or codepoint offsets.")
    raise PassageAnalysisError("invalid_offset", "Offset is outside the passage or divides a UTF-16 character.")


def _letter(char):
    return bool(char) and unicodedata.category(char)[0] in "LM"


def tokenize_span(text, start, end):
    """Lossless segments, including spaces and every editorial character."""
    tokens, cursor = [], start
    while cursor < end:
        begin, char = cursor, text[cursor]
        if _letter(char):
            kind = "word"
            cursor += 1
            while cursor < end and (_letter(text[cursor]) or text[cursor] in APOSTROPHES):
                cursor += 1
        elif char.isspace():
            kind = "space"
            cursor += 1
            while cursor < end and text[cursor].isspace():
                cursor += 1
        else:
            kind = "editorial" if char in EDITORIAL else "punctuation"
            cursor += 1
        original = text[begin:cursor]
        partial = kind == "word" and ((begin == start and begin > 0 and
                   (_letter(text[begin - 1]) or text[begin - 1] in APOSTROPHES)) or
                  (cursor == end and cursor < len(text) and
                   (_letter(text[cursor]) or text[cursor] in APOSTROPHES)))
        tokens.append({"id": f"t{len(tokens)}", "text": original, "kind": kind,
                       "start": begin, "end": cursor,
                       "start_utf16": utf16_offset(text, begin), "end_utf16": utf16_offset(text, cursor),
                       "partial_word": bool(partial), "warnings": []})
    # An interruption inside printed wording (α[β]γ, α[…]β) must not become
    # three independently asserted complete words, or an invented repaired one.
    previous_word, only_editorial = None, False
    for token in tokens:
        if token["kind"] == "word":
            if previous_word is not None and only_editorial:
                previous_word["editorial_fragment"] = True
                token["editorial_fragment"] = True
            previous_word, only_editorial = token, False
        elif token["kind"] == "editorial":
            only_editorial = previous_word is not None
        else:
            previous_word, only_editorial = None, False
    return tokens


def lint_syntax(syntax, *, editorial=False):
    """Conditional checks of a prediction, never corrections of Greek verse."""
    warnings = []
    if syntax.get("state", syntax.get("status")) != "ready":
        return {"status": "unavailable", "warnings": warnings}
    tokens = syntax.get("tokens", [])
    by_id = {token.get("id"): token for token in tokens}
    for token in tokens:
        if token.get("prediction_status") == "not_applicable":
            continue
        head = by_id.get(token.get("head"))
        relation = str(token.get("deprel", "")).split(":")[0]
        if head and relation in {"amod", "det"}:
            left, right = token.get("features") or {}, head.get("features") or {}
            for feature in ("Case", "Number", "Gender"):
                a, b = left.get(feature), right.get(feature)
                a = set(a if isinstance(a, list) else str(a).split(",")) if a else set()
                b = set(b if isinstance(b, list) else str(b).split(",")) if b else set()
                if a and b and a.isdisjoint(b):
                    warnings.append({"code": "predicted_agreement_conflict", "token_ids": [token["id"], head["id"]],
                        "severity": "uncertain", "evidence_type": "conditional_model_check",
                        "message": f"If the predicted {relation} attachment and morphology are right, {feature.lower()} differs. Review the attachment, poetic usage, and missing material; this is not a grammatical error finding."})
        if (token.get("head") is not None and not head) or token.get("attachment_status") == "unresolved_nonlexical_head":
            warnings.append({"code": "unresolved_attachment", "token_ids": [token["id"]],
                "severity": "uncertain", "evidence_type": "conditional_model_check",
                "message": "The predicted head is outside this analysis or is editorial/whitespace material; review the attachment and the incomplete text."})
    if editorial:
        warnings.append({"code": "editorial_uncertainty", "token_ids": [], "severity": "uncertain",
            "evidence_type": "conditional_model_check",
            "message": "Editorial marks or uncertain letters occur in this selection. Dependency predictions do not restore missing material."})
    return {"status": "conditional", "warnings": warnings}


def _context(passage):
    translations = deepcopy(passage.get("translation_previews") or [])
    for row in translations:
        row["evidence_type"] = "published_translation"
        row["selection_aligned"] = False
        row["scope_note"] = "Published context for the whole source passage; not an exact translation of this selected span."
    commentary = []
    for row in passage.get("related", []):
        if row.get("kind") in {"commentary", "comment", "scholion", "scholia", "note"} and row.get("parent_id") == passage["id"]:
            commentary.append({**deepcopy(row), "evidence_type": "published_commentary", "scope": "whole_passage", "selection_aligned": False})
    return {"published_translations": translations, "commentary": commentary,
            "translation_scope": "whole_passage", "translation_status": "available" if translations else "unavailable",
            "commentary_status": "available" if commentary else "unavailable",
            "structured_evidence": deepcopy(passage.get("structured_evidence") or {"ready": False, "claims": []}),
            "author_profile": deepcopy(passage.get("author_profile")),
            "dialect_note": "Authorial dialect is context, not proof that each word belongs exclusively to that dialect."}


class PassageAnalysisService:
    def __init__(self, passage_lookup, word_lookup, *, machine_service=None, syntax_provider=None, ranker=None):
        self.passage_lookup, self.word_lookup = passage_lookup, word_lookup
        self.machine_service, self.syntax_provider, self.ranker = machine_service, syntax_provider, ranker
        self._slots = BoundedSemaphore(2)

    def analyze(self, request, *, visitor_id=None, ranker_visitor_id=None):
        if not self._slots.acquire(blocking=False):
            raise PassageAnalysisError("busy", "Passage analysis is busy. Try again shortly.", 429)
        try:
            return self._analyze(request, visitor_id=visitor_id, ranker_visitor_id=ranker_visitor_id)
        finally:
            self._slots.release()

    def _analyze(self, request, *, visitor_id, ranker_visitor_id):
        allowed = {"version", "passage_id", "start", "end", "offset_unit", "selected_text", "rerank", "fetch_machine"}
        if not isinstance(request, dict) or set(request) - allowed:
            raise PassageAnalysisError("invalid_request", "Only corpus identity, exact selection, and analysis flags are accepted.")
        if type(request.get("version", VERSION)) is not int or request.get("version", VERSION) != VERSION:
            raise PassageAnalysisError("unsupported_version", "Unsupported passage analysis version.")
        for flag in ("rerank", "fetch_machine"):
            if type(request.get(flag, False)) is not bool:
                raise PassageAnalysisError("invalid_flag", "Analysis flags must be booleans.")
        passage_id = request.get("passage_id")
        if not isinstance(passage_id, str) or not 1 <= len(passage_id) <= 500:
            raise PassageAnalysisError("invalid_passage_id", "A corpus passage ID is required.")
        selected = request.get("selected_text")
        if not isinstance(selected, str) or not selected or len(selected) > MAX_CHARACTERS:
            raise PassageAnalysisError("invalid_selection", f"Select 1–{MAX_CHARACTERS} characters from the corpus passage.")
        passage = self.passage_lookup(passage_id)
        if not passage:
            raise PassageAnalysisError("passage_not_found", "Passage not found.", 404)
        text = passage.get("text")
        if not isinstance(text, str) or passage.get("language") not in (None, "grc") or passage.get("kind") not in (None, "text"):
            raise PassageAnalysisError("unsupported_passage", "Analysis requires a Greek source text passage.")
        unit = request.get("offset_unit", "utf16")
        start, end = (codepoint_offset(text, request.get(field), unit) for field in ("start", "end"))
        if end <= start or end - start > MAX_CHARACTERS:
            raise PassageAnalysisError("invalid_span", f"Select a forward span of at most {MAX_CHARACTERS} characters.")
        if text[start:end] != selected:
            raise PassageAnalysisError("stale_selection", "Selected text no longer matches the stored passage at these offsets. Reload and select again.", 409)
        tokens = tokenize_span(text, start, end)
        word_count = sum(token["kind"] == "word" for token in tokens)
        if not 1 <= word_count <= MAX_WORDS:
            raise PassageAnalysisError("invalid_word_count", f"Select between 1 and {MAX_WORDS} words.")
        source_cache, machine_cache, fetch_count = {}, {}, 0
        for token in tokens:
            if token["kind"] != "word":
                continue
            form = token["text"]
            if token["partial_word"] or token.get("editorial_fragment"):
                token.update({"source_candidates": [], "contextual_candidates": [],
                              "machine": {"status": "editorial_fragment" if token.get("editorial_fragment") else "partial_word", "machine_candidates": [], "receipt": None}})
                token["warnings"].append("Editorial marks interrupt this printed word; fragments are preserved without constructing a repaired word."
                                         if token.get("editorial_fragment") else
                                         "Selection cuts through a word; select the complete word for morphological alternatives.")
                continue
            if form not in source_cache:
                try:
                    source_cache[form] = self.word_lookup(form, passage_id) or {}
                except Exception:
                    source_cache[form] = {"warnings": ["Source lookup is unavailable for this token."], "status": "unavailable"}
            source = source_cache[form]
            token.update({"source_candidates": deepcopy(source.get("candidates", [])),
                          "contextual_candidates": deepcopy(source.get("contextual_candidates", [])),
                          "structured_evidence": deepcopy(source.get("structured_evidence", {"ready": False, "claims": []})),
                          "source_status": source.get("status", "available"),
                          "candidate_scope": "General-form and passage-level alternatives, not a resolved analysis of this occurrence. Only exact_token_span claim applications bind to this token; ordering is not a probability.",
                          "warnings": list(source.get("warnings", []))})
            for field in ("contextual_supporting_claims", "contextual_unresolved_claim_ids", "parallel_contexts", "lexicon_entries", "lexical_evidence", "quarantined_source_analyses", "context_analysis_status", "analysis_match_status", "match_status"):
                if field in source:
                    token[field] = deepcopy(source[field])
            claims = [*token["structured_evidence"].get("claims", []), *token.get("contextual_supporting_claims", [])]
            token["claim_applications"] = {}
            for claim in claims:
                subject = claim.get("subject") or {}
                scope = "general_source_record"
                if subject.get("passage_id") == passage_id:
                    if type(subject.get("start")) is int and type(subject.get("end")) is int:
                        scope = "exact_token_span" if (subject["start"], subject["end"]) == (token["start"], token["end"]) else "other_passage_span"
                    else:
                        scope = "whole_passage_not_token_aligned"
                elif subject.get("passage_id"):
                    scope = "other_passage"
                token["claim_applications"][claim.get("id", "")] = {"scope": scope, "source_start": subject.get("start"), "source_end": subject.get("end")}
            if form not in machine_cache:
                machine = {"status": "unavailable", "machine_candidates": [], "receipt": None}
                if self.machine_service is not None:
                    try:
                        machine = self.machine_service.analyze(form, visitor_id, fetch=False)
                        if request.get("fetch_machine") and machine.get("status") == "cache_miss":
                            if fetch_count < MAX_MACHINE_FETCHES:
                                fetch_count += 1
                                machine = self.machine_service.analyze(form, visitor_id, fetch=True)
                            else:
                                machine = {**machine, "status": "request_limit", "warnings": ["At most three uncached computational forms are fetched per explicit passage request."]}
                    except Exception:
                        machine["warnings"] = ["Computational morphology is unavailable; source alternatives remain available."]
                machine_cache[form] = machine
            token["machine"] = deepcopy(machine_cache[form])
        syntax = self._syntax(selected, text, start, end)
        editorial = any(char in EDITORIAL for char in (text if syntax.get("scope") == "whole_passage" else selected))
        result = {"version": VERSION, "status": "ok",
            "passage": {**{key: passage.get(key) for key in ("id", "author", "work", "citation", "source", "source_url", "edition", "license")},
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest()},
            "selection": {"text": selected, "start": start, "end": end, "start_utf16": utf16_offset(text, start),
                          "end_utf16": utf16_offset(text, end), "offset_unit": "codepoint"},
            "tokens": tokens, "syntax": syntax, "lint": lint_syntax(syntax, editorial=editorial),
            "context": _context(passage), "ranking": {"status": "not_requested"},
            "limits": {"max_characters": MAX_CHARACTERS, "max_words": MAX_WORDS,
                       "max_machine_fetches": MAX_MACHINE_FETCHES, "machine_fetches": fetch_count},
            "warnings": ["Morphological alternatives and dependency predictions are not verified readings of this occurrence.",
                         "Source lookups are bounded; absence is not evidence of linguistic impossibility."]}
        if request.get("rerank"):
            if self.ranker is None:
                result["ranking"] = {"status": "unavailable", "warnings": ["Context reranking is not configured."]}
            else:
                try:
                    result["ranking"] = self.ranker(deepcopy(result), visitor_id=ranker_visitor_id)
                except Exception:
                    result["ranking"] = {"status": "unavailable", "warnings": ["Context reranking failed; all original alternatives are retained."]}
        return result

    def _syntax(self, selected, full_text, start, selection_end):
        if self.syntax_provider is None:
            return {"status": "unavailable", "state": "unavailable", "tokens": [], "evidence_type": "contextual_prediction", "reason": "Local syntax provider is not configured."}
        try:
            use_full = len(full_text) <= MAX_CHARACTERS and sum(token["kind"] == "word" for token in tokenize_span(full_text, 0, len(full_text))) <= MAX_WORDS
            context, context_start = (full_text, 0) if use_full else (selected, start)
            result = deepcopy(self.syntax_provider.analyze(context))
            result["status"] = result.get("state", result.get("status", "unavailable"))
            result.update({"scope": "whole_passage" if use_full else "selected_span", "context_start": context_start,
                           "context_end": context_start + len(context)})
            if not use_full:
                result.setdefault("warnings", []).append("Only the bounded selection was parsed; attachments to words outside it cannot be resolved.")
            for token in result.get("tokens", []):
                begin, end = token.get("start"), token.get("end")
                if type(begin) is not int or type(end) is not int or not 0 <= begin < end <= len(context) or context[begin:end] != token.get("text"):
                    raise ValueError("Parser offsets did not match the original selection.")
                token.update({"absolute_start": context_start + begin, "absolute_end": context_start + end,
                    "selected": context_start + begin < selection_end and context_start + end > start,
                    "start_utf16": utf16_offset(full_text, context_start + begin), "end_utf16": utf16_offset(full_text, context_start + end)})
            result["evidence_type"] = "contextual_prediction"
            return result
        except Exception as exc:
            return {"status": "unavailable", "state": "unavailable", "tokens": [], "evidence_type": "contextual_prediction",
                    "code": getattr(exc, "code", "provider_error"), "reason": "Local dependency analysis is unavailable or could not preserve source offsets."}
