# Deployment handoff

Melos has two deployable parts. Vercel serves the static reader and design studio. A separate persistent Python service serves `/api/*` from the accepted corpus, dictionary, and search indexes. Deploying the frontend alone does not make the reader functional.

## Static frontend

Create a Vercel project from the public Melos GitHub repository, with the repository root as the project root. `vercel.json` runs `npm run build` and serves only `dist/`. The build copies an explicit set of HTML, CSS, JavaScript, and generated painting assets. It places the research reader at `/`, the original design studio at `/legacy` (also `/design-studio`), and keeps `/reader.html` as a reader alias. No `data/`, Python code, source paintings, reports, model files, or credentials are in the output.

Set `MELOS_API_ORIGIN` in the Vercel project's environment variables to the public HTTPS origin of the separately hosted API, such as `https://api.your-domain.example`. This is a public address embedded into `dist/js/config.js`, not a secret. The production build fails if it is absent, local, or HTTP. Set it for each Vercel environment that should build. Do not set it to the Vercel frontend origin unless that origin actually routes `/api/*` to the live service.

For a local static artifact check without a deployed API, run `npm run build:preview`. It generates a same-origin API configuration for local preview only. For a production build check, set `MELOS_API_ORIGIN` to the intended public HTTPS API origin and run `npm run build`.

## Persistent API service

Host `backend.server:app` on a service with persistent storage for the accepted indexes and enough memory and CPU for search and embedding loads. Build and audit the corpus and indexes using the procedures in [reader.md](reader.md) before making the API public. The API host must serve over HTTPS, expose a health/status endpoint at `/api/status`, and be reachable from browsers visiting the Vercel domain. Do not put the corpus, SQLite databases, downloaded source records, model weights, or API credentials in the public GitHub repository or the Vercel static artifact. Arrange backups and a documented index rebuild path for the persistent data.

Configure the API's `MELOS_CORS_ORIGINS` with the exact Vercel production and preview origins that should access it, and set `MELOS_PUBLIC_DEPLOYMENT=1` on the public API host. Browser CORS must allow the reader's read requests. Verify the API status, author/work listing, search, passage, word lookup, and usage space from the deployed frontend origin. A local browser test against `127.0.0.1` does not establish that public users can reach the API.

Any hosted classification credential (`TYPESAFE_API_KEY` or `JEV_API_KEY`) belongs only in the API host's secret environment. The frontend must never contain the credential or call a paid classifier provider directly. The current `/api/classify-context` endpoint is local-only and returns 403 for remote callers or when `MELOS_PUBLIC_DEPLOYMENT=1`. The public reader can expose the sourced candidate analyses while contextual hosted classification remains unavailable. Before enabling that paid endpoint publicly, implement authentication or other abuse controls, rate limits, request size limits, and usage monitoring on the API host. Browser-visible API calls can be replayed by anyone; CORS by itself is not access control.

## Release check

1. Complete the accepted corpus and indexes, and verify local backend tests and `/api/status` report the intended coverage.
2. Provision the persistent HTTPS API service and set its exact allowed frontend origins. Check read endpoints and operational limits.
3. Configure `MELOS_API_ORIGIN` in Vercel. Build the static artifact and inspect `dist/` for only the allowed frontend paths. `dist/` is Git-ignored.
4. Deploy a Vercel preview and test reader searches, passage navigation, word inspection, usage space, design studio, and unavailable-service states in a browser. Confirm the public contextual-classifier action reports its local-only restriction, browser calls go to the HTTPS API origin, and no keys or corpus files appear in the deployed assets.
5. Promote to production only after the preview checks pass and the source rights and attribution review for any publicly exposed corpus data is complete.

Vercel project configuration follows its [build and output directory](https://vercel.com/docs/builds/configure-a-build) and [routing configuration](https://vercel.com/docs/project-configuration/vercel-json) documentation. No Vercel project or live deployment is created by the repository configuration alone.
