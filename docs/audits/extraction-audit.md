# Extraction audit

## Scope and acceptance rule

This is an independent audit of collector JSONL against `docs/corpus-contract.md`.
The automated gate is `python scripts/audit_corpus.py --json data/reports/audit-corpus.json`.
It checks every record's required schema, categories, ID uniqueness, saved raw
artifact and SHA-256, source URL, source-derived text, chronology attribution,
language contamination, placeholders, and OCR classification. It draws a
repeatable random sample of 20 for manual output-to-source tracing.

`PASS` means the mechanical checks passed. It is not a claim that the author,
edition, citation, license, or source URL has been independently verified.
`WARN` needs review before a record is called curated. `FAIL` blocks that
collector's affected records until repaired or quarantined. Actual source
counts are accepted as reported; round counts alone are never a reason to fail.

## Modular review ledger

| Step | Check | Current status |
| --- | --- | --- |
| 1. Discovery | Exact source URL, authority, license, and scope | Pinned source paths checked; unresolved edition/editor identities disclosed |
| 2. Download | Reproducible request, saved bytes, SHA-256 | PASS for all accepted corpus JSONL; OGC 155 raw JSONL, Perseus 197 TEI, Lyra four OCR sources, etc. |
| 3. Parse | Text and editorial signs in raw source; no placeholder or mixed-attribution leakage | PASS within source-specific quality labels and reference quarantine |
| 4. Transform | Whitespace-only changes unless documented; dates and mappings sourced | TEI marks retained/flagged; OCR never reconstructed; OGC derived spans exact; author chronology separate |
| 5. Output | Contract schema, stable unique IDs, language/kind/quality labels | PASS for eight accepted corpus files |
| 6. Integration | Counts and metadata match authoritative JSONL; no unreviewed text curated | Pending final SQLite build check; required OGC overlay is hash-bound |
| 7. Cross-validation | Seeded 20-record trace through output, parser, raw, and URL | PASS per collector; independent manual OGC/Sappho reports supplement these samples |

## Classification boundaries

- OGC's author-labelled files may contain other poets, Latin apparatus,
  bibliography, and commentary. A filename or collection label is not proof
  of authorship. Such spans need direct attribution evidence or a reference /
  `mixed_content` / `needs_review` label.
- Scan OCR is evidence of a page image and an OCR process, not a verified
  ancient Greek edition text. Keep it available as reference with `machine_ocr`
  or `needs_review` until visually checked against the page.
- A translation placeholder is neither translation nor commentary. Exclude it
  from the corpus and record the gap in the collector report.
- Missing bibliographic identity, chronology, and attribution must be marked
  unknown or omitted as permitted by the contract; never filled from memory.
- Editorial brackets, lacunae, daggers, dots, and uncertain readings belong in
  the source text layer. Normalized or reconstructed variants require separate,
  explicitly linked records with their own provenance.

## Automation limits

The audit script confirms that a normalized passage occurs in the saved raw
text, or that each declared line occurs there. This proves text origin only.
It cannot prove that a line was selected from the right TEI element, attributed
to the right author, or cited correctly. It also cannot read image-only PDFs;
those require a saved OCR artifact linked to the scanned page plus visual QA.
The final ledger records manual checks and unresolved uncertainty by source.

## Accepted corpus outputs, 2026-09-30

The combined manual/mechanical allowlist is
`data/reports/audit-acceptance.json`. It includes each JSONL file's exact
SHA-256, count, manual decision, and any required overlay. Changing a file
invalidates its acceptance even if its name stays the same. Every file below
has zero remaining mechanical failures and warnings at its recorded hash.

| File | Records | Raw artifacts | Acceptance scope | Sample trace |
| --- | ---: | ---: | --- | --- |
| `perseus.jsonl` | 14,706 | 197 TEI | Main text; 1,197 editorial/review records kept distinct | 20/20 |
| `sappho.jsonl` | 2,647 | 200 HTML | 399 Greek text, 2,248 commentary; 21 mixed records marked | 20/20 plus stratified manual 20/20 |
| `lyric_web.jsonl` | 102 | 28 API revisions | 85 Greek text, 17 uncertain references | 20/20 |
| `commentary.jsonl` | 326 | 175 DCLP TEI | 175 witness references, 119 apparatus, 32 commentary | 20/20 |
| `reception.jsonl` | 589 | 8 TEI | Comparative Latin/English, no direct Greek influence claimed | 20/20 |
| `lyra.jsonl` | 2,460 | 4 DjVuXML | Uncorrected OCR, reference only; no Greek transcription | 20/20 |
| `ogc.jsonl` | 258,548 | 155 JSONL | Labeled staging only, never blanket curated poet text | 20/20 exact raw rows plus independent manual 20/20 |
| `ogc_derived.jsonl` | 638 | 40 parent raw files | Exact prefixes, unknown-author reference only | 20/20 |

