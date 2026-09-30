"""Bounded local LLM diagnostic; outputs are model inferences, never corpus claims.

Usage:
  py -3.13 scripts/probe_local_classifier.py --download --dcc-fixtures
  py -3.13 scripts/probe_local_classifier.py --packets path/to/eval.jsonl

The optional JSONL format has packet_id, query, passage, candidates (each with
id and text), and evidence (each with id and text). Expected IDs are optional
evaluation labels and are never shown to the model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "0.6b": ("Qwen/Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca",
             ROOT / "data/cache/local_models/qwen3-0.6b-c1899de"),
    "1.7b": ("Qwen/Qwen3-1.7B", "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
             ROOT / "data/cache/local_models/qwen3-1.7b-70d244c"),
}
DEFAULT_REPORT = ROOT / "data/reports/local-classifier.json"


def download_model(model_id: str, revision: str, model_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    required_bytes = 5_000_000_000 if "1.7B" in model_id else 2_000_000_000
    free_bytes = shutil.disk_usage(ROOT).free
    if free_bytes < required_bytes:
        raise RuntimeError(f"Only {free_bytes} free bytes; need {required_bytes} for download")
    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=model_dir,
        allow_patterns=[
            "LICENSE", "README.md", "config.json", "generation_config.json",
            "model*.safetensors", "model.safetensors.index.json",
            "tokenizer.json", "tokenizer_config.json",
            "vocab.json", "merges.txt", "special_tokens_map.json",
        ],
    )


def require_model(model_dir: Path) -> None:
    for name in ("config.json", "tokenizer.json"):
        if not (model_dir / name).is_file():
            raise RuntimeError(f"Missing {model_dir / name}; run with --download")
    if not list(model_dir.glob("model*.safetensors")):
        raise RuntimeError(f"Missing model weights in {model_dir}; run with --download")


def dcc_fixtures() -> list[dict]:
    """Small reranking fixtures derived only from saved DCC commentary records."""
    path = ROOT / "data/processed/sappho.jsonl"
    notes = None
    greek = None
    for line in path.open(encoding="utf-8"):
        record = json.loads(line)
        if record.get("id") == "dcc-sappho:frag-1:notes":
            notes = record
        elif record.get("id") == "dcc-sappho:frag-1":
            greek = record
        if notes and greek:
            break
    if not notes or not greek:
        raise RuntimeError("Accepted DCC Sappho fragment 1 source records missing")
    raw_path = ROOT / notes["raw_path"]
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if digest != notes["raw_sha256"]:
        raise RuntimeError("DCC raw artifact SHA-256 does not match processed record")
    lines = [line.strip() for line in notes["text"].splitlines() if line.strip()]
    # The forms below are evaluation queries, not data or historical assertions.
    forms = ["ποικιλόθρον", "ὀνίαισι", "ἀίοισα", "ἀποτέλεσμα"]
    fixtures = []
    for i, form in enumerate(forms):
        candidates = [
            {"id": f"{notes['id']}:line-{j + 1}", "text": text}
            for j, text in enumerate(lines[:8])
        ]
        expected = [c["id"] for c in candidates if form in c["text"]]
        fixtures.append({
            "packet_id": f"dcc-frag-1-form-{i + 1}",
            "query": f"Which source note directly discusses the Greek form {form}?",
            "passage": greek["text"],
            "candidates": candidates,
            "evidence": [{
                "id": notes["id"], "source_url": notes["source_url"],
                "raw_path": notes["raw_path"], "raw_sha256": digest,
            }],
            "expected_ids": expected,
            "fixture_type": "synthetic_query_over_saved_source",
        })
    return fixtures


def load_packets(path: Path) -> list[dict]:
    packets = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    for packet in packets:
        if not isinstance(packet.get("candidates"), list) or not packet.get("packet_id"):
            raise ValueError("Each packet requires packet_id and candidates list")
    return packets


def context_fixtures() -> list[dict]:
    """Source-grounded classifier tests; staged claims remain evaluation inputs only."""
    sys.path.insert(0, str(ROOT))
    from backend.classifier import build_evidence_packet

    claim_ids = {
        "p2-notes:c3b5e37829b98bff7309781b",  # explicit equivalent
        "p2-notes:3b8bbbd781a1be24a855c22b",  # explicit morphology
        "p2-notes:c5bf587953cba232810ce4bb",  # other form morphology
        "p2-notes:b21cf70514232b3152d7db46",  # editorial alternatives
        "p2-notes:82a3eef7398051e291ec0f71",  # unresolved token alignment
    }
    claims = {}
    for line in (ROOT / "data/claims/p2_notes.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("id") in claim_ids:
            claims[row["id"]] = row
    if set(claims) != claim_ids:
        raise RuntimeError(f"Missing staged note claims: {sorted(claim_ids - set(claims))}")
    passage_ids = {
        "dcc-sappho:brothers-poem", "digital-sappho:the-brothers-poem:1",
        "digital-sappho:fr98:1",
    }
    passages = {}
    for line in (ROOT / "data/processed/sappho.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("id") in passage_ids:
            passages[row["id"]] = row
    if set(passages) != passage_ids:
        raise RuntimeError(f"Missing Greek passages: {sorted(passage_ids - set(passages))}")
    for claim in claims.values():
        for evidence in claim["evidence"]:
            raw = ROOT / evidence["raw_path"]
            if hashlib.sha256(raw.read_bytes()).hexdigest() != evidence["raw_sha256"]:
                raise RuntimeError(f"Raw source hash mismatch for {claim['id']}")

    equiv = claims["p2-notes:c3b5e37829b98bff7309781b"]
    morphology = claims["p2-notes:3b8bbbd781a1be24a855c22b"]
    other = claims["p2-notes:c5bf587953cba232810ce4bb"]
    editor = claims["p2-notes:b21cf70514232b3152d7db46"]
    alignment = claims["p2-notes:82a3eef7398051e291ec0f71"]
    first_candidates = [
        {"id": "source-morphology", "matched_form": morphology["subject"]["form"],
         "analysis": morphology["object"], "gloss": equiv["object"],
         "claim_ids": [morphology["id"], equiv["id"]]},
        {"id": "different-form-morphology", "matched_form": other["subject"]["form"],
         "analysis": other["object"], "claim_ids": [other["id"]]},
    ]
    editorial_quote = editor["evidence"][0]["quote"]
    readings = re.findall(r"that C\. [^)]*", editorial_quote)
    if len(readings) != 3:
        raise RuntimeError("Expected three explicit editorial readings in saved note")
    editorial_candidates = [
        {"id": f"editorial-reading-{i + 1}", "matched_form": editor["subject"]["form"],
         "analysis": {"source_phrase": reading}, "claim_ids": [editor["id"]]}
        for i, reading in enumerate(readings)
    ]
    occurrences = alignment["metadata"]["match_candidates"]
    if len(occurrences) != 2 or alignment["subject"].get("passage_id"):
        raise RuntimeError("Expected two unresolved source token locations")
    alignment_candidates = [
        {"id": f"token-offset-{row['start']}", "matched_form": row["surface"],
         "analysis": {"start": row["start"], "end": row["end"]},
         "claim_ids": [alignment["id"]]}
        for row in occurrences
    ]
    inputs = [
        ("source-supported-morphology", morphology["subject"]["form"],
         passages["dcc-sappho:brothers-poem"], first_candidates,
         [equiv, morphology, other], "source-morphology"),
        ("competing-editorial-readings", editor["subject"]["form"],
         passages["digital-sappho:the-brothers-poem:1"], editorial_candidates,
         [editor], "abstain"),
        ("unresolved-token-alignment", alignment["subject"]["form"],
         passages["digital-sappho:fr98:1"], alignment_candidates,
         [alignment], "abstain"),
    ]
    return [{"packet_id": name, "packet": build_evidence_packet(form, passage, candidates, evidence),
             "expected_choice": expected,
             "fixture_type": "synthetic_decision_over_staged_source_claims"}
            for name, form, passage, candidates, evidence, expected in inputs]


def parse_decision(output: str, packet: dict) -> tuple[dict | None, list[str]]:
    errors = []
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        return None, [f"json_parse: {exc.msg}"]
    if not isinstance(value, dict):
        return None, ["output is not an object"]
    candidate_ids = {str(c["id"]) for c in packet["candidates"]}
    selected = value.get("candidate_id")
    abstain = value.get("abstain")
    if not isinstance(abstain, bool):
        errors.append("abstain must be boolean")
    if selected is not None and selected not in candidate_ids:
        errors.append("candidate_id is not in packet")
    if abstain is True and selected is not None:
        errors.append("abstention must have null candidate_id")
    if abstain is False and selected is None:
        errors.append("non-abstention requires candidate_id")
    evidence_ids = value.get("evidence_ids")
    valid_evidence = {str(e["id"]) for e in packet.get("evidence", [])}
    if not isinstance(evidence_ids, list) or any(e not in valid_evidence for e in evidence_ids):
        errors.append("evidence_ids must be packet evidence IDs")
    return value, errors


def rescore_report(path: Path) -> None:
    """Record strictly normalized fenced-JSON results without rerunning a model."""
    report = json.loads(path.read_text(encoding="utf-8"))
    for run in report.get("runs", []):
        for result in run.get("results", []):
            raw = result["raw_output"]
            if raw.startswith("```json\n") and raw.endswith("\n```"):
                raw = raw[len("```json\n"):-len("\n```")]
                result["format_warning"] = "Model added a JSON code fence despite prompt"
            else:
                result.pop("format_warning", None)
            packet = {"candidates": [{"id": cid} for cid in result["candidate_ids"]],
                      "evidence": [{"id": eid} for eid in result["evidence_ids"]]}
            decision, errors = parse_decision(raw, packet)
            expected = result.get("expected_ids")
            result["normalized_decision"] = decision
            result["normalized_schema_errors"] = errors
            result["normalized_matches_fixture"] = (
                None if expected is None or errors else
                (decision.get("candidate_id") in expected if expected else decision.get("abstain") is True)
            )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download pinned model to project cache")
    parser.add_argument("--download-only", action="store_true", help="Download without loading GPU model")
    parser.add_argument("--model", choices=MODELS, default="0.6b")
    parser.add_argument("--append", action="store_true", help="Append this run to existing report")
    parser.add_argument("--rescore-report", action="store_true", help="Normalize saved raw JSON outputs without GPU inference")
    parser.add_argument("--dcc-fixtures", action="store_true", help="Use saved DCC Sappho evaluation fixtures")
    parser.add_argument("--context-fixtures", action="store_true", help="Use staged source claims with the classifier provider")
    parser.add_argument("--packets", type=Path, help="JSONL evidence packets")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    args = parser.parse_args()
    if args.rescore_report:
        rescore_report(args.report)
        print(json.dumps({"rescored_report": str(args.report)}))
        return 0
    model_id, revision, model_dir = MODELS[args.model]
    if args.download or args.download_only:
        download_model(model_id, revision, model_dir)
    if args.download_only:
        print(json.dumps({"model": model_id, "cache": str(model_dir), "downloaded": True}))
        return 0
    require_model(model_dir)
    if sum((args.dcc_fixtures, args.context_fixtures, bool(args.packets))) != 1:
        parser.error("Choose exactly one fixture/input mode")

    if args.context_fixtures:
        if args.model != "1.7b":
            parser.error("The classifier provider is pinned to the 1.7B model")
        sys.path.insert(0, str(ROOT))
        from backend.local_classifier import LocalModelProvider, local_model_status

        provider = LocalModelProvider()
        observations = []
        for fixture in context_fixtures()[: args.limit]:
            before = time.perf_counter()
            try:
                answer = provider.decide(fixture["packet"])
                error = None
            except (RuntimeError, ValueError, OSError) as exc:
                answer = None
                error = str(exc)
            observations.append({
                "packet_id": fixture["packet_id"],
                "fixture_type": fixture["fixture_type"],
                "expected_choice": fixture["expected_choice"],
                "candidate_ids": [c["id"] for c in fixture["packet"]["candidates"]],
                "claim_ids": [c["id"] for c in fixture["packet"]["claims"]],
                "source_urls": sorted({e["source_url"] for c in fixture["packet"]["claims"]
                                       for e in c["evidence"] if e.get("source_url")}),
                "answer": answer, "error": error,
                "matches_fixture": (answer is not None and answer.get("choice") == fixture["expected_choice"]),
                "seconds_including_first_load": round(time.perf_counter() - before, 3),
            })
        context_run = {"report_type": "source_claim_context_pilot_not_historical_corpus",
                       "claim_input_status": "staged_source_claims_pending_independent_acceptance",
                       "provider_status": local_model_status(), "results": observations}
        if args.report.is_file():
            report = json.loads(args.report.read_text(encoding="utf-8"))
        else:
            report = {"report_type": "local_model_diagnostics_not_source_claims", "runs": []}
        report.setdefault("context_runs", []).append(context_run)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"context_cases": len(observations),
                          "matches": sum(x["matches_fixture"] for x in observations),
                          "errors": sum(x["error"] is not None for x in observations),
                          "report": str(args.report)}, ensure_ascii=False))
        return 0

    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    packets = (dcc_fixtures() if args.dcc_fixtures else load_packets(args.packets))[: args.limit]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    start_load = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, local_files_only=True, torch_dtype=dtype, low_cpu_mem_usage=True,
    ).to(device).eval()
    load_seconds = time.perf_counter() - start_load
    results = []
    for packet in packets:
        public_packet = {k: v for k, v in packet.items() if k != "expected_ids"}
        task = (
            "Select the one candidate source note that directly answers the query. "
            "Use only the supplied text. If none does, abstain. Return one JSON object "
            "with candidate_id (string or null), evidence_ids (array), abstain (boolean), "
            "and a short reason (string). No markdown.\n"
            + json.dumps(public_packet, ensure_ascii=False)
        )
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": "You are a cautious evidence reranker."},
             {"role": "user", "content": task}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096).to(device)
        before = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs, max_new_tokens=args.max_new_tokens, do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        if device == "cuda":
            torch.cuda.synchronize()
        duration = time.perf_counter() - before
        output = tokenizer.decode(generated[0, inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
        decision, errors = parse_decision(output, packet)
        expected = packet.get("expected_ids")
        results.append({
            "packet_id": packet["packet_id"], "fixture_type": packet.get("fixture_type"),
            "query": packet.get("query"),
            "candidate_ids": [c["id"] for c in packet["candidates"]],
            "evidence_ids": [e["id"] for e in packet.get("evidence", [])],
            "source_urls": sorted({e.get("source_url") for e in packet.get("evidence", []) if e.get("source_url")}),
            "expected_ids": expected, "raw_output": output,
            "decision": decision, "schema_errors": errors,
            "matches_fixture": (None if expected is None or errors else
                                (decision.get("candidate_id") in expected if expected else decision.get("abstain") is True)),
            "seconds": round(duration, 3),
            "input_tokens": int(inputs.input_ids.shape[1]),
            "output_tokens": int(generated.shape[1] - inputs.input_ids.shape[1]),
        })
    report = {
        "report_type": "local_model_diagnostic_not_source_claims",
        "model_id": model_id, "revision": revision, "license": "Apache-2.0",
        "model_cache": str(model_dir.relative_to(ROOT)).replace("\\", "/"),
        "model_file_bytes": sum(p.stat().st_size for p in model_dir.glob("model*.safetensors")),
        "python": sys.version.split()[0], "torch": torch.__version__,
        "transformers": transformers.__version__, "device": device, "dtype": str(dtype),
        "load_seconds": round(load_seconds, 3),
        "gpu_peak_allocated_mib": (round(torch.cuda.max_memory_allocated() / 1048576, 1) if device == "cuda" else None),
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    if args.append and args.report.is_file():
        old = json.loads(args.report.read_text(encoding="utf-8"))
        old_runs = old.get("runs", [old] if "model_id" in old else [])
        report = {"report_type": "local_model_diagnostics_not_source_claims",
                  "runs": old_runs + [report]}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(args.report), "model": model_id, "load_seconds": load_seconds,
        "cases": len(results), "schema_valid": sum(not r["schema_errors"] for r in results),
        "fixture_matches": sum(r["matches_fixture"] is True for r in results),
        "gpu_peak_allocated_mib": (round(torch.cuda.max_memory_allocated() / 1048576, 1) if device == "cuda" else None),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
