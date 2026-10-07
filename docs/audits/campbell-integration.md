# Audit: Campbell Alcaeus integration and release

Independent auditor: `/root/campbell_release_audit`. Date: 2026-10-06.

Scope: append the five source-audited Campbell texts for Alcaeus 34a, 129,
130b, 326, and 350 to the exact QA29 corpus. Do not change existing texts,
the deployed application image, environment, secrets, or frontend.

## Step 6: pre-execution integration review

**Verdict: HOLD. No production execution approval.**

Reviewed `scripts/integrate_campbell_assignment.py`,
`scripts/embed_campbell_assignment.py`, `scripts/stage_corpus_addition.py`,
`deploy/campbell_release.py`, and its delegated `deploy/release_qa29.py`.

Checks already satisfied at code level:

- New rows require an independent source PASS matching the exact JSONL hash,
  record count, and raw source hashes; exactly the five assigned labels are
  required. This does not itself approve the transcription.
- Corpus staging uses a fresh directory and SQLite backup. Existing passage,
  token, author-membership, and FTS rows are compared exhaustively. Existing
  work fields are preserved except justified counts; unrelated vocabulary and
  metadata are preserved. Evidence is copied byte-identically.
- Encoder requires the pinned BGE-M3 revision, CUDA float16 computation,
  512-token maximum, 1024 dimensions, and the existing weighted-window pooling
  routine. It emits five finite, normalized vectors, not inferred text.
- Vector append compares the old array prefix exactly and preserves old row
  metadata; new vectors bind their input text hashes and attribution.
- Release uses the exact QA29 image and verifies unchanged environment,
  runtime configuration, resource/security restrictions, existing bind mounts,
  and gateway. Candidate artifacts are separate read-only mounts. Private
  snapshots and guarded routing retain the old container for rollback.
- Independently ran all four synthetic integration tests: PASS. These exercise
  staging, duplicate/missing assignment rejection, stale manifest rejection,
  and exact old-vector preservation. Synthetic test rows never enter the corpus.

Initial blocking findings, now resolved in the revised release code:

1. Semantic warmup must require explicit semantic readiness and expected
   embedding/source counts. Nonempty search results alone may come from a
   lexical fallback and do not prove a usable semantic index.
2. Warmup must compare all five served texts with accepted text hashes, not
   merely verify that the IDs exist with nonempty text.
3. The release artifact list must contain the manifest's exact referenced row
   and vector files. The manifest's corpus size/mtime binding must match the
   deployed corpus after transfer; copying can alter mtime and disable search.

The updated `replacements()` verifies exact artifact membership and corpus
size/mtime binding. Updated `warm()` requires semantic readiness/count/source
coverage and checks every served assignment text against its accepted SHA256.
Code preflight is therefore **PASS for staging only**, not production acceptance.

Independently ran the nine underlying staging tests as well: **13/13 combined
mechanics tests passed**. They include source/raw hash failures, altered existing
rows, concurrent mutation, policy/evidence preservation, and unsafe output paths.

### Independently observed live baseline

Read-only commands inside `melos-api` recomputed these SHA256 values:

| Artifact | SHA256 |
| --- | --- |
| corpus.sqlite | `be68b1afac0c87f17db7bb1f38d74c580fc28a5a5f29e200eba2f16509eaa4fe` |
| evidence.sqlite | `f2b960a4f136b435f541e146df4dc7d7306006dfd378c8451f9f6b1be6492755` |
| semantic manifest | `17361055065988d3205d9f4094772f4ebf28a0c9d753b4362ec64f453a0d4d23` |
| semantic rows | `0864001ae572751a1838e0d720f2ee8a650595006375a86f1c0dfe2e31a0dac9` |
| semantic vectors | `fa4d08fff2a78c1cafb0fbf417debe202589403838976a241fbdfaabf08b9496` |

Live manifest: 116,191 vectors; 119,228 total windows;
`BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`;
float16 computation, 512-token maximum, 1024 dimensions, and
`token_windows_weighted_mean_v2` pooling. Stored vectors are float32 outputs,
which is distinct from float16 model computation.

Live `backend/textutils.py`, `backend/author_aliases.py`, and alias JSON hashes
independently match their local counterparts exactly. Current encoder script
hash is `9c7e318ccaa85e5aa544c0ddd0f5401dd311af354aed1b699dd96392ef152e9c`.
Its implementation is tracked unchanged, but the historical embedding manifest
did not store the encoder source hash. Thus this audit verifies the published
model/window contract, not an unavailable immutable historical source receipt.

