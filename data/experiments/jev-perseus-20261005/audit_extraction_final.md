# Audit: Download through final cross-validation — Greek morphology pilot

## Steps: 2–7
## Agent Action

Team A downloaded live Perseus pages through requests, preserved raw bytes and metadata, parsed source candidates and paired passages, and wrote isolated experimental JSON. The original strict run stopped after a timeout. A documented, parent-authorized amendment permitted logged omissions after failures, at most three consecutive morphology failures per passage, and a separately identified previously inspected positive control.

## Audit Checks

- [x] Step 2: Actual requests execute; successful responses and HTTP error bodies have raw artifacts, URLs, timestamps, byte counts, and SHA-256 hashes. Original and amended timeout receipts are separately retained.
- [x] Step 3: Every surviving candidate row independently compared to its raw morphology HTML, including lemma, gloss, form, morphological string, displayed votes, displayed percentage, and selected-row class. All four rows match exactly.
- [x] Step 3: Greek context, published translation, clicked target anchor, href, occurrence callback, and passage alignment independently checked against raw files.
- [x] Step 4: Only HTML decoding and whitespace normalization operate on linguistic text. Vote/percentage strings undergo deterministic numeric parsing; no transliteration, phonological conversion, inferred glosses, or generated translations occur. All four numeric transformations independently recomputed and matched. Linguistic transformation-reference requirements are therefore inapplicable.
- [x] Step 5: Valid JSON, unique case and candidate identities, complete required fields, no padding. Four alternatives remain distinguishable by lemma and morphology.
- [x] Step 6: Summary counts and cases SHA-256 match files; raw references resolve. No production dictionary or existing dirty file modifications introduced by extraction.
- [x] Step 7: Exhaustive audit covers all surviving records (one case/four candidate rows), exceeding a random sample for this small result. Complete provenance chains resolve to live source URLs and saved raw responses.

## Evidence

- Case: odyssey-002, explicitly labeled previously_inspected_positive_control.
- cases.json SHA-256: b351a8babba4a096c8b0e05aba9a40dd14e9244672389412b05a6dd4e9d61a3d.
- Counts: one positive control, zero fresh cases, seven amended attempts, six unavailable occurrences.
- Independently checked all 12 raw metadata files: seven HTTP 200 responses and five HTTP 503 bodies; all saved byte counts and hashes match.
- Original first-occurrence 60-second timeout and amended 15-second timeout are separately logged. The original selection plan and original pending attempt are preserved alongside selection_amendment_v2.json.
- Candidate source form for the selected row includes a dagger. This field MUST remain outside blind requests because it reveals the source winner. Source votes, percentages, evaluator tables, original row positions, and selected flags also MUST remain excluded.
- Greek and English context share the Odyssey CTS passage 1.1–1.43. Published translation attribution and edition descriptions remain in the source record.

## Verdict: PASS
## Blocking: NO

Approval covers data integrity of the surviving positive control and preparation of four score-blind experimental requests. It does not imply the aspirational fresh sample was obtained. Zero fresh cases means this run can only check the comparison procedure and behavior on an already inspected example; it cannot estimate general accuracy or superiority. Final request artifacts require a separate blindness and budget audit before network execution.
