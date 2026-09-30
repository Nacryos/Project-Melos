# Corpus interchange

Each collector owns `scripts/ingest_NAME.py`, `data/raw/NAME/`,
`data/processed/NAME.jsonl`, and `data/reports/NAME.json` (or `.md`).
Do not edit another collector's output. UTF-8 throughout. Preserve source text;
never supply missing Greek, translations, or bibliographical details from memory.

Each JSONL passage has these fields (additional fields allowed):

```
id                  stable source-specific string
source              collector name
source_url          original source or exact raw file URL
raw_path            relative saved artifact path
raw_sha256          saved artifact hash
author              source author label
work                source work title
edition             source edition identity
citation            original source passage/fragment reference
language            grc / eng / lat / other ISO code
text                extracted text, unchanged except whitespace processing
kind                text / translation / commentary / apparatus / reference
quality             source_text / machine_corrected_ocr / machine_ocr / mixed_content / needs_review
license             actual source license or unknown
parent_id           optional related Greek passage ID
lines               optional list of {label,text}
date_start          optional integer year, negative BCE; omit if not sourced
date_end            optional integer year
date_source         required when supplying chronology
metadata            optional source-specific object
```

Extract bibliographical labels from source metadata where possible. Configured
author/collection mappings must cite their source and are metadata, not invented
ancient text. Preserve apparatus and editorial marks. Keep uncertain mixed OCR
available as reference material; do not mislabel it as the poet's authored text.
Interpretive annotations and reconstruction proposals belong in separate records
with model/source/method and evidence spans, never overwriting the raw text.

Collectors: use reproducible requests, save raw bytes, retry politely, log failures,
and produce actual counts. Do not copy TLG content. Prefer source repositories over
scraping their reading interfaces. Inform the independent audit agents when source
discovery and outputs are ready. Publish no payload as curated before audit.

Cached-source boundary repairs must preserve existing IDs for unchanged source
identities; inserting a newly recognised heading must not shift old numeric IDs
onto different fragments. Preserve explicit source headings, column and witness
labels. Parallel layouts without recoverable per-fragment allocation stay
labelled source groups requiring review, never appended to the preceding poem.
An unresolved commentary heading ends the preceding parent scope. Keep the
source note, but do not invent its exact passage alignment.

Source footnote markers belong to source-note metadata, not reconstructed Greek
text; retain their supplied descriptions and links. Printed verse numbers and
editorial uncertainty signs remain in the source transcription. Stage reparsed
JSONL, affected claim/offset repairs, lexical indexes and embeddings as a single
audited snapshot. Re-encode changed text with the pinned model/window contract;
updating an embedding manifest alone is not valid after a source-text repair.
Staging tools emit PENDING artifacts and must not overwrite active acceptance
reports or self-certify independent review.
