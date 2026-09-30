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

Any hosted classification credential (`TYPESAFE_API_KEY` or `JEV_API_KEY`) belongs only in the API host's secret environment. The frontend must never contain the credential or call a paid classifier provider directly. The current `/api/classify-context` endpoint is local-only and returns 403 for remote callers or when `MELOS_PUBLIC_DEPLOYMENT=1`. The public reader can expose the sourced candidate analyses while contextual hosted classification remains unavailable. Before enabling that paid endpoint publicly, implement authentication or other abuse controls, rate limits, request size limits, and usage monitoring on the API host. Browser-visible API calls can be replayed by anyone; CORS by itself is not access control.

## Release check

1. Complete the accepted corpus and indexes, and verify local backend tests and `/api/status` report the intended coverage.
2. Provision the persistent HTTPS API service and set its exact allowed frontend origins. Check read endpoints and operational limits.
3. Configure `MELOS_API_ORIGIN` in Vercel. Build the static artifact and inspect `dist/` for only the allowed frontend paths. `dist/` is Git-ignored.
4. Deploy a Vercel preview and test reader searches, passage navigation, word inspection, usage space, design studio, and unavailable-service states in a browser. Confirm the public contextual-classifier action reports its local-only restriction, browser calls go to the HTTPS API origin, and no keys or corpus files appear in the deployed assets.
5. Promote only after the preview checks pass and the operator has selected and documented the publication policy. Extraction acceptance does not itself establish redistribution permission.

Vercel project configuration follows its [build and output directory](https://vercel.com/docs/builds/configure-a-build) and [routing configuration](https://vercel.com/docs/project-configuration/vercel-json) documentation.

## Published frontend (2026-09-30)

- Vercel project: `nacryos-projects/project-melos`, connected to `Nacryos/Project-Melos` on GitHub.
- Custom domain: <https://greeklyric.com>; Vercel alias: <https://project-melos.vercel.app>.
- Production and Preview environments explicitly set `MELOS_FRONTEND_ONLY=1`. No hosted corpus API is connected, and no Jev credential is installed in this frontend project.
- HTTPS root, design studio, configuration script, and a fingerprinted painting asset returned HTTP 200. JavaScript is `no-cache`; fingerprinted paintings have the one-year immutable cache policy. The live browser displays the preview notice and disables corpus controls.
- `.env`, `.env.local`, database files, source paintings, and model/index files were excluded from the CLI upload. The static build uses its own explicit output allowlist.

The frontend is not yet connected to the backend described below. Do not describe the frontend-only release as a functioning public dictionary.

## Basecamp backend (2026-09-30)

The backend now runs on the existing Hetzner Basecamp machine in `/home/alvin/services/melos`, container `melos-api`, image `melos-api:20260930`. Host port `127.0.0.1:8791` is intentionally loopback-only. No existing Basecamp services or firewall rules were changed.

- Runtime: 125 files, 6,433,058,045 source bytes; all transfer hashes verified and all three SQLite quick checks passed. The original local corpus remains intact.
- Coverage: 287,536 source records and 111,578 embedded records. Read endpoints, sourced word analysis, Wiktionary lookup, dense search, and usage-space projection passed `deploy/smoke_backend.py` on the host.
- Warm measured container memory: about 1.87 GiB. Repeated semantic queries took 0.18–0.30 seconds in the bounded smoke test; this is not a concurrent-load benchmark.
- Limits: two CPU cores, low CPU scheduling weight, 8 GiB memory with no container swap, eight concurrent HTTP connections, one worker, and bounded logs. Data and model mounts are read-only; the container has no access to other projects, Docker's socket, or a Jev key.
- Encoder: CPU BGE-M3, pinned model revision in `deploy/cache_model.py`; runtime downloads are disabled.
- Publication: the owner explicitly selected `MELOS_PUBLICATION_POLICY=source-labels`. This overrides only conservative publication filtering. Source labels, including unknown rights, are preserved; provenance/hash acceptance checks remain enforced. This selection is not a conclusion that every public source grants redistribution permission.
- Paid classification: `MELOS_PUBLIC_DEPLOYMENT=1` still blocks `/api/classify-context` with HTTP 403 regardless of publication policy. No API key is shipped in the image or frontend.

### Remaining network step

Tailscale Funnel requires owner enablement. The intended public endpoint uses HTTPS port **8443** forwarding only to `http://127.0.0.1:8791`. Basecamp's existing port-443 console must remain tailnet-only. Never replace the existing port-443 service with a default Funnel command.

After approval, run `tailscale funnel --bg --https=8443 --yes http://127.0.0.1:8791` on Basecamp, inspect `tailscale serve status` and `tailscale funnel status`, and verify the resulting public HTTPS API from outside the tailnet. Then configure that exact origin in Vercel, remove `MELOS_FRONTEND_ONLY`, redeploy, and verify public browser search. Until then the production frontend stays explicitly in preview mode.

### Maintenance

- Inspect: `docker stats --no-stream melos-api`, `docker logs --tail=50 melos-api`, and `python3 deploy/smoke_backend.py` from the service directory.
- Restart without changing data: `docker restart melos-api`. Stop only this service with `docker stop melos-api`.
- Rebuild: package a frozen local runtime with `scripts/package_runtime.py`, transfer it privately, verify with `deploy/verify_runtime.py`, build `deploy/Dockerfile`, and cache the pinned model with `deploy/cache_model.py` before starting offline. Do not package databases while a collector/indexer is writing them.
- `deploy/start_backend.sh` deliberately refuses to replace an existing container. Review the old image and mounts and arrange rollback before explicitly replacing it. Retain the previous verified runtime snapshot for data rollback; no automatic backup job has been configured.
- To restore conservative publication filtering, recreate only the Melos container without `MELOS_PUBLICATION_POLICY=source-labels`. Do not weaken source validation or the separate paid-classifier guard.
