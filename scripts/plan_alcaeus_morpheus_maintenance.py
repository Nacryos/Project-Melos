"""Read-only next-batch proposal from literal audited occurrences and receipts.

No network calls, quota overrides, corpus writes, or inferred word repairs.
Conservatively excludes the entire source line if it has editorial barriers.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.machine_morphology import validate_form, ELISION_MARKS, ELISION_CONVENTION

DIRECTORY = ROOT / "runtime/alcaeus-morpheus-maintenance"
OCCURRENCES = ROOT / "runtime/alcaeus-occurrences/release-f/occurrences.json"
SOURCE = ROOT / "data/campbell_glp/alcaeus_five_corrected.jsonl"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    rows = json.loads(OCCURRENCES.read_text(encoding="utf-8"))
    records = {r["id"]: r for r in (json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip())}
    with sqlite3.connect((DIRECTORY / "machine.sqlite").resolve().as_uri()+"?mode=ro", uri=True) as con:
        metadata_rows = [json.loads(row[0]) for row in con.execute(
            "SELECT metadata FROM receipts r JOIN cache c ON c.receipt_id=r.id WHERE c.expires IS NULL")]
        cached = {metadata.get("source_form", metadata["request_form"]) for metadata in metadata_rows}
        attempts, visitors = con.execute("SELECT count(*),count(distinct visitor) FROM attempts").fetchone()
    eligible = defaultdict(list)
    same_literal_occurrences = defaultdict(list)
    excluded = Counter()
    for row in rows:
        record = records[row["passage_id"]]
        text, a, b = record["text"], row["start"], row["end"]
        if not row.get("source_exact") or sha(text.encode()) != row["source_text_sha256"] or text[a:b] != row["text"]:
            raise ValueError("Source occurrence binding failed")
        source_line = text[text.rfind("\n", 0, a)+1:text.find("\n", b) if "\n" in text[b:] else len(text)]
        if source_line != row["source_line"]:
            raise ValueError("Source line binding failed")
        if row.get("editorial_fragment") or row.get("partial_word") or row.get("editorial_barriers"):
            excluded["token_editorial_or_partial"] += 1
            continue
        same_literal_occurrences[row["text"]].append(row)
        if row.get("source_line_editorial_barriers"):
            excluded["source_line_editorial_barrier"] += 1
            continue
        # This intentionally omits safe-looking words elsewhere on a damaged
        # line instead of treating absent API flags as philological certainty.
        if row.get("machine_status") not in ("cache_miss", "invalid_form"):
            excluded["not_missing_in_release_f"] += 1
            continue
        try:
            literal = validate_form(row["text"])
        except ValueError:
            excluded["not_supported_literal_input"] += 1
            continue
        if literal != row["text"]:
            excluded["requires_normalization"] += 1
            continue
        if row.get("machine_status") == "invalid_form" and not literal.endswith(tuple(ELISION_MARKS)):
            excluded["invalid_not_approved_elision"] += 1
            continue
        eligible[literal].append(row)
    candidates = []
    for form, instances in eligible.items():
        all_instances = same_literal_occurrences[form]
        all_no_literal = sum(not r.get("display_gloss_available") and not r.get("alternative_glosses_available")
                             and not r.get("literal_sense_alternatives") for r in all_instances)
        no_literal = sum(not r.get("display_gloss_available") and not r.get("alternative_glosses_available")
                         and not r.get("literal_sense_alternatives") for r in instances)
        missing_display = sum(not r.get("display_gloss_available") for r in instances)
        candidates.append({"form": form, "eligible_occurrences": len(instances),
            "same_literal_unflagged_occurrences": len(all_instances),
            "same_literal_unflagged_no_meaning_occurrences": all_no_literal,
            "baseline_f_no_literal_meaning_occurrences": no_literal,
            "baseline_f_no_preferred_gloss_occurrences": missing_display,
            "already_in_pilot_cache": form in cached, "literal_elision": form.endswith(tuple(ELISION_MARKS)),
            "occurrences": [{k: r[k] for k in ("occurrence_id", "passage_id", "start", "end", "source_text_sha256", "source_line")}
                            for r in instances]})
    remaining = [r for r in candidates if not r["already_in_pilot_cache"]]
    remaining.sort(key=lambda r: (-r["same_literal_unflagged_no_meaning_occurrences"], -r["same_literal_unflagged_occurrences"],
                                  -r["baseline_f_no_preferred_gloss_occurrences"], r["form"]))
    remaining_today = max(0, 20-attempts)
    proposed = remaining[:min(12, remaining_today)]
    report = {"format": "melos-maintenance-proposal-v1", "network_calls": 0, "authorized_to_execute": False,
        "source_occurrences_sha256": sha(OCCURRENCES.read_bytes()), "source_records_sha256": sha(SOURCE.read_bytes()),
        "script_sha256": sha(Path(__file__).read_bytes()), "machine_module_sha256": sha((ROOT / "backend/machine_morphology.py").read_bytes()),
        "scope": "Conservative clean-line subset across all5 assigned poems; not all linguistically valid words",
        "literal_elision_authority": ELISION_CONVENTION,
        "summary": {"source_occurrences": len(rows), "eligible_missing_occurrences_before_pilot": sum(len(v) for v in eligible.values()),
            "eligible_missing_unique_forms_before_pilot": len(eligible), "pilot_cached_within_eligible": sum(r["already_in_pilot_cache"] for r in candidates),
            "eligible_remaining_unique_forms": len(remaining), "eligible_remaining_elided_forms": sum(r["literal_elision"] for r in remaining),
            "eligible_remaining_without_literal_meaning": sum(r["baseline_f_no_literal_meaning_occurrences"]>0 for r in remaining),
            "pilot_requests_spent": attempts, "pilot_distinct_identities": visitors, "proposed_next_count": len(proposed)},
        "exclusions": dict(excluded), "ranking": "Among forms with a clean-line eligible occurrence: descending identical unflagged spelling occurrences without literal meaning, total identical unflagged recurrence, clean-line missing-preferred-gloss count, Unicode form. Recurrence on other damaged lines changes priority only, never makes a new form eligible.",
        "execution_requirements": [
            "Explicit approval of this new batch before any fetch",
            "Use the actual production service cache/attempt ledger, not a new database per run",
            "One stable maintenance identity across days and runs; no rotation by author or batch",
            "Keep existing visitor3 per rolling60s and20 per rolling24h, global10 per rolling60s and200 per rolling24h; normal traffic shares global allowance",
            "Count all8 approved pilot requests within today's maintenance20, at most12 additional calls even though receipt imports do not transfer operational counters",
            "At most one inflight maintenance request; stop/defer on rate limiting, upstream error, busy, or normal-traffic capacity",
            "Successful source-parser receipts remain machine alternatives; no contextual sense/parse assertion or corpus insertion"],
        "proposed_next": proposed, "all_eligible": candidates}
    path = DIRECTORY / "next-batch-proposal.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "sha256": sha(path.read_bytes()), "summary": report["summary"],
                      "next": [{k:r[k] for k in ("form", "eligible_occurrences", "baseline_f_no_literal_meaning_occurrences")} for r in proposed]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