The final OGC base file is accepted only with the `ogc-quality.jsonl`
annotation at SHA-256
`91aa1d4df5d1fd0323732f54cc1de17724d66438c6d43ee4c611b334bea04ffc`.
All 258,548 labels were bound in order to the parent ID, text SHA-256, and raw
path/hash. A source-text record with Greek variants and `(Voigt)`/`(Campbell)`
(`ogc:sappho.fragmenta.jsonl:194`) is marked ineligible by that overlay.
The 638 derived records were independently checked for exact parent spans,
boundary evidence, parent hashes, and reference/unknown-author labels.

## Findings and repairs by pipeline step

- **Download:** No accepted record lacks its saved raw artifact or matching
  SHA-256. Source URLs are pinned by commit where repositories provide commits;
  Wikisource API revisions and page URLs are retained. Four linked Wikisource
  pages were genuinely absent and logged; none were fabricated to reach a count.
- **Parsing:** An early lyric-web parser dropped the Greek editorial supplement
  `<έο>`; the collector preserved it in the final source line. Early Sappho
  records included WordPress controls and DCC English notes in Greek; these
  were separated or removed. OGC poet-named files mixed other authors,
  testimonia, Latin apparatus, and Greek prose; source-scope flags and the
  quality overlay now prevent their unqualified default use.
- **Transformation:** Perseus initially included deleted TEI readings as plain
  source text and omitted visible gap/supplement marks. The revised 14,706-row
  file retains visible marks, 109 standalone apparatus records, and 2,152 exact
  serialized TEI evidence fragments; 1,197 affected records are `needs_review`.
  Sappho fragments 103 and 137 retain explicit multi-poem or uncertain speaker
  attribution labels. No inferred translations, poem dates, or OCR Greek were
  supplied.
- **Output:** Required schema, IDs, hash bindings, language, kind, and quality
  pass. The auditor itself was corrected to split JSONL only at `\n`, preserving
  U+0085 lacuna markers, and to trace TEI structured apparatus and HTML
  commentary assembled across omitted tables. This prevented false failure
  counts from being mistaken for source defects.
- **Integration:** The completed SQLite index has 280,016 passages from all
  eight accepted files, 653 work groups, and no rejected or quarantined rows.
  Each indexed file still matches the allowlisted SHA-256. The 280,016 FTS
  rows reconcile with passages; there are no missing work, parent, token, or
  FTS links. The OGC overlay demoted 21,060 otherwise clean-labeled text rows
  to `reference/needs_review`. None received tokens. All 88,180 retained OGC
  `text/source_text` rows meet overlay eligibility, clean-source-text, and
  poetry-scope predicates. OCR, mixed, review, and reference rows received no
  tokens. In particular, `ogc:sappho.fragmenta.jsonl:194` is
  `reference/needs_review` with zero tokens. All 638 OGC derivatives remain
  `reference/machine_ocr` with unknown author. The coverage JSON was regenerated
  from this same index; its SQL-derived 280,016 records and per-source counts
  equal the index manifest, with 90 exact author labels. Exact-label target
  matches keep case variants visible without merging substring candidates.

## Chronology metadata

`data/metadata/chronology.json` is separate from poem passages. Its saved
Wikidata response hash matches; all ten configured QIDs and 52 statement IDs
match raw claims. Selected sorting claims are referenced and non-deprecated,
qualifier bounds and alternative claims are retained, and all ten `poem_date`
values are null. These are source-reported biographical claims for sorting,
not established poem composition dates. Wikidata JSON represents a BCE year
as a negative year number, with century/decade precision requiring interval
interpretation ([Wikidata date help](https://www.wikidata.org/wiki/Help:Dates),
[Wikibase time model](https://www.mediawiki.org/wiki/Wikibase/DataModel)).

## Remaining uncertainty

This acceptance validates reproduction and labeling of source artifacts, not
every poem's ancient attribution or an independent critical edition. OGC's
`primary_search_eligible=true` is a retrieval candidate, not a scholarly
certification. Lyra OCR contains no reliable Greek Unicode text and is useful
only as page-linked reference. The Perseus/Sappho edition readings still carry
editorial choices. DCLP authors are witness-level labels; source witness dates
are not dates of poem composition. Individual editor attribution remains
unresolved in OGC's pinned coverage and edition registries. The exact
source-specific manual evidence is in `docs/audits/sappho-manual.md` and
`docs/audits/ogc-manual.md`.
