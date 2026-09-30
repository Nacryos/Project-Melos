# Lexicon and form extraction audit

## Verdict

**PASS for source integrity and extraction traceability.** The machine gate is
`python scripts/audit_lexica.py`, which writes
`data/reports/audit-lexica.json`. Its `files` object gives a `PASS` verdict and
exact SHA-256 for each output. This audit applies to dictionary entries and
annotated treebank token observations, not the passage corpus contract.

| Output | Records | SHA-256 |
| --- | ---: | --- |
| `data/lexica/entries.jsonl` | 126,294 | `ca2e64c5bace58fe58f44cd111884b0362b4f83480702077f526f14f13ae546e` |
| `data/lexica/forms.jsonl` | 478,086 | `a649f46b22408b8fefe79ff53f27e88996083a2cc87ab1e02c59386c5848a46f` |

The entries comprise 116,497 LSJ and 9,797 Autenrieth records. The form file
comprises 478,086 Perseus Greek Dependency Treebank v1.6 token analyses. The
collector saw 558,019 treebank tokens, skipping 79,688 non-Greek tokens and
245 Greek tokens without a usable lemma or analysis. The Autenrieth raw file
has 9,824 `entryFree` elements; 27 were skipped for missing or invalid keys,
orthography, or IDs. Their source IDs and reasons are in
`data/reports/lexica_ingest.json`.

## Evidence by extraction step

| Step | Independent check | Result |
| --- | --- | --- |
| Discovery | Three pinned source repositories and commits, source-specific notices and bibliography in ingestion report; one pinned raw URL per source returned HTTP 200 on 2026-09-30 | PASS; Autenrieth license unresolved |
| Download | 105 saved XML source files checked against manifest byte lengths, SHA-256 and Git blob SHA-1; pinned URLs checked against path and commit | PASS |
| Parsing | Output schemas, source IDs, raw paths, URL and raw hash checked on every record; 20 seeded records reparsed from saved XML | PASS |
| Transformation | Sampled Beta Code headwords reconverted; sampled full entry text and first four distinct marked glosses compared to XML; treebank `postag` checked verbatim against token | PASS |
| Output | Exact JSONL line counts, required fields, unique dictionary IDs and file SHA-256 checked | PASS |
| Integration | Ingestion counts match output counts; machine gate exposes per-file verdict and hash | PASS |
| Final trace | Five LSJ, five Autenrieth and ten treebank records traced through output, raw XML, source URL, and raw hash | PASS |

The deterministic sample IDs are LSJ `n81739`, `n36126`, `n34695`,
`n36208`, `n49896`; Autenrieth `n9589`, `n9130`, `n955`, `n8691`, `n2180`;
and ten treebank tokens with exact source file, sentence ID and token ID in
the JSON report. The full trace includes each sampled original `postag`.

Manual inspection of LSJ `n49896` and Autenrieth `n9130` confirmed that an
empty marked gloss can accompany substantive source text or a cross-reference.
The audit therefore does not reject missing short glosses. There are 25,576
such LSJ records and 2,378 Autenrieth records. A short gloss is a limited
preview, not the full definition: LSJ takes at most four unique `<tr>` elements
and Autenrieth at most four `<gloss>` elements. `entry_text` retains the
complete plain text of each source entry, with Greek spans still in Beta Code.

## Use constraints and warnings

- LSJ's displayed Unicode `lemma` removes a terminal homograph index from
  2,278 source keys. `lemma_beta` and the unique entry ID preserve the source
  identity; dictionary lookup must keep distinct entries separate.
- The treebank's normalized `lemma` removes terminal source indices in
  298,242 token rows, while `lemma_raw` retains them. A `postag` is the source's
  contextual token annotation. It must be presented as a candidate for an
  uncontextualized matching form, because 14,328 forms have multiple distinct
  lemma/postag pairs in this dataset.
- Autenrieth has no verified reuse license in the downloaded Homerica
  notices. Those records accurately carry `license: "unknown"`; publication
  or redistribution needs a separate rights determination.
- Autenrieth XML requires recovery parsing because its DTD entities are
  undeclared in the saved file. The audit observed only undeclared-entity
  diagnostics in the parser's capped error log and confirmed literal entity
  references survive in `entry_text`. These references may require display
  handling; the extraction does not silently replace them with invented text.

This PASS is a reproducible provenance and extraction verdict for the named
file hashes. It does not assert that every dictionary interpretation is
scholarly correct or that Autenrieth has a verified redistribution license.
