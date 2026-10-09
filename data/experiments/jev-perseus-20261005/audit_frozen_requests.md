# Audit: Frozen Jev requests and blind judge packet

## Agent Action

Parent prepared four arms for the single audited positive control: form_only, greek_context, translation_context, translation_reversed. An independent judge receives only blind_judge_packet.json.

## Audit Checks

- [x] Frozen plan hash independently verified: c5783ecca5f55639f5212cf8cce791a52a94a0752452e8dcff93e1c6e0a8cd05.
- [x] Cases and judge packet hashes agree with plan. Each request body independently re-serialized and its hash matched.
- [x] All four request bodies use jev-1.13.0; total calls equals four and remains within the runner's hard maximum of 48.
- [x] Candidate whitelist is exactly id, lemma, morphology, gloss. Scores, user votes, selected flags, source row positions, original candidate IDs, evaluator tables, and dagger-bearing form displays are absent.
- [x] Neutral option IDs are assigned after a per-case deterministic shuffle; mapping independently recomputed and matched. The mapping stays outside transmitted request bodies.
- [x] Form-only arm includes only target and candidates. Context arms retain exact target-line surroundings and occurrence metadata. Translation appears only in translation arms and contains only source text plus alignment status.
- [x] Reverse arm reverses candidate ordering while retaining option identities. Criteria insertion order follows candidate ordering.
- [x] Blind judge packet has the same clean candidate set and contains no baseline scores or predictions.
- [x] Runner review: fixed endpoint, blocked redirects, credentials read only from explicitly supplied environment file, no credential printing, receipt reserved before each call, existing receipts skipped, and no automatic retry.

## Verdict: PASS
## Blocking: NO

Approval is for exactly four calls from this frozen plan. This is a procedure/control experiment on one previously inspected occurrence; results cannot support a general accuracy estimate. The judge's reference remains provisional model judgment, not source gold.
