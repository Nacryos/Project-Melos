# Second-pass implementation contract

Workspace: this repository. Preserve the existing corpus and the user's
original `index.html`, `css/styles.css`, `js/app.js`, `js/dither.js`, and assets.
Only root rebuilds `data/corpus.sqlite`, changes `backend/server.py`, restarts
port 8791, or merges acceptance manifests. Never touch the user's port 8790.
Collection agents must not reset, clean, commit, or push shared work. The lead
agent handles publication only when the user explicitly requests it.

## Collection and audit

Read the available `data-extraction` skill completely before extraction, and
`docs/corpus-contract.md`. Use `apply_patch` for code edits.
Each new collector owns `scripts/ingest_p2_NAME.py`, `data/raw/p2_NAME/`,
`data/processed/p2_NAME.jsonl`, and `data/reports/p2_NAME.json`. Keep ancient
text, commentary, apparatus, bibliography, OCR, and model proposals distinct.
No handwritten corpus entries or repaired Greek from model memory. OCR may be
run reproducibly against saved scans but remains review-needed until checked.
No paywall, access-control, rate-limit or CAPTCHA circumvention; no acquisition
of paid subscriptions or extraction permissions by assumption.

Before new-source ingestion, send exact source/rights URLs and scope to
`/root/p2_source_audit` (web/repositories) or `/root/p2_edition_audit` (Loeb,
scans, modern editions/articles). Previously audited pinned sources may be
reused with the existing source verdict and new file-level provenance.
Stage outputs first. Send completed textual outputs and hashes to
`/root/p2_text_audit`; send structured claim outputs to `/root/p2_claim_audit`.
Only auditors accept files; collectors never edit acceptance manifests.

Report actual new coverage, duplication against existing data, failures and
unresolved rights. More records are not necessarily more ancient evidence.
Avoid broad epic/prose expansion unless it supplies a specifically missing
edition, commentary, apparatus or lyric-relevant resource.

## Structured evidence claims

Claims go in `data/claims/NAME.jsonl`, not `data/processed`. Each line:

```text
id                stable source-specific identifier
subject           {type, id?, passage_id?, form?, start?, end?}
predicate         lemma / morphology / dialect_label / sense_gloss /
                  equivalent_form / variant_reading / editorial_state / grammar_rule /
                  author_alias / literary_dialect / parallel_proposal
object            JSON value preserving source scope and alternatives
evidence          [{record_id?, source_url, raw_path, raw_sha256,
                   quote, locator?}]
assertion_type    quoted_source / extracted_annotation / model_inference
status            source_claim / machine_proposed / needs_review
method            extraction/mapping/model procedure identifier
source_family     underlying source/edition, not count of mirrors
metadata          optional source labels, bibliographic fields, caveats
```

Evidence quotes must be exact source text (or explicitly documented whitespace
normalization), traceable to saved artifacts or an accepted parent record.
Token offsets are Python Unicode codepoint offsets into original passage text,
not normalized text. Omit offsets rather than guessing an alignment. A claim
may concern a form without asserting that it occurs in a particular author.
`object` is source-specific; keep raw grammatical labels alongside standardized
features where normalization is sourced. Do not force a single dialect or sense.

Model judgments are allowed in a separate inference layer, with actual model
identity, candidate IDs, evidence IDs and abstention. A model score is not a
calibrated probability of philological truth. Do not manufacture model results
or confidence scores. Preserve contradictory source claims and dependency.

The claims implementation owns a derived `data/evidence.sqlite`; it must bind
inputs to independently accepted claim hashes. No graph database is required:
source-bearing subjects, relations and objects provide the initial graph.

## Retrieval and interface

Use a bounded, inspectable hybrid retrieval baseline before elaborate learned
hierarchies: lexical/form candidates plus dense candidates, passage-level
grouping of linked commentary/translation hits, and explicit retrieval reasons.
Do not add incomparable scores naively or treat similarity as influence.
Evaluation queries may be synthetic and labelled as evaluation fixtures, never
mixed into the historical corpus. Distinguish commentary-assisted retrieval
from Greek-only retrieval, and calibration from schema validity.

The user's original Melos hero, shader, painting choices, fonts and exact palette
are the design authority. Interface changes are integration into that design,
not a new visual identity. Keep research controls and source distinctions.

Coordinate contracts with root before integration. Prefer small completed,
audited units that work end to end over unfinished abstractions.
