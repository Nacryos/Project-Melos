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

from .phrase_meaning import phrase_meaning
from .interlinear import candidate_identity, interlinear_reading, join_machine_dictionary, catalog_machine_subentries
from .translation_languages import is_english_translation
from .lacuna_boundaries import annotate_lacuna_boundaries

VERSION = 1
MAX_CHARACTERS = 2000
MAX_WORDS = 80
MAX_MACHINE_FETCHES = 3
MAX_DICTIONARY_LEMMA_LOOKUPS = 24
MAX_MACHINE_SUBENTRY_LOOKUPS = 24


def machine_dictionary_lookup(form, *, machine_lookup, subentry_lookup):
    """Standalone query envelope using the same receipt/catalog proof as spans.

    Offsets describe the query string only, never an occurrence in a poem.
    The caller supplies cache-only machine lookup; no syntax or sense ranking
    is requested and definitions remain under their exact parser hypotheses.
    """
    result = {'version': 1, 'scope': 'standalone_form_query', 'status': 'unavailable',
              'query_form': form, 'tokens': [], 'ranking_status': 'unsupported_source_type'}
    try:
        machine = machine_lookup(form)
        if machine.get('status') != 'ok' or machine.get('form') != form:
            result['status'] = machine.get('status', 'unavailable') if machine.get('form') == form else 'unavailable'
            return result
        length_utf16 = len(form.encode('utf-16-le')) // 2
        token = {'id': 'query:' + hashlib.sha256(form.encode('utf8')).hexdigest(),
                 'text': form, 'kind': 'word', 'start': 0, 'end': len(form),
                 'start_utf16': 0, 'end_utf16': length_utf16,
                 'machine': deepcopy(machine), 'source_candidates': [], 'contextual_candidates': []}
        catalog = {'version': 1, 'ranking_status': 'unsupported_source_type'}
        token['machine_subentries'] = catalog_machine_subentries(catalog, subentry_lookup(deepcopy(token)))
        result.update(status=token['machine_subentries']['status'], tokens=[token],
                      selection={'text': form, 'start': 0, 'end': len(form),
                                 'start_utf16': 0, 'end_utf16': length_utf16},
                      machine_subentry_evidence=catalog)
        result['interlinear'] = interlinear_reading(result)
        return result
    except Exception:
        result.update(status='unavailable', tokens=[],
                      warning='Source-subentry evidence could not be verified; no meaning was inferred.')
        result.pop('machine_subentry_evidence', None)
        result.pop('interlinear', None)
        return result
MAX_EDITORIAL_LOOKUPS = 16
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


RECONSTRUCTION_MARKS = "[]"
UNCERTAIN_MARK = "̣"


def analysis_form(token):
    """The editor's printed reading of a word, used for every lookup.

    Square brackets mark letters the editor supplied; an underdot marks a
    doubtfully read letter. Both are kept verbatim in ``text`` and removed
    only here, so the lookup form is exactly the edition's reading.
    """
    form = token.get("form")
    if form:
        return form
    return printed_reading(token.get("text") or "")


def printed_reading(text):
    stripped = "".join(char for char in unicodedata.normalize("NFD", text)
                       if char not in RECONSTRUCTION_MARKS and char != UNCERTAIN_MARK)
    return unicodedata.normalize("NFC", stripped)


