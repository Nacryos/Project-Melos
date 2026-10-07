# Discovery release (2026-10-06)

**Rolled back at the owner's request.** Live now uses the exact pre-discovery
QA29 container and frontend; this document's promotion entries below are history.
Discovery code/assets remain available locally at http://127.0.0.1:8792/.
The new production container is retained stopped as `melos-api-reverted-discovery`.
Private rollback receipt:
`/home/alvin/services/melos/releases/discovery-revert-20261006/revert-receipt.json`.
Existing dictionary, phrase, parser, translation and BGE checks passed after
rollback. Do not republish the discovery design without owner approval.

The release layers a bounded discovery API over the exact existing QA29 image
`sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777`.
It does not replace the corpus, dictionary sources, embeddings, or models.

`deploy/package_discovery.py` creates an explicit six-file image context: the
Dockerfile; new `discovery.py` and `discovery_units.py`; source-bound
`visual_themes.py`; the existing validated visual annotation sidecar; and
`server.py` reconstructed from the fetched live source with only the discovery
router registration and author chronology response field added. Existing local
visual-theme modifications to passage endpoints are excluded. The sidecar is
placed at `/app/discovery-data/validated.json`, outside the existing data mount.
Discovery prefers the ordinary validated sidecar if present and otherwise reads
this bundled fallback. Annotations retain literal source identity/hash checks.

The live server source SHA-256 before patching is
`16ffa671afc26a25480000648811118b2d1daf7d851179ea09b25968d9776c7e`.
Existing local dictionary senses, morphology, publication policy, author aliases,
and semantic backend files matched live SHA-256 exactly during preparation.

The read-only baseline inspection confirmed all seven mounts, the offline model
configuration, two CPUs, 8 GiB RAM without container swap, 128 PIDs, non-root user,
read-only root filesystem, dropped capabilities and no-new-privileges. The
release helper verifies the exact environment and every HostConfig field except
the intended loopback canary port; bind order is normalized while every bind
specification and effective mount must remain identical. Private routes on 80
and 443 remain unchanged.

`deploy/discovery_release.py` reuses the QA29 promotion and rollback procedure,
with a unique `melos-api-discovery-canary` at `127.0.0.1:8792` and retained
`melos-api-before-discovery`. It snapshots current identity, configuration and
routing privately, warms the canary, and requires an image/container-bound pass
receipt before promotion. Promotion temporarily directs the existing 8443
route to the canary while replacing the main container and then restores 8791.
No new public route or provider call is introduced. The prior container remains
stopped for rollback. The inherited failure retention name is
`melos-api-qa29-failed`; its absence is checked before promotion.

Canary checks run the existing hosted read smoke, accepted-CGL regression and
QA29 feature suites plus
`deploy/discovery_smoke.py`: dictionary browse/English source spans, catalogue,
author chronology, all six unit modes, literal source offsets, nature annotation
hashes, and a bounded local BGE-M3 child-span rerank. These checks make no claim
of philological accuracy. Private receipts and snapshots belong only in
`/home/alvin/services/melos/releases/discovery-20261006`, not the public repo.

The final v3 package shipped after 90 combined backend tests and independent QA
approval of discovery module SHA-256
`ff3bfc52825788ca15c38d84e2fda93d422879af8e1be2a1434e9bd09696d28c`.
Initial promoted image:
`sha256:af8668a0b802d1e014da4decaaca1569389f180ad4bfe12dd8456198bb5a3610`.
Initial production container:
`30936d1455819241528698b90c11e45ab78a503c98d93d8569523b5e380648eb`.
Retained exact QA29 container:
`cc62bec35b7b83462f2ba7dcacad0a7c616d1dda81e3afe42004e8e8f02df2a9`.

All final canary suites passed. All 247 positive annotations (from the existing
6,706-record sidecar) matched live source identities, hashes and quoted evidence.
The discovery probe checked 25 exact source spans across six unit modes, with
an empty stanza category correctly remaining empty. It also verified sourced
English `love` dictionary results, author chronology and actual BGE-M3 reranking
of sampled words and lines. Nature-plus-query windows and sampled child-unit
totals explicitly disclose their bounded scope.

After encoder warmup, an uncached line query took 3.166 seconds and its repeated
page 0.014 seconds; final word reranking took 1.590 seconds and its repeat 0.031
seconds. These are spot measurements, not concurrency benchmarks. The new
production container was warmed for syntax, BGE, dictionary browsing and child
reranking before the route switched back to port 8791. A post-promotion memory
sample was 2.471 GiB of the unchanged 8 GiB limit. Public discovery and existing
QA29 feature checks passed. No paid model call, model download, corpus change,
mount/env change or expanded public exposure occurred.

Both prior canary iterations remain stopped for evidence; the final canary is
also stopped after promotion. Private snapshot, package manifests, all pass
receipts and `promotion-receipt.json` remain in the release directory. The final
archive SHA-256 is
`610099265dc628f2c735c1040fb92d651cc172c22a79dc6b2a08d89d8aa8d0fd`.

## Source-span eligibility correction

Browser review found editorial-only source lines such as `⟨ ⟩` in semantic child
results. The corrective image changes only `backend/discovery.py`: child
semantic candidates must contain a printed Greek alphabetic letter. Lacunose
Greek spans remain eligible and source text is unchanged. The response reports
the excluded-unit count and the eligibility rule. Focused checks exercise the
exact observed `love and longing` / Sappho / line query across its entire
returned sample, not only the first page.

The correction uses `deploy/discovery_correction.py` and an independent private
release directory `/home/alvin/services/melos/releases/discovery-20261006b`.
Its image is
`sha256:14d429094a7770d79ea9f2ec81e82f9fa36134970eeb41dd52a52c3468603be5`;
the corrected module hash is
`00ffce711eea1f6e2867901945fccde797259dbf3f489e01fc80780c8e7a50d4`.
The immediately preceding discovery container is retained as
`melos-api-before-discovery-correction`, alongside the original QA29 rollback.
The same environment, mount, route and security guards apply. The correction
passed 92 combined backend tests and focused canary source/discovery checks.
The correction is promoted and publicly verified. Production container is
`1046ef08d6fe5b5ccd44c8c62bd0ed3056ce9e96c0d0862ca934d839de8e6464`.
The exact public regression returned 52 Greek-bearing lines, zero editorial-only
rows, and disclosed 42 excluded units. Public dictionary, chronology, nature,
literal-span and actual child-semantic checks passed. Post-promotion memory was
2.508 GiB of 8 GiB; the routing snapshot remained identical.