### Encoder compatibility investigation

The integration agent reported a bounded three-record reproduction check:
cosines approximately 0.98519, 0.999998, and 0.94410 against existing vectors.
The first and third discrepancies are material and not accepted as routine
numeric roundoff. Actual source-text identity, row/vector alignment, historical
checkpoint hashes, tokenizer, and software versions require investigation.
**New vector publication is on HOLD until resolved.** A separately approved
manifest may retain the old vectors with all five additions explicitly pending,
but that would not provide new Campbell semantic/thematic coverage and must not
be described as complete embedding integration.

Root approved the explicit pending-five fallback. The integration agent further
checked that the three tested source texts match live/local text exactly and
that published vectors equal their checkpoint arrays with matching contract
hashes. The numerical discrepancy remains unexplained; software/padding drift
is a hypothesis, not an established cause. Candidate acceptance will require
116,191 unchanged vectors, 116,196 eligible rows, five explicit pending IDs,
and `corpus_rebinding.new_ids_embedded: false`. No new vectors will be appended
in this release.

## Required final artifact acceptance

Pending source auditor PASS and completed staged artifacts. Before independent
integration PASS, check:

- Live baseline is still 288,584 rows and the exact QA29 container/image.
- All old corpus/index rows and vectors are unchanged; candidate has 288,589
  rows with exactly five new source-bound records.
- Independently reconcile FTS/token/vocabulary/work and manifest counts.
- Verify baseline corpus/evidence/semantic artifact hashes and deterministic
  indexing helper compatibility with QA29, plus the pinned window contract.
- Bind final release corpus, semantic manifest, row and vector files by SHA256.
- Verify source and addition receipts against these exact artifacts.
- Canary checks validate retrieval, full text equality, semantic readiness, and
  word/phrase analysis; separate coverage QA must not equate successful HTTP
  responses with correct philological parsing.
- Promotion requires separate canary PASS for the actual canary container;
  retain exact old-container rollback and verify public routing afterward.

No production state was changed by this auditor. The source audit remains in
`docs/audits/campbell-assignment.md`; source acquisition PASS alone is not final
transcription or publication acceptance.

## Final staged integration: PASS

Source package approved by the independent source auditor at SHA256
`bcd7403ffe8ffe8f633b149e570f18925ac99bf6286b7c8f8590e25cd530340c`.
The source audit retains an explicit faint-glyph uncertainty for fragment 34a;
this integration PASS does not upgrade it to perfect diplomatic transcription.

Ran the independent read-only auditor against the actual staged Basecamp files:

- All 288,584 old passages, 1,976,890 token records, 326,148 author memberships,
  and 288,584 FTS records preserved. Candidate has exactly 288,589 passages.
- All five stored source records/texts match accepted package data, with only
  the established derived work ID added. Tokenization, normalized FTS fields,
  affected vocabulary counts, work counts, and corpus manifest counts reconcile.
- Old works, unrelated metadata/vocabulary, and semantic artifacts preserved.
- Semantic manifest has 116,191 vectors, 116,196 eligible records, and exactly
  the five new IDs pending. Candidate size/mtime binding matches.
- Candidate corpus SHA256:
  `c2bc15ad79e7e8575fe0aa94823d8b6dc2359af093e98623e5ac20b2ecf56e8b`.
- Candidate semantic manifest SHA256:
  `15dd08069839f771e5b1db1d2b99fac31b3311d834987b6615cda2162fd4edf4`.

### Narrow tokenizer overlay: PASS

Root separately authorized one same-image read-only source overlay after QA
found standalone combining accents treated as words and underdotted text treated
as intact. The pre-patch local file was independently byte-compared with deployed
QA29 `backend/passage_analysis.py`, SHA256
`287326782fb2eb099cb532e37fc04dda6d6d11f64917500e99ed1014873ecea1`.

The reviewed four-hunk patch only changes word starts to require base letters,
classifies orphan combining marks as editorial, marks underdotted segments as
uncertain, and supplies an accurate warning. It preserves source text and offsets
and prevents uncertain segments from triggering ordinary morphology/model lookup.
Normal attached accents and supplied whole words retain their prior behavior.

Independently ran 38 Python passage/tokenizer tests and 14 focused frontend
word/fragment tests: all passed. Approved overlay SHA256:
`b29c23536c5e14b313c5bbe1a88214edc77f3ea6e26f3bbd3b209aed8fc5b56b`.