def uncertain_edge_variants(token):
    """Readings of a lacuna-adjacent word without its doubtfully read edge letters.

    ". . ς̣βιότοις̣ . ." may be the end of one word followed by βιότοις; the
    underdotted edge letters are dropped one side at a time and the remainder
    is offered as a labelled query variant, never as the printed reading.
    """
    if not token.get("uncertain_letters") or not token.get("lacuna_boundary_uncertain"):
        return []
    decomposed = unicodedata.normalize("NFD", token.get("text") or "")
    letters = []
    for char in decomposed:
        if unicodedata.category(char).startswith("L"):
            letters.append([char, False])
        elif char == UNCERTAIN_MARK and letters:
            letters[-1][1] = True
        elif unicodedata.category(char).startswith("M") and letters:
            letters[-1][0] += char
    def reading(rows):
        return unicodedata.normalize("NFC", "".join(row[0] for row in rows))
    found = []
    head = 0
    while head < len(letters) and letters[head][1]:
        head += 1
    tail = len(letters)
    while tail > head and letters[tail - 1][1]:
        tail -= 1
    whole = reading(letters)
    note = "Doubtfully read letters at the edge of a damaged word omitted; the remainder read as a complete word"
    options = []
    if head:
        options.append(("leading", reading(letters[head:])))
    if tail < len(letters):
        options.append(("trailing", reading(letters[:tail])))
    if head and tail < len(letters):
        options.append(("both", reading(letters[head:tail])))
    for side, candidate in options:
        if len(candidate) >= 2 and candidate != whole and candidate not in [item["form"] for item in found]:
            found.append({"form": candidate, "rule": "uncertain_edge_letters_dropped_" + side,
                          "tier": "dialect_normalised_query", "note": note})
    return found


def supplied_letters(text):
    """Letters the editor supplied inside square brackets, in printed order."""
    runs, current, inside = [], [], False
    seen_bracket = False
    for char in text:
        if char == "[":
            # Letters before an opening bracket are attested, not supplied.
            inside, seen_bracket, current = True, True, []
        elif char == "]":
            if not seen_bracket and current:
                # The word began inside a lacuna opened on an earlier line.
                runs.append("".join(current))
            elif inside and current:
                runs.append("".join(current))
            current, inside, seen_bracket = [], False, True
        elif inside or not seen_bracket:
            current.append(char)
        else:
            continue
    if inside and current:
        runs.append("".join(current))
    return [run for run in runs if run]


def tokenize_span(text, start, end):
    """Lossless segments, including spaces and every editorial character.

    A printed word interrupted by square brackets (νᾶ̣]σον, Δ[ίος, θύ[μ]ῳ) is one
    word token whose ``form`` is the editor's reading; brackets at the edges of a
    word stay separate editorial tokens.
    """
    tokens, cursor = [], start
    while cursor < end:
        begin, char = cursor, text[cursor]
        # Combining accents without a base letter are source editorial marks,
        # not independently look-up-able words. Marks still attach after letters.
        if unicodedata.category(char).startswith("L") and char not in APOSTROPHES:
            kind = "word"
            cursor += 1
            while cursor < end:
                if _letter(text[cursor]) or text[cursor] in APOSTROPHES:
                    cursor += 1
                    continue
                if text[cursor] in RECONSTRUCTION_MARKS:
                    ahead = cursor
                    while ahead < end and text[ahead] in RECONSTRUCTION_MARKS:
                        ahead += 1
                    if ahead < end and unicodedata.category(text[ahead]).startswith("L") and text[ahead] not in APOSTROPHES:
                        cursor = ahead
                        continue
                break
        elif char.isspace():
            kind = "space"
            cursor += 1
            while cursor < end and text[cursor].isspace():
                cursor += 1
        else:
            kind = "editorial" if char in EDITORIAL or unicodedata.category(char).startswith("M") else "punctuation"
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
        if kind == "word":
            token = tokens[-1]
            token["form"] = printed_reading(original)
            if UNCERTAIN_MARK in unicodedata.normalize("NFD", original):
                token["uncertain_letters"] = True
            opened_before = begin > 0 and text[begin - 1] == "["
            closed_after = cursor < len(text) and text[cursor] == "]"
            supplied = supplied_letters(original)
            if opened_before and "[" not in original:
                # [σον] or [ίος: the whole printed word, up to its first
                # closing bracket, was supplied by the editor.
                head = printed_reading(original.split("]", 1)[0])
                supplied = [head] + [run for run in supplied if run != head]
            elif closed_after and "[" not in original and "]" not in original:
                supplied = [printed_reading(original)]
            if supplied or any(mark in original for mark in RECONSTRUCTION_MARKS):
                token["editorial_reconstruction"] = True
                token["supplied_letters"] = [printed_reading(run) for run in supplied if printed_reading(run)]
                token["supplied_whole_word"] = bool(supplied) and printed_reading("".join(supplied)) == token["form"]
    # An interruption inside printed wording by anything other than brackets
    # (α…β, α†β) is a damaged span; its pieces are preserved, not repaired.
    previous_word, only_editorial = None, False
    for token in tokens:
        if token["kind"] == "word":
            if previous_word is not None and only_editorial:
                previous_word["editorial_fragment"] = True
                token["editorial_fragment"] = True
            previous_word, only_editorial = token, False
        elif token["kind"] == "editorial":
            # Brackets between letters were absorbed into the word above, so an
            # editorial run here is a lacuna or damage sign (α[…]β, α†β).
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
            "message": "Editorial marks or uncertain letters occur in the analyzed source context. Dependency predictions do not restore missing material."})
    return {"status": "conditional", "warnings": warnings}


