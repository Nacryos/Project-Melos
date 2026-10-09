# Audit: Source discovery and prospective method

## Step: 1

Independent auditor read the data-extraction skill and inspected the earlier pilot extraction code. The earlier one-control pilot is not evidence for the new sample and does not count toward its size. No judge answers or new model responses were inspected for this audit.

## Audit checks

- PASS: Official legacy Hopper homepage independently fetched with HTTP 200, 23,961 bytes, title `Perseus Digital Library`.
- PASS: Official Odyssey Greek page independently fetched with HTTP 200, 124,315 bytes, title identifying Homer, Odyssey, Book 1, line 1. This verifies source availability, not the new sample's passage selection.
- PASS: Official PerseusDL canonical README independently fetched with HTTP 200, 3,403 bytes. Its copyright section permits personal use by students, scholars, and the public and notes that individual objects have varying copyright status.
- PASS: Greek text page explicitly links CC BY-SA 3.0 US. This text license must not be generalized to morphology analyses or voting data.
- PENDING: New exact passage and morphology URLs, downloaded snapshots, source contexts, selection freeze, and parser output require their own subsequent audits.

## Evidence

Verified 2026-10-05 UTC with Python requests, browser User-Agent, 15-second timeout. Web access also independently displayed the homepage and official repository README.

- https://www.perseus.tufts.edu/hopper/
- https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.01.0135:book=1:card=1
- https://raw.githubusercontent.com/PerseusDL/canonical/master/README.md

The homepage describes the service as Perseus 4.0 (Hopper), identifies its Tufts affiliation, and distinguishes it from newer reading systems. These are authentic legacy source endpoints.

## Prospective method requirements

1. Freeze the passage pool, random seed, sampling algorithm, exclusions, and rarity proxy before inspecting model outcomes or judge labels. Distinguish a convenience passage pool from random selection within that pool. Document whether sampling units are forms or occurrences.
2. Define less-famous or rare operationally. Occurrence frequency in a small chosen passage is only a local rarity proxy; it cannot substantiate corpus-wide rarity. Do not imply that an obscure passage makes every selected form rare.
3. Keep a complete eligibility and attempt ledger. Log unavailable pages and ambiguous/unambiguous exclusions. Do not silently substitute convenient successes or treat a target count as permission to invent entries.
4. Preserve fetched bytes, exact requested and effective URLs, UTC capture time, SHA-256, request context, source document and occurrence identifier. Browser snapshots are acceptable cached fetches when captured mechanically and parsed deterministically.
5. Extract every available candidate row and retain lemma, morphology, source row, displayed percentage, user votes, and winner markers. The combined Perseus evaluator percentage is not a historical vote count, a calibrated probability, or gold truth.
6. Preserve tied maxima and zero-vote conditions. Evaluate set-valued agreement when multiple analyses are equivalent or acceptable. Do not resolve ties by incidental row order without separately reporting the tie.
7. Blind judges to scores, votes, source winner markers, model answers, model probabilities, and identifying candidate IDs. Freeze their judgments before revealing model answers. Retain abstention, missing-candidate, and indeterminate cases explicitly.
8. Report closed-candidate ranking separately from parser coverage. If the linguistically correct analysis is absent, selecting among the supplied candidates cannot establish correctness. Match analyses by the full morphology and lemma, not by lemma alone.
9. Source Greek and translation context from captured editions, align their passage scope, and preserve edition attribution. A translation is useful context but is not independent gold.
10. Keep this experiment isolated from production lexicons and training/gold corpora. Report sample-size and selection limits; twelve cases cannot support broad accuracy or calibration claims.

## Verdict: PASS

## Blocking: NO

This pass covers source authority and bounded local scholarly use only. It does not approve unseen extraction output. Subsequent stages must verify the new artifacts before model evaluation.
