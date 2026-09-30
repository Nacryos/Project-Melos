# Phase 2 textual extraction audit

## Gate and current state

Phase 2 text files remain staged until an independent audit grants a
hash-bound decision in `data/reports/p2-text-acceptance.json`. The script
`python scripts/audit_p2_texts.py data/processed/p2_NAME.jsonl` writes a full
report to `data/reports/p2-text-audit.json` and a separate acceptance file.
The existing `audit_corpus.py` checks every row's schema, ID, source URL,
saved artifact hash, text occurrence, classification, and chronology. This
Phase 2 wrapper checks IDs against the accepted corpus, flags OCR promoted to
`source_text`, lists exact Greek text overlaps with accepted rows, and selects
20 repeatable samples per file. Exact overlap indicates a possible shared
edition, not an independent textual witness and not by itself an error.

The automatic gate never supplies `manual_verdict: PASS`. For each sample the
auditor checks the original span and whether the source identifies the stated
author, work, edition, and citation. For TEI, this means examining the passage
element and header or canonical repository metadata, including editorial
readings. For HTML or JSON sources, inspect the publisher page or revision
and the saved source artifact. A saved OCR transcription alone cannot certify
ancient text; inspect the actual scan independently or retain
`reference/machine_ocr` or `needs_review` status. Record the sample IDs and
specific evidence here before editing a file's manual verdict at its exact
SHA-256. The root agent merges accepted hashes into the main manifest.

The ledger below records independent manual decisions at exact output hashes;
an edited output requires a new audit.

## Review ledger

| File | Output SHA-256 | Rows | Mechanical | 20 source/label checks | Edition lineage | Decision |
| --- | --- | ---: | --- | --- | --- | --- |
| `p2_melic.jsonl` | `ca4fe25e52abf47178d46772e33ff83b3c0988b467bb9da7a5f99c806be37db5` | 2 | PASS | 2/2 records; all 13 lines | Wikisource edition unspecified; not an independent witness | PASS, `needs_review` transcription |
| `p2_grammar.jsonl` | `bfb344e8e4682fbe14aaf298852df82db599f54c26db14a7eee3704bb9bced98` | 22 | PASS | 22/22 exact DOM text/cells | DCC commentary, selected grammar | PASS, source subset |
| `p2_ogc.jsonl` | `9648e77aaa3a50cf9c15bd68eec9a9c3414cce58b3a1dcf0f297fe17e2a434e2` | 481 | PASS | 20/20 exact raw rows | Bergk OCR and First1K mirror; not independent witnesses | PASS, labeled staging only |
| `p2_perseus.jsonl` | `d15bb50bbf034c69af0b293c5855f8c4bed15152bc3196954d19665bccb36da2` | 5,994 | PASS | 20/20 direct TEI traces | First1K/Perseus/Drachmann edition family | PASS, commentary/reference |
| `p2_elegy.jsonl` | `ec4f6324b64bddac74c6d4d0fd11992996deebae3b48f43b9139fc1fe74115e3` | 327 | PASS | 20/20 blocks; all 1,403 lines structurally checked | Composite Wikisource Theognidean anthology | PASS, source anthology |
| `p2_stesichorus.jsonl` | `217c9ec2b6a74f86f2ce79a46124c024ebd4c0cd93c88aab5aaa4b4d2a12fbda` | 101 | PASS | 10/10 Greek visual; 20/20 other blocks; all rows regenerated | Pitotto 2024 modern edition | PASS, eight glyph-bearing texts `needs_review` |
| `p2_ibycus.jsonl` | `f88d6e4f3b45685064034b3aad6cb4772cb4e6ad82e84de28a83f1e8b278aa5f` | 19 | PASS | 5/5 Greek lines visual; 14 reference rows traced | Edmonds 1924; five partial lines only | PASS, scan-verified lines plus references |
| `p2_alcaeus.jsonl` | `148cdff49df61ba1a264a0f072364746653f702f64e33bb8e83b32667bcd2a08` | 157 | PASS | 20/20 section/citation checks; all lines DOM-traced | Edmonds/Bergk Wikisource transcription | PASS, three `needs_review` |
| `p2_perseus_notes.jsonl` | `3f2f301e2c1fc836d3a6da6525d5a1907a8cdbe5b4b162c59b527ac5b0a2f680` | 91 | PASS | 91/91 TEI note text/role checks | Pindar repository default; Bacchylides explicit TEI terms | PASS, apparatus/commentary only |
| `p2_editions.jsonl` | `d6112603f36fee0dc6f1a971e100790ce1578b614ebb466da2e8412bd06f6213` | 203 | PASS | 203/203 image/OCR/index hashes; 20 source images reviewed | Existing Lyra/Bergk scan families | PASS, machine-OCR page references only |
| `p2_scholarship.jsonl` | `beff3fd5f3b5bde3e3b660305ebddd0eda931e874ee23a0076b1dfae8fd4dc80` | 123 | PASS | 123/123 notes and raw hashes; five corrected H1 citations | DCC Hulse commentary | PASS, commentary only |

`p2_melic`: independently read saved MediaWiki API revision 60169, whose
`pageid` is 18806. Its page title and both internal headings match the two
output works/citations. The first record preserves eleven unaccented Greek
lines; the second preserves two lines under the separately titled epigram.
Every line is present in the saved response, and the exact raw SHA-256 and
output SHA-256 match the report. The collector downloads the revision and
parses the two sections without repairing Greek. Both records explicitly
retain `needs_review`, page-title attribution, and unspecified printed
edition; the count is two source sections, not two independent witnesses.

