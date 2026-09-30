# Evidence-bound contextual classifier

`backend.classifier.classify_context(form, passage, candidates, claims=(),
author_profile=(), dialect_rules=(), provider=None)` returns a **model proposal**
(`status: proposed`) or an explicit abstention. It never writes corpus passages,
Greek, source claims, or a resolved dialect label. The returned `packet` lets a
reader inspect the exact text, candidate IDs, accepted source claims, author
profile, dialect rules, and conflicts that the model saw. `evidence_ids` point
back to the selected candidate's linked claim IDs or cited candidate source
metadata. Source claims remain separate from the model's ranking.

The caller supplies the original Greek passage and candidate analyses. For
phase 2, `backend.evidence.EvidenceIndex.lookup(form, passage_id)` can supply
its `claims` array, which has already been gated by independent claim acceptance
hashes. Only `status: source_claim` records with a source URL and exact quote
enter the packet. Machine proposals, unquoted assertions, and unsupported
author profiles are excluded. Contradictory accepted claims are retained side
by side. A dictionary listed form establishes that an entry lists a form; it
does not establish occurrence in a given poet. A nearby spelling remains a
correction suggestion, never an exact contextual parse.

The output shape is:

```json
{
  "status": "proposed | abstained",
  "candidate_id": "existing candidate ID or null",
  "reason": "plain-language reason",
  "model": "actual provider model identity or null",
  "evidence_ids": ["accepted claim or candidate source reference ID"],
  "packet": {"form": "...", "passage": {}, "candidates": [],
             "claims": [], "author_profile": [], "dialect_rules": [],
             "constraints": [], "warnings": []},
  "warnings": []
}
```

If a provider supplies probabilities or confidence, the API labels them
`model_probabilities_uncalibrated` and `model_confidence_uncalibrated`. They
are raw provider signals; no philological calibration has been measured. A
model abstention retains these signals and token usage for inspection.
Schema validity is not proof that the interpretation is right. The
classifier abstains when the queried form is absent from the original Greek
passage, text or candidates are missing, candidate provenance is absent,
input exceeds bounds (12 candidates, 24 claims, 16,000 state
characters), the provider is unavailable, a returned ID is unknown, or the
selected candidate is only a spelling suggestion. A model can explicitly
choose `abstain`. Candidate `features`, `analysis_text`, `dialect`, matched
forms, and source references remain visible for comparison. An author profile
can inform judgment only if supplied as source-bearing claims. No rule makes
every Sappho word exclusively Aeolic.

## Jev integration and cost

The official [TypeSafe API schema](https://api.typesafe.ai/openapi.json)
defines bearer authenticated `POST https://api.typesafe.ai/v1/systemone`, a
structured `state`, and named typed questions. The adapter sends one `choice`
question whose options are exactly the candidate IDs plus `abstain`; it checks
the returned ID and records the actual response `model` and token usage.
`GET /v1/models` can enumerate names available to a particular authenticated
account; the default alias here is `jev-latest`. Set `TYPESAFE_API_KEY` (or
`JEV_API_KEY`) in the server environment to enable it. No key is logged,
returned, or required for unconfigured abstentions. No account was created by
this implementation; the user supplied the key for the bounded live probe
reported below.

TypeSafe [describes Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
as a fast typed decision model without free-form string generation. Its
published price on 30 September 2026 is **$0.042 per million input tokens**;
output tokens are listed as free. At 4,000 input tokens, that is roughly
$0.000168 per request; 1,000 such requests would be roughly $0.168, subject
to actual usage and current pricing. This is an estimate, not a benchmark or
authorization for a bulk job. The application makes at most one model call
per classification request and has an 8-second timeout. The project has no
Greek philology benchmark validating Jev's decisions or its calibration, so
every result is presented as an inference proposal with its sources exposed.

`provider_status()` reports whether a Jev key or local classifier is available
without exposing a secret. `configured_provider()` uses Jev when a key is
configured. Merely downloading local weights does not enable classification:
the local adapter must report `validated: true` from an appropriate benchmark
and the server must explicitly set `MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER=1`.
The initial Qwen3-0.6B smoke test failed contextual accuracy and produced a
choice for an absent form; it is therefore disabled. Tests use synthetic
fixtures and an intercepted HTTP request to verify the official request
schema; fixture responses are not represented as live model judgments.

## Bounded Jev diagnostic

`python scripts/probe_jev_classifier.py --dry-run` verifies the exact
accepted hash of `p2_notes.jsonl` and constructs three source-grounded
evaluation packets without a request. With a TypeSafe-issued key in the
server's `TYPESAFE_API_KEY` environment variable, run
`python scripts/probe_jev_classifier.py`; an optional `--env-file` reads only
`TYPESAFE_API_KEY` or `JEV_API_KEY` from that explicitly named private file.
The script never scans other credential files. It makes at most three requests
for the current fixtures and has an absolute ten-request cap. The report in
`data/reports/jev-classifier.json` contains the actual model response, selected
ID, raw provider probability/confidence signals, token usage, estimated input
cost, and latency, without key or request headers. The three expected outcomes
are one source-supported morphology candidate and abstention on two unresolved
source alternatives. These are evaluation cases, not corpus entries or an
accuracy estimate for Ancient Greek. Candidates may share a source while
presenting different senses or features; the provider still evaluates them
against the passage. Shared provenance alone is not an abstention rule.

On 30 September 2026, a TypeSafe-issued key was made available in the
ignored project `.env`, and the three-case probe made three live calls. Jev
returned actual model `jev-1.13.0`: `source-morphology` for the explicit
`πέμπην` morphology (0.65 choice probability, 0.47 provider confidence),
`abstain` for the competing `ἔλθην` editorial readings (0.96, 0.94), and
`abstain` for the unresolved `ἔχη` token offsets (0.58, 0.37). All matched
the fixture expectations. Latencies were 0.2063, 0.1194, and 0.0879 seconds;
input usage was 3,011, 2,585, and 1,904 tokens respectively. At the published
price, total estimated input cost is $0.000315. The report contains the raw
provider responses and no credential value. Three examples establish that
the integration works, but cannot establish Greek-language accuracy or
philological calibration. The server loads its explicitly chosen private env
file (for example with Uvicorn's `--env-file` option) without copying a key
into the frontend or repository.
