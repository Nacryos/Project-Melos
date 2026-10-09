# Audit: Final receipts and reported result

## Step: 7

## Agent action

The independent judge file was frozen and four approved Jev requests were executed for the one available morphology case. The harness produced `summary.json` and `human_report.txt`. The auditor inspected the judge only after request preparation and source audits were complete, then independently recomputed the reported values from preserved responses.

## Audit checks

- PASS: Exactly four request receipts and four original response files exist. All four requests succeeded; no additional request or retry receipt exists.
- PASS: Each original response hash matches its receipt, parsed response equals the receipt response, request hash equals the frozen request hash, and plan hash equals the approved plan. Returned model is `jev-1.13.0` in every case.
- PASS: The current morphology artifacts remain identical to the hashes in the frozen plan.
- PASS: Judge hash matches the summary. Judge file modification time is 2026-10-05 23:51:29 UTC; the first request receipt starts 23:52:09 UTC. This supports the separately reported orchestration order in which judgment preceded calls.
- PASS: Judge accepts the singular masculine accusative source row. All four top choices select that row. Every probability, API confidence, accepted-set mass, and latency in the summary matches its response or receipt.
- PASS: Independently summed usage is 29,288 input tokens and 292 output tokens.
- PASS: Coverage is explicitly one evaluable occurrence out of twelve frozen targets. The eleven unavailable targets remain in the coverage ledger. Four arm/order calls are controls on that one occurrence.
- PASS: Perseus combined top displayed score is 61.2%, selecting the same row. Historical user votes are zero for both rows; the report labels this no evidence and excludes it from evaluable vote aggregates.
- PASS: The human-readable report states this is provisional model-judge agreement, not gold accuracy, and makes no performance-advantage claim. No corpus or production annotation integration occurred in this workflow.

## Independently verified result

| Arm | Order | Selected-row probability | API confidence |
|---|---|---:|---:|
| Greek context | Forward | 0.71 | 0.56 |
| Greek context | Reverse | 0.70 | 0.55 |
| Greek plus translation | Forward | 0.73 | 0.60 |
| Greek plus translation | Reverse | 0.78 | 0.67 |

These model outputs cannot be compared as calibrated equivalents of Perseus's 61.2% combined evaluator score. One available occurrence cannot establish accuracy, calibration, translation benefit, or an order effect. The requested ten-or-more completed comparisons were not achieved because eleven source analyses were unavailable.

## Verdict: PASS

## Blocking: NO

The final artifacts faithfully report the bounded experiment and its incomplete source coverage. This is acceptance of provenance and reporting integrity, not certification of linguistic gold labels or completion of a ten-case comparison benchmark.
