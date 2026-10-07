"""Offline acceptance map from saved receipts; never a semantic gold benchmark.

No network, parser execution, lookup, ranking, or source mutation. Literal Greek
and English fields are copied only from accepted records and saved API receipts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.editorial_readings import editorial_readings
from backend.passage_analysis import tokenize_span


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def proof(path):
    path = Path(path)
    return {"path": path.as_posix(), "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}


def compact_sense(sense):
    return {k: sense[k] for k in ("id", "text", "entry_id", "source", "source_url", "source_locator") if k in sense}


def receipt(path, sources):
    data = read(path)
    assert data["http_status"] == 200
    raw = (ROOT / path).with_suffix(".body")
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == data["raw_body_sha256"]
    request, body = data["request"], data["body"]
    assert request["base"] == "https://greeklyric.com"
    payload = request["payload"]
    assert payload["rerank"] is False and payload["fetch_machine"] is False
    source = sources[payload["passage_id"]]
    assert source["text"][payload["start"]:payload["end"]] == payload["selected_text"]
    return data, body


def main():
    source_path = "runtime/campbell-assignment/campbell_assignment.jsonl"
    sources = {r["id"]: r for r in map(json.loads, (ROOT / source_path).read_text(encoding="utf-8").splitlines())}
    h_path, i_path = "runtime/lexical-release-h/live-verify.json", "runtime/lexical-release-i/live-verify.json"
    h, i = read(h_path), read(i_path)
    assert h["source_artifact_sha256"] == proof(source_path)["sha256"]
    records = []
    for source in sources.values():
        words = [t for t in tokenize_span(source["text"], 0, len(source["text"])) if t["kind"] == "word"]
        editorial = editorial_readings(source)
        source_hash = hashlib.sha256(source["text"].encode()).hexdigest()
        assert source_hash == h["public_sources"][source["id"]]["text_sha256"]
        records.append({"id": source["id"], "source_text_sha256": source_hash,
                        "tokenizer_segments": len(words),
                        "editorial_diagnostic_rows": len(editorial["rows"]),
                        "eligible_conditional_editorial_words": editorial["lookup_eligible"],
                        "uncertain_projectable_words": editorial["uncertain_projectable"],
                        "commentary_paragraphs": h["public_sources"][source["id"]]["commentary_paragraphs"],
                        "whole_poem_other_edition_comparisons": h["public_sources"][source["id"]]["comparison_count"]})

    context_path = "runtime/lexical-release-h/live-context/report.json"
    context = read(context_path)
    cases = []
    for result in context["results"]:
        path = "runtime/lexical-release-h/live-context/receipts/" + result["receipt"]
        data, body = receipt(path, sources)
        token = next(t for t in body["tokens"] if t["kind"] == "word")
        display = next(t for t in body["interlinear"]["readings"][0]["tokens"] if t["kind"] == "word")
        linked = token.get("linked_dictionary") or {}
        variants = [{"lemma": v.get("lemma"), "dictionary_pos": v.get("dictionary_pos"),
                     "scope": v.get("scope"), "claim_ids": v.get("claim_ids"),
                     "literal_senses": [s for s in v.get("entry_senses", [])]} for v in token.get("lexical_variants", [])]
        paths = [{"candidate_id": c.get("candidate_id"), "lemma": c.get("lemma"),
                  "features": c.get("features"), "parse_short": c.get("parse_short"),
                  "source_entry_id": c.get("linked_path", {}).get("source_entry_id"),
                  "target_entry_id": c.get("linked_path", {}).get("target_entry_id"),
                  "literal_senses": [compact_sense(s) for s in c.get("senses", [])]}
                 for c in linked.get("candidates", [])]
        cases.append({"form": token["text"], "passage_id": result["passage_id"],
                      "start": token["start"], "end": token["end"], "receipt": proof(path),
                      "recorded_at_unix": data["recorded_at_unix"],
                      "display": {k: display.get(k) for k in ("lemma", "features", "parse_short", "status", "selection_basis", "gloss", "syntax_conflict")},
                      "literal_source_variants": variants, "linked_dictionary_paths": paths,
                      "candidate_meanings_count": len(display.get("candidate_meanings", [])),
                      "commentary_paragraph_count": len(body["context"]["published_commentary"].get("paragraphs", [])),
                      "relevant_commentary_excerpt": [p for p in body["context"]["published_commentary"].get("paragraphs", [])
                                                       if len(cases) == 4 and p.get("ordinal") == 7],
                      "syntax_predictions_not_verified": result["selected_predictions"],
                      "context_scope": result["context_scope"],
                      "meaning_status": body["meaning"]["status"],
                      "meaning_limitations": body["meaning"].get("limitations", []),
                      "translation_comparison_contract": {k: v for k, v in body["context"]["translation_comparisons"].items() if k != "translation_comparisons"}})

    # G provides the freshest complete editorial replay. Keep it historical:
    # H changed interlinear behavior; I is transport-only. Never relabel G as H.
    g_path = "runtime/lexical-release-g/live-editorial/report.json"
    g = read(g_path)
    editorial_rows = {}
    for item in g["results"]:
        path = "runtime/lexical-release-g/live-editorial/receipts/" + item["receipt"]
        _, body = receipt(path, sources)
        for row in body.get("editorial_analysis", {}).get("rows", []):
            if not row.get("lookup_eligible"):
                continue
            key = (item["passage_id"], row["start"], row["end"])
            analysis = row.get("analysis", {})
            editorial_rows[key] = {"passage_id": key[0], "start": key[1], "end": key[2],
                                   "original_text": row["original_text"], "projected_text": row["projected_text"],
                                   "historical_g_status": analysis.get("status"),
                                   "candidate_count": analysis.get("candidate_count"),
                                   "candidates_with_parse_fields": analysis.get("candidates_with_parse_fields"),
                                   "candidates_with_literal_meanings": analysis.get("candidates_with_literal_meanings"),
                                   "receipt": proof(path), "current_h_i_lookup_rechecked": False}

    tense_path = "runtime/lexical-release-h/live-tense/report.json"
    tense = read(tense_path)
    staged = read("runtime/alcaeus-morpheus-maintenance/subentry-integration-response.json")
    staged_subentries = staged.get("machine_subentry_evidence", {}).get("subentries", {})
    staged_meanings = [{"id": key, "literal_senses": [compact_sense(s) for s in value.get("source_subentry", {}).get("dictionary_senses", [])]}
                       for key, value in staged_subentries.items()]
    report = {
        "version": 1, "scope": "Saved production acceptance and gap map, not a philological accuracy score",
        "offline_only": True, "new_http_calls": 0, "paid_calls": 0, "parser_calls": 0,
        "live_backend_id": i["live_id"], "scholarly_baseline_backend_id": h["live_container_id"],
        "release_evidence": [proof(h_path), proof(i_path)],
        "freshness": {"latest_backend": "I: negotiated compression only; H scholarly behavior retained",
                      "latest_full_occurrence_audit": "F: historical only, not current acceptance counts",
                      "current_h_unique_selected_words": len(cases),
                      "current_full_word_coverage_known": False,
                      "reader_i_behavior": "No renderer semantic-accuracy inference from backend receipts"},
        "source_artifact": proof(source_path), "records": records,
        "acceptance_limits": [
            "Tokenizer segments are not whole orthographic words or verified readings.",
            "No selected gloss in rerank=false receipts is not absence of source English alternatives.",
            "Source morphology and dictionary-entry meanings do not establish occurrence correctness.",
            "Five full English comparisons and 88 Campbell commentary paragraphs are available; comparisons are other-edition whole-poem, non-aligned, and not model eligible.",
            "Partial-phrase translation generation and verified phrase alignments are not configured.",
            "Open lacunae, whitespace-spanning brackets and two uncertainty-flagged projections are not eligible for invented completion."],
        "current_h_targeted_cases": cases,
        "tense_acceptance": {"form": tense["form"], "parse_short": tense["interlinear"]["parse_short"],
                             "complete_source_senses": tense["interlinear"]["complete_source_senses"],
                             "literal_compact_meanings": [{k: m.get(k) for k in ("text", "source", "sense_id")} for m in tense["compact_meanings"]],
                             "receipt": proof(tense_path)},
        "editorial_historical_g": {"scope": "Conditional source-backed lookup availability, not current H/I semantic verification",
                                    "report": proof(g_path), "counts": g["totals"],
                                    "eligible_rows": list(editorial_rows.values())},
        "not_deployed_evidence": [{"path": "runtime/alcaeus-morpheus-maintenance/subentry-integration-response.json",
                                   "status": "local next-release fixture; not current production acceptance",
                                   "source_selection": staged["selection"],
                                   "source_passage_id": staged["passage"]["id"],
                                   "literal_subentry_meanings": staged_meanings,
                                   "proof": proof("runtime/alcaeus-morpheus-maintenance/subentry-integration-response.json")}],
        "prioritized_gaps": [
            {"priority": 1, "case_index": 4, "category": "contextual_dictionary_path_selection",
             "action": "Review selected adjective lemma against the distinct noun/cubit source path and Campbell commentary; current source inventory already contains alternatives. Do not certify the selected lemma merely from syntactic compatibility."},
            {"priority": 1, "case_indices": [1, 2], "category": "lexical_meaning_visible_but_complete_parse_unavailable",
             "action": "Retain exact lexical-variant English as source alternatives while resolving the dictionary/syntax lemma conflict independently. Entry POS does not justify inventing complete inflectional features."},
            {"priority": 1, "category": "machine_lemma_subentry_display_not_deployed",
             "evidence": "not_deployed_evidence[0]", "action": "Complete independent source-binding release for the staged cached-parser lemma/subentry connection; keep dictionary English separate from contextual selection and raw-form attestation."},
            {"priority": 2, "case_index": 0, "category": "polysemy_and_source_gender_display",
             "action": "Source-linked noun paths already carry masculine gender and English alternatives; selected row shows only case/number and no contextual gloss. Preserve political-collective ambiguity rather than labeling English entirely missing."},
            {"priority": 2, "category": "conditional_editorial_lookup_gaps",
             "historical_g_unavailable_row_indices": [index for index, r in enumerate(editorial_rows.values()) if r["historical_g_status"] == "unavailable"],
             "action": "Re-evaluate these exact eligible projections offline using the frozen current bundle before fresh API requests. Source-backed alternatives only; no fuzzy form repair or missing-letter invention."},
            {"priority": 2, "category": "phrase_translation_alignment",
             "action": "Full other-edition English comparisons are available for all five, but none establishes exact selected phrase or word alignment. The current API explicitly lacks verified phrase alignment/generation."},
            {"priority": 3, "case_index": 3, "category": "already_improved_tense_regression_guard",
             "action": "Preserve source aorist morphology and tense-scoped dictionary alternatives; do not regress to generic Past or present-only senses. No selected gloss in no-rerank mode is not itself a defect."},
        ],
        "next_minimal_measurement": {"priority": "Use cached offline replay against the frozen live H/I module bundle first; do not repeat whole-poem HTTP.",
                                     "if_unanswerable": "One rerank=false, fetch_machine=false bounded source-word request for the exact unresolved case after its change; preserve receipt and offsets.",
                                     "not_authorized_by_this_report": "Fresh paid ranking, parser fetches, source edits or broad production sweeps."},
    }
    output = ROOT / "runtime/alcaeus-occurrences/current-h-reader-i-gap-map.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "records": len(records), "h_word_cases": len(cases), "historical_g_editorial_words": len(editorial_rows)}, indent=2))


if __name__ == "__main__":
    main()
