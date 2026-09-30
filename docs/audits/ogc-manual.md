# Independent OGC manual audit

Audited 2026-09-30 against `docs/corpus-contract.md` and the data-extraction skill. This decision is bound to `data/processed/ogc.jsonl` SHA-256 `837f527f096141a926930e9f929ba475550788779a5b97dbafb9127d6834bbce` (258,548 records from 155 saved, commit-pinned OGC JSONL files at `f4062a5013e56d2727e3e88e7a8d8e13d207a06d`). The exact 20 sampled IDs and machine-readable check outcomes are in `data/reports/ogc-manual.json`.

## Verdict

**PASS for labeled, provenance-preserving staging; FAIL for treating the entire OGC selection as curated poet text.** All 20 sampled processed passages matched their saved raw row's text, URN, edition, locus, source and original license; the raw-file hashes and pinned URL paths matched. This validates extraction traceability for the sample, not scholarly attribution or textual reliability. The independent source audit separately checked source accessibility. This pass did not refetch every sampled URL over HTTP.

The collector now keeps mixed OCR, scholia, testimonia and prose witnesses available as references. The high-risk corrections verified here are:

| Source evidence | Final scope |
| --- | --- |
| `alcaeus-lyric.fragmenta:2` contains an explicit **Cleobulus** label and Latin/Greek apparatus after its initial Greek; `:120` cites Herodian and discusses Alcaeus. | Both `reference` / `mixed_content` / `author=unknown`; the filename does not establish authorship. |
| `xenophanes.testimonia` contains cited testimonia, including `:2` beginning with `THEOL. arithm.` and editorial notes. | All 410 rows `reference` / `mixed_content` / `author=unknown`. |
| `aratus-sicyonius.fragmenta` consists of seven Greek/Latin prose witnesses about Aratus. Row `:1` begins `Συμμίξας δὲ τῷ Ἀράτῳ περὶ Κόρινθον ὁ Ἆγις`; row `:2` refers to Aratus's `Ὑπομνήμασιν`. | All seven `reference` / `author=unknown`, even when source transcription is clean. |
| `callimachus.aetia` interleaves verse with Greek introductory and bibliographical prose. Loci `0.1`, `0.4`, and `0.5` are introductory witness text; `0.2` is verse. | Those three loci `reference` / `mixed_content` / `author=unknown`. Other loci carry a review flag in the separate annotation where appropriate. |
| `anthologia-graeca.anthologia-graeca:1` is Greek source text from a collection, with no passage-level poet attribution in the raw row. | `author=unknown`; quality annotation keeps collection scope out of primary poet attestations. |
| `scholia-in-pindarum...:1` is source-transcribed scholion material. | `reference`, though `quality=source_text` correctly describes transcription method. |

The sampled Perseus, DCC, First1K, DFHG, Wikisource and OCR rows preserve their upstream `source` and `edition` fields. `source_text` means a source transcription, not an independent scholarly review. Perseus and DCC reading texts can be searched with their upstream edition and rights caveats. OCR of public-domain print editions has effective `CC-BY-4.0` per the pinned OGC `LICENSE`; the original upstream `PD` label remains in `metadata.ogc_record_license`. The pinned coverage and edition registries do not supply the promised individual editor names, so editor attribution remains unresolved.

## Quality annotation and search gate

`scripts/label_ogc.py` reads the pinned OGC README for edition-level OCR status and records exact marker spans without changing the parent text. Its output report binds to the same processed SHA. All 258,548 annotations align by parent ID, parent-text SHA-256 and raw SHA-256, and every stored marker span matches the parent text. All 638 derived prefixes equal their exact parent spans and remain `reference` / `author=unknown`; zero mismatches were found. The annotation and derived file hashes are recorded in the JSON report.

The screen is conservative but incomplete. `aratus-sicyonius.fragmenta:1` and `callimachus.aetia:1` were Greek-only prose that initially appeared `clean_source_text`, demonstrating that Unicode and Latin-marker rules cannot certify verse or authorship. The final source-scope correction demotes the former, and the collector plus annotation demote or review the latter. Even a remaining `primary_search_eligible=true` is a search candidate, not a verified primary attestation.

For the default poem index, join the annotation by `parent_id` and matching input/raw hashes; require base `kind=text`, `quality=source_text`, `block_label=clean_source_text`, `bibliographic_scope=poetry`, `primary_search_eligible=true`, and no source-scope demotion. Keep flagged source text, OCR, and derived prefixes in a separate reference/review route. Preserve both raw and annotated records rather than silently rewriting poem text. This recommendation is an indexing policy, not an assertion that the remaining candidates are fully curated.
