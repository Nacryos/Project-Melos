# Deployment handoff

## Prepared, NOT deployed: release GLP — every poem in Campbell's *Greek Lyric Poetry* (2026-10-08)

Adds the 232 remaining Campbell poems (`campbell-glp:*`; audit `docs/audits/campbell-glp-full.md`)
and public-domain comparison translations for 209 of them. Live K3 is unchanged until this is run.

What ships (branch `worktree-agent-a6e935236d3ca4e7c`, on top of K3 source `b0934b4`):
- Corpus: `data/campbell_glp/campbell_glp.jsonl` imported into a copy of the live corpus by
  `scripts/import_campbell_glp.py` (idempotent; refuses to overwrite a differing row; the five approved
  Alcaeus rows are not touched). Passages **288,589 → 288,821**. Semantic manifest rebound to the new
  corpus (existing vectors kept; the 232 new ids listed as pending embedding, so they are found by word
  search and reading, not yet by semantic search).
- Backend code: `backend/translation_comparisons.py` (GLP sidecar loader) and
  `backend/translation_comparisons_glp_data.json` (sha256 pinned in the module). No frontend change: the
  reader's existing "English translation · another edition" panel renders these items.

Steps on Basecamp (needs ~1.7 GB free; disk was 98 % full on 2026-10-07):
1. Copy the source tarball of this branch to the box and unpack into `/home/alvin/melos-glp/src`.
2. `sh /home/alvin/melos-glp/src/deploy/release_glp.sh stage` — copies the live corpus
   (`releases/campbell-20261007b/candidate-data/corpus.sqlite`) to `/home/alvin/melos-glp/data/`, imports,
   rebinds `manifest.json`, then `verify_campbell_glp.py --corpus … --expected-passages 288821` must report
   `failures: 0` (receipts `import-receipt.json`, `verify-corpus.json`). Do not copy or touch the staged
   corpus afterwards (the manifest is bound to its mtime and size).
3. `… release_glp.sh build` (image `melos-api:20261008glp` from `Dockerfile.patch` atop QA29, as K).
4. `… release_glp.sh canary`, then on the box:
   `python3 deploy/smoke_backend.py --origin http://127.0.0.1:8792 --expected-passages 288821` and
   `python3 scripts/verify_campbell_glp.py --origin http://127.0.0.1:8792 --expected-passages 288821 --analyze sample`.
5. `… release_glp.sh promote` (K3 kept stopped as `melos-api-before-glp`; `rollback` restores it).
6. From anywhere: `python deploy/smoke_backend.py --origin https://greeklyric.com --expected-passages 288821`
   and `python scripts/verify_campbell_glp.py --origin https://greeklyric.com --expected-passages 288821`.
   From then on the production smoke expectation is **288,821**.

Not in this release: corrections to the five live Alcaeus texts (see the audit's findings table), BGE-M3
vectors for the 232 new passages.

## Current: release K3 — every intact word fully parsed (2026-10-07, night)

Public backend: image `melos-api:20261007k3`, same recipe and mounts as K
(`MELOS_K_TAG=k3 sh /home/alvin/melos-k/src/deploy/release_k.sh …`, source tarball
sha256 `e602bef35e4e0796e41fa020cf9279ec65955367b63cf5c9ec46d4cd0fbc66ee`). K2 kept
stopped as `melos-api-before-lexical-20261007k3`; canary as `melos-api-lexical-canary-k3`.
Adds over K2: second ranking pass from neighbours' resolved parses (τὼ ξίφεος,
ἄχω θεσπεσία), precedents from settled readings of the same form (νᾶϊ), fullest
same-lemma row across a wrongly predicted feature (ἄεθλον acc. neut. sg.), genitive
patronymics, labelled top-ranked proposals for tied nominals (γλαύκας), open
supplements at a line end labelled conditional (Μύρσιλ̣[ο).

Verified on https://greeklyric.com:
- Production audit (`runtime/dev/audit-13-production`): **305 of 305 intact words
  with complete parse fields**, 16 damaged letter-runs labelled, 201 words with a
  selected gloss.
- `scripts/check_span_parses.py --random 30`: every printed line plus 150 random
  2–5 word spans across the five poems, 227 multi-word selections, 821 word rows,
  **0 failures**.

## Current: release K2 — last tier, damaged pieces, ranking refinements (2026-10-07, later)

Public backend: image `melos-api:20261007k2` (`sha256:6f6086d02cd5…`), built on
Basecamp from the K2 source tarball (sha256
`0414035862ce771454d2cfbeaea80c22de93e3625b01a16957fdf58c079a9091`) with the same
recipe and mounts as K (`MELOS_K_TAG=k2 sh /home/alvin/melos-k/src/deploy/release_k.sh …`).
K is retained stopped as `melos-api-before-lexical-20261007k2`; the K2 canary as
`melos-api-lexical-canary-k2`. Canary passed `smoke_backend.py --expected-passages 288589`
and the probes; public origin verified after promotion (ἴφθ]ιμοι voc. masc. pl.,
Ὕρραον acc. masc. sg. by ending pattern, ἔοι̣ 3rd sg. pres. opt. act. conditional,
ς̣βιότοις̣ dat. masc. pl. of βίοτος conditional, ἤπειτα adv. via ἔπειτα).
Morpheus cache: 350 receipts (empty-result receipts and the new normalisation
variants imported). Frontend: Vercel `project-melos-39qawr5j0` aliased to
greeklyric.com (labels for damaged pieces and ending-only analyses).

What K2 adds over K (`docs/morphology.md`, "Last tier"): ending-based pattern
analyses for words no lexicon knows; `damaged_piece` labels for letter-runs beside
lacunae (excluded from word counts); uncertain-edge-letter variants; more Aeolic
rules and a Lesbian lexical table; ranking: nom./voc. folding except under a
vocative prediction, adjacent-nominal agreement, featureless predictions treated as
none, fuller same-lemma rows win, exact attestations outrank parser guesses,
POS filled from the prediction; the syntax provider now waits up to 20 s for a
concurrent analysis instead of dropping the prediction (audit chunks had lost
their predictions to `provider_busy`).

