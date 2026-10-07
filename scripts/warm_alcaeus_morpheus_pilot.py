"""Bounded source-bound Morpheus maintenance diagnostic, never corpus ingestion.

Plan first, independently audit the plan/code, then run at most five intact
source forms. Uses one persistent shared ledger and fixed maintenance identity.
No quota overrides, retries, identity rotation, editorial repair, or LLM calls.
The other authorized elision diagnostic shares this same ledger and identity.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.machine_morphology import ELISION_MARKS, MachineMorphologyService, validate_form

DIRECTORY = ROOT / "runtime/alcaeus-morpheus-maintenance"
DATABASE = DIRECTORY / "machine.sqlite"
VISITOR = hashlib.sha256(b"melos-alcaeus-maintenance-v1").hexdigest()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def records(path):
    return {row["id"]: row for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def make_plan(occurrences_path, records_path):
    source = records(records_path)
    occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))
    eligible, skipped = [], {}
    for row in occurrences:
        if (not row.get("source_exact") or row.get("machine_status") != "cache_miss"
                or row.get("editorial_fragment") or row.get("partial_word")
                or row.get("editorial_barriers") or row.get("source_line_editorial_barriers")
                or row.get("display_gloss_available") or row.get("text", "").endswith(tuple(ELISION_MARKS))):
            continue
        passage = source[row["passage_id"]]
        text, a, b = passage["text"], row["start"], row["end"]
        if sha(text.encode()) != row["source_text_sha256"] or text[a:b] != row["text"]:
            raise ValueError("Occurrence does not bind to exact supplied source text")
        line = text[text.rfind("\n", 0, a)+1:text.find("\n", b) if "\n" in text[b:] else len(text)]
        if line != row["source_line"]:
            raise ValueError("Source line evidence mismatch")
        try:
            form = validate_form(row["text"])
        except ValueError as error:
            skipped[row["text"]] = str(error)
            continue
        if form != row["text"]:
            raise ValueError("Diagnostic only accepts unchanged already-NFC source forms")
        eligible.append(row)
    # One first eligible literal occurrence per supplied poem: deterministic,
    # not cherry-picked after observing parser responses or reconstructed text.
    selected, seen = [], set()
    for passage_id in source:
        row = next((r for r in eligible if r["passage_id"] == passage_id and r["text"] not in seen), None)
        if row is None:
            continue
        seen.add(row["text"])
        selected.append({key: deepcopy(row[key]) for key in (
            "occurrence_id", "passage_id", "text", "start", "end", "source_text_sha256", "source_line",
            "editorial_fragment", "partial_word", "editorial_barriers", "source_line_editorial_barriers", "machine_status")})
        if len(selected) == 5:
            break
    if not selected:
        raise ValueError("No intact source-bound forms available; no substitute data created")
    plan = {"format": "melos-intact-morpheus-pilot-v1", "maximum_network_requests": 5,
        "database": str(DATABASE), "fixed_visitor": VISITOR,
        "occurrences_path": str(occurrences_path.resolve()), "occurrences_sha256": sha(occurrences_path.read_bytes()),
        "records_path": str(records_path.resolve()), "records_sha256": sha(records_path.read_bytes()),
        "script_sha256": sha(Path(__file__).read_bytes()),
        "selection_rule": "first unchanged-NFC cache miss with no displayed gloss and no token/line editorial barriers per poem; at most5 distinct forms",
        "eligible_occurrences": len(eligible), "rejected_literal_inputs": skipped, "selected": selected}
    target = DIRECTORY / "intact-plan.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != plan:
        raise ValueError("Existing plan differs; preserve it and review changes rather than silently replacing")
    save(target, plan)
    print(json.dumps({"plan": str(target), "sha256": sha(target.read_bytes()), "selected": selected}, ensure_ascii=True))


def run(plan_path, audit_path, max_new):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if (audit.get("verdict") != "PASS" or audit.get("plan_sha256") != sha(plan_path.read_bytes())
            or audit.get("script_sha256") != sha(Path(__file__).read_bytes())
            or audit.get("machine_module_sha256") != sha((ROOT / "backend/machine_morphology.py").read_bytes())):
        raise ValueError("Independent pre-run audit not bound to this plan and code")
    if len(plan["selected"]) > 5 or not 1 <= max_new <= 5 or plan["fixed_visitor"] != VISITOR or Path(plan["database"]) != DATABASE:
        raise ValueError("Bounded maintenance protocol mismatch")
    if plan["script_sha256"] != sha(Path(__file__).read_bytes()):
        raise ValueError("Selection plan was produced by different script bytes")
    if sha(Path(plan["records_path"]).read_bytes()) != plan["records_sha256"] or sha(Path(plan["occurrences_path"]).read_bytes()) != plan["occurrences_sha256"]:
        raise ValueError("Source artifacts changed after audit")
    service = MachineMorphologyService(DATABASE)
    # Lower configured quotas are honored; never raise a cap through environment.
    if service.global_day > 200 or service.global_minute > 10 or service.visitor_day > 20 or service.visitor_minute > 3:
        raise ValueError("Configured quotas exceed established defaults; refusing overrides")
    report_path = DIRECTORY / "intact-results.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "plan_sha256": sha(plan_path.read_bytes()), "machine_module_sha256": sha((ROOT / "backend/machine_morphology.py").read_bytes()),
        "fixed_visitor": VISITOR, "database": str(DATABASE), "results": [], "paid_model_calls": 0}
    if report["plan_sha256"] != sha(plan_path.read_bytes()):
        raise ValueError("Prior run belongs to another plan")
    done = {row["form"] for row in report["results"] if row.get("network_attempted")}
    new = 0
    for selected in plan["selected"]:
        form = selected["text"]
        if form in done or new >= max_new:
            continue
        before = service.analyze(form, VISITOR, fetch=False)
        start = time.monotonic()
        result = service.analyze(form, VISITOR, fetch=True)
        seconds = round(time.monotonic()-start, 4)
        attempted = before["status"] == "cache_miss" and result["status"] not in ("rate_limited", "busy", "disabled", "cache_full", "invalid_form")
        new += int(attempted)
        row = {"form": form, "source_occurrence": selected, "status": result["status"], "seconds": seconds,
               "network_attempted": attempted, "result": result}
        receipt = result.get("receipt")
        if receipt:
            with sqlite3.connect(DATABASE.resolve().as_uri()+"?mode=ro", uri=True) as con:
                raw, metadata = con.execute("SELECT raw,metadata FROM receipts WHERE id=?", (receipt["id"],)).fetchone()
            if sha(raw) != receipt["raw_sha256"] or sha(metadata.encode()) != receipt["id"]:
                raise ValueError("Immutable raw receipt failed integrity check")
            raw_path = DIRECTORY / "raw" / f"{receipt['id']}.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            if raw_path.exists() and raw_path.read_bytes() != raw:
                raise ValueError("Existing raw artifact conflicts with immutable receipt")
            raw_path.write_bytes(raw)
            row.update({"raw_path": str(raw_path), "raw_sha256": sha(raw), "raw_bytes": len(raw)})
        report["results"].append(row)
        save(report_path, report)
        print(json.dumps({"form": form, "status": result["status"], "seconds": seconds,
                          "analyses": len(result.get("machine_candidates", [])), "network_attempted": attempted}, ensure_ascii=True), flush=True)
        if result["status"] not in ("ok", "no_analyses"):
            break


def dictionary_projection():
    """Read existing dictionary artifacts; never copy hypotheses into the corpus."""
    from backend.morphology import Morphology
    from backend.interlinear import join_machine_dictionary, _gloss
    path = DIRECTORY / "intact-results.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    dictionary = Morphology()
    cache = {}
    def lookup(lemma):
        if lemma not in cache:
            if len(cache) >= 30:
                return {"lexicon_entries": [], "dictionary_lookup_status": "diagnostic_limit"}
            cache[lemma] = dictionary.analyze(lemma)
        return cache[lemma]
    output = {"result_sha256": sha(path.read_bytes()), "hypotheses_not_occurrence_attestations": True, "forms": []}
    output["projection_module_sha256"] = {name: sha((ROOT / "backend" / name).read_bytes())
        for name in ("interlinear.py", "morphology.py", "lexicon_senses.py", "lexicon_render.py")}
    for row in report["results"]:
        if row["status"] != "ok":
            continue
        token = {"text": row["form"], "machine": deepcopy(row["result"]), "lexicon_entries": []}
        join_machine_dictionary(token, lookup)
        hypotheses = []
        for candidate in token["machine"]["machine_candidates"]:
            hypotheses.append({"candidate": candidate, "dictionary_join": candidate.get("dictionary_join"), "gloss": _gloss(candidate, token)})
        output["forms"].append({"form": row["form"], "receipt_id": row["result"]["receipt"]["id"],
                                "hypotheses": hypotheses, "lexicon_entries": token["lexicon_entries"]})
    output["lexical_artifact_sha256"] = sha((ROOT / "data/lexica/entries.jsonl").read_bytes())
    save(DIRECTORY / "intact-dictionary.json", output)
    print(json.dumps({"forms": len(output["forms"]), "unique_lemma_lookups": len(cache)}, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "dictionary"))
    parser.add_argument("--occurrences", type=Path, default=ROOT / "runtime/alcaeus-occurrences/release-f/occurrences.json")
    parser.add_argument("--records", type=Path, default=ROOT / "runtime/campbell-assignment/campbell_assignment.jsonl")
    parser.add_argument("--audit", type=Path, default=DIRECTORY / "audit/pre-run.json")
    parser.add_argument("--max-new", type=int, default=3)
    args = parser.parse_args()
    if args.command == "plan": make_plan(args.occurrences, args.records)
    elif args.command == "run": run(DIRECTORY / "intact-plan.json", args.audit, args.max_new)
    else: dictionary_projection()


if __name__ == "__main__":
    main()
