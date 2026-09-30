# Deployment handoff

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

### General maintenance

- Inspect: `docker stats --no-stream melos-api`, `docker logs --tail=50 melos-api`, and `python3 deploy/smoke_backend.py` from the service directory.
- Restart without changing data: `docker restart melos-api`. Stop only this service with `docker stop melos-api`.
- Rebuild: package a frozen local runtime with `scripts/package_runtime.py`, transfer it privately, verify with `deploy/verify_runtime.py`, build `deploy/Dockerfile`, and cache the pinned model with `deploy/cache_model.py` before starting offline. Do not package databases while a collector/indexer is writing them.
- `deploy/start_backend.sh` deliberately refuses to replace an existing container. Review the old image and mounts and arrange rollback before explicitly replacing it. Retain the previous verified runtime snapshot for data rollback; no automatic backup job has been configured.
- To restore conservative publication filtering, recreate only the Melos container without `MELOS_PUBLICATION_POLICY=source-labels`. Do not weaken source validation or the separate paid-classifier guard.
