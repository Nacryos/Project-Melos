# Sappho manual source audit

## Verdict

**PASS** for `data/processed/sappho.jsonl` at SHA-256
`dc9b17b5c8410e171f42e4a05b037435e577633dd6ebb3b9a0b5667ceb5bf5d1`.
This verdict covers source fidelity and classification of the Sappho collector's
current output. The central corpus acceptance ledger is maintained separately.

The collector reports 2,647 records from 101 linked Digital Sappho pages and 99
linked Dickinson College Commentaries (DCC) pages: 399 Greek text records and
2,248 commentary records. The edition split is Digital 202 text / 2,219
commentary and DCC 197 text / 29 commentary. The report has zero fetch failures
and zero pages without extracted text. The JSONL count agrees with the report.

## Source, rights, and extraction checks

| Step | Evidence | Result |
| --- | --- | --- |
| Discovery | Fragment links come from the saved Digital sidebar and DCC fragment navigation. Independent live GETs of the Digital home, its `fr118-168` page, DCC `frag-1`, DCC `frag-169-192`, and DCC terms page returned HTTP 200 on 2026-09-30. | PASS |
| Download | `scripts/ingest_sappho.py` uses `requests` with retries and saves source HTML before parsing. Every sampled record's declared `raw_sha256` equals the saved bytes' SHA-256. | PASS |
| Parse | Greek is selected from verse containers; notes and vocabulary are separate commentary. Source editorial brackets, lacunae, daggers, and uncertain letters remain. The 20-record trace below matched saved HTML. | PASS |
| Transform | Text normalization is limited to whitespace and exclusion of page controls, footnotes, display headings, and explicit placeholders. No translation or Greek text is supplied from memory. | PASS |
| Output | IDs are unique, parent IDs resolve, and 399 text records contain Greek with no four-letter Latin prose or numeric-only fragment-heading lines. No bare `.` or `[insert table]` commentary survives. | PASS |
| Integration | 2,647 JSONL rows match `data/reports/sappho.json`; the two source editions and license labels remain distinct. | PASS |
| Cross-validation | Seeded, edition-and-kind-stratified 20-record raw trace: 20/20 saved-file hashes and 20/20 text or line matches. | PASS |

The saved Digital home states Creative Commons Attribution-ShareAlike 4.0
International. The saved DCC terms page states CC BY-SA without a version.
The output preserves that distinction. Digital commentary author `Heather` is
the page byline; DCC introduction and notes credit Heather Waddell.

DCC raw pages contain only two translation-field values: `translation goes
here` and `test`. Both are excluded; the output claims no translations.
Repeated vocabulary definitions across different fragments are present in the
source and are not duplicate poem records. No identical Greek text record is
repeated within either edition.

## Exact 20-record raw trace

Seed `290930`; draw 6 Digital text, 6 Digital commentary, 6 DCC text, and 2
DCC commentary records in JSONL order. For every row, the recorded
`source_url` names the page below; the recorded `raw_path` names the listed
saved artifact under `data/raw/sappho/`. I independently parsed that artifact
as HTML, checked its SHA-256 against `raw_sha256`, and found every declared
`lines[].text` (or the commentary `text`) in the visible page after whitespace
normalization. `Parts` is the number of line/text spans checked. All rows pass.

