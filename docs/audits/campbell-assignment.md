# Audit: Campbell Alcaeus assignment

Date: 2026-10-06. Independent auditor: `/root/campbell_audit`.

Scope: requested Alcaeus fragments 34a, 129, 130b, 326, 350, in the user-supplied Campbell edition. No substitution of another edition, conjectural restoration, or invented translation is permitted.

## Steps 1-2: source discovery and acquisition

**Verdict: PASS for identity and acquisition. Publication metadata caveat recorded below.**

- Source: `C:/Users/alvin/Downloads/Campbell Greek Lyric Poetry.pdf.pdf`, supplied by the user; no HTTP acquisition is necessary or claimed.
- Size: 19,731,467 bytes; 493 PDF pages.
- SHA256: `8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f`.
- Title page: David A. Campbell, *Greek Lyric Poetry: A Selection of Early Greek Lyric, Elegiac and Iambic Poetry*, Macmillan / St Martin's Press.
- Copyright page: copyright David A. Campbell 1967, all rights reserved; first edition 1967, subsequent reprints. This is not evidence of an open digital-corpus license. Task scope is the five requested ancient Greek texts and necessary edition/provenance metadata, not bulk redistribution of commentary or the book scan.
- Independently recomputed file hash matches the extractor manifest.
- `scripts/campbell_assignment_extract.py` reads the supplied file, emits raw text, coordinate-bearing text blocks, and page raster images with no repair.
- All 14 emitted raw-text files equal fresh PyMuPDF extraction from their indicated PDF pages; all referenced image/block files exist.

## Step 3a: page selection and raw extraction

**Verdict: PASS for source evidence; FAIL as publication-ready Greek. Blocking: YES for direct OCR publication.**

Visually inspected rendered pages 85, 86, 88, 89, 90, 91, 93, and 94 against the extracted evidence. Raw text is corrupt OCR with Latin lookalikes and replacement characters, not usable Greek transcription.

| Requested fragment | PDF pages (one-based) | Printed pages | Edition-specific boundaries |
| --- | --- | --- | --- |
| 34a | 85-86 | 53-54 | Begins below preceding fragment; continues at top of 54; exclude apparatus and following 38A. |
| 129 | 88-89 | 56-57 | Preserve lacunae, uncertain letters, and final missing-verses notice; exclude following 130. |
| 130b | 89-90 | 57-58 | Campbell labels it `(130)`; printed lines 16-35, not an independently complete poem. Four lines before next page's 20 are 16-19. Do not invent preceding lines. |
| 326 | 91 | 59 | Nine surviving displayed verse lines plus terminal lacuna; exclude apparatus and 332. Do not silently expand from other editions. |
| 350 | 93 | 61 | Two verse lines, an intervening Greek prose source quotation, then resumed verse. Preserve the prose/verse distinction. Exclude apparatus and 347. |

## Step 3b: cropped OCR trial

**Verdict: PASS for reproducible crop provenance; FAIL for direct Tesseract publication.**

- Crop configuration identifies source PDF pages and coordinate rectangles; source-derived image hashes and Tesseract commands/outputs are retained in `runtime/campbell-assignment/ocr-receipts.json`.
- Visually checked the 350 verse/prose crops and 129 continuation against full rendered pages. Fragment 350 has six displayed verse lines (two before and four after the prose), not seven. The printed numeral 5 is beside the second resumed verse line: retain the printed margin label and chunk boundary, not an invented contiguous 1-6 numbering or reconstructed intervening line.
- Tesseract 326 PSM6 omits the visible eighth verse line and inserts diacritic debris as separate lines. Other words are corrupted. These candidates cannot be labeled verified transcription.
- The final `desunt iv versus` notice after 129 lies outside the verse crop; missing-four-verses metadata needs source-bound retention.

## Step 3c: image-based re-OCR review (in progress)

The extractor retains API request metadata, image hashes, complete model responses, and parsed line JSON. The auditor compares candidates to source pixels; no replacement Greek is authored in the audit. `campbell-assignment-approval.json` gates packaging by exact candidate SHA256.

