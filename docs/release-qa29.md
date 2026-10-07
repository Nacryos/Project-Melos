# QA29 live release — 2026-10-05 Pacific

Production frontend: https://greeklyric.com

- Vercel deployment: `dpl_GFKWjw24R7SmfTWZrEejYTdxWA73`
- Deployment URL: https://project-melos-izlp7vgy7-nacryos-projects.vercel.app
- Hetzner image: `sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777`
- Remote release directory: `/home/alvin/services/melos/releases/qa29`
- This deploy includes the current working-tree application, not merely the last Git commit.

## Shipped

The current morphology/syntax selection pipeline, structured source-bound LSJ and
Autenrieth senses, English-only translation previews, phrase/interlinear reader,
multiword sequence retrieval, and the complete current frontend styling are live.
OdyCy is installed offline at revision
`83046e93fa6b5dee122c3ca7cff1377512928143`, mounted read-only at `/syntax-model`.
Both actual syntax inference and BGE-M3 semantic queries passed on Linux.

The existing 288,584-record corpus and 116,191-row semantic index were retained.
SHA-256 comparisons of the active corpus, manifest, rows, vectors, and all 28
dictionary XML files matched local. No staged experimental annotations were
silently admitted and no source database or embeddings were rebuilt.

Two successful, hash-verified Perseus response receipts were merged into the
live morphology cache: κηλήμασι and παντοδαποῖς. Existing records and all request
counters were preserved. No local classifier database or secret was uploaded.

## Verification

- Predeployment: 1,101 backend tests and 249 frontend tests passed.
- Receipt migration: eight additional tests passed.
- Canary and public-origin feature checks: structured dictionary senses, three
  multiword relations and reversed-order control, real parser offsets, English
  translation filtering, and actual BGE-M3 queries passed.
- Existing hosted smoke and source/regression suites passed against the canary.
- Browser: two-word selection, interlinear source meanings, phrase search results,
  fullscreen image header, exit control, and plain normal heading verified live.
- One explicit live Jev ranking request completed for both words. It proposed
  the neuter dative plural analyses and retained the masculine alternative for
  παντοδαποῖς. No sense-model comparison ran for this control: κήλημα had one
  extracted sense, and παντοδαπός lacked a complete exact-lemma sense inventory.
- Public feature checks completed in roughly 0.7–1.7 seconds per grouped check
  after warmup; these are spot checks, not latency or accuracy guarantees.

## Operations

The original six data/model/runtime/secret mounts were retained, with one new
read-only syntax-model mount. CPU remains limited to two cores and RAM to 8 GiB.
A post-warmup sample showed approximately 2.49 GiB memory use. The private
Basecamp routes on ports 80 and 443 and `melos-lab` were left unchanged.

Previous production is retained, stopped, as `melos-api-before-qa29`; the prior
QA28 canary was retained separately. Private original-container and routing
snapshots, package hashes, canary results and promotion receipt are in the remote
release directory. Do not publish the private snapshots: they may contain env values.

Model predictions remain distinguishable from source-attested analyses. Missing
partial English translations remain missing; semantic rank is not evidence of
literary influence. Deployment tests do not establish philological accuracy rates.
