"""Read-only source inventory for a saved assignment QA report.

This is diagnostics, not a morphology dataset. Matches in dictionary prose
are never promoted to parses or lemma links. No network/model calls occur.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.morphology import normalize
from backend.passage_analysis import tokenize_span


def nfc(value):
    return unicodedata.normalize("NFC", value)


def passage_occurrences(records):
    result = {}
    for record in records:
        for token in tokenize_span(record["text"], 0, len(record["text"])):
            if token["kind"] != "word":
                continue
            result.setdefault(nfc(token["text"]), []).append({
                "passage_id": record["id"],
                "start": token["start"], "end": token["end"],
                "editorial_fragment": bool(token.get("editorial_fragment")),
                "partial_word": bool(token.get("partial_word")),
            })
    return result


def wiktionary_matches(connection, form):
    rows = connection.execute(
        "SELECT e.record_json,k.kind,k.form_index FROM lookup_keys k "
        "JOIN entries e ON e.id=k.entry_id WHERE k.key=?", (normalize(form),)
    )
    matches = []
    for raw, kind, index in rows:
        record = json.loads(raw)
        entry = record["entry"]
        item = entry["forms"][index] if kind == "listed_form" else {"form": entry["word"]}
        matches.append({
            "id": record["id"], "headword": entry["word"], "kind": kind,
            "literal_nfc_match": nfc(item.get("form", "")) == nfc(form),
            "listed_form": item, "pos": entry.get("pos"),
            "senses": entry.get("senses", []),
            "raw_path": record.get("raw_path"), "raw_line": record.get("raw_line"),
            "raw_line_sha256": record.get("raw_line_sha256"),
        })
    return matches


def audit(report_path, source_path, database):
    report = json.loads(report_path.read_text(encoding="utf8"))
    records = [json.loads(line) for line in source_path.read_text(encoding="utf8").splitlines()]
    occurrences = passage_occurrences(records)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    gaps = []
    for row in report["word_lookups"]:
        if row.get("exact_parse_count"):
            continue
        form = row["form"]
        seen = occurrences.get(nfc(form), [])
        intact = [occ for occ in seen if not occ["editorial_fragment"] and not occ["partial_word"]]
        gaps.append({"form": form, "occurrences": seen,
                     "has_backend_unflagged_occurrence": bool(intact),
                     "completeness_note": "Backend token flags only; spaced lacunae may leave isolated traces unflagged. Not a certification of complete words.",
                     "saved_dictionary_preview_entries": row.get("dictionary_preview_entries"),
                     "wiktionary_source_matches": wiktionary_matches(connection, form)})
    connection.close()
    return {
        "scope": "diagnostic source inventory; not proposed scholarly annotations",
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "lookup_segments": len(report["word_lookups"]),
        "unparsed_segments": len(gaps),
        "unparsed_with_backend_unflagged_occurrence": sum(row["has_backend_unflagged_occurrence"] for row in gaps),
        "unparsed_with_literal_wiktionary_match": sum(any(m["literal_nfc_match"] for m in row["wiktionary_source_matches"]) for row in gaps),
        "gaps": gaps,
    }


def audit_occurrence_variants(path):
    """Compare isolated source projections with saved live occurrence output.

    This is a local counterfactual availability check, not a fresh HTTP test
    or an assessment of whether a dictionary sense suits its poetic context.
    """
    from backend.evidence import EvidenceIndex
    from backend.lexical_variants import lookup_variants
    records = json.loads(path.read_text(encoding="utf8"))
    index = EvidenceIndex()
    cache, changes = {}, []
    for record in records:
        if record.get("editorial_fragment") or record.get("partial_word"):
            continue
        form = record["text"]
        if form not in cache:
            cache[form] = lookup_variants(form, index)
        projection = cache[form]
        if not projection["lexical_variants"] and not projection["dictionary_crossreferences"]:
            continue
        changes.append({
            "occurrence_id": record["occurrence_id"], "form": form,
            "baseline_selected_gloss_available": record.get("display_gloss_available"),
            "baseline_alternative_glosses_available": record.get("alternative_glosses_available"),
            "source_line_editorial_barriers": record.get("source_line_editorial_barriers", []),
            "lexical_variants": projection["lexical_variants"],
            "dictionary_crossreferences": projection["dictionary_crossreferences"],
        })
    return {"scope": "counterfactual local lexical evidence availability; not contextual accuracy or live deployment",
            "baseline_path": str(path), "baseline_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "baseline_occurrences": len(records), "unflagged_unique_forms_examined": len(cache),
            "occurrences_with_variant_meanings": sum(any(v["entry_senses"] for v in row["lexical_variants"]) for row in changes),
            "occurrences_with_unresolved_crossreferences": sum(bool(row["dictionary_crossreferences"]) for row in changes),
            "source_projections_by_form": {form: result for form, result in cache.items()
                                           if result["lexical_variants"] or result["dictionary_crossreferences"]},
            "occurrences": changes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "runtime/alcaeus-assignment-qa/canary/report.json")
    parser.add_argument("--source", type=Path, default=ROOT / "runtime/campbell-assignment/campbell_assignment.jsonl")
    parser.add_argument("--database", type=Path, default=ROOT / "data/wiktionary.sqlite")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--occurrences", type=Path,
                        help="Instead compare new local variant projection with a saved live occurrence inventory")
    args = parser.parse_args()
    result = audit_occurrence_variants(args.occurrences) if args.occurrences else audit(args.report, args.source, args.database)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf8")
    else:
        print(encoded)