def _context(passage):
    translations = [deepcopy(row) for row in (passage.get("translation_previews") or [])
                    if is_english_translation(row) and row.get("record_id")
                    and row.get("parent_id") == passage["id"]]
    for row in translations:
        row["evidence_type"] = "published_translation"
        row["selection_aligned"] = False
        row["scope_note"] = "Published context for the whole source passage; not an exact translation of this selected span."
    commentary = []
    for row in passage.get("related", []):
        if row.get("kind") in {"commentary", "comment", "scholion", "scholia", "note"} and row.get("parent_id") == passage["id"]:
            commentary.append({**deepcopy(row), "evidence_type": "published_commentary", "scope": "whole_passage", "selection_aligned": False})
    return {"published_translations": translations, "commentary": commentary,
            "published_commentary": deepcopy(passage.get("published_commentary")),
            "translation_comparisons": deepcopy(passage.get("translation_comparisons")),
            "translation_scope": "whole_passage", "translation_status": "available" if translations else "unavailable",
            "commentary_status": "available" if commentary else "unavailable",
            "structured_evidence": deepcopy(passage.get("structured_evidence") or {"ready": False, "claims": []}),
            "author_profile": deepcopy(passage.get("author_profile")),
            "dialect_note": "Authorial dialect is context, not proof that each word belongs exclusively to that dialect."}


