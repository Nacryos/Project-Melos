# Separate Wiktionary reference index

`data/lexica/wiktionary-entries.jsonl` is a source-preserving, machine-extracted
Kaikki Ancient Greek snapshot. It is not a critical edition, a lyric corpus,
or a source of contextual parsing decisions. Its nested `entry` object is
kept intact in `data/wiktionary.sqlite`; that database is a derived index and
does not alter the audited JSONL.

The build command is `python -m scripts.build_wiktionary_index`. It refuses
to build unless `data/reports/wiktionary-audit.json` has `status: accepted`
and its `output_sha256` exactly matches the full JSONL bytes. Loading the
index repeats this check and also compares the SQLite metadata hash. The
database is written separately from `data/corpus.sqlite` and installed only
after a complete build and integrity check.

```python
from backend.wiktionary import WiktionaryLookup

service = WiktionaryLookup()
try:
    response = service.lookup("ὀρέων", limit=8)
finally:
    service.close()
```

The response is `{query, normalized, results, total, source_sha256, method, warnings}`.
Each result identifies the source snapshot, quality, license, raw line, and
hash. Entry-level `tags`/`raw_tags`, sense-level `tags`/`raw_tags` and
`form_of`/`alt_of`, and matched form objects remain at their source scope.
Only a bounded number of source entries, senses, and matching forms are
returned; `total` and `total_senses` disclose truncation. A listed form has
`evidence_type: dictionary_listed_form`. That label makes no assertion about
whether the spelling appears in the corpus. The warning explains that
dictionary form lists are not textual attestations.

`source_url` identifies the fixed Kaikki download. `live_entry_url` is a
convenience link to the corresponding live Wiktionary headword and may have
changed since the audited snapshot. The reference service never merges its
entries into LSJ/treebank morphology candidates or the corpus search index.