Dev audit 8 (`runtime/dev/audit-8`): 298 of 306 intact words complete, 15 damaged
pieces labelled, 194 words with a selected gloss (109 at K). Backend tests: 1880
pass, 1 expected frozen-manifest failure. Production audit after promotion
(`runtime/dev/audit-9-production`, through https://greeklyric.com): 299 of 306
intact words complete, 15 damaged pieces labelled, 195 words with a selected
gloss. The seven residual words: Ὦγεσιλαΐδα and τυνδέων (ending-pattern parses
without a determinable gender), γλαύκας and τὼ (genuine ties left as consensus),
Μύρσιλ̣[ο and ἄχω (model prediction only), ον̣ beside a lacuna, νᾶϊ and ἄεθλον
(prediction conflicts in the 80-word audit window).

## Historical: full parses for every printed word, release K (2026-10-07)

Public backend: image `melos-api:20261007k`
(`sha256:f441cca71f37bc12d4d523a5b40b379494918dd90f2da92ac40a1577e319d90c`), built
on Basecamp with `deploy/Dockerfile.patch` atop the verified QA29 base
`melos-api:20261005-qa29` from the K source tarball (sha256
`ab0007aa1c353b0d92ba27dc39aa7ad2ea73a0462694038f58549bfe4266c7f0`, unpacked in
`/home/alvin/melos-k/src`; `releases/` is root-owned). Unlike E–I, K carries the
whole `backend/` package in the image with **no per-module bind overlays**; the
data, models, syntax-model, runtime, corpus (`campbell-20261007b`) and secrets
mounts are the live I mounts. New environment: `MELOS_MACHINE_GLOBAL_DAILY=1000`,
`MELOS_MACHINE_GLOBAL_MINUTE=30`, `MELOS_MACHINE_VISITOR_DAILY=100`,
`MELOS_MACHINE_VISITOR_MINUTE=10`. Recipe and rollback:
`deploy/release_k.sh build|receipts|canary|promote|rollback`.

Promotion path: canary `melos-api-canary` on 8792 passed
`deploy/smoke_backend.py --expected-passages 288589` and the five-poem probes;
`qa_regressions.py` fails identically against I (stale "Ibycus 286" expectation
without `--cgl`), so it is not a K regression. I is retained stopped as
`melos-api-before-lexical-20261007k`; the K canary is retained stopped as
`melos-api-lexical-canary-k`. Verified through the public origin after
promotion: ἦλθες `2nd sg. aor. ind. act.`, νᾶ̣]σον `acc. fem. sg.` (νῆσος),
λίποντε[ς `nom. masc. pl. aor. act. ptcp.`, εὐρύσαο `2nd sg. aor. ind. mid.`
(via ἐρρύσαο), ῤήα adv. (via ῥήα).

Morpheus cache: 331 receipts in `runtime/machine_morphology.sqlite` (was 26):
every printed word of Alcaeus 34a, 129, 130b, 326, 350 plus the labelled
Aeolic normalisations, imported with `deploy/sync_morphology_receipts.py import
--apply` from `runtime/dev/receipts-bundle.json` (sha256
`0c10830a0ee0fe00bf3016907e08b9f757131248e2569a12199de8d2abf4b48f`; empty-result
receipts are now exported too).

Frontend: Vercel production `project-melos-nfdrtedjl-nacryos-projects.vercel.app`,
aliased to https://greeklyric.com (`vercel deploy --prod --yes --build-env
MELOS_READER_ONLY=1`). The reader now opens each Greek text with a
`POST /api/passage-morphology/warm` call, requests a parser fetch on single-word
clicks, shows the editor's reading of bracketed words and "Parses ranked by fit
to the context".

Local five-poem audit (`scripts/audit_alcaeus_occurrences.py` against the dev
server, `runtime/dev/audit-4`): 301 of 321 printed words have complete parse
fields (baseline: 227 of 269 intact segments, with 119 bracket fragments
unparsed); the 20 remaining are damaged pieces beside lacunae (labelled
conditional) and a few proper names/hapax forms the parser does not know. Design
and ranking rules: `docs/morphology.md`, "Full parses for every printed word".

Backend tests at promotion: 1876 pass; the only failure left is
`tests/test_run_commentary_relevance.py` (its frozen manifest pins the previous
`sense_ranker.py` hash; the commentary-relevance cues are now gated behind
`MELOS_COMMENTARY_RELEVANCE=1`, off in production).

## Historical: gzip backend and grouped reader I (2026-10-07)

Public backend: `f888ab8692593446a2495b3543be2ce7274bfcd672cc0d5f8379083af8f50a19`,
release `/home/alvin/services/melos/releases/lexical-20261007i`, unchanged QA29 image.
I adds only negotiated large single-body JSON gzip and its four-line server
registration. No dictionary, corpus, runtime cache, parser or vector changes.
Independent review passed 79 relevant tests; actual private HTTP checks proved
byte-exact identity/gzip equivalence, explicit gzip refusal, and non-JSON/small
response passthrough. The sampled dictionary response shrank from 717,597 to
119,024 transferred bytes. Compression does not reduce lookup CPU or decoded
browser payload size; no general latency claim is made.

Root approved the exact private canary in
`runtime/lexical-release-i/canary-promotion-pass.json` (SHA256
`601ece8f5170c67da0f260599471cc2f9fc5c6afbca959a4f67d188d553a5781`).
Guarded promotion verified preserved resources, environment, source databases,
semantic coverage and routes. H is retained stopped as
`melos-api-before-lexical-20261007i`; private I is also retained stopped.
Root repeated all nine raw-transport probes against the public backend
`https://basecamp.taila44c41.ts.net:8443`: PASS, matching the private decoded
bytes exactly. Final receipt `runtime/lexical-release-i/live-verify.json`, SHA256
`ff5108c9c7bc42023878fff8afbf0d7488a6ce3b7251f99a2b90c8efa83bc07c`,
binds those bodies, exact deployed modules, retained rollback, unchanged
environment/resources and preserved routes. This raw-transport test targets
the backend endpoint; the separate browser check below targets greeklyric.com.

Reader-I frontend: `dpl_4t9JqwmbUUAtJsKqXAoghEKVrRY1`,
https://project-melos-8bypsq3yq-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Root verified the public reader using computer use:
the complete aorist parse and “come or go” remain visible; duplicate source
records group together and expand to their original incomplete analyses.
Distinct noun/adjective readings remain separate in the private checks.
This verifies the tested grouping and default dictionary presentation, not
universal parsing or contextual meaning accuracy.

Optional isolated CPU diagnostic completed with network disabled, read-only
mounts, one CPU, 4 GiB and a 120-second limit. No serving worker was modified.
`runtime/lexical-release-i/isolated-word-profile-r3.json` records 12.99 seconds
of initial warmup and 2.288 seconds across five second-pass profiled lookups;
70 source-entry renders consumed 1.472 cumulative seconds (about 64% of the
profiled lookup time). These are diagnostic-process timings with profiler
overhead, not HTTP latency or a philologically representative benchmark.
The automatic selector included `ις`, which is not independently certified
as an intact word. No rendering optimization was deployed with I.

## Historical: source-tense dictionary headlines H (2026-10-07)

Public backend: `e37c1e216b508388caa8d9260298390b59edc9b5bf07b3d825fc5d3fb3b68eda`,
release `/home/alvin/services/melos/releases/lexical-20261007h`, unchanged QA29 image.
Immutable H-r2 reader frontend: `dpl_BiSgFewQxH9JPQ4UyE3BgqZmPzLk`,
https://project-melos-8vw4pzmdi-nacryos-projects.vercel.app. Root verified
the four live JavaScript files against the frozen H-r2 artifact during this
completed rollout; the dirty working tree was not deployed.
Root also reloaded the public reader and clicked `ἦλθες`: both the searched-form
card and the separate source-definition excerpt visibly showed “come or go”,
with the complete aorist parse. This verifies that default dictionary correction
in the live UI, not universal contextual sense accuracy.

Only `lexicon_senses.py` and `interlinear.py` changed in the backend, with 282
exact-stage tests passing. The narrowly audited LSJ backward-reference note
marks two senses as present-only. For known aorist candidates, those senses
no longer supply the dictionary headline. No missing tense is inferred, and
all 14 literal LSJ senses remain available in the expanded source inventory.
The visible `ἦλθες` compact meanings now start with “come or go”; its full
second-person singular aorist indicative active parse is retained.

Final verification: `runtime/lexical-release-h/live-verify.json`, SHA256
`774feeebfadd6b6682580efcd982adaa0b3976de83b53fa61d5ed69594884b80`.
Eleven bounded live HTTP probes verified the exact two-response tense case,
five contextual parses and both linked inventories (15/11 senses). Exact
source text, 88 commentary paragraphs and five English comparisons remain
unchanged, as do environment, resources, routes and the original runtime.
No cached receipts, counters, corpus rows or vectors were imported or replaced
for H. No paid calls or upstream morphology fetches were requested.

G is retained stopped as `melos-api-before-lexical-20261007h`, ID
`b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb`.
Private H `07f6ceacbe94e4f509aee1ce3ce8b54fc430d44d39d5ff18072f93acf5026ae9`
is retained stopped after production warmup. This fix does not resolve every
candidate identity: a single interlinear gloss may remain unavailable while
compatible candidate meanings are shown separately. The large whole-poem
payload/performance problem documented under G also remains unresolved.

## Historical: contextual alternatives and editorial readings G (2026-10-07)

Public backend: `b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb`,
release `/home/alvin/services/melos/releases/lexical-20261007g`, unchanged QA29 image.
Reader-only frontend: `dpl_74H2frBj2KHABBc8LGrfzXbyRuKX`,
https://project-melos-nr5bfctdd-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. This is the immutable reviewed G frontend, not the newer
H working files. Discovery pages remain unpublished.

Ten narrow backend overlays passed 410 exact-stage tests. G adds source-owned
noun gender, unresolved homograph inventories, ranked uncertain sense alternatives,
documented elision transport, and separately displayed conditional editorial
readings. Larger sense packets retain all alternatives through reversible short
IDs. Capacity limits are character proxies, not a guarantee of Jev token fit.
The commentary instruction was clarified after the eight-call experiment;
thresholds remain unchanged and no accuracy improvement is claimed.

Final public verification: `runtime/lexical-release-g/live-verify.json`, SHA256
`0173d2319ab11cd5453b0d0d6738e84f4c3a522d0a105d9e0e081643ad225f00`.
It binds all ten module hashes, unchanged environment/resources/routes, the five
exact Greek texts, 88 commentary paragraphs and five English comparisons.
Public probes preserve full `ἦλθες` parsing, all 15/11 linked senses, and verify
eight cached source forms against exact receipt IDs and candidate counts.
Eight editorial API chunks retain 54 source rows, with 26 eligible conditional
projections and 10 having source-backed analysis. Missing analyses remain missing;
printed supplements are not promoted to securely transmitted text.

Public whole-poem analysis is functionally correct in these checks but still
too heavy: some raw responses were roughly 38–46 MB and took tens of seconds.
This known repeated-provenance payload problem is not fixed by G. No low-latency
or universal philological accuracy claim is made.

Eight audited Morpheus receipts were imported after preview using G's validator.
Independent audit `runtime/lexical-release-g/public-import-audit.json` (SHA256
`1311e6cbd84469163ee544a616fa0ee84ddfa234be8f606225a57145759d2099`)
proves the previous 18 cache entries, 18 receipts and 15 attempt records remain
unchanged, including the separate maintenance additions; cache/receipt totals
are now 26/26. No operational counters or in-flight records were imported.
No paid calls or upstream parser fetches were requested by release verification.

F is retained stopped as `melos-api-before-lexical-20261007g`, ID
`e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52`.
Private G `bc0e2210c9dd78928250b875bbb861cc5ad4b35d7ba5608c33f1e87f4474e8ed`
is stopped; its separately audited SQLite snapshot/import never replaced the
production runtime. Source databases, corpus, vectors, quotas, secrets and
Basecamp/private routes were preserved. Five Campbell embeddings remain pending.
The optional H tense-restriction change is not included in this release.

## Historical: source-linked dictionary and comparison release F (2026-10-07)

Public backend is `e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52`,
release `/home/alvin/services/melos/releases/lexical-20261007f`, on the unchanged
QA29 image. Frontend is reader-only deployment
`dpl_GQjuM5iMG9pHRLtWtXmGCdV1VhHG`, aliased to https://greeklyric.com.
The rejected discovery pages remain unpublished.

Nine exact backend overlays add source-linked dictionary alternatives and
five source-bound English comparisons from other editions. The comparisons
remain explicitly unaligned with Campbell's Greek, retain translator/source/
license labels, and are reader context rather than model translation evidence.
No corpus, vector, evidence index, source index, secret, resource or route
changes were made. All five Campbell Greek texts and 88 commentary paragraphs
match the approved artifacts. Existing 116,191 semantic vectors remain ready;
the five Campbell poems remain explicitly pending embeddings.

Independent module approval: `docs/audits/lexical-context-backend-f.json`.
Root's public promotion authorization:
`runtime/lexical-release-f/canary-promotion-pass.json`, SHA256
`6095acc72e42937180e5423a0b951d606d44ebce979d1ddde2b7421b2a19f4b9`.
Post-promotion verification: `runtime/lexical-release-f/live-verify.json`, SHA256
`8705c33914134eacfbc3596f26c19a55737f49f852f03e4203c9110d9edc9524`.
That receipt binds exact live module hashes, retained E, stopped private F,
unchanged resources/environment/routes, all five source/comparison checks,
and nine public HTTP probe receipts without paid ranking or parser fetching.

Public probes preserve the full `ἦλθες` second-person singular aorist indicative
active parse. All 15 source-linked senses for `παχέων` and 11 for `δᾶμον` reach
the ranking input. Root separately checked the live browser: the English
comparison expands with attribution, and the cubit dictionary path appears
alongside distinct competing adjective entries. This demonstrates source
coverage and functionality, not universal parsing or sense accuracy.
The one authorized private Jev trial favored the cubit sense at an uncalibrated
0.57 and remained uncertain; no further paid calls were made for deployment.
Conflicting predictions for `τάλαις` and `ὄππᾳ` remain suppressed. The subsequently
identified prompt contradiction is not fixed by F and belongs to follow-up work.

E is retained stopped as `melos-api-before-lexical-20261007f`, ID
`0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5`.
Private F `36de860ef7770eeb649f1a5e522c76cd5eb275c984ca570c775ae5f6b0b1f4d6`
is retained stopped after the production warmup. Funnel 8443 still serves
localhost 8791; Basecamp 80/443 remain private and unchanged.

The following sections are historical release snapshots, not current status.

## Historical: commentary-ready reader display (2026-10-07)

Live frontend: `dpl_HFbuHTZF2kbEJB14k15kqYWrnh1o`,
https://project-melos-knym4dnfb-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Reader-only build; 378 frontend tests pass.
Live `reader.js` and `passage-analysis.js` bytes match independently reviewed
hashes `045e53ce9bf7cc9713162fc073a7aebb95e721163a737b9118e799db30baee22`
and `7719a2c97a0893b4633e6b2c6a9d42301de5ae23e8c90bb8173661bccfb617c9`.

Exact lexical variants no longer trigger false dictionary-absence copy when
only a complete morphological parse is unavailable. New source-bound
commentary rendering is backward compatible with the current D backend:
whole-poem notes stay collapsed, while literal NFC printed-heading matches
can appear beside an intact clicked word. No accent folding, substring
matching, cross-poem binding or inferred word attestation is permitted.
Uncertain OCR paragraphs cannot become these heading matches.

E backend is live: `0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5`,
release `/home/alvin/services/melos/releases/lexical-20261007e`. It adds an exact
neighboring syntax window for long poems and the audited commentary sidecar.
Independent staged review: 360 application tests and 31 deployment guards.
Root approval: `runtime/lexical-release-e/canary-promotion-pass.json`.
Final verification: `runtime/lexical-release-e/live-verify.json` (SHA256
`ab4a5e0f28830117d169df1ce437cb8ee98f3ba902251298429afd65ed49ed77`).
Root independently repeated the five public context checks in
`runtime/lexical-release-e/live-root/`; all five Greek texts and all 88 reader
commentary paragraphs remain bound to approved sources. The model receives
87 paragraphs, excluding the uncertain OCR paragraph. Browser verification
confirmed the immediate Campbell note on clicked `στάσιν` and the expanded
whole-poem commentary panel on live fragment 326.

The old local test tunnel had expired; its failed request receipt is preserved
under `runtime/lexical-release-e/operational/`. The replacement tunnel was
verified before the explicit successful retry in `operational-restored-tunnel/`.
D is retained stopped as `melos-api-before-lexical-20261007e`; private E is
retained stopped. Existing corpus, vectors, resources and routes are unchanged.

Newer 23-sense saved `στάσιν` packets initially exceeded the unchanged 32k
classification budget. Lossless common-field sharing now retains all 23
choices and the eligible commentary at 30,817 characters. One actual paid
Jev sense call completed in 2.293 seconds: it favored the literal LSJ sense
"position in relation to the compass" at an uncalibrated 0.68, below the
decisive threshold; no definitive gloss was substituted. The morphology
comparison abstained before a provider call. See `jev-stasin/` receipts.

This is not universal accuracy: long-window predictions for `τάλαις` and
`ὄππᾳ` still conflict with source lexical identity and remain suppressed.
`δᾶμον` now has a compatible contextual prediction but no resolved meaning.
`παχέων` retains a possible `παχύς` analysis; Campbell's royal-cubit discussion
exposes the missing alternative. Source investigation found explicit Kaikki
links from quantity-marked `πᾱχέων` to `παχέων#Ancient_Greek`, and from
`πᾶχυς` to `πῆχυς`; source-link alias support is being developed separately.
The separately audited five English translation comparisons remain staging
only, without reader/model integration or exact Campbell alignment.
The independently audited `backend/dictionary_crossrefs.py` resolver is also
staged only. Do not claim its source-backed alternative meanings are live.

## Exact-form dictionary display cleanup (2026-10-07)

Live frontend: `dpl_5ZaetrW4yGf9hnbHyanUABzMZ1Ze`,
https://project-melos-cumk6reie-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Explicit `MELOS_READER_ONLY=1` build; `/lexicon`,
`/authors`, and `/themes` remain 404. All 365 frontend tests pass; the three
changed live JavaScript files match local reviewed hashes. Exact NFC form
scope now separates normalized matches from exact grammatical evidence.
Inherited headword form-of prose from the actual Wiktionary `ἦλθον` payload
no longer appears as a meaning of table-matched `ἦλθες`. Exact lexical
variant display is now backed by release D's live API fields.

Public backend is release D (`71c6555a265f83a01f781e3673a815a073c2ed9bc7f8153d36297b8f6797b0c0`),
release directory `/home/alvin/services/melos/releases/lexical-20261007d`.
Five exact module overlays passed 301 application and 23 deployment guard
tests; audit: `docs/audits/lexical-context-backend-d.json`. Root's separate
canary approval is `runtime/lexical-release-d/canary-promotion-pass.json`.
Production verification: `runtime/lexical-release-d/live-verify.json` and
root's independently repeated public probes in `runtime/lexical-release-d/live-root/`.
The five approved Campbell texts, corpus, vectors, and Basecamp routes are
unchanged. B is retained stopped for rollback as
`melos-api-before-lexical-20261007d`; C and D canaries are retained stopped.

Exact source features now survive incomplete or conflicting model parses:
`ἦλθες` shows `2nd sg. aor. ind. act.` and `δᾶμον` sourced `acc. sg.`.
Exact lexical variants retain meanings without a fabricated full parse.
Contradictory standalone model parses for `ὄππᾳ` and `τάλαις` are suppressed;
the raw model predictions remain separate. Never promote the older C release:
its operational probes exposed these contradictions. C artifacts are frozen.
The audited surrounding-context window helper is not yet integrated or live.

Fresh source-occurrence baseline: 388 segments, 119 API-flagged damaged
segments and 269 unflagged (not independently certified intact words).
Only 47 selected English glosses, 120 occurrences with any candidate gloss,
and 137 with exact-surface source/contextual candidates. These are coverage
counts, not accuracy scores. See `runtime/alcaeus-occurrences/baseline/`.

New source packages remain STAGING ONLY, not live context:

- `runtime/campbell-commentary/commentary-candidates.jsonl`: five records,
  88 retained paragraphs, package SHA256
  `3e33ec114f43058f62553d4f6764f65c0e7bc655b204376c7ac82b063c07335a`.
  Independent pixel/package approval under its `audits/` directory. Two
  unreliable OCR paragraphs excluded; one documented unreadable glyph remains
  unsuitable for exact lexical evidence.
- `runtime/alcaeus-translations/translation-candidates.jsonl`: five audited
  English comparisons, Edmonds for 34a/326/350 and Lowell Edmunds for 129/130b.
  None is asserted to be an exact translation of the Campbell Greek. Preserve
  edition differences, translator attribution and original rights labels.

The goal of accurate contextual meanings and full source-backed analyses for
all words/spans remains incomplete. Do not report successful requests or
passing code tests as universal linguistic accuracy.

## Contextual dictionary and complete-parse repair (2026-10-06)

Live frontend: `dpl_8z6qJU4nuhg78NRvGZaJ4HghSWmJ` at
https://greeklyric.com, built explicitly with `MELOS_READER_ONLY=1`.
The rejected discovery routes still return 404. All 348 frontend tests pass.

Live backend: `ec2cdc5176ed0f747cb03de0037d7bfb1bc00e93644fae7fbf761822e6eb6aa5`,
release `/home/alvin/services/melos/releases/lexical-20261007b`, with five
hash-verified module overlays on the unchanged QA29 image: `classifier.py`,
`interlinear.py`, `lexicon_senses.py`, `passage_analysis.py`, `sense_ranker.py`.
The prior Campbell container is retained stopped as
`melos-api-before-lexical-20261007b`; both lexical canaries are stopped and
retained. Corpus, embeddings, secrets, environment, resource limits and
private Basecamp routes are unchanged. Independent module approval:
`docs/audits/lexical-context-backend-b.json` (274 tests, canary eligibility only).
Actual operational promotion evidence:
`runtime/lyric-context-eval/canary-b-promotion-pass.json` and
`runtime/lyric-context-eval/live-b-verify.json`.

Hyphenated Wiktionary person tags now survive projection. Coarse UD Past no
longer incorrectly contradicts a source's explicit aorist; it never supplies
an aorist by inference. Partial source analyses cannot displace an otherwise
compatible fuller analysis. When exact source alternatives agree on a complete
parse but lexical identity remains unresolved, the parse can be displayed
without choosing a dictionary homograph or inventing a gloss.

The new explicit **Read in context** word action uses Jev to choose an existing
English dictionary sense independently of resolving every morphological
alternative. Full passage hashes, source-entry/sense/candidate bindings and
stale-response guards are checked. No automatic paid calls on word selection.
Shared packet-local references reduce repeated metadata without dropping
meaning choices; source coordinates stay bound in the server inventory hash.

Bounded actual canary results: ἀνέμων → "wind", κῦμα → "wave, billow", and
ἦλθες → "come or go"; στάσιν remained uncertain with all 23 senses retained.
These are three useful proposals and one abstention, not an accuracy benchmark.
Live browser verification confirmed the four-word phrase ἦλθες ἐκ περάτων γᾶς
shows **2nd sg. aor. ind. act.** for ἦλθες, and its word inspector's explicit
context action shows "come or go" with that full parse.

Known gaps remain: default phrase analysis does not automatically run Jev;
περάτων still lacked an English preview in that phrase; source-order dictionary
previews and form-of headword descriptions can still be unhelpful. Do not claim
universal morphology or contextual-meaning accuracy. The staged 717-entry LSJ
subentry index was NOT shipped: its independent audit found a source-tagging
error producing a truncated definition, documented in
`docs/audits/lyric-subentries.json`.

## Campbell Alcaeus assignment release (2026-10-06)

Frontend: `dpl_B9ZWF9NfiHe6nu4RyiwEZxEYgemj`, aliased to
https://greeklyric.com. Explicit reader-only production build; rejected discovery
routes remain 404. Includes five source-facsimile pages, immutable excerpt-image
caching, and editorial-segment lookup guards. All 330 frontend tests pass.

Backend candidate: `/home/alvin/services/melos/releases/campbell-20261007b`.
Five IDs: `campbell-glp:alcaeus:{34a,129,130b,326,350}`. Campbell prints the
assignment's 130b as 130; citation metadata explicitly indexes both references.
Source JSONL SHA256: `afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b`.
Independent acceptance: `runtime/campbell-assignment/integration-pass-v2.json`.
Production promotion passed the final canary gate. Live container:
`99ac41bf357439a2e07bb69cde3f279b6bf8ae8b89690c8cc7d9ee28be517460`.
Original QA29 container `cc62bec35b7b...` is retained stopped as
`melos-api-before-campbell`; routes, environment and resource limits preserved.
Both private Campbell canaries are stopped and retained. Promotion receipt:
`/home/alvin/services/melos/releases/campbell-20261007b/promotion-receipt.json`.
Public UTF-8 API verification matched all five exact Greek text hashes and
all five reference searches after promotion.

The immutable QA29 image is retained with exactly two audited read-only module
overlays: `passage_analysis.py` and `interlinear.py`. These preserve damaged
Greek segments, attach exact dictionary entries to machine lemma hypotheses,
and avoid displaying a sole syntax prediction when explicit candidates
contradict it. Machine alternatives do not become source attestations.

Scope limitations: tiny glyphs in 34a remain explicitly uncertain; source
facsimiles are available for comparison. These records have no aligned English
translation. Existing 116,191 semantic vectors are unchanged; the five new
records are explicitly pending embedding. Do not claim complete contextual
parsing accuracy or complete dictionary coverage from HTTP/offset tests.

QA artifacts live under `runtime/alcaeus-assignment-qa/`. The baseline full run
tested 227 distinct printed lookup segments (not necessarily complete words):
149 had exact indexed parses; 166 had displayable sourced English dictionary
previews. All 60 sampled phrase analyses preserved source text and offsets;
28 literal phrase searches and 10 intact Forms searches retrieved their target.
Editorial/lacuna barriers are reported separately, not repaired for matching.

Final V2 QA report SHA256:
`1916a8e4b5f7160caa00878b7fe8183a80a30d9945a1092148d60bb44d6b6bef`.
Word/Wiktionary results were reused only after checking unchanged code/image
and all 227 exact source-context hashes; all 60 phrase checks and reference
navigation checks were freshly repeated against V2. Three additional cached
Morpheus projections were rechecked without new external model/parser calls.

Live browser verification covered fragment 326 word lookup, endpoint-based
four-word selection, successful analysis, Same wording retrieval (Campbell
plus a separately labelled other edition), and fullscreen artwork. Important
unresolved semantic regressions: the word preview for `στάσιν` leads with
source-order senses "erection" and "standing stone, pillar", not an adjudicated
meaning in this poem; OdyCy proposes adverb for `ἀσυννέτημμι` when no exact
indexed candidate is available. Operational QA is not philological approval.

## Fullscreen artwork and touch selection fix (2026-10-06)

Live: `dpl_EVjdaLHk6ahtiXTcDmh4q1yz9EoU` at https://greeklyric.com.
Built with `vercel deploy --prod --yes --build-env MELOS_READER_ONLY=1`.
The old hero/reader remain; discovery navigation is absent and `/lexicon`,
`/authors`, `/themes` return 404. Discovery source remains local. Backend QA29
was not changed. Do not use ordinary preview promotion for this profile:
promotion rebuilt using production settings and dropped the one-off build
environment; the explicit production build above corrected that immediately.

Fullscreen loads a real decorative image eagerly, preserves the CSS fallback,
uses one dark overlay, and has a fixed-overlay fallback for missing/failing
native dialog support. Touch-friendly Select phrase lets readers tap endpoints;
native selection remains available. The selection dock tracks the exit toolbar
height and becomes nonsticky on short landscape screens to avoid covering text.

327 frontend tests pass, including missing/throwing modal APIs, image failure
fallback, selection ranges, and reader-only build isolation. Browser QA verified
artwork and four-word selection at 390x844 and 844x390 in Chromium. Actual iOS
Safari hardware testing was not available; do not claim all-device verification.

## Discovery frontend rolled back at owner request (2026-10-06)

The owner rejected the current lexicon arrangement and author portraits/names.
Live Vercel was restored to the pre-discovery nature-header deployment
`dpl_GXF8m6Md3c8xdpzw9KxmrQNAv4vF`. The discovery implementation is retained
locally, not discarded, at http://127.0.0.1:8792/ with its local API on 8791.
The exact pre-discovery QA29 backend container `cc62bec35b7b...`, image
`sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777`,
was restored and publicly verified; new discovery API routes again return 404.
`tools/serve_timeline_preview.py` now serves the three discovery routes and
their public assets. Do not redeploy this design without the owner's approval.
The earlier release descriptions below are historical, not current live state.

## Discovery routes release (2026-10-06 Pacific)

Production `dpl_4YFGiy5cncWfMaK8k5GYBno1QwSU` is aliased to
https://greeklyric.com. The original hero/reader remain, with three new entry
cards and `/lexicon`, `/authors`, `/themes`. Vercel builds use their own API
rewrite, avoiding cross-origin production calls from preview deployments.

The author catalogue contains 13 source-extracted Wikipedia biographies,
10 image-backed profiles, and two DCC commentary excerpt instances. Original
images are unchanged; CSS framing provides portrait details. Expanded pictures
precede biographies. Revision, license and image provenance remain accessible.
The old local timeline preview remains intact.

Browser checks covered English `love` lookup, Greek `ἄνθρωπος`, Sappho's
expanded portrait/biography and real work-to-passage navigation, garden category
results, line-level `love and longing` within Sappho, and phone-sized layouts.
The last query exposed editorial-only semantic hits; a focused backend fix
excludes spans with no printed Greek letters without changing source texts.
See `discovery-release.md` for backend image identities, tests and rollback.

Limits: English definitions currently inspect up to 256 source-entry candidates.
Child semantics encode a bounded sample on demand (at most 64 spans across 16
retrieved parents), not a complete materialised hierarchical index. Stanzas
require explicit blank lines; sentence/phrase boundaries are heuristic. Literary
categories launch discovery searches, not certified poem classifications.
Ancient Greek semantic rankings remain exploratory, especially for lacunose text.

## Nature-header preset release (2026-10-05 Pacific)

Production deployment `dpl_GXF8m6Md3c8xdpzw9KxmrQNAv4vF` is aliased to
https://greeklyric.com. Five owner-approved landscape images are served as
content-hashed 960px and 480px WebPs from `/assets/nature-presets/`, with
one-year immutable caching. Originals and portrait favourites remain local.

`tools/build_nature_presets.py` rebuilds the selected images;
`tools/build_nature_assignments.py` exports only existing source-validated
positive aesthetic annotations (247 records: 169 Greek, 78 translations).
Both support `--check`. The public export contains IDs, hashes and theme IDs,
not source text or private file paths. Runtime matches exact record ID and
SHA-256 of the returned text; missing/stale annotations use a decorative grove
default, not a new theme classification.

The plain reading view stays white. Only fullscreen poem headings consume
the image under the existing dark overlay. `js/nature-presets.js` exposes a
reusable preset registry and lazy assignment accessor. Background images warm
sequentially at low priority after the hero painting queue; data-saver/2G skips
speculative warming. Opening fullscreen explicitly warms the selected image.
No backend deployment, paid inference, corpus edit or runtime generation is
required. Existing Hetzner service remains unchanged.

Checks: 272 frontend tests, 14 annotation/export tests, deterministic asset
verification, production asset/cache checks, and live fullscreen browser QA.

Melos has two deployable parts. Vercel serves the static reader and design studio. A separate persistent Python service serves `/api/*` from the accepted corpus, dictionary, and search indexes. Deploying the frontend alone does not make the reader functional.

## Static frontend

Create a Vercel project from the public Melos GitHub repository, with the repository root as the project root. `vercel.json` runs `npm run build` and serves only `dist/`. The build copies an explicit set of HTML, CSS, JavaScript, and generated painting assets. It places the research reader at `/`, the original design studio at `/legacy` (also `/design-studio`), and keeps `/reader.html` as a reader alias. No `data/`, Python code, source paintings, reports, model files, or credentials are in the output.

Set `MELOS_API_ORIGIN` in the Vercel project's environment variables to the public HTTPS origin of the separately hosted API, such as `https://api.your-domain.example`. This is a public address embedded into `dist/js/config.js`, not a secret. The production build fails if it is absent, local, or HTTP. Set it for each Vercel environment that should build. Do not set it to the Vercel frontend origin unless that origin actually routes `/api/*` to the live service.

For a local static artifact check without a deployed API, run `npm run build:preview`. It generates a same-origin API configuration for local preview only. For a production build check, set `MELOS_API_ORIGIN` to the intended public HTTPS API origin and run `npm run build`.

To publish the design before backend hosting is available, explicitly set `MELOS_FRONTEND_ONLY=1` instead of `MELOS_API_ORIGIN`. This produces a labelled frontend preview with search disabled and no API network requests. It is not a functioning public corpus reader. When the API is ready, remove `MELOS_FRONTEND_ONLY`, set `MELOS_API_ORIGIN`, and redeploy. Conflicting settings fail the build. Run `npm run test:frontend` to check the configuration guards and API routing.

## Persistent API service

Host `backend.server:app` on a service with persistent storage for the accepted indexes and enough memory and CPU for search and embedding loads. Build and audit the corpus and indexes using the procedures in [reader.md](reader.md) before making the API public. The API host must serve over HTTPS, expose a health/status endpoint at `/api/status`, and be reachable from browsers visiting the Vercel domain. Do not put the corpus, SQLite databases, downloaded source records, model weights, or API credentials in the public GitHub repository or the Vercel static artifact. Arrange backups and a documented index rebuild path for the persistent data.

Configure the API's `MELOS_CORS_ORIGINS` with the exact Vercel production and preview origins that should access it, and set `MELOS_PUBLIC_DEPLOYMENT=1` on the public API host. Browser CORS must allow the reader's read requests. Verify the API status, author/work listing, search, passage, word lookup, and usage space from the deployed frontend origin. A local browser test against `127.0.0.1` does not establish that public users can reach the API.

Any hosted classification credential (`TYPESAFE_API_KEY` or `JEV_API_KEY`) belongs only on the API host. The frontend never contains it or calls TypeSafe directly. Public `/api/classify-context` requires explicit `MELOS_PUBLIC_CLASSIFIER=1`; otherwise it remains local-only. The enabled route accepts only small JSON requests naming an existing corpus passage and form, constructs the source evidence server-side, and passes paid decisions through durable cache/quota checks. CORS and browser-session cookies are not authentication; the global persistent quota bounds new provider attempts even when cookies are reset or the Funnel endpoint is called directly.

## Release check

1. Complete the accepted corpus and indexes, and verify local backend tests and `/api/status` report the intended coverage.
2. Provision the persistent HTTPS API service and set its exact allowed frontend origins. Check read endpoints and operational limits.
3. Configure `MELOS_API_ORIGIN` in Vercel. Build the static artifact and inspect `dist/` for only the allowed frontend paths. `dist/` is Git-ignored.
4. Deploy a Vercel preview and test reader searches, passage navigation, word inspection, usage space, design studio, and unavailable-service states in a browser. Confirm contextual comparisons are labelled as model proposals, repeat decisions use the cache, quota errors are clear, and no keys or corpus files appear in deployed assets.
5. Promote only after the preview checks pass and the operator has selected and documented the publication policy. Extraction acceptance does not itself establish redistribution permission.

Vercel project configuration follows its [build and output directory](https://vercel.com/docs/builds/configure-a-build) and [routing configuration](https://vercel.com/docs/project-configuration/vercel-json) documentation.

## Published frontend (2026-09-30)

- Vercel project: `nacryos-projects/project-melos`, connected to `Nacryos/Project-Melos` on GitHub.
- Custom domain: <https://greeklyric.com>; Vercel alias: <https://project-melos.vercel.app>.
- Production and Preview environments set `MELOS_API_ORIGIN=https://greeklyric.com`. `MELOS_FRONTEND_ONLY` is removed; the generated configuration sets it to `false`. No Jev credential is installed in this frontend project.
- `vercel.json` proxies only `/api/*` to the hosted Melos service. Browser traffic uses ordinary HTTPS on greeklyric.com, without requiring a tailnet connection or access to outbound port 8443. API responses are `no-store`.
- HTTPS root, design studio, configuration script, and a fingerprinted painting asset returned HTTP 200. JavaScript is `no-cache`; fingerprinted paintings have the one-year immutable cache policy. The connected configuration removes the preview notice and enables corpus controls.
- `.env`, `.env.local`, database files, source paintings, and model/index files were excluded from the CLI upload. The static build uses its own explicit output allowlist.

The frontend and backend are connected. Public API checks run with `python deploy/smoke_backend.py --origin https://greeklyric.com`. The desktop/mobile design was visually checked before connection; the final connected-browser automation attempt timed out, so it is not recorded as a completed visual click-through test.

## Basecamp backend (2026-09-30)

The backend now runs on the existing Hetzner Basecamp machine in `/home/alvin/services/melos`, container `melos-api`, image `melos-api:20260930-jev`. The stopped `melos-api-before-jev` container retains the pre-Jev version for rollback. Host port `127.0.0.1:8791` is intentionally loopback-only. No other Basecamp services or firewall rules were changed.

- Runtime: 125 files, 6,433,058,045 source bytes; all transfer hashes verified and all three SQLite quick checks passed. The original local corpus remains intact.
- Coverage: 287,536 source records and 111,578 embedded records. Read endpoints, sourced word analysis, Wiktionary lookup, dense search, and usage-space projection passed `deploy/smoke_backend.py` on the host.
- Warm measured container memory: about 1.87 GiB. Repeated semantic queries took 0.18–0.30 seconds in the bounded smoke test; this is not a concurrent-load benchmark.
- Limits: two CPU cores, low CPU scheduling weight, 8 GiB memory with no container swap, eight concurrent HTTP connections, one worker, and bounded logs. Corpus and model mounts remain read-only; only separate operational classifier state is writable. No access to other projects or Docker's socket is provided.
- Encoder: CPU BGE-M3, pinned model revision in `deploy/cache_model.py`; runtime downloads are disabled.
- Publication: the owner explicitly selected `MELOS_PUBLICATION_POLICY=source-labels`. This overrides only conservative publication filtering. Source labels, including unknown rights, are preserved; provenance/hash acceptance checks remain enforced. This selection is not a conclusion that every public source grants redistribution permission.
- Paid classification: enabled with pinned `jev-1.13.0`. The existing key is stored in owner-only `secrets/jev.env`, mounted read-only at `/run/secrets/jev.env` and loaded by Uvicorn. It is not shipped in the image, Docker environment configuration, Vercel, Git, or logs. The transfer helper selects only the Jev key from the local environment; it never uploads the entire local `.env`.

### Jev cache and budgets

- `runtime/classifier.sqlite` is operational state, not source evidence. Cache identity includes the exact evidence packet, configured model, and explicit prompt/schema version. Changed evidence does not reuse an older decision. Entries expire after 30 days; maximum 20,000 cached decisions.
- Defaults: 500 new provider attempts per UTC day site-wide; 10 per minute and 60 per day per signed browser session; at most two concurrent calls. Each attempt is reserved atomically before contacting Jev, including failed attempts. Duplicate in-flight packets do not start another call. Cached results remain available after quota exhaustion.
- Session cookies are HttpOnly, Secure in production, SameSite=Lax, and contain no key or raw IP. Visitors can reset cookies, so they are a convenience throttle, not user authentication. Global quotas persist across restarts. The provider's own capped key is an additional limit, not a replacement for these checks.
- API outcomes: 429 with Retry-After for busy/quota conditions; 503 for unavailable model/cache state; invalid or oversized requests fail before a paid call. The model can choose a sourced candidate or abstain; its preference signals are not calibrated philological probabilities.
- Verify without spending: `python deploy/smoke_backend.py --origin https://greeklyric.com`. Explicit paid check: `python deploy/smoke_jev.py --allow-paid`, which requests a real Sappho comparison and verifies a cache hit on repetition. Initial live verification returned `jev-1.13.0`, one new comparison, then a cached repeat.
- Set `MELOS_PUBLIC_CLASSIFIER=0` when recreating the container to disable new public comparisons without changing corpus access. Adjust `MELOS_CLASSIFIER_DAILY_LIMIT`, `MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT`, `MELOS_CLASSIFIER_VISITOR_DAILY_LIMIT`, and `MELOS_CLASSIFIER_CONCURRENCY` in the container configuration as needed. Back up the runtime database alongside deployment state if preserving usage accounting across host recovery is required.

### Public network route

The owner enabled Tailscale Funnel. The public endpoint `https://basecamp.taila44c41.ts.net:8443` forwards only to `http://127.0.0.1:8791`. Basecamp's existing port-443 console was verified to remain tailnet-only. Never replace that private console with a default Funnel command.

Activation used existing key-based administrator access, without changing any password or granting new operator privileges: `tailscale funnel --bg --https=8443 --yes http://127.0.0.1:8791`. The public relay was checked independently of tailnet DNS, followed by the Vercel proxy at `https://greeklyric.com/api/status`. Only the Melos Funnel can be stopped with `tailscale funnel --https=8443 off`; this leaves port 443 unchanged. The persisted background configuration and container restart policy keep Melos running independently of the local computer.

### Maintenance

### Live QA repair release (2026-09-30)

`melos-api:20260930-qa1` adds exact author/fragment navigation, conservative
ambiguous-lemma expansion guards, and distinct classifier preflight outcomes.
The previous container is retained as `melos-api-before-qa1`. A loopback-only
canary on port 8792 passed the hosted read smoke checks before production was
replaced; that canary is stopped after promotion.

`scripts/repair_search_layout.py` produced a separate accepted-index snapshot:
413 passage search representations changed, 9,621 vocabulary keys checked,
all source-bearing passage fields compared unchanged, SQLite quick check passed.
Only explicit Greek line-end hyphenation is joined in derived search fields.
Displayed Greek, edition metadata, raw sources, claims and embeddings are not
rewritten. Host `data/corpus-before-qa1.sqlite` retains the previous index;
local rollback copy is `.benchmarks/corpus-before-qa1.sqlite`.

The migration changes SQLite's file identity and therefore correctly trips the
semantic stale-index guard. Before declaring the release healthy, run
`scripts/rebind_search_embeddings.py` against the previous and current corpus
and the prior embedding manifest. It verifies every source-bearing field and
the previous manifest identity before writing a separate rebound manifest;
promote that manifest atomically and retain the old one. The live repair checked
all 287,536 records unchanged; no vectors were recalculated or relabelled.
Then repeat semantic search and usage-space checks through the public origin.

Run `python deploy/qa_regressions.py --origin https://greeklyric.com` for the
specific read-only regressions, without provider calls. These checks and unit
tests are engineering evidence, not a philological accuracy benchmark.
Conflicting lemma attributions remain visible; withholding automatic expansion
also affects legitimate homographs until a headword is explicitly selected.
Reference lookup does not infer numbering equivalences, and catalogue pointers
remain labelled as missing Greek reading text.

For a code-only patch use `deploy/Dockerfile.patch` with `BASE_IMAGE` set to an
existing verified local image. `deploy/start_backend.sh` accepts explicit
`MELOS_IMAGE`, `MELOS_CONTAINER_NAME` (production or canary only), and
`MELOS_HOST_PORT` (8791 or 8792 only), and refuses to replace an existing
container. Preserve rollback state and validate before promotion.

### Combining-mark search repair (qa6, 2026-09-30)

`scripts/repair_search_tokens.py` rebuilds mismatched derived word tokens in a
separate SQLite snapshot. Attached combining marks, including editorial
underdots, remain part of the surface word; accent-folded lookup keys remain
separate. It does not supply missing letters or resolve uncertain readings.

The local and Hetzner migrations each scanned 103,171 eligible text/translation
records, repaired 318 tokenized passages, and checked 3,653 affected vocabulary
keys. All 287,536 source records, work metadata, normalized search text, and FTS
rows compared unchanged. SQLite integrity and input-stability checks passed.
The existing embeddings were rebound only after verifying unchanged inputs;
no vectors were regenerated. Run this workflow on quiescent snapshots.

For qa6 rollback, restore the paired previous corpus and embedding manifest,
not just the old container. Local backups are
`.benchmarks/corpus-before-qa6.sqlite` and
`data/embeddings/manifest-before-qa6.json`; host backups use
`data/corpus-before-qa6.sqlite` and the same manifest filename. Stop the Melos
service before swapping the pair. Retain the previous image/container until
the public smoke checks and live reader checks pass.

The read-only regression probe includes the original underdotted form
`βασί̣λ̣η̣αν` in `dcc-sappho:brothers-poem`: its source transcription must retain
the marks, and its word occurrence lookup must include that same passage.
This is a token-boundary regression, not an adjudication of the word's reading,
parse, dialect, or sense.

### Attached-apostrophe search repair (qa7, 2026-09-30)

Tokenizer version 3 retains a printed terminal apostrophe rather than indexing
only its bare preceding letters. The local and independent Hetzner rebuilds
each repaired 3,622 of 103,171 eligible passages and checked 50,819 affected
vocabulary keys. All 287,536 source records, normalized search text, FTS and
work metadata compared unchanged; existing embedding inputs were verified and
their manifest rebound without regenerating vectors.

The paired rollback is local `.benchmarks/corpus-before-qa7.sqlite` plus
`data/embeddings/manifest-before-qa7.json`, and host
`data/corpus-before-qa7.sqlite` plus that manifest filename. Restore the pair
with the previous qa6 image/container if rolling back the tokenizer.

The public read-only regression checks now require `κἄμμ’` to find its own
Brothers Poem occurrence and require bare `κἄμμ` exact-word search not to claim
that passage. The frontend also compares whole printed tokens for linked
commentary previews, so the original DCC note is discoverable without creating
new structured claims. See `docs/api-contract.md` for the conservative Greek
single-quotation boundary tradeoff.

### General maintenance

- Inspect: `docker stats --no-stream melos-api`, `docker logs --tail=50 melos-api`, and `python3 deploy/smoke_backend.py` from the service directory.
- Restart without changing data: `docker restart melos-api`. Stop only this service with `docker stop melos-api`.
- Rebuild: package a frozen local runtime with `scripts/package_runtime.py`, transfer it privately, verify with `deploy/verify_runtime.py`, build `deploy/Dockerfile`, and cache the pinned model with `deploy/cache_model.py` before starting offline. Do not package databases while a collector/indexer is writing them.
- `deploy/start_backend.sh` deliberately refuses to replace an existing container. Review the old image and mounts and arrange rollback before explicitly replacing it. Retain the previous verified runtime snapshot for data rollback; no automatic backup job has been configured.
- To restore conservative publication filtering, recreate only the Melos container without `MELOS_PUBLICATION_POLICY=source-labels`. Do not weaken source validation or the separate paid-classifier guard.
