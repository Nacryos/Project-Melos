# Audit: Passage acquisition, extraction, transformation, and frozen sampling

## Steps: 2-5 (passages and sampling only)

## Agent action

The harness acquired three parent-observed legacy Perseus Greek sources and their source-linked English editions, then selected twelve occurrences with seed 20261005 before morphology acquisition. The auditor inspected `scripts/jev_perseus_blind12.py`, its imported parser and prompt, and its thirteen protocol tests. No judge answers or Jev responses were inspected.

## Audit checks

- PASS: All six saved response bodies match receipt SHA-256 and byte count, with HTTP status 200. Actual HTTP acquisition code is present and used.
- PASS: Greek and English full contexts reproduce exactly from `.text_container > .text` in their respective saved HTML with the declared whitespace normalization.
- PASS: Ten seeded occurrence samples per Greek source (30 total) match source target text, morphology href, and occurrence onclick. Parsing reads saved/external HTML; no linguistic rows are authored.
- PASS: Linked editions have matching CTS ranges and work identifiers. Individual edition descriptions remain preserved.
- PASS: Unicode NFC composition and Greek letter counting are deterministic; UAX #15 is cited. The folded search key is an indexed prefilter only; final rarity counts retain exact case-sensitive NFC identity.
- PASS: All 3,243 source occurrence exact-frequency values independently recomputed against the read-only corpus agree with the freeze. No corpus write was performed.
- PASS: All three nearest-rank quartile thresholds, eligibility pools, seeded selections, and reserve orders independently reproduce the freeze. All passage hashes match.
- PASS: Twelve selected occurrences contain twelve distinct printed forms. The old pilot control contributes zero cases.
- PASS: No ambiguity filter, outcome-based replacement, or fallback relaxation occurs in the frozen sampling rule. Every frozen target remains in the denominator even if morphology fails.

## Frozen evidence

`sampling_freeze.json` SHA-256:

`454885d1d4067daec90bb7f184044916284326168a02a08609809c7568a7dd1e`

| Source | Source occurrences | Eligible rare-proxy occurrences | Exact-count cutoff | Selected |
|---|---:|---:|---:|---:|
| Bacchylides, Epinicians 5 | 747 | 115 | 2 | 4 |
| Odyssey 7.152-7.197 | 318 | 40 | 12 | 4 |
| Pindar, Pythian 4 | 2,178 | 355 | 2 | 4 |

Eligibility excludes the first fifty linked Greek occurrences, requires at least five Greek letters, and includes every form tied at the lower-quartile cutoff. Sampling operates on occurrences, not unique forms, although the actual selection has no duplicate forms.

## Necessary interpretation limits

The source pool contains two whole poems and a mid-work Odyssey card, selected purposively. Only the eligible occurrence selection within each source is random. This is not a random sample of ancient Greek or a representative accuracy benchmark.

The selected literal printed forms `πατρὸ]ς` and `ἄκουσ᾽` each have exact corpus count zero. Editorial punctuation and tokenization can cause non-attestation; zero does not establish lexical rarity. Both must remain disclosed in the sample, including any parser failure or missing-candidate result. Proper names and inflected forms are also eligible under the declared criterion.

The initial receipt field `wire_bytes_preserved` was imprecise for requests' decompressed response content. The harness added `receipt_terminology_erratum.json`; frozen passage bytes were not altered. The preserved artifact is the HTTP response body after library decoding of content encoding, not raw compressed network bytes.

## Verdict: PASS

## Blocking: NO

Passage acquisition and frozen sampling are accepted. Morphology acquisition, candidate extraction, blinding, frozen requests, and results still require separate checks before evaluation. The paid runner should verify morphology hashes stored in the request plan, and orchestration must record the judge's frozen timestamp/hash before unblinding.