| Record ID | Source URL | Saved HTML artifact | Parts |
| --- | --- | --- | ---: |
| `digital-sappho:fr70:1` | `https://digitalsappho.org/fragments/fr70/` | `digitalsappho.org__fragments__fr70.html` | 14 |
| `digital-sappho:fr65:1` | `https://digitalsappho.org/fragments/fr65/` | `digitalsappho.org__fragments__fr65.html` | 11 |
| `digital-sappho:fr118-168:9` | `https://digitalsappho.org/fragments/fr118-168/` | `digitalsappho.org__fragments__fr118-168.html` | 1 |
| `digital-sappho:fr118-168:40` | `https://digitalsappho.org/fragments/fr118-168/` | `digitalsappho.org__fragments__fr118-168.html` | 1 |
| `digital-sappho:fr81:1` | `https://digitalsappho.org/fragments/fr81/` | `digitalsappho.org__fragments__fr81.html` | 7 |
| `digital-sappho:fr169-192:7` | `https://digitalsappho.org/fragments/fr169-192/` | `digitalsappho.org__fragments__fr169-192.html` | 1 |
| `digital-sappho:fr32:vocab:3` | `https://digitalsappho.org/fragments/fr32/` | `digitalsappho.org__fragments__fr32.html` | 1 |
| `digital-sappho:fr118-168:vocab:239` | `https://digitalsappho.org/fragments/fr118-168/` | `digitalsappho.org__fragments__fr118-168.html` | 1 |
| `digital-sappho:fr118-168:vocab:117` | `https://digitalsappho.org/fragments/fr118-168/` | `digitalsappho.org__fragments__fr118-168.html` | 1 |
| `digital-sappho:fr23:vocab:22` | `https://digitalsappho.org/fragments/fr23/` | `digitalsappho.org__fragments__fr23.html` | 1 |
| `digital-sappho:fr102:vocab:1` | `https://digitalsappho.org/fragments/fr102/` | `digitalsappho.org__fragments__fr102.html` | 1 |
| `digital-sappho:fr65:vocab:11` | `https://digitalsappho.org/fragments/fr65/` | `digitalsappho.org__fragments__fr65.html` | 1 |
| `dcc-sappho:frag-94` | `https://dcc.dickinson.edu/sappho/frag-94` | `dcc.dickinson.edu__sappho__frag-94.html` | 29 |
| `dcc-sappho:frag-169-192:188` | `https://dcc.dickinson.edu/sappho/frag-169-192` | `dcc.dickinson.edu__sappho__frag-169-192.html` | 1 |
| `dcc-sappho:frag-169-192:183` | `https://dcc.dickinson.edu/sappho/frag-169-192` | `dcc.dickinson.edu__sappho__frag-169-192.html` | 2 |
| `dcc-sappho:frag-80` | `https://dcc.dickinson.edu/sappho/frag-80` | `dcc.dickinson.edu__sappho__frag-80.html` | 6 |
| `dcc-sappho:brothers-poem` | `https://dcc.dickinson.edu/sappho/brothers-poem` | `dcc.dickinson.edu__sappho__brothers-poem.html` | 20 |
| `dcc-sappho:frag-95` | `https://dcc.dickinson.edu/sappho/frag-95` | `dcc.dickinson.edu__sappho__frag-95.html` | 16 |
| `dcc-sappho:brothers-poem:vocabulary` | `https://dcc.dickinson.edu/sappho/brothers-poem` | `dcc.dickinson.edu__sappho__brothers-poem.html` | 1 |
| `dcc-sappho:frag-103:Frag. 103:editorial` | `https://dcc.dickinson.edu/sappho/frag-103` | `dcc.dickinson.edu__sappho__frag-103.html` | 1 |

## Targeted semantic checks and resolved defects

- DCC grouped pages now retain source fragment headings as distinct citations.
  Bare labels such as `169A` no longer enter Greek text. Combined labels such
  as `24b 24c 24d`, `90b 90c`, and `99A 99C` remain combined and are marked
  `mixed_content` where parallel fragments share a source block.
- Digital grouped vocabulary follows source table headings. Independently
  checked rows `fr104-117:vocab:2`, `:50`, `:83`, `:160` and
  `fr118-168:vocab:2`, `:11`, `:117`, `:239`, `:370`: each citation and parent
  match the preceding source heading. Page-wide commentary uses page scope.
- Both editions explicitly say fragment 103 contains first lines of ten
  different poems. Their aggregate records retain those lines with
  `mixed_content` and the source notice, while 103Β is separate.
- Both fragment 137 records retain Greek dialogue speaker labels and carry
  uncertain authorship / `mixed_content`. The Digital source note warns that
  identifying its speakers as Alcaeus and Sappho is spurious. Fragment 140's
  chorus and Aphrodite labels are dramatic speakers, so its Sappho author
  label remains in place.
- Seven Greek-only vocabulary snippets have `language=grc`; the other 2,241
  commentary records are `eng`. A total of 21 records are explicitly marked
  `mixed_content`; they are retained for review, not asserted as single clean
  poems.

This is an audit of the saved source artifacts and the current collector
output, not an independent critical edition of every fragment. Source-page
editorial attributions, uncertain fragments, and parallel column groups remain
visible with their source URLs and review labels.
