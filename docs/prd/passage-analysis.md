# Passage analysis for Project Melos

User-approved scope, 2026-10-05.

## Outcome

Extend the existing reader from word lookup to bounded selection of words,
phrases and sentences. The selected span receives ranked morphological
alternatives, contextual syntactic proposals, dictionary meanings, dialect
evidence, and explicitly scoped published translations and commentary.
Preserve the existing Melos visual language, responsive layouts and search.

## Evidence contract

- Source annotations, machine morphology, contextual predictions and generated
  translations must be distinct record types and visible states.
- Every token retains its exact original spelling and character offsets.
- Preserve editorial brackets, gaps and supplements. Never silently repair text.
- Authorial dialect is a prior, not evidence that every word is exclusive to it.
- Keep all plausible candidates available; group genuinely equivalent analyses
  without losing dictionary identities or provenance.
- Jev probabilities are model estimates, not verified correctness rates.
- Published translations must identify source and alignment scope. A whole-passage
  translation is not presented as an exact translation of a selected subphrase.
- Prefer passage annotations and linked commentary when present; absence stays
  explicit. No invented citations, glosses, annotations or restored letters.

## Architecture

1. Versioned bounded passage-analysis API bound to corpus passage and exact span.
2. Existing source-evidence morphology plus a replaceable open-source morphology
   adapter. Retain source receipts and cache by provider/model/text version.
3. Replaceable local dependency-parser adapter chosen through current published
   evidence and actual runtime tests, not an unsupported universal-best claim.
4. Conditional syntax linter reports conflicts and uncertain attachments without
   treating poetic exceptions or missing material as proven errors.
5. Existing published translations and authorial commentary are supplied as
   scoped context. Exact aligned translations are preferred where available.
6. Bounded, cached Jev reranking is optional and explicit, with no API credentials
   in browser code. Probabilities can be aggregated over justified equivalence
   classes; raw candidate alternatives remain inspectable.
7. Reader supports mouse selection, keyboard selection and touch, offers an
   explicit Analyze selection action, and renders per-token alternatives,
   syntax relationships and translation/evidence panels in the existing theme.

## Operational constraints

- Protect other agents' and the user's dirty changes.
- Bound token/span length, external calls, concurrency and caches.
- Never silently fetch a large model during a public request.
- Missing providers fail visibly; source lookup still works.
- Externally acquired data requires independent provenance review.
- No auto-publication of model judgments into the corpus.
- Intertextual references and a new general translation-generation service are
  later extensions, not fabricated substitutes in this first delivery.

## Acceptance

- Tests cover Unicode offsets, repeats, multiword spans, punctuation, gaps,
  stale selections, invalid requests, provider failures and candidate retention.
- At least one real open-source syntactic provider runs on an actual passage;
  models cannot be advertised as ready based only on mocks.
- Source and model provenance is visible throughout the rendered result.
- Existing Python and reader JavaScript regression tests remain passing or
  unrelated pre-existing failures are explicitly reported.
- Browser QA verifies selecting and analyzing multiple words in the reader.
- Deployment readiness and actual live deployment are reported separately.
