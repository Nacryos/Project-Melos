# Audit: Content integration and final provenance — Melos author profiles

## Step: 6–7
## Agent Action

Team A integrated the thirteen-profile catalog with `js/authors-page.js`, `css/authors-page.css`, `authors.html`, frontend asset copying and the `/authors` route. This audit covers content provenance and code-level integration. Browser visual QA is assigned to the root/UI agents and remains separate.

## Audit Checks

- [x] Metadata paths/counts: PASS. All thirteen biography raw paths and receipts resolve, as do both DCC source references and all ten image references. Ten references resolve to nine unique byte-identical image files. Published catalog equals staging. Consumer field names match output schema, including nullable portraits and optional reading lists.
- [x] Attribution rendering: PASS by inspected consumer logic. Expanded profiles render exact biography text with a source link. The source disclosure renders article URL, immutable revision URL, license link, contributor attribution and extraction notice. Image attribution includes title, artist, credit, license, description, source and applicable license link, plus an explicit crop/desaturation and historical-likeness notice. DCC commentary renders its exact text, source title, author credit and unversioned CC BY-SA terms link. Source text is assigned through textContent, not parsed as HTML.
- [x] Caveat rendering: PASS by inspected consumer logic. The expanded figure caption consumes the manuscript, uncertain-identity and later-depiction labels. Collapsed manuscript/uncertain images receive a visible type badge. Browser positioning/readability remains outside this audit.
- [x] Build/route linkage: PASS by code inspection. The frontend builder copies catalog/image files and authors HTML/CSS/JS. The Vercel route maps `/authors` to `/authors.html`. The consumer fetches `/assets/authors/catalog.json` and resolves image paths at the site root. Raw files and extraction code remain repository provenance assets, not required public URL targets.
- [x] Existing-source preservation: PASS within the extraction scope. The build only reads original local-preview portrait files and metadata. Original raw Commons metadata still has SHA-256 `d2d96120f3d9d0c9ea2896139d52d546000003c50b2652e02042aa65f20cc5b8`, identical to step 1. Published portrait metadata and source image hashes still match that prior source chain. Unrelated dirty-worktree changes are outside this audit and were not modified.
- [x] Final provenance: PASS for all thirteen records, since the complete dataset is smaller than the requested twenty-entry sample. Every biography traces from published catalog to staging to saved JSON, verified receipt and exact external summary URL/revision. Both DCC instances trace to saved introduction HTML and its receipt, with saved license terms. Every selected portrait traces to its published image hash, original local asset, source-backed portrait manifest, Commons imageinfo raw data and receipt, and the external Commons file URL.
- [x] Functional consumer verification: PASS. All eight existing authors-page tests pass, including source-safe rendering, expansion, cached works, passage navigation, filtering, chronology handling and catalog failure behavior.

## Evidence

```
node --test tests/authors-page.test.mjs
python data/author-profiles/audits/verify_staging.py
python data/author-profiles/audits/verify_output.py
```

All commands exit 0. The provenance verifiers cover Archilochus, Alcman, Sappho, Alcaeus, Stesichorus, Ibycus, Anacreon, Simonides, Pindar, Bacchylides, Homer, Hesiod and Theocritus without sampling omissions. Counts, URLs, revision identifiers, text equality/prefix boundaries and file hashes are independently checked.

A minor source-code comment describing the presentation focus coordinates as source-supplied was reported directly to the UI agent for correction. These coordinates are implementation-selected presentation metadata; this wording does not alter the source data or invalidate its provenance.

## Verdict: PASS for content integration and end-to-end provenance
## Blocking: NO within the audited scope

This is not a browser visual approval. Final crop identity, layout, responsiveness, disclosure visibility and production/browser behavior still require the root/UI agents' visual and runtime QA. Chronology data itself belongs to the separate chronology source pipeline; this report only checks its consumer's claim-type handling and does not certify historical date accuracy.
