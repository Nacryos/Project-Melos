# Phase 2 integration QA

Independent integration verification on 2026-09-30. Synthetic pytest fixtures
are test-only and are not historical evidence or corpus inputs. This audit
checks admission and API contracts; it does not certify every source claim or
validate Ancient Greek semantic retrieval quality.

## Final admission and served status

`python -m scripts.check_p2_integration` passed with no errors after the final
root-owned rebuild. It independently rehashed and counted every PASS input:

- 19 accepted text JSONL files, exactly 287,536 rows. The corpus SQLite has
  exactly 287,536 passages from those 19 files, no missing or unaccepted input
  file, and `PRAGMA integrity_check = ok`. The 11 phase 2 text units are present,
  including the final 123-row scholarship file.
- Five accepted claim JSONL files, exactly 298,416 rows: apparatus 7,868;
  authors 104; grammar 22; notes 1,214; Wiktionary 289,208. The evidence
  SQLite has exactly 298,416 `source_claim` records, matching all five current
  hashes and counts, with `PRAGMA integrity_check = ok`.
- One separately accepted author-profile metadata JSON has its own verified
  hash and 11 profiles. It is not counted as 11 additional claims.

The live `GET /api/status` on 127.0.0.1:8791 reported 287,536 passages,
298,416 evidence claims with `ready: true`, and 111,578 embeddings with
`ready: true`. These are index-admission counts, not accuracy scores. No paid
classifier request was made during this QA.

## Live API and reader checks

For the accepted `dcc-sappho:brothers-poem` passage, a clicked `πέμπην`
returned two DCC `explicit_passage_span` claims through `/api/evidence`.
`/api/word` carried the same two source claims and two contextual candidates,
including the equivalent-form projection. Earlier independent source tracing
verified offsets 130:136 slice exactly `πέμπην` in the accepted Greek passage;
the raw DCC HTML hash matches the claim provenance and the quoted note states
`πέμπην : = πέμπειν, pres. act. inf.`. This confirms source transport and
occurrence scope, not an independent grammatical judgment.

Live `λύεις` lookup returned four Wiktionary general-form claims and one
listed-entry-form claim, with a
source-tagged form-of target `λῡ́ω` in `/api/word`. These are dictionary
annotations, not an attestation in the clicked passage. The accepted source
retains 1,611,458 listed form rows; the Greek-only derived reverse index has
1,422,683 searchable form edges, so the edge count is not the source-row count.

Live hybrid search for `πέμπην` returned Greek text passages in both
commentary-assisted and Greek-only modes, with reciprocal-rank-fusion score
labels and bounded-pool warnings. The top five included the DCC Brothers Poem
and a separate Digital Sappho edition; the result keeps supporting hits
inspectable rather than merging distinct editions. The Greek-only top five
were all `grc` text. Synthetic integration tests separately verify that an
explicit commentary parent projects to the Greek text while an unrelated
commentary hit does not, and that Greek-only retrieval excludes commentary.

Browser QA on port 8791 confirmed the Melos painting/dither hero, palette,
painting tabs and search controls in the integrated reader. Clicking
`πέμπην` visibly showed the two DCC span claims first, their exact quote,
human-readable morphology and `form: πέμπειν`; general claims, source
candidates, literal commentary, disabled model comparison and nearby spelling
analyses were visually separated. A 278px-wide responsive viewport had 267px
document scroll width, with no horizontal overflow observed. Port 8790 was
not touched. This was one representative visual/interaction trace, not a full
accessibility or cross-browser audit.

## Regression coverage and security boundary

`python -m pytest tests/test_p2_integration.py -q`: **14 passed**. The suite
covers clicked-form occurrence scope; general vs explicit vs model claims;
reverse-indexed forms; acceptance-hash fail-closed and atomic index retention;
classifier abstention and non-mutating proposal; `/api/word` evidence;
explicit-parent hybrid grouping; API statistics against SQLite; corpus builder
rejection of accepted record-count mismatch without replacing its prior DB;
revocation of a previously accepted phase 2 text file; immutable caching for a
real hashed painting; non-exposure of `/assets/source/foo`; and 403 before any
provider call for non-loopback and `MELOS_PUBLIC_DEPLOYMENT=1` classifier POSTs.
The API classifier success test uses a synthetic provider, never the paid one.

The count-mismatch test initially found that the corpus builder could publish
a partial DB despite a manifest `records` mismatch. Root added strict count
validation and the regression now passes. Another synthetic test initially
found that merging new PASS text left a previously accepted phase 2 file in
the manifest after revocation; root fixed both replacement and the all-revoked
case. During collection, a notes file changed after its initial PASS (1,216
claims at SHA `d9196aa...`); the old evidence DB was stale. The auditor
re-accepted the revised 1,214-claim file at SHA
`c46fce81f2c76e8a4744d755790c7ccaf5df1d51a56607884aa96b64e369fb1b`,
the engine rebuilt, and runtime evidence lookup now fails closed if current
bytes, acceptance and indexed provenance diverge. The final gate above
confirms the current matching state.

## Retrieval interpretation limit

Word and form candidate pools often contain the same records, giving
correlated lexical signals two reciprocal-rank-fusion votes relative to dense
retrieval. The API exposes retrieval ranks and matched evidence so this is
inspectable, but RRF is neither probability nor independent corroboration.
The dense model's Ancient Greek quality remains unvalidated here; the live
search checks contract behavior and source separation, not ranking quality.