Machine acceptance is `runtime/campbell-assignment/integration-pass.json`.
It permits the two data artifacts plus this one hash-bound code overlay only.
The release is no longer literally data-only. No other application code,
environment, secrets, or discovery redesign is approved by this receipt.
Separate canary QA remains required before production promotion.

## Revised release: bounded dictionary meanings overlay

Root authorized a second narrow module overlay to bridge existing parser lemma
hypotheses to existing exact dictionary headwords. Independently compared both
modules with freshly checked deployed QA29 baselines. No data definitions are
generated: only exact NFC/casefold headword records are copied from the existing
dictionary response; occurrence morphology claims are not copied. Lookups are
request-cached and capped at 24. Machine candidates stay labeled predictions.

Homographs remain unresolved, source entry/sense identity checks remain enforced,
and Modern Greek definitions cannot stand in for English. Candidate alternatives
gain source meanings without forcing one chosen sense. Syntax-only features are
suppressed when every explicit candidate truly contradicts the predicted lemma
or shared morphology. An initial bug treated insufficient feature overlap as a
contradiction; requested and verified its correction plus regression test.

Independently ran 170 related passage, tokenizer, interlinear, ranker, sense, and
server tests: all passed. Accepted frozen module hashes:

- `passage_analysis.py`: `a91f126eeb4617cc97b104f5fc81b81ca011e518a0c066ca2fd731c65252e8a8`
- `interlinear.py`: `f4bb41431a260c66de516bd31c903b80af0352cdee4b573f2c6eb64579d28d58`

Independent patch receipt: `runtime/campbell-assignment/backend-patches-pass.json`.
The first dictionary sense remains a labeled preview, not independently verified
contextual meaning. Missing definitions and parser errors are not cured by this
plumbing change. Fresh corpus metadata integration and canary QA are still
required for the revised release; the prior candidate receipt is not reusable
for modified artifacts.

## Later bounded audit: unresolved homograph inventory

Reviewed only the new inventory-preservation delta against the frozen
`runtime/alcaeus-morpheus-maintenance/interlinear-before-homograph-inventory.py`
baseline (`5e093a96302df53fcca2133b1eaee127ee204f78b061f24dcf1973e71804caff`).
This does not reapprove intervening unrelated changes or authorize deployment.

The new path preserves exact literal English senses under separate unresolved
dictionary entry identities instead of returning an entirely empty inventory.
It does not choose a homograph or populate selected gloss text. Broken explicit
entry pointers and already homograph-marked candidate identities still fail
closed. Definition spans require source URL, source locator, valid SHA256,
English provenance, and exact sense-to-entry binding.

Audit requested and verified two corrections: validate both qualified and raw
entry-pointer namespaces against the enclosing entry; reject conflicting
duplicate entry/sense identities rather than silently retaining the first.
Exact duplicate records remain safely deduplicated.

Independently ran 192 related tests, all passing. Independent replay of the
archived `intact-dictionary.json` evidence for μακάρων / μάκαρ yields three
entry groups and four sourced senses with no selected gloss. Accepted delta
result: `c8ca0b41d8ece747875766525c68567541e0814fc08544144adc9096cb5c57cc`.
Receipt: `runtime/alcaeus-morpheus-maintenance/homograph-inventory-audit.json`.
No paid inference, corpus edits, or deployment performed by this audit.

## Optional later audit: source-tense consumer

Reviewed separately against the approved homograph snapshot
`c8ca0b41d8ece747875766525c68567541e0814fc08544144adc9096cb5c57cc`.
Accepted consumer hash:
`463667edc5bc24757480ea8a70a2f8149cae59b344634631bc0519e3bb73b598`.
This is not deployment approval.

The consumer recognizes only the independently audited extractor's explicit
two-foregoing-present-senses declaration. Source hash, URL, qualified/raw entry
identity, sense IDs, locator bounds, and offset bases must agree. It never
infers missing tense. Audit requested and verified guards for malformed nested
proof and conflicting raw entry IDs; invalid proof cannot constrain meanings.

Independently ran 226 consumer/related tests and 16 extractor tests, all passing.
Independently replayed archived LSJ `lsj:5:n42827`: its first two restricted
sense units reject explicitly supplied aorist morphology but retain unknown
tense; the unrestricted third sense remains eligible. With unresolved competing
parses, a present or unknown supporting alternative prevents exclusion. A
selected parse constrains headline compatibility only; source alternatives
remain in the response and ranking inventory.

Receipt: `runtime/alcaeus-morpheus-maintenance/source-tense-consumer-audit.json`.
No inference calls, source data writes, or production changes were performed.

