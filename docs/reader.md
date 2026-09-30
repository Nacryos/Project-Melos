# Melos research reader

The research reader uses the original Melos hero, painting controls, mosaic
effects, typography and palette. Its research data comes from downloaded
sources, never `data/lexicon.json`'s historical sample entries.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8791
```

Open http://127.0.0.1:8791. The original design/search page remains at `/legacy`.
No remote deployment or subscription-corpus scraping is involved.

## Sources and rebuilding

Collectors under `scripts/ingest_*.py` retain downloaded artifacts, source URLs,
edition identities and SHA-256 hashes. Reports live in `data/reports/`.
Consult each script's `--help` before rerunning a large collection.

`python scripts/build_corpus.py` admits only independently accepted outputs
whose hashes still match `data/reports/audit-acceptance.json`. Merely placing a
file in `data/processed/` does not make it accepted. Audit findings and limitations
are recorded in `docs/audits/`. Source-faithful extraction is not proof that the
underlying edition's author attribution or reconstruction is correct.

Once the accepted index is stable:

```powershell
# Separate dictionary-reference index; requires its accepted audit hash:
python -m scripts.build_wiktionary_index
python scripts/merge_p2_acceptance.py
python scripts/build_corpus.py
python scripts/build_evidence.py
# Expand incrementally to all eligible material:
python scripts/build_embeddings.py --max-passages 0
python -m pytest tests -q
```

Raw corpora, derived JSONL, generated source metadata/reports, model weights,
and indexes remain on local disk and are excluded from Git. Collectors and
audit scripts preserve the reproduction workflow; local reports preserve the
actual extraction trail. Per-record licenses and original source notices govern
reuse. Unknown rights remain unknown; collection for this local installation
is not a blanket license to redistribute all source material.

## What the interface means

- Wording search tolerates Greek accents and offers explicit spelling suggestions.
- Form search expands only through source-indexed analyses, not invented paradigms.
- Clicked-word analyses are alternatives, not automatically adjudicated senses.
- Explicit source claims linked to the clicked passage appear first, with
  quotations, locators and scope. General dictionary entries, spelling
  suggestions and other contexts remain distinct. A source claim reports what
  its source says; it is not a guarantee that the philological judgment is right.
- Wiktionary is a separate, machine-extracted reference panel. Its entry, sense,
  and listed-form labels retain their original scopes; a listed form is not an
  attestation in an ancient author. Live dictionary links may differ from the
  saved snapshot.
- All-evidence search combines lexical, source-listed form and multilingual
  vector candidate rankings through reciprocal-rank fusion. Explicitly linked
  commentary/translation evidence can retrieve a Greek parent passage. There
  is no invented thematic ontology or automatic inference of literary influence.
- A small [retrieval evaluation](retrieval-evaluation.md) covers 38 source-based
  queries, not general Ancient Greek semantic accuracy. Literal/form search
  remains available because hybrid search is not uniformly superior.
- Author-date ordering uses sourced biographical metadata, not secure poem dates.
- The 3D view is a lossy similarity projection, not a map of proven influences.
- Mixed OCR, apparatus, and review-needed records are separately labelled and
  excluded from ordinary text search unless reference material is enabled.
- Editorial supplements remain edition evidence, not necessarily surviving letters.

## Current coverage and limits

Current exact counts are reported by `/api/status` and the reproducible
[coverage report](coverage.md). Records are not unique poems, fragments or
independent witnesses; OCR and reference collections remain separately labelled.

The dictionary layer has 126,294 LSJ/Autenrieth entries and 478,086 source
treebank token observations. The separate Wiktionary snapshot has 68,196
entries. These counts measure different things and must not be added into a
single attestation count. Structured Wiktionary extraction additionally retains
sense-level relationships, dialect-label scope and whole source paradigms.
The UI reports current semantic coverage of eligible source text, translations
and commentary. Greek, English, Latin, Italian, French, German and multilingual
records may be eligible; OCR, uncertain mixed material and apparatus are excluded.

Sappho, continuous epic and hymns are much better covered than many fragmentary
lyric poets. The second pass adds 157 Alcaeus source-edition records (154
search-eligible), Pindar scholia, a Theognidean anthology, Pitotto's licensed
2024 Stesichorus edition and source-critical notes. Ibycus has only five
scan-verified partial Greek lines plus references and labelled page OCR:
this is not a complete Ibycus corpus. Modern edition coverage remains partial.
Source-backed author identity profiles merge verified aliases; mixed or
unidentified labels remain unresolved. Neither a large collection nor an audit
establishes completeness, editorial correctness, or reliable sense selection.

Jev is the preferred optional contextual classifier when a server-side
`TYPESAFE_API_KEY` is configured. Its bounded choices are model proposals,
not new corpus facts or calibrated probabilities. See [classifier setup and
limits](context-classifier.md). The tested local Qwen alternative stays disabled:
it failed source-critical abstention cases. Public paid classification is
blocked until an authenticated, rate-limited gateway is added; read-only corpus
search can be hosted separately for the [Vercel frontend](deployment.md).

See [corpus schema](corpus-contract.md), [API](api-contract.md),
[morphology](morphology.md), [semantic models](semantic-models.md), and
[usage-space interpretation](usage-space.md). The separate dictionary layer is
documented in [Wiktionary references](wiktionary-reference.md).
