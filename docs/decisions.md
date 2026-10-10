# Owner decisions on corpus policy

This file records decisions by the project owner that change rules stated
elsewhere in `docs/`. Where an older document and this file disagree, this
file wins. Each entry names what changed, why, and what it does not change.

## 2026-09-30: coverage over caution

The first two collection passes produced a large index with almost no
searchable text for the fragmentary lyric poets (Ibycus: five lines;
Stesichorus: two records) while the same poets were sitting in the index as
unlabelled reference material, and while complete modern texts were freely
readable online. The owner reviewed the causes and decided the following.

### 1. Machine-corrected OCR is searchable

Open Greek Corpus OCR of the public-domain Bergk editions that the upstream
project marks **auto-corrected** enters ordinary search under the quality
label `machine_corrected_ocr`. Blocks with Latin apparatus, replacement
characters, negligible Greek or mixed-author flags stay reference material.
Raw OCR stays reference material behind the "include reference" toggle.

Consequences: the corpus contract gains the quality value
`machine_corrected_ocr`; the OGC collector keeps the poet named by a
fragment collection's file name as the source attribution instead of
`unknown`; `scripts/label_ogc.py` marks corrected-OCR candidate blocks
eligible; `scripts/build_corpus.py` promotes matching `machine_ocr` rows
from an existing annotation without re-running the collector. The reader,
coverage report and status endpoint show the label. Embeddings include
these rows.

### 2. Modern editions are admitted, without limit

Text that follows a modern critical edition (Page, Davies, Campbell, West,
Voigt, Finglass and others), and text whose printed edition the source does
not name, may be collected and indexed for the site. Rights and licence
information are still recorded on every record exactly as the source states
them, and attribution travels with the text, but a licence is no longer a
gate on admission. The owner accepts responsibility for the resulting rights
position of the site.

This reverses the `FAIL` verdicts in `docs/audits/p2-sources.md` and
`docs/audits/p2-edition-sources.md` that rested only on rights or on a
missing edition name, in particular for the Centre for the Greek Language
anthology, Graecia Antiqua, Eulogikon, the Perseus Hopper Edmonds volumes and
the Wikisource *Anacreontea*. Verdicts that rested on text quality (broken
markers, unverifiable OCR) still describe the text and must be recorded as
metadata, not used to exclude it.

It does not change the operational rules: no login, paywall, rate-limit or
CAPTCHA circumvention; no acquisition of subscriptions by assumption; save
raw bytes and hashes; never author Greek from memory; never present a
translation placeholder as text.

### 3. Author labels are merged

`backend/author_aliases.json` maps the spellings different collectors use for
one poet (English name, "name of place" forms, aggregator slugs, Greek
script in any accentuation) onto one display name. Merging drives the author
chooser, the author filter, works listing, semantic filtering, mirror
grouping and the coverage report. Labels that join several poets with
`" / "` are never merged; they answer a filter for any of their parts and
stay visibly joint. Every record keeps its original source label. The
audited identity profiles of the second pass still apply where present.

### 4. Identical copies are grouped

Search results group records with the same merged author, language, record
kind, quality label and words into one result. The representative is chosen by quality
(edited text before corrected OCR) and by source (a direct collector before
an aggregator mirror). Collapsed IDs are returned as `mirrored_ids` with a
`mirror_count`, the passage view lists them under "identical text in other
copies", and totals count groups. Different words never merge, however
similar the citation. This replaces the earlier rule that collapsed only
copies sharing an edition identifier.

### 5. Verification of scans is optional

Visual checking of OCR against page images remains a good practice and the
route exists (`scripts/ingest_p2_editions.py`, `docs/audits/p2-texts.md`),
but it is no longer required before text is searchable, and it is not
worth doing where a modern edition of the same poet is available.

### 6. The owner accepts outputs

`scripts/accept_owner_outputs.py` writes PASS entries with exact hashes and
record counts into the acceptance manifests, replacing the independent
auditor step for files the owner has decided to admit. The build's
fail-closed checks (hash and count binding, quarantine of changed files)
are unchanged.

### New collectors

- `scripts/ingest_p2_cgl_anthology.py`: Centre for the Greek Language,
  *Anthology of Archaic Lyric Poetry* (ed. S. Tselikas): 383 poems and
  fragments with modern-edition numbering (West, Page, Voigt, Maehler ...)
  and Modern Greek translations linked as `translation` records.