- Accepted so far: 34a both chunks, 129 first chunk, 130b first chunk, 326, 350 first verse chunk and prose chunk.
- Initial concern about the rho breathing in 129 was withdrawn after a second independent visual comparison with the same-line initial alpha: both show smooth breathing. The original candidate is retained. A targeted retry introduced a visibly wrong vowel and is rejected, not merged.
- **34a glyph fidelity WARN:** lexical content, brackets, and line count match, but tiny possible marks under mu/phi in line 3 cannot be distinguished confidently from scan speckling or broken ink. Initial OCR is retained with explicit unresolved-glyph metadata and a source-crop requirement. This is not exact-diplomatic certification at every glyph. The first-line alpha underdot is also faint.
- Existing schema bucket `machine_corrected_ocr` is acceptable only with explicit method metadata: image-based re-OCR replaces corrupt embedded machine OCR; no manual philological correction or universal certainty is implied.

## Subsequent stages

Remaining OCR chunks, transformation, final schema, integration, and end-to-end trace checks are pending. No complete corpus package has yet been approved by this audit. The source-evidence PASS does not approve corrupt raw OCR or allow a substitute text to be branded Campbell.

## Source facsimile integration

**Verdict: PASS.** Reviewed `scripts/build_campbell_facsimiles.py`, all 10 asset hashes in `runtime/campbell-assignment/facsimile-manifest.json`, and the five generated HTML source pages. Fragment mappings and section counts are correct (34a: 2; 129: 2; 130b: 2; 326: 1; 350: 3 including explicitly separate prose).

An initial boundary review found clipped/omitted terminal marks. Three facsimile-only crops were expanded without modifying OCR input artifacts. Visually verified the new images include the complete terminal five-dot marks for 34a/130b and the `desunt iv versus` notice for 129, without following fragment headings or apparatus. All final asset hashes match the manifest. Full PDF and private OCR receipts are not part of these public excerpts.

## Steps 4-5 and 7: transformation, packaged output, full cross-validation

**Verdict: PASS with the explicit 34a glyph-fidelity limitation above. Live integration remains a separate check.**

Approved final package: `runtime/campbell-assignment/campbell_assignment.jsonl`, SHA256 `afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b`. This supersedes the initial package after an independently rechecked structural gap was added between 350's two verse quotations, followed by the citation-only revision below.

- Exactly five unique requested records, IDs `campbell-glp:alcaeus:{34a,129,130b,326,350}`; no padding, duplicate records, empty required fields, or replacement characters in public poem text.
- Display-line counts: 34a 13 (including terminal dots), 129 28, 130b 20, 326 10 (including terminal dots), 350 7 (six verse lines plus one explicitly documented structural blank). The two intervening prose display lines in 350 are stored separately, not counted as verse. Verse-segment offsets preserve the two-plus-four separation.
- Printed margin labels are preserved without inventing sequential line numbering. In particular 130b retains labels 20/25/30/35, and 350 retains printed 5 beside its fourth displayed verse line.
- Two rejected line candidates were replaced deterministically from independently reviewed, hash-bound source-image OCR retries: 129 printed 24 (replacement character resolved), 130b printed 31 (wrong vowel resolved). No Greek correction string was authored in the transformation.
- One replacement-character-only row from clipped preceding prose at the top of 350's second verse crop was excluded by explicit audited geometry metadata. The original candidate remains in the evidence ledger.
- Independently reconstructed **every** final line, not a sample, from each original API candidate plus its allowed retry/exclusion rules. All final structured lines and joined `text` fields match exactly. All ten OCR candidate hashes, all ten crop hashes, retry hashes, and five source-bundle hashes match.
- All source-provenance paths exist; source edition, PDF hash, fragment identity, OCR method, uncertainty, source notes, facsimile URLs, and transformation ledgers are retained. The package does not claim an open license for Campbell's edition or universal exact-diplomatic certainty.

### Citation-only revision

Reaccepted SHA256 `afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b` after changing 130b's citation to `Fragment 130 (assignment: Fragment 130b)` for reference lookup. Independently reversed that single byte-string substitution in memory and reproduced the previously approved full-file SHA256 `bcd7403ffe8ffe8f633b149e570f18925ac99bf6286b7c8f8590e25cd530340c`. Exactly one occurrence changed: all Greek, structured lines, other metadata, and serialization bytes are unchanged. All five source-bundle hashes still match.
