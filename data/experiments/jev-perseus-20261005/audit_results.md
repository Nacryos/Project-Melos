# Audit: Completed four-arm positive-control results

## Agent Action

Parent executed the four frozen Jev requests once each and summarized responses against the independent GPT-5.6 Sol provisional judgment. No source annotations were overwritten.

## Audit Checks

- [x] Exactly four success receipts exist, one per frozen arm. Every receipt matches its frozen request hash and the previously approved plan hash.
- [x] All requested and returned model identifiers are jev-1.13.0.
- [x] Judge accepts option_1 and option_4, which map exactly to source candidates p3 and p2 respectively. All four Jev top choices fall within that provisional accepted set.
- [x] Every summary probability, choice, confidence, and per-call latency matches its stored receipt. Candidate probabilities sum to one.
- [x] Independently recomputed accepted-group probability mass: 0.96 form-only; 0.99 Greek context; 0.99 translation context; 0.99 translation with reversed options.
- [x] Perseus top candidate is p2 at displayed score 94.7; combined displayed score of accepted candidates p2/p3 is 97.3. Summary explicitly distinguishes these source scores from calibrated probabilities.
- [x] Independently summed input usage: 11,585 tokens. Total measured latency: 0.8553 seconds; median: 0.20255 seconds.
- [x] Estimated Jev cost is $0.00048657. Official https://docs.typesafe.ai/models independently checked during audit: jev-1.13.0 costs $0.042 per million input tokens and output tokens are free. Judge usage is not included in this Jev estimate.
- [x] Summary explicitly marks one previously inspected positive control, provisional judge labels, no general benchmark, no confidence calibration estimate, and no production changes.
- [x] Runner has no automatic retry and reserves a receipt before a call. Four receipts and frozen four-call plan are consistent with one call per arm. Read-only audit made no model calls.

## Evidence and limits

Frozen plan SHA-256 remains c5783ecca5f55639f5212cf8cce791a52a94a0752452e8dcff93e1c6e0a8cd05. Summary source data were independently recomputed from cases.json, judge_sol.json, frozen_plan.json, and all four receipts. An initial console encoding error reported by parent affected display after summary serialization; final JSON parses correctly and all values agree with receipts. Receipt response hashes document original response bytes, but the original wire-format bytes are not separately retained, so those response-byte hashes cannot be independently recomputed from this artifact set.

## Verdict: PASS
## Blocking: NO

This verifies the reported control result and procedure. It does not establish Jev's general Greek accuracy, superiority to Perseus, calibration, or a reliable translation/order effect from one call per arm.
