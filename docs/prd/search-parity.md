# Melos lexical and sequence retrieval

Status: implementation authorized 2026-10-05; staged delivery, no TLG-parity claim.

## Objective

Make Melos dependable for word/form and phrase retrieval before claiming improvements in diachronic or thematic interpretation. Compare shared texts and editions separately from corpus coverage. Preserve source text, editorial uncertainty, source citations, and the existing Melos design.

## Baseline evidence

- QA27 is live at commit `889114103522f2658298fd4b03aa673332cdc76e`.
- Live exact `κηλήμασι παντοδαποῖς` finds two Ibycus witnesses; reversed order finds none.
- Current multiword Forms also retrieves a Homeric Hymn containing only `παντοδαποῖς`. It unions expanded tokens rather than verifying a sequence; only the first 12 input tokens are expanded.
- Tokens currently store passage/form/count, not positions. Chronology is author-date sorting, not passage dating or influence detection.
- TLG browser inspection on 2026-10-05 reached a login requirement even for the abridged search. User login requested; actual result comparisons remain pending. Do not substitute documentation claims for observed baseline results.
- Public TLG help viewed through computer use: https://stephanus.tlg.uci.edu/help.php describes word/lemma/text searches, proximity, case/diacritic controls, results grouped by author or grammar, parallel browsing and n-gram comparison. TLG is used only for baseline testing, not corpus scraping.

## Stage 1: explicit, source-backed multiword Forms

Implement now:

1. Keep existing single-word Forms behavior and source/quality/author/edition filters.
2. Multiword Forms defaults to an ordered adjacent sequence. Every original query occurrence is a separate term group, including repeated words. A single passage token cannot satisfy two query occurrences.
3. Offer clearly labelled alternatives: ordered sequence, nearby words in any order, and all words anywhere in the passage. A bounded nonnegative gap specifies the total extra words permitted inside an ordered/nearby match; zero means adjacent. Do not change these into vague relevance controls.
4. Use source-backed form alternatives, never invented paradigms or a model's confidence as attestation. Preserve ambiguous alternatives rather than select a meaning merely from the author's dialect.
5. Use existing token indexes to find candidates, then verify source-derived token positions. Show matched wording/positions with clear provenance; do not fabricate a continuous quote across editorial damage. Preserve printed text.
6. No silent token, expansion, candidate, or window truncation. Return explicit limit/completeness metadata; either reject unsupported requests clearly or disclose a bounded result set. Do not call an incomplete result count a corpus-wide total.
7. Preserve existing exact, reference, semantic and hybrid behavior unless specifically covered by a regression test. Do not make hybrid results appear to be strict sequence matches. Usage-space must not silently discard search constraints.
8. Persist controls in shareable URLs, pagination, and repeat searches. Phrase selection should invoke the appropriate ordered Forms search. Mobile controls must remain compact, keyboard-accessible and styled in the existing palette.

Acceptance:

- Ibycus's two-word phrase does not return the one-word Homeric Hymn overlap in multiword Forms.
- Reversed terms fail ordered matching but may match explicitly unordered proximity.
- Repeated query terms require distinct source positions; ambiguous form groups cannot reuse one token.
- Gap boundaries, punctuation, apostrophes, transliteration, safe line wraps and damaged/editorially interrupted forms have explicit regression tests.
- Every successful strict hit contains a witness covering every query group.
- No source corpus or embedding assets are modified for this code-only stage.
- Existing regression suites pass; independent review, local browser QA and guarded live deployment precede claims of completion.

## Stage 2: sequence comparison and chronology

- Add a versioned derived positional index only if candidate verification proves too slow; do not rebuild the corpus merely to add positions.
- Support cross-record sequences only within explicitly established work/edition order. Never join separate fragments or editions by numeric-looking citation guesses.
- Add inspectable lexical/lemma sequence alignment, matching coverage, gaps and parallel passage display. Distinguish exact reuse, inflected reuse and weaker vocabulary resemblance.
- Add explicit author-date filtering and display uncertainty. Composition dates require separately sourced claims. No automatic claim of dependence or influence from chronological order or similarity.
- Compare exact/lemma/proximity/n-gram cases with TLG on the same source editions after login. Record misses, false matches and citation errors; document differences in scope rather than count them as engine failures.

## Stage 3: thematic retrieval evaluation

- Build a source-bound, human-reviewable evaluation set with genuine parallels and hard negatives; distinguish theme, formula, lexical overlap and claimed allusion.
- Measure precision at the displayed result ranks and recovery of known parallels before changing encoders or adding model reranking.
- Keep lexical proof and thematic similarity separate in the UI. Model-supported interpretations and generated translations must never become source assertions.
- Only claim superiority for a defined task and tested corpus slice; do not extrapolate from passing unit tests or embedding coverage.

## Release and collaboration

Push this plan to the repository before implementation. Assign backend, frontend and independent review to non-overlapping owners. Preserve unrelated Fable/user changes. Release code through a private backend canary, preserve rollback and private Basecamp routes, then deploy the frontend and test the public site through computer use.
