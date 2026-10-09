# Private mode (release T)

An owner-only layer on greeklyric.com. When the owner is signed in, the reader, the headword
(lexicon) page and search also show the owner's own licensed or in-copyright material in full,
labelled **Private — owner only** with its source and page. Signed out, the API never returns
private text. Nothing about it is advertised: the only public trace is a small "·" link in the
reader and headword-page footers that leads to the sign-in page (`/owner`, `noindex`).

## The rule for public responses (the single gate)

1. **Private text is shown only to the signed-in owner.** Every owner payload is tagged
   `"visibility": "private-owner-only"` and comes from `/api/private/*`.
2. **Private material may steer public search, never fill it.** It may be used behind the scenes
   to improve public ranking (keyword matches, passage links, and later vectors). Every text a
   signed-out visitor sees comes from public material.
3. **One exception, off by default:** a public result may carry at most one short cited excerpt
   from private material — **30 words or fewer**, with its source and page
   (`"visibility": "public-excerpt"`). It is on only when the operator sets
   `MELOS_PRIVATE_PUBLIC_EXCERPTS=1`. Otherwise no excerpt at all.

The gate is `backend/private_gate.py`, and public code calls exactly one function in it,
`apply_public_search` (in `/api/search`). It re-orders the public results already on the page by
reciprocal-rank fusion with the private links (weight 0.5); it never adds or removes a result, and
its only route to private text is `cited_excerpt`, which caps the excerpt at 30 words and refuses
one without a source and page. A failure in the private store leaves public search unchanged.
`MELOS_PRIVATE_SIGNALS=0` turns the re-ranking off.

So that the gate cannot be bypassed by accident:

- `backend/private_store.py` (the only code that reads private text) can be imported only by the
  gate and the owner routes. A test parses every backend module and fails on any other import.
- Owner functions in `private_store` demand an `OwnerContext`, which only a verified session
  produces.
- **Response guard** (`backend/private_mode.py`, innermost middleware, so it reads uncompressed
  bodies): for every signed-out `/api` request it answers `/api/private/*` with 404 before
  routing, and scans every other response body for the private tag. A match becomes a 404 (or the
  stream is cut if headers were already sent) and is logged as an error. A test plants a leaky
  route to prove it.

## How release S's commentary inbox fits

| | `data/commentary_inbox/` (release S) | `/home/alvin/melos-private/inbox/` (release T) |
|---|---|---|
| Where | the repository / build data | the box only, outside the repo and the Vercel build |
| What | public or derived material that may be shown publicly | licensed or in-copyright material the owner supplies |
| Becomes | public index entries and public search text | `private.sqlite` pages, links, signals |
| Shown to visitors | yes, as public text | never, except a ≤ 30-word cited excerpt if excerpts are turned on |

Nothing in the private inbox or store is ever copied into `data/commentary_inbox/`. Derived
**signals** (which public passages a private page discusses, keyword matches) stay in the private
store and reach public search only through the gate. If S later wants private signals inside its
own ranking (for example private-commentary vectors), it should call
`private_gate.rank_signals(q)`, which returns public passage ids and scores only, rather than
reading the store. Material the owner is free to publish (public domain, or their own notes they
want public) goes to S's commentary inbox instead.

## Sign-in

- Name `Alvin` (any case). The password is never in the repository: the box keeps only an
  **argon2id** hash (time 3, 64 MiB, parallelism 2) and a random 256-bit session key in
  `/home/alvin/services/melos/secrets/owner_auth.env` (mode 600), written by
  `scripts/owner_auth_setup.py`, which reads the password from standard input. Without that file
  private mode is off and every owner route is 404.
- **Session:** cookie `__Host-melos_owner` = random id + HMAC; `HttpOnly`, `Secure`,
  `SameSite=Strict`, `Path=/`, 12 hours. Sessions are held server-side (one worker), so sign-out
  ends them and a restart signs the owner out. A second, non-secret cookie `melos_owner_ui=1`
  tells the static pages to ask `/api/owner/session`; visitors without it make no owner request.
- **Session fixation:** sign-in ignores any incoming session cookie and mints a new id; signing
  in again from a session ends the old one.
- **CSRF:** sign-in needs a one-use token from `/api/owner/login-token`, bound to an HttpOnly
  cookie and valid 10 minutes, sent in `X-Melos-CSRF`; sign-out needs the session's own token.
  Both need JSON, an `Origin` of `https://greeklyric.com` (`MELOS_OWNER_ORIGINS`), and refuse
  `Sec-Fetch-Site: cross-site`. CORS stays without credentials, so other sites cannot read
  responses.