- `scripts/ingest_p2_eulogikon.py`: Eulogikon *ancient-greek-texts*, pinned
  to a commit; archaic lyric, elegiac and iambic poets by default,
  `--all-poetry` for the whole domain. Edition unspecified by the source;
  scholia and testimonia are typed `commentary` and `reference`.
- `scripts/ingest_p2_perseus_elegy.py`: Edmonds, *Elegy and Iambus* I-II
  (Loeb 1931) from the Perseus open-source archive: Greek fragments, ancient
  testimonia and Edmonds's English, linked fragment by fragment.
- `scripts/ingest_p2_attalus_anthology.py`: Paton's Greek Anthology
  translations from attalus.org, linked to the Perseus Greek epigram rows.
- `scripts/ingest_lyric_web.py --source p2_wikisource_lyric --more`: further
  Greek Wikisource author pages under a separate source name.

English translations linked to Greek passages are what make English search
reach Greek text (see the retrieval lab, `scripts/lab_eval.py`), so
translation sources rank with text sources.

### Rebuild or upgrade required

These changes add `author_canonical` and `text_key` columns and a
`passage_authors` table. The API keeps serving an older index: authors still
merge (through SQL functions over the stored label) but identical copies are
not grouped, and `/api/status` reports `mirror_grouping: false`. A deployment
that holds only the built SQLite upgrades it in place, keeping a backup:

```
python scripts/migrate_corpus_schema.py --db /path/to/corpus.sqlite --promote-corrected-ocr
```

Where the collector outputs live, rebuild instead, in this order:

```
python scripts/ingest_ogc.py --commit f4062a5013e56d2727e3e88e7a8d8e13d207a06d
python scripts/label_ogc.py
python scripts/accept_owner_outputs.py --ogc
python scripts/ingest_p2_cgl_anthology.py
python scripts/ingest_p2_eulogikon.py
python scripts/accept_owner_outputs.py p2_cgl_anthology.jsonl p2_eulogikon.jsonl
python scripts/build_corpus.py
python scripts/build_embeddings.py --max-passages 0
python scripts/report_coverage.py
```

Without the OGC re-run the build still promotes corrected OCR in files
whose rows were already typed `text`, but the poet fragment collections
stay `reference / unknown` because the earlier collector labelled them so.

## 2026-10-10: literal machine translations as search rows and a last-resort reader fallback

The owner had Claude (Fable 5.1) make literal, line-by-line English renderings of every Sappho, Alcaeus and
Anacreon poem in Campbell's *Greek Lyric Poetry* (59 poems, 506 lines; the Word document of 2026-10-10) and
asked for them to go into the site "mostly for semantic search, backend work, and displayed only when there are
no available English author translations for that poem".

### What changed

- **A new quality value `machine_translation`** (corpus contract). Rows are `kind: translation`, `language: eng`,
  `parent_id` = the Campbell poem, `source: literal_translation_claude`, id `<poem id>:literal`
  (`data/campbell_glp/literal_translations_rows.jsonl`, built by `scripts/build_literal_translations.py` from the
  committed source `data/campbell_glp/literal_translations/claude-fable-5.1-2026-10-10.json`; appended to a corpus
  copy with `scripts/import_literal_translations.py`). They enter the English BM25 bridge and the dense indexes
  (release O BGE-M3 and the release S stack), crediting the Greek poem exactly as a published translation row does.
- **Reader sidecar** `backend/literal_translations_data.json` (`backend/literal_translations.py`), served by
  `/api/passage` as `literal_translation` with `display_policy: fallback_only`, `model_eligible: false`,
  `published_source: false` and `published_english_available`. The reader renders it only when neither a published
  translation preview nor an other-edition comparison was shown (today: Alcaeus 45 alone), under the heading
  "Literal line-by-line rendering · unpublished, machine-made", with the translator, date and method stated.
- Each record is bound to the Campbell text it was made from (record id, edition fragment, PDF hash, text hash,
  line count); a changed text yields `status: unavailable`, never a stale line.

### What it does not change

- The rule in `docs/corpus-contract.md` against supplying missing translations from memory as *source* records
  stands: these rows carry their own quality value and licence note, are excluded from `related` source material
  and from reference-query listings, are never `translation_previews` or `translation_comparisons`, and never reach
  the analysis context, the Jev ranker or the sense ranker.
- The other-edition comparison sidecars (pre-1930 published English) are untouched and keep display priority.