## Local-only opt-in machine-subentry consumer: PASS

Reviewed the consumer delta against the frozen approved tense `interlinear.py`
and release-G `passage_analysis.py` snapshots. Independently recomputed the
audited helper, subordinate-entry index, and dictionary manifest hashes; all
match `docs/audits/machine-subentries-helper.json`.

The optional keyword-only callback defaults to `None`; no server/API caller is
wired to it. Existing calls remain compatible and disabled responses gain no
subentry fields. Enabled calls use at most 24 distinct exact forms per request,
cache repeats, and exclude editorial/partial tokens. Proof is pooled once in
the response and attached as references to the same machine candidate, not as
ordinary headword senses or a selected meaning. Original variant scope and
source identity remain unchanged; the automatic Jev inventory stays empty for
these unsupported references.

Requested and verified transactional envelope validation, a source orthography
to lookup-key check, binding-ID recomputation, and target machine status/form
checks. Independently ran 271 related tests, including actual cached receipt
and hash-verified LSJ replay, all passing. No inference/network calls, corpus
writes, or deployment changes were made.

Accepted local deltas:

- `interlinear.py`: `2203f9f0268bacb636efca9764cffc248f01836ece1c39f63fcd604efeb4cd0c`
- `passage_analysis.py`: `4ed1370e98b8b7385584a8c2e7f8515055ebe24dc469b364c3b8b79bc1c922e8`

Receipt: `runtime/alcaeus-morpheus-maintenance/machine-subentry-integration-audit.json`.
Future runtime wiring, dependency provisioning, frontend handling, and production
deployment require separate review; this receipt does not authorize them.

### Revised corpus v2: independent integration PASS

Re-ran the full independent read-only artifact audit against
`releases/campbell-20261007b/workspace/data/staging/candidate`, using the newly
source-approved metadata package SHA256
`afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b`.
All preservation, source, derived-index, and pending-vector checks passed again.
All five Greek text hashes remain identical to v1; the 130b citation metadata
now supports the user's natural fragment-number query.

Revised artifacts:

- Corpus: `f57e0bdd5c27d9e6364319f0bb5789ee62aa5289abc249437e43380116ea0fc9`
- Semantic manifest: `11739ed23b4d5ca6dc1bcf8be137b0edea4639a437776960d58645f709e69cca`

`runtime/campbell-assignment/integration-pass-v2.json` binds these artifacts and
the two independently accepted backend module hashes. The v1 receipt is retained
for history, not reused. Separate v2 canary QA must pass before promotion.

### Machine-subentry HTTP wiring and literal feature labels: independent PASS

Reviewed the frozen opt-in callback, ordinary `/api/word` HTTP wrapper, and
literal morphology-label adapter. The deployable server is derived from the
exact I baseline, not the dirty local server. Its narrow diff leaves internal
`word()` calls source-only, adds cached enrichment only at the HTTP boundary,
and lazily initializes the hash-bound dictionary resolver. Passage work retains
the 24-distinct-form limit and editorial/partial exclusions. Configuration or
hash failures return unavailable evidence, not invented lexical content.

Independently ran 312 tests in 45.08 seconds, including 16 actual HTTP probes
covering both local and exact I-derived servers. Enabled, disabled, bad-hash and
missing-configuration behavior passed for both word and passage routes. The
full-word archived response contains the literal English subordinate-entry
meaning, `Person=1`, and `1st sg. pres. ind. act.` while its selected gloss stays
unset. Subentry references remain outside automatic Jev sense ranking.

Reproduced the archived label inventory: 26 hash-verified receipts, 72 machine
candidates, 82 raw feature pairs, 34 canonical projections and 48 raw-only
pairs. Explicit ordinals, mediopassive and nonfinite labels are retained in
compact parsing; conflicting supplied labels remain unresolved. This is adapter
coverage on a finite sample, not a claim of philological accuracy.

Verified all 35 package/existing-dependency hash and size bindings locally, plus
the exact overlay file set. The integrator's read-only preflight receipt matches
all 27 existing dependencies and the package manifest; this reviewer did not
repeat its remote inspection. No source rows, caches, embeddings, production
services or routes were changed by this audit.

Receipt: `runtime/alcaeus-morpheus-maintenance/machine-subentry-wiring-audit.json`.
The receipt binds exact reviewed backend and package hashes. It permits the
release owner to proceed to separate staging/canary gates, not direct production
promotion. Frontend review remains separately owned; lacuna handling is outside
this delta.
