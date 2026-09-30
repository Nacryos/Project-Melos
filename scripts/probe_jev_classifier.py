"""Bounded live Jev diagnostic over accepted source-claim evaluation fixtures.

Examples:
  python scripts/probe_jev_classifier.py --dry-run
  python scripts/probe_jev_classifier.py --env-file /path/to/private.env

This does not write corpus data. At most ten paid System One calls are possible
per invocation; the default is three. No API key, headers, or request body is
written to the report or printed. An env file is read only when explicitly
named by --env-file or MELOS_ENV_FILE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.classifier import JevProvider  # noqa: E402
from scripts.probe_local_classifier import context_fixtures  # noqa: E402


REPORT = ROOT / "data/reports/jev-classifier.json"
CLAIM_FILE = ROOT / "data/claims/p2_notes.jsonl"
ACCEPTANCE = ROOT / "data/reports/p2-claim-acceptance.json"
PRICE_PER_MILLION_INPUT = 0.042  # TypeSafe public price, 2026-09-30.


def accepted_claim_hash() -> str:
    """Reject stale or unaccepted fixture claims before any paid request."""
    manifest = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    entry = manifest["files"][CLAIM_FILE.name]
    actual = hashlib.sha256(CLAIM_FILE.read_bytes()).hexdigest()
    if entry.get("verdict") != "PASS" or entry.get("sha256") != actual:
        raise RuntimeError("Fixture claim file is not independently accepted at this hash")
    return actual


def key_from_explicit_sources(env_file: Path | None) -> tuple[str | None, str | None]:
    """Read only documented Jev names; never expose or persist their values."""
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value, f"process:{name}"
    if env_file is None:
        return None, None
    if not env_file.is_file():
        raise RuntimeError("Explicit env file does not exist")
    from dotenv import dotenv_values

    parsed = dotenv_values(env_file)
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY"):
        value = parsed.get(name)
        if value:
            return str(value), f"env-file:{name}"
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path,
                        default=Path(os.environ["MELOS_ENV_FILE"]) if os.environ.get("MELOS_ENV_FILE") else None)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("--limit must be 1 through 10")
    accepted_hash = accepted_claim_hash()
    fixtures = context_fixtures()[:args.limit]
    if args.dry_run:
        print(json.dumps({"accepted_claim_sha256": accepted_hash,
                          "fixture_ids": [fixture["packet_id"] for fixture in fixtures],
                          "planned_calls": len(fixtures), "paid_calls_made": 0}))
        return 0
    key, source = key_from_explicit_sources(args.env_file)
    report = {
        "report_type": "jev_source_claim_context_pilot_not_corpus_data",
        "claim_file": str(CLAIM_FILE.relative_to(ROOT)).replace("\\", "/"),
        "accepted_claim_sha256": accepted_hash,
        "provider": "TypeSafe Jev",
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "requested_model": "jev-latest",
        "key_source_name_only": source,
        "max_paid_calls": 10,
        "planned_calls": len(fixtures),
        "requests_attempted": 0,
        "paid_calls_made": 0,
        "pricing_reference": "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
        "input_usd_per_million_tokens": PRICE_PER_MILLION_INPUT,
        "results": [],
    }
    if key is None:
        report["availability"] = "no TypeSafe Jev key in process or explicit env file"
    else:
        report["availability"] = "key present; requests attempted"
        provider = JevProvider(api_key=key)
        for fixture in fixtures:
            before = time.perf_counter()
            answer = None
            error = None
            try:
                report["requests_attempted"] += 1
                answer = provider.decide(fixture["packet"])
                report["paid_calls_made"] += 1
            except (RuntimeError, ValueError, TypeError, TimeoutError) as exc:
                error = str(exc)
            elapsed = round(time.perf_counter() - before, 4)
            usage = answer.get("usage") if answer else None
            input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
            report["results"].append({
                "packet_id": fixture["packet_id"],
                "fixture_type": "evaluation_over_accepted_source_claims",
                "expected_choice": fixture["expected_choice"],
                "candidate_ids": [row["id"] for row in fixture["packet"]["candidates"]],
                "claim_ids": [row["id"] for row in fixture["packet"]["claims"]],
                "choice": answer.get("choice") if answer else None,
                "model": answer.get("model") if answer else None,
                "model_confidence_uncalibrated": answer.get("model_confidence") if answer else None,
                "model_probabilities_uncalibrated": answer.get("model_probabilities") if answer else None,
                "usage": usage,
                "estimated_input_cost_usd": (round(input_tokens * PRICE_PER_MILLION_INPUT / 1_000_000, 8)
                                             if isinstance(input_tokens, int) else None),
                "raw_response": answer.get("raw_response") if answer else None,
                "latency_seconds": elapsed,
                "matches_fixture": (answer.get("choice") == fixture["expected_choice"]
                                    if answer else None),
                "error": error,
            })
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"availability": report["availability"],
                      "planned_calls": report["planned_calls"],
                      "requests_attempted": report["requests_attempted"],
                      "paid_calls_made": report["paid_calls_made"],
                      "matches": sum(row["matches_fixture"] is True for row in report["results"]),
                      "report": str(args.report)}, ensure_ascii=False))
    return 0 if key else 2


if __name__ == "__main__":
    raise SystemExit(main())
