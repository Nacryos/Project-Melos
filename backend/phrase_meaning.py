"""Phrase-first display projection; never synthesize a translation from glosses.

Published translations already admitted by the passage lookup may cover a whole
selection only when the selection is the complete source passage. A dependency
tree is a prediction, not a set of coherent alternative English interpretations.
"""
from copy import deepcopy
import unicodedata

from .translation_languages import is_english_translation


def _translation_key(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def phrase_meaning(passage, result):
    selection = result["selection"]
    text = passage["text"]
    start, end = selection["start"], selection["end"]
    words = [token for token in result["tokens"] if token["kind"] == "word"]
    complete = not text[:start].strip() and not text[end:].strip()
    translations = [deepcopy(row) for row in result["context"]["published_translations"]
                    if is_english_translation(row)]
    interpretations, by_text = [], {}
    if complete:
        for row in translations:
            # Excerpts cannot be silently promoted to complete translations.
            translated = row.get("text")
            if not isinstance(translated, str) or not translated.strip():
                continue
            if row.get("parent_id") != passage["id"] or not row.get("record_id"):
                continue
            proof = row.get("pairing_proof") or {}
            if (row.get("scope") != "whole_source_passage"
                    or not isinstance(proof, dict)
                    or proof.get("translation_of") != passage["id"]):
                continue
            # The upstream projector validates source anchors and raw receipts.
            # Do not admit stale projected evidence after the passage changes.
            if passage.get("raw_sha256") and proof.get("parent_raw_sha256") != passage["raw_sha256"]:
                continue
            key = _translation_key(translated)
            if key in by_text:
                by_text[key]["sources"].append(row)
                continue
            item = {
                "id": "published:" + row["record_id"], "text": translated,
                "language": "eng", "evidence_type": "published_translation",
                "selection_aligned": True, "alignment": "whole_source_passage_selected",
                "rank": None, "confidence": None, "sources": [row],
                "explanation": {"status": "unavailable", "note":
                    "This published translation covers the selected source passage; it is not an aligned word-by-word grammatical analysis. The translator may follow a different Greek edition."},
            }
            interpretations.append(item)
            by_text[key] = item

    syntax = result.get("syntax") or {}
    syntax_rows = syntax.get("tokens") or []
    by_id = {row.get("id"): row for row in syntax_rows}
    relationships = []
    if syntax.get("state", syntax.get("status")) == "ready":
        for row in syntax_rows:
            if not row.get("selected") or row.get("prediction_status") == "not_applicable":
                continue
            head = by_id.get(row.get("head"))
            if not head or head.get("prediction_status") == "not_applicable":
                continue
            relationships.append({
                "token_id": row.get("id"), "text": row.get("text"),
                "start": row.get("absolute_start"), "end": row.get("absolute_end"),
                "head_id": head.get("id"), "head_text": head.get("text"),
                "head_start": head.get("absolute_start"), "head_end": head.get("absolute_end"),
                "head_in_selection": bool(head.get("selected")), "relation": row.get("deprel"),
                "evidence_type": "contextual_prediction",
            })
    if interpretations:
        summary = "Published English translation" if len(interpretations) == 1 else "Published English translations"
    elif translations:
        summary = "No English translation is aligned to this selection. A translation of the surrounding passage is available below."
    else:
        summary = "No English translation is currently available for this selection."
    return {
        "status": "available" if interpretations else "unavailable",
        "language": "eng", "scope": "selected_span",
        "selection_kind": "phrase" if len(words) > 1 else "word",
        "summary": summary, "interpretations": interpretations,
        "context_translations": [] if interpretations else translations,
        "relationships": relationships, "ranking_status": "not_ranked",
        "joint_alternatives_status": "unavailable",
        "limitations": [
            "Independent word rankings do not establish a joint reading or rank competing translations.",
            "Dependency relationships are predictions, not verified explanations of a published translation.",
            "Partial-phrase translation generation and verified phrase alignments are not configured.",
        ],
    }