class PassageAnalysisService:
    def __init__(self, passage_lookup, word_lookup, *, machine_service=None, syntax_provider=None, ranker=None, sense_ranker=None,
                 machine_subentry_lookup=None):
        self.passage_lookup, self.word_lookup = passage_lookup, word_lookup
        self.machine_service, self.syntax_provider, self.ranker = machine_service, syntax_provider, ranker
        self.sense_ranker = sense_ranker
        # Explicit deployment dependency only. The callback must wrap the
        # approved resolver with a trusted cache-only receipt loader.
        self.machine_subentry_lookup = machine_subentry_lookup
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
        # The source's freshly verified identity, not a request flag or an
        # attached commentary status, opts in to critical dot-run handling.
        # Spaced dots are not universally physical lacunae in arbitrary prose.
        boundary_policy = {"status": "not_applicable"}
        if passage.get("source") == "campbell_assignment":
            from .edition_commentary import for_passage as approved_commentary
            approval = approved_commentary(passage)
            if approval and approval.get("status") == "available":
                tokens = annotate_lacuna_boundaries(text, tokens, source_critical=True)
                boundary_policy = {"status": "applied", "basis": "approved_critical_edition_dot_notation",
                    "source_pdf_sha256": approval["source_pdf_sha256"],
                    "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "scope_note": "Dot adjacency leaves a word boundary uncertain; it does not prove an incomplete or invalid word."}
                for token in tokens:
                    if token.get("lacuna_boundary_uncertain"):
                        token.update(word_attestation=False, occurrence_verified=False,
                                     analysis_scope="conditional_on_word_boundary")
            else:
                boundary_policy = {"status": "source_unverified",
                    "reason": "Approved Campbell source identity could not be revalidated; no dot-boundary annotation was inferred."}
        word_count = sum(token["kind"] == "word" for token in tokens)
        if not 1 <= word_count <= MAX_WORDS:
            raise PassageAnalysisError("invalid_word_count", f"Select between 1 and {MAX_WORDS} words.")
        source_cache, machine_cache, fetch_count = {}, {}, 0
        dictionary_cache = {}
        subentry_cache, subentry_catalog = {}, {'version': 1, 'ranking_status': 'unsupported_source_type'}

        def subentry_lookup(token):
            if token['machine'].get('status') != 'ok':
                return {'status': 'machine_unavailable', 'candidate_refs': []}
            form = analysis_form(token)
            if form not in subentry_cache:
                if len(subentry_cache) >= MAX_MACHINE_SUBENTRY_LOOKUPS:
                    return {'status': 'request_limit', 'candidate_refs': [],
                            'limit': MAX_MACHINE_SUBENTRY_LOOKUPS}
                try:
                    payload = self.machine_subentry_lookup(deepcopy(token))
                    if not isinstance(payload, dict) or not payload.get('inventory_sha256'):
                        raise ValueError('Unverified machine-subentry callback result')
                    subentry_cache[form] = catalog_machine_subentries(subentry_catalog, payload)
                except Exception:
                    subentry_cache[form] = {'status': 'unavailable', 'candidate_refs': [],
                        'warning': 'Source-subentry evidence could not be verified; no meaning was inferred.'}
            return deepcopy(subentry_cache[form])

        def dictionary_lookup(lemma):
            key = unicodedata.normalize('NFC', lemma).casefold()
            if key not in dictionary_cache:
                if len(dictionary_cache) >= MAX_DICTIONARY_LEMMA_LOOKUPS:
                    return {'dictionary_lookup_status': 'request_limit'}
                try:
                    # Only dictionary records are copied from this bare-headword
                    # lookup, never another occurrence's morphological claims.
                    dictionary_cache[key] = self.word_lookup(lemma, '') or {}
                except Exception:
                    dictionary_cache[key] = {'dictionary_lookup_status': 'unavailable'}
            return dictionary_cache[key]
        for token in tokens:
            if token["kind"] != "word":
                continue
            form = analysis_form(token)
            if token["partial_word"] or token.get("editorial_fragment"):
                token.update({"source_candidates": [], "contextual_candidates": [],
                              "machine": {"status": "editorial_fragment" if token.get("editorial_fragment") else "partial_word", "machine_candidates": [], "receipt": None}})
                token["warnings"].append("Editorial marks interrupt this printed word; fragments are preserved without constructing a repaired word."
                                         if token.get("editorial_fragment") else
                                         "Selection cuts through a word; select the complete word for morphological alternatives.")
                continue
            reading_notes = []
            if token.get("editorial_reconstruction"):
                reading_notes.append(f"Letters in square brackets were supplied by the editor; the analysis follows the printed reading {form}.")
            if token.get("uncertain_letters"):
                reading_notes.append("Underdots mark doubtfully read letters; the analysis follows the printed reading.")
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
                          "warnings": [*reading_notes, *source.get("warnings", [])]})
            if token.get("lacuna_boundary_uncertain"):
                token["candidate_scope"] = "Literal-string alternatives conditional on a complete word boundary; neither an intact attestation nor a resolved occurrence meaning."
                token["warnings"].append("Printed dots leave this word boundary uncertain. Literal dictionary alternatives and parser hypotheses remain available conditionally; no missing letters or invalidity are inferred.")
            for field in ("contextual_supporting_claims", "contextual_unresolved_claim_ids", "parallel_contexts", "lexicon_entries", "lexical_evidence", "lexical_variants", "dictionary_crossreferences", "lexical_variant_supporting_claims", "lexical_variant_status", "linked_dictionary", "linked_dictionary_status", "quarantined_source_analyses", "context_analysis_status", "analysis_match_status", "match_status"):
                if field in source:
                    token[field] = deepcopy(source[field])
            claims = [*token["structured_evidence"].get("claims", []), *token.get("contextual_supporting_claims", []), *token.get("lexical_variant_supporting_claims", [])]
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
                if token.get("lacuna_boundary_uncertain"):
                    token["claim_applications"][claim.get("id", "")].update(
                        word_boundary_status="uncertain", word_attestation=False,
                        application_scope="conditional_literal_string")
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
                from .aeolic_variants import LEXICAL
                if (machine.get("status") == "no_analyses" or (form in LEXICAL and machine.get("status") == "ok")) and self.machine_service is not None:
                    # The exact printed form is unknown to the parser. Query a few
                    # labelled Aeolic spelling normalisations; each resulting parse
                    # carries its rule and never outranks an exact-form analysis.
                    machine = {**machine, "machine_candidates": list(machine.get("machine_candidates") or []),
                               "normalised_queries": []}
                    from .aeolic_variants import variants
                    for variant in [*variants(form), *uncertain_edge_variants(token)]:
                        try:
                            result = self.machine_service.analyze(variant["form"], visitor_id, fetch=False)
                            if (result.get("status") == "cache_miss" and request.get("fetch_machine")
                                    and fetch_count < MAX_MACHINE_FETCHES):
                                fetch_count += 1
                                result = self.machine_service.analyze(variant["form"], visitor_id, fetch=True)
                        except Exception:
                            result = {"status": "unavailable", "machine_candidates": []}
                        entry = {**variant, "status": result.get("status"),
                                 "candidate_count": len(result.get("machine_candidates") or []),
                                 "receipt_id": (result.get("receipt") or {}).get("id")}
                        machine["normalised_queries"].append(entry)
                        for candidate in result.get("machine_candidates") or []:
                            machine["machine_candidates"].append({
                                **candidate, "basis": "machine_analysis", "candidate_kind": "machine_analysis",
                                "normalised_query": variant["form"], "normalisation_rule": variant["rule"],
                                "normalisation_note": variant["note"], "tier": variant["tier"]})
                    if machine["machine_candidates"] and machine.get("status") != "ok":
                        machine["status"] = "ok_normalised"
                        machine.setdefault("warnings", []).append(
                            "No analysis of the exact printed form; the parses shown come from labelled Aeolic spelling normalisations.")
                machine_cache[form] = machine
            token["machine"] = deepcopy(machine_cache[form])
            if token.get("lacuna_boundary_uncertain"):
                token["machine"].update(occurrence_scope="conditional_on_word_boundary",
                                        word_attestation=False, occurrence_verified=False)
            if self.machine_subentry_lookup is not None:
                token['machine_subentries'] = subentry_lookup(token)
            join_machine_dictionary(token, dictionary_lookup)
            # Give legacy rows stable transport identities, without promoting
            # those generated IDs into evidence of source provenance.
            for candidate in [*token["source_candidates"], *token["contextual_candidates"],
                              *token["machine"].get("machine_candidates", [])]:
                if not candidate.get("id"):
                    candidate["id"] = candidate_identity(candidate)
                    candidate["generated_candidate_identity"] = True
        syntax = self._syntax(selected, text, start, end)
        self._last_tier(tokens, syntax, text)
        syntax_text = text[syntax["context_start"]:syntax["context_end"]] if syntax.get("scope") in {"whole_passage", "bounded_context_window"} else selected
        editorial = any(char in EDITORIAL for char in syntax_text) or any(token.get("lacuna_boundary_uncertain") for token in tokens)
        result = {"version": VERSION, "status": "ok",
            "passage": {**{key: passage.get(key) for key in ("id", "author", "work", "citation", "source", "source_url", "edition", "license")},
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest()},
            "selection": {"text": selected, "start": start, "end": end, "start_utf16": utf16_offset(text, start),
                          "end_utf16": utf16_offset(text, end), "offset_unit": "codepoint"},
            "tokens": tokens, "syntax": syntax, "lint": lint_syntax(syntax, editorial=editorial),
            "lacuna_boundary_policy": boundary_policy,
            "context": _context(passage), "ranking": {"status": "not_requested"},
            "limits": {"max_characters": MAX_CHARACTERS, "max_words": MAX_WORDS,
                       "max_machine_fetches": MAX_MACHINE_FETCHES, "machine_fetches": fetch_count,
                       "max_dictionary_lemma_lookups": MAX_DICTIONARY_LEMMA_LOOKUPS,
                       "dictionary_lemma_lookups": len(dictionary_cache)},
            "warnings": ["Morphological alternatives and dependency predictions are not verified readings of this occurrence.",
                         "Source lookups are bounded; absence is not evidence of linguistic impossibility."]}
        if self.machine_subentry_lookup is not None:
            result['machine_subentry_evidence'] = subentry_catalog
            result['limits'].update(max_machine_subentry_lookups=MAX_MACHINE_SUBENTRY_LOOKUPS,
                                    machine_subentry_lookups=len(subentry_cache))
        if request.get("rerank"):
            if self.ranker is None:
                result["ranking"] = {"status": "unavailable", "warnings": ["Context reranking is not configured."]}
            else:
                try:
                    result["ranking"] = self.ranker(deepcopy(result), visitor_id=ranker_visitor_id)
                except Exception:
                    result["ranking"] = {"status": "unavailable", "warnings": ["Context reranking failed; all original alternatives are retained."]}
        result["meaning"] = phrase_meaning(passage, result)
        result["interlinear"] = interlinear_reading(result)
        result["sense_ranking"] = {"status": "not_requested"}
        if request.get('rerank') and self.sense_ranker is not None:
            from .sense_ranker import apply_sense_ranking
            try:
                result['sense_ranking'] = self.sense_ranker(deepcopy(result), visitor_id=ranker_visitor_id)
                apply_sense_ranking(result['interlinear'], result['sense_ranking'], source_result=result)
            except Exception:
                result['sense_ranking'] = {'status': 'unavailable', 'warnings': ['Sense comparison failed; literal dictionary alternatives remain available.']}
        # Re-derive conditional printed-letter projections from the exact
        # accepted poem only after all rankers have run. This separate reader
        # result never becomes a raw token, source claim, or model packet.
        if passage.get('source') == 'campbell_assignment' and passage.get('kind') == 'text' and passage.get('language') == 'grc':
            commentary = passage.get('published_commentary') or {}
            if isinstance(commentary, dict) and commentary.get('status') == 'available':
                try:
                    from .editorial_analysis import analyze_editorial_readings
                    result['editorial_analysis'] = analyze_editorial_readings(
                        passage, start, end, self.word_lookup, max_lookups=MAX_EDITORIAL_LOOKUPS)
                except (ImportError,OSError,RuntimeError,ValueError,TypeError,KeyError):
                    result['editorial_analysis'] = {'version':1,'status':'unavailable','rows':[],
                        'selection_expansion_hints':[],
                        'reason':'Conditional editorial analysis could not verify its source projection.'}
            else:
                result['editorial_analysis'] = {'version':1,'status':'unavailable','rows':[],
                    'selection_expansion_hints':[],
                    'reason':'Approved Campbell source identity is unavailable.'}
        return result

    @staticmethod
    def _last_tier(tokens, syntax, text=""):
        """Ending-based analyses for unrecognised words; damaged-piece labels.

        Runs after the lexicon, parser and normalisation tiers. A word that no
        source attests and no parser knows gets labelled ending-pattern analyses
        (never a lemma or a gloss). Letters surviving beside a lacuna that do
        not form a word are labelled a damaged piece rather than parsed.
        """
        from .interlinear import _exact as exact_candidate, canonical_features
        from .pattern_morphology import pattern_candidates
        ready = syntax.get("state", syntax.get("status")) == "ready"
        rows = syntax.get("tokens") or [] if ready else []
        by_span = {(row.get("absolute_start"), row.get("absolute_end")): row
                   for row in rows if row.get("prediction_status") != "not_applicable"}
        for token in tokens:
            if token.get("kind") != "word" or token.get("partial_word") or token.get("editorial_fragment"):
                continue
            form = analysis_form(token)
            letters = sum(1 for char in unicodedata.normalize("NFD", form) if unicodedata.category(char).startswith("L"))
            machine = token.get("machine") or {}
            has_machine = bool(machine.get("machine_candidates"))
            # For a short run of letters beside a lacuna only an analysis of the
            # exact printed letters counts; a normalised spelling of one or two
            # surviving letters (ἀ → ἁ) is not evidence of a word.
            has_exact_machine = any(not row.get("normalised_query") and row.get("candidate_kind") != "pattern_analysis"
                                    for row in machine.get("machine_candidates") or [])
            source_rows = [row for row in [*(token.get("source_candidates") or []), *(token.get("contextual_candidates") or [])]
                           if exact_candidate(row, token)]
            has_source = bool(source_rows)
            # A bare headword match (the letter α as a dictionary entry) is not
            # a grammatical analysis of one or two surviving letters.
            has_source_parse = any(canonical_features(row) for row in source_rows)
            exact_identities = {(row.get("lemma"), tuple(sorted(canonical_features(row).items())))
                                for row in machine.get("machine_candidates") or []
                                if not row.get("normalised_query") and row.get("candidate_kind") != "pattern_analysis"}
            # Two surviving letters beside a lacuna count as a word only when
            # the parser gives them exactly one reading (ις → ἴς); several
            # readings of a two-letter scrap are not evidence of any of them.
            source_identities = {(row.get("lemma"), tuple(sorted(canonical_features(row).items())))
                                 for row in source_rows if canonical_features(row)}
            unique_scrap_reading = (len(exact_identities) == 1 and len(source_identities) <= 1) or \
                                   (not exact_identities and len(source_identities) == 1)
            if token.get("lacuna_boundary_uncertain") and (letters <= 1 or (letters == 2 and not unique_scrap_reading)):
                token["damaged_piece"] = True
                token["warnings"].append("Surviving letters beside a lacuna, not a complete word; no analysis is asserted.")
                continue
            if has_machine or has_source:
                continue
            if token.get("lacuna_boundary_uncertain"):
                token["damaged_piece"] = True
                token["warnings"].append("Surviving letters beside a lacuna that no analysis fits; not a complete word.")
                continue
            predicted = by_span.get((token["start"], token["end"])) or by_span.get((token["start"], token["end"] - 1))
            candidates = pattern_candidates(form, predicted.get("upos") if predicted else None)
            if candidates:
                for candidate in candidates:
                    candidate["id"] = candidate_identity(candidate)
                token["machine"] = {**machine, "status": "ok_pattern", "machine_candidates": candidates,
                                    "warnings": [*(machine.get("warnings") or []),
                                                 "No dictionary or parser used here knows this word; the analyses shown read only its ending."]}
                token["pattern_analysis"] = {"status": "ending_pattern_only", "ending": candidates[0]["pattern_ending"],
                                             "candidate_count": len(candidates)}
            elif token.get("lacuna_boundary_uncertain"):
                token["damaged_piece"] = True
                token["warnings"].append("Surviving letters beside a lacuna that no analysis fits; not a complete word.")

    def _syntax(self, selected, full_text, start, selection_end):
        if self.syntax_provider is None:
            return {"status": "unavailable", "state": "unavailable", "tokens": [], "evidence_type": "contextual_prediction", "reason": "Local syntax provider is not configured."}
        from .syntax_context import project_syntax_tokens, syntax_context_window
        try:
            window = syntax_context_window(full_text, start, selection_end,
                                           max_words=MAX_WORDS, max_characters=MAX_CHARACTERS)
            if full_text[start:selection_end] != selected:
                raise ValueError("Selected source text does not match its offsets")
        except (ValueError, TypeError):
            return {"status": "unavailable", "state": "unavailable", "tokens": [], "evidence_type": "contextual_prediction",
                    "code": "context_window_invalid", "reason": "The exact source selection could not fit a valid bounded syntax context."}
        try:
            result = deepcopy(self.syntax_provider.analyze(window["text"]))
            result["status"] = result.get("state", result.get("status", "unavailable"))
            result.update({key: window[key] for key in ("scope", "context_start", "context_end",
                           "context_start_utf16", "context_end_utf16", "partial_start_word", "partial_end_word")})
            result["context_strategy"] = window["strategy"]
            result.setdefault("warnings", []).extend(window["warnings"])
            result["tokens"] = project_syntax_tokens(result.get("tokens", []), window, full_text)
            result["evidence_type"] = "contextual_prediction"
            return result
        except Exception as exc:
            return {"status": "unavailable", "state": "unavailable", "tokens": [], "evidence_type": "contextual_prediction",
                    "code": getattr(exc, "code", "provider_error"), "reason": "Local dependency analysis is unavailable or could not preserve source offsets."}
