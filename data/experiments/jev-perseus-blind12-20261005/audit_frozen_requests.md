# Audit: Candidate provenance and frozen requests

## Steps: 3-6 (morphology and evaluation artifacts)

## Agent action

Parent reports manually clicking all twelve frozen source occurrences. Eleven browser popups returned HTTP 503; one showed analysis. Twelve separate direct HTTP acquisitions failed. The successful browser's `.analysis.outerHTML` was mechanically read, serialized verbatim into a JSON cache, decoded by the harness, and deterministically parsed. No linguistic candidate data was generated. Four score-blind requests were frozen for the single available occurrence.

## Audit checks

- PASS: Cached JSON hash matches receipt, decoded HTML equals the saved HTML bytes exactly, and HTML hash matches receipt.
- PASS: Both candidate rows independently reparse identically, including Greek lemma, morphology, gloss, displayed percentages, zero user votes, row identity, and winner marker. Browser-inserted `tbody` wrappers are unwrapped structurally without changing text.
- PASS: The source URL's `l`, `d`, and `i` match the frozen occurrence. All twelve manually reported popup URLs likewise match their frozen occurrences.
- PASS: Candidate coverage preserves twelve distinct frozen occurrences: one successful and eleven failed. The attempt journal contains thirteen attempts: twelve failed direct requests and one successful cached-browser extraction, not thirteen distinct test cases.
- PASS: Four requests comprise Greek-context and translation-context arms, each in forward and reversed candidate order. Requests preserve full source context and target neighbors.
- PASS: Candidate IDs are opaque and deterministic; model and judge packets omit source percentages, votes, source IDs, and winner markers. Both candidate rows and `none_of_these` remain available.
- PASS: Every request hash, candidate mapping, packet hash, morphology artifact hash, and sampling hash agrees with the frozen plan. The runner now verifies morphology hashes before sending requests or summarizing.
- PASS: Maximum four requests for this plan, no automatic retries, durable request reservation, pinned endpoint/model, and preserved raw responses provide a bounded auditable evaluation path.

## Frozen evidence

`frozen_plan.json` SHA-256:

`8bf66c8dd5fe9e596da9bb1a6302db3ca61e81546d8f8a423e3d815ea9fa7bdf`

Case: `bacchylides_ep5-0578`, printed form `ἀδεισιβόαν`.

- Source candidate p1: `noun sg masc acc epic doric aeolic`, displayed combined score 61.2%, no user votes.
- Source candidate p2: `noun pl masc gen doric aeolic`, displayed combined score 38.8%, no user votes.
- Both rows use source lemma `ἀδεισιβόας` and source gloss `not fearing the battle-cry`.

## Evidence limits

The auditor verified the entire saved fragment and deterministic extraction, but did not control the browser or independently repeat the live popup because the parent owns UI interaction and the source was returning failures. The browser click outcome ledger is explicitly parent-reported evidence. This is a DOM fragment, not original HTTP response bytes; the detailed evaluator table outside `.analysis` was not captured and remains empty rather than invented.

The historical-user-vote baseline has **no votes**, hence no empirical vote preference. All-zero ties must not be presented as a calibrated 50/50 probability or substantive voter disagreement.

Twelve random eligible occurrences were attempted, but only one is evaluable. This does not fulfill a claim of ten or more completed comparisons. The four requests are controls on one occurrence, not four independent examples. The independent judge must freeze before model answers are revealed; this audit has not inspected judge answers or model outputs.

## Verdict: PASS

## Blocking: NO

GO for the exact four-call plan after the blind judge is frozen. This approves provenance and protocol, not an accuracy or superiority claim. All eleven unavailable occurrences remain disclosed.