- **Brute force:** 5 failures from one client lock that client for 15 minutes; 20 failures in an
  hour from anyone lock sign-in for an hour (client addresses can be spoofed, the global limit
  cannot). A wrong name costs the same argon2 check as a wrong password. At most two checks run at
  once. Counters are in memory (a restart clears them).
- **HTTPS only:** on the box the API listens on 127.0.0.1 and is reached only through the Tailscale
  Funnel (TLS) and Vercel (TLS, HSTS). With `MELOS_PUBLIC_DEPLOYMENT=1` the owner routes need
  `X-Forwarded-Proto: https`; anything else is treated as signed out (404). Locally, loopback only.
- **404, not 403:** signed out, every `/api/private/*` path (known or not) is 404. Sign-in and
  sign-out errors (wrong password 401, CSRF 403, lockout 429) are on `/api/owner/*`, which holds no
  private material.

| Route | Signed out | Signed in |
|---|---|---|
| `GET /api/owner/session` | `{"signed_in": false}` | name, expiry, CSRF token, UI script URL |
| `GET /api/owner/login-token` | one-use sign-in token | same |
| `POST /api/owner/login` | `{username, password}` + token | — |
| `POST /api/owner/logout` | 404 | ends the session |
| `GET /api/private/status`, `/documents` | 404 | store summary, documents with provenance |
| `GET /api/private/passage?id=` | 404 | private pages linked to the passage |
| `GET /api/private/lemma?lemma=` | 404 | pages naming the headword (or a word on its stem) |
| `GET /api/private/search?q=` | 404 | private full-text search |
| `GET /api/private/page?doc=&page=` | 404 | one page |
| `GET /api/private/ui.js` | 404 | the owner panels script (not in the static site) |

## Private corpus store and drop folder

```
/home/alvin/melos-private/          (mode 700, box only)
  inbox/        drop files here, each with <file name>.json beside it
  store/private.sqlite              mounted read-only into the API at /private
  manifests/<doc_id>.json           provenance record per document
  rejected/                         files refused, with <file>.reason.txt
  log/ingest.jsonl
/home/alvin/storagebox/melos-private/originals/<sha256>.<ext>   the original files
```

Formats: PDF (text layer, one page per PDF page, printed page numbers from the PDF's page labels
or `page_offset`; **OCR** with Tesseract `grc+eng` when a page has no text layer or, for Greek, an
unreadable legacy-font layer), EPUB (the book's printed page breaks when marked, else sections),
TXT/Markdown (form feeds are pages), TEI XML (`<pb n=…/>` are pages), Beta Code text (for example
the owner's own licensed TLG export: `"encoding": "betacode"`).

Manifest (`Page-Sappho-Alcaeus.pdf.json`):

```json
{
  "title": "Sappho and Alcaeus", "author": "D. L. Page", "year": 1955, "kind": "commentary",
  "language": "eng", "citation": "Page, Sappho and Alcaeus (1955)",
  "rights_basis": "owner's own printed copy, scanned by the owner",
  "acquired_from": "bought second-hand, 2024", "owner_attestation": true,
  "page_offset": 12, "ocr_languages": "grc+eng", "expect_greek": true,
  "passage_links": [{"passage_id": "…", "page": 40}]
}
```

Required: `title`, `kind` (commentary, translation, edition, lexicon, grammar, other),
`rights_basis`, `citation`, and `owner_attestation: true`. A manifest naming a shadow library is
refused. The pipeline never downloads anything (it runs in a container with no network); it does
not scrape the TLG or any subscription service and does not get past any login or paywall.

```
sh /home/alvin/melos-t/src/deploy/private_ingest.sh build    # once
sh /home/alvin/melos-t/src/deploy/private_ingest.sh ingest   # after dropping files
sh /home/alvin/melos-t/src/deploy/private_ingest.sh link     # passage links (Greek word trigrams shared with
                                                             # public passages; 2+ shared, formulae ignored)
sh /home/alvin/melos-t/src/deploy/private_ingest.sh status
```

The store is rebuilt in a working copy and swapped in atomically; the API picks it up without a
restart.

## Tests

`tests/test_private_mode.py` (synthetic fixtures; each run hashes a random password):
sign-in flow and cookie attributes, sign-out, wrong name or password, per-client lockout, global
limit, login CSRF (missing, foreign, replayed token; wrong origin; cross-site; non-JSON), logout
CSRF, session fixation (planted, replaced and forged cookies), expiry, HTTPS-only on the public
deployment, private mode off without secrets, **every `/api` route requested signed out with
queries that match the private text** (no private text, tag or title in any response; every
`/api/private/*` 404), unknown private paths, the guard on a planted leaky route, public search
re-ranked by private links with no private text, the 30-word cited excerpt, the import rule, no
private paths in static files, and the ingest refusals (no manifest, shadow library, no
attestation).