`p2_grammar`: all twenty selected DCC Aeolic table rows match the saved
HTML's three DOM cells and column headings exactly after declared whitespace
normalization. Both prose rows match source paragraphs. Five raw artifacts,
Waddell/Goodell/Ayer credits and CC BY-SA terms verify. The source table has
29 data rows; two separators and seven blank-feature preposition examples
were not selected. The file is a faithful subset, not comprehensive grammar.

`p2_perseus`: the independent reviewer traced twenty stratified passages
directly through eight saved TEI files. Three spans from each of four scholia
files, all six Vita/testimonia chapters, Olympian 9.156.a and Nemean 3.16
matched the raw hashes, titleStmt author/work, edition metadata, CTS citation,
and source text. Olympian 9.156 has eight misnested parts, but its explicit
`xml:base` locators recover eleven distinct parts. Four Vita `sourceDesc`
monograph titles contradict their `titleStmt` titles; the output uses
`titleStmt` and flags the mismatch. Editorial passages retain TEI markup and
`needs_review`. These 5,994 records add scholia/reference coverage from an
existing edition family, not independent ancient witnesses.

`p2_ogc`: the reviewer sampled twelve OCR rows across all nine OCR files and
eight Hephaestion rows across all three First1K files. Text, URN, edition,
locus, upstream source and raw license match source JSONL; all twelve raw
hashes and 161 First1K TEI links verify. The 320 OCR rows remain `reference`
with unknown author and unverified scans. The 161 Hephaestion rows are
`commentary`. Nine near-duplicate song pairs share Bergk's edition, and OGC's
First1K rows are mirrors. A mixed-content heuristic misses some editorial
material, so this file is accepted for labeled staging only.

`p2_elegy`: twenty spread blocks and an independent full structural pass
match Greek Wikisource page 11840 revision 92231: 327 blocks, 1,403 verse
lines, and exact source marker metadata. Source marker sequences drift 178
times in A and 33 in B; the output preserves them instead of inventing line
numbers. Seventy-seven lines overlap the prior corpus; fourteen repeated
lines within the anthology are source repetitions. Attribution is to a
composite Theognidean anthology, with printed edition unspecified. The
restricted Edmonds TEI contributes no processed passages.

`p2_stesichorus`: all 101 records regenerate exactly from the fixed publisher
PDF. An independent reviewer matched twenty stratified testimony, apparatus
and commentary records to page/block source positions, and visually inspected
all ten Greek reading-text records. Fr22b's split quotation now has its
physical PDF block-line locators; surrounding testimony stays separate.
Fr22a/b have readable scan-confirmed text. Eight other Greek records retain
`needs_review` because metrical font signs extract as private-use characters;
fr15 also contains a U+FFFD replacement in the extracted layer. The source is
Pitotto's edited reading, not a new documentary witness.

`p2_ibycus`: the fourteen bibliography/locator rows match saved HTML, with
the one ISO-8859-1 page preserved byte-for-byte and a reproducible UTF-8
companion. Five Greek lines have exact saved OCR and crop hashes; I inspected
all five line crops and the full printed pages 84/86. Their words, accents,
fragment headings and line positions agree with Edmonds's 1924 scan. The
five isolated lines do not establish full-fragment coverage.

`p2_alcaeus`: 157 Greek records trace line-by-line to pinned Wikisource
revision 122262. Twenty seeded records were independently checked under
their section headings and citations; saved Edmonds I scans pp. 318, 320,
350 and 390 corroborate edition context. Ten bold topic/addressee labels and
numeric HTML counters are excluded from verse. Heading 146 is withheld
because the source scan questions lyric versus comic Alcaeus. Three source
passages remain `needs_review`.

`p2_perseus_notes`: all 91 notes match saved First1K TEI text, parent ode,
source note type and responsibility: 62 textual apparatus, 29 commentary;
74 Svarlien translator, 17 Perseus Project editorial. The 54 Pindar notes
use a repository-default CC BY-SA 4.0 license, not a TEI-specific license
notice, and require Svarlien/Perseus credit and the repository's
modification-offer condition. Bacchylides TEI has an explicit notice.
None of these notes is ancient poem text.

`p2_editions`: all 203 reference records bind exact saved IA JPEGs and OCR
bytes to pre-existing Lyra leaf IDs and page/edition metadata. Twenty
stratified images were visually checked for page boundaries and headings.
The material remains uncorrected, mixed Greek/Latin page OCR with
`machine_ocr`/`needs_review`, not verified verse or new witnesses.

`p2_scholarship`: all 123 DCC Hulse note paragraphs and 21 raw artifact
hashes check. Five Argonautica note citations now use the visible publisher
H1 ending 832 rather than the URL slug ending 830. The output includes
scholarly commentary, not a Greek text edition or translation.

## Required manual checks

1. Confirm collector code downloads actual raw content and records exact URL,
   timestamp or immutable revision, raw path and SHA-256. Verify independent
   publisher or canonical repository source where feasible.
2. Trace at least 20 sampled records through output text to source span.
   Independently inspect author, work, edition, citation, and kind. Uncertain
   authors or editorial supplements remain labeled as such.
3. Verify that every `source_text` record came from a textual edition rather
   than unverified OCR. A machine transcription of a scan can remain a
   page-linked reference without pretending to be verified Greek.
4. Compare duplicate passages and edition metadata with existing Perseus,
   Sappho, DCC, Wikisource and OGC records. Shared wording or a mirrored
   edition does not increase the count of independent witnesses.
5. Cross-check the exact final output hash and count, then document a PASS,
   WARN or FAIL with scope and unresolved issues in the separate acceptance
   file. A rerun invalidates a manual verdict if output bytes change.
