# Perseus lexica ingestion: Middle Liddell, Cunliffe (Slater blocked)

Status (2026-10-08): **wired into lookup** through the open-lexica supplement,
together with LSJ (Logeion edition) and Dodson. See
[`docs/lexica-open-supplement.md`](lexica-open-supplement.md) for what is now
read, the dictionary order, the short-gloss rules, coverage numbers and the
deploy steps. The staging description below is still accurate for the two
Perseus sources. Script: `scripts/ingest_perseus_lexica.py`.

```
python -I scripts/ingest_perseus_lexica.py --download --report   # fetch missing pinned raws, parse, print counts + 5 samples each
python -I scripts/ingest_perseus_lexica.py --source cunliffe       # one source only
```

## Where the sources actually are

The brief assumed all three lexica were in `github.com/PerseusDL/lexica`. They
are not. At its current head `56061ca127f4a2844980baffc5f2b6d1332897b3`
(2026-09-02, the same commit production LSJ was built from), that repository
holds only LSJ (`grc/lsj`), Lewis & Short (`lat/ls`) and one other Latin
lexicon (`lat/viaf2845558`). The sources actually used are:

| Lexicon | Raw file | Pinned source | Raw SHA-256 | Licence |
|---|---|---|---|---|
| Middle Liddell (Liddell & Scott, *An Intermediate Greek-English Lexicon*, Oxford 1889; Perseus `1999.04.0058`) | `data/raw/perseus-lexica/hopper-2011-05-27/Classics/LSJ/opensource/ml.xml` (19,138,674 B; CVS rev 1.9, 2011-03-31) | Perseus Hopper open-source texts tarball `https://www.perseus.tufts.edu/hopper/opensource/downloads/texts/hopper-texts-GreekRoman.tar.gz` (Last-Modified 27 May 2011, 124,801,865 B, sha256 `b88ef05d73fabce6245ba387410e1b854abf6337925a6a594f0f8e3e35c1862c`), member `Classics/LSJ/opensource/ml.xml` | `cff0a7e50111bb86b282e11db5c725351cb37723900659371396fe835bcc1d7c` | CC BY-SA 3.0 US: "Texts are licensed under the Creative Commons ShareAlike 3.0 License" on https://www.perseus.tufts.edu/hopper/opensource/download (a copy is saved as `opensource-download-page.html`, sha256 `b6f7301e…902450`) |
| Cunliffe, *A Lexicon of the Homeric Dialect* (London 1924), Perseus TEI edited by G. Crane, corrected by H. Dik | `data/raw/perseus-lexica/homerica-d71ed43cc912d3e053cbb0dd6341f798ea058378/cunliffe.lexentries.unicode.xml` (14,898,460 B) | `gregorycrane/Homerica@d71ed43c` (the same repo and commit as production Autenrieth). Git blob `3454855639a0513d3953556962d87ad586426a07` is checked on download | `4c4dd04000ad73a77f5d33c4440337f3d1c3758a9c436ffed71ebd22d44d4d7a` | `unknown`: the repo has no licence file, the same as the Autenrieth rows. The 1924 print edition is in the US public domain, but the rights to the digital edition are not stated |
| Slater, *Lexicon to Pindar* (De Gruyter 1969; Perseus `1999.04.0072`) | **not ingested** | No open TEI found. It is absent from PerseusDL/lexica, from Homerica and from the 2011 Hopper open-source tarball, which has only Pindar texts and Gildersleeve. GitHub code search finds only catalogue records (`PerseusDL/catalog_pending`). | n/a | Edition under copyright. Perseus shows it online but has not released it as open data |

Other mirrors of Middle Liddell were found but not used, because the official
Perseus download is the authoritative copy. `cltk/cltk_grc_liddell_scott_intermediate/ml.xml`
is byte-size-identical to the Hopper file. The others are
`blinskey/middle-liddell`, `adiel-mittmann/middle-liddell` and `helmadik/MiddleLiddell`.
`data/raw/` is git-ignored. Each raw download went into a new, empty directory.

## Counts (staging, `data/staging/lexica/`)

| File | Rows |
|---|---|
| `middle-liddell.entries.jsonl` | 36,493 entries (30,679 `type="main"`, 5,814 `type="cv"`), 55,137 `<sense>` records |
| `middle-liddell.xrefs.jsonl` | 19,330 TEI `<ref>` cross-references |
| `cunliffe.entries.jsonl` | 9,821 entries, 12,591 sense `<div>`s |
| `cunliffe.forms.jsonl` | 6,022 printed inflected forms (`<term type="orth">`) |
| `cunliffe.xrefs.jsonl` | 11,847 TEI `<ref>` cross-references |
| `perseus-lexica.manifest.json` | Provenance, counters, skipped items |

Diagnostics:
- Middle Liddell: 2,142 entries have no `<tr>`, so their gloss is empty.
  1,773 entries have no `<sense>`; these are mostly "= X" or etymology-only
  stubs, and their full text is still in `entry_text`. In 218 entries the
  `<orth>` headword differs from the `@key`. For example, `key="kai\2"` has
  orth `kai\ga/r`. The lemma comes from `<orth>`, the printed headword, and
  `key` is kept. One commented-out `<sense>` (n21475) is correctly ignored.
  Three source ids are each used by two different entries: n16257
  (καθεύδω/καθηγεμών), n16281 and n33943. The second occurrence gets the id
  `middle-liddell:<id>@<byte_start>`, which keeps all 36,493 ids unique.
- An independent audit agent found 0 mismatches. It used its own parser with
  seed 20261007 and checked 20 ML entries, 20 Cunliffe entries and 20 Cunliffe
  form rows: lemma, every sense text at its locator, gloss items, and the
  form/label/citations. It also confirmed the hashes, the git blob, the
  tarball member identity, and that production `data/lexica/` is untouched.
- Cunliffe: 2,825 entries have no `<gloss>`. 4,567 have no sense sub-`<div>`;
  these are mainly form cross-reference stubs such as γοῶντες ("contr. nom. pl.
  masc. pres. pple. γοάω"), and their entry-level `<p>` blocks are kept in
  `paragraphs`. Three top-level divs were skipped and logged in the manifest:
  `care-cunliffe-lex-morph.b`, `care-cunliffe-lex-morph.c` and
  `care-cunliffe-lex-2.d`. They are κάρη sub-senses that are mis-nested in the
  source, and they contain 8 orth terms that are not in `forms`. 119 form
  strings contain a parenthetical alternative, for example `νηός (νηϝός)`.

## Validation headwords (first sense, verbatim; ML shown with Greek spans rendered)

| Source | Headword | First sense |
|---|---|---|
| ML | καί | "Conjunction, used in two principal senses, either copulative, to join words and sentences, and, Lat. et; or making a single word or clause emphatic, also, even, …" |
| ML | ἔρχομαι | "to come or go, Hom., etc." |
| ML | ναῦς | "a ship, Hom., etc.; ἐν νήεσσι or ἐν νηυσίν at the ships, i. e. in the camp …" |
| ML | ἀείδω | "to sing, Il., etc.:—then of any sound, to twang, of the bowstring, Od.; …" |
| ML | μῆνις | "wrath, anger, of the gods, Hom., Hdt., attic" |
| ML | ἄναξ | "a lord, master, being applied to the gods, esp. to Apollo and Zeus, Hom.; …" |
| Cunliffe | ἄναξ | "1 A king (the main notion being app. that of a protecting chief rather than that of a ruler; …" |
| Cunliffe | ἀείδω | "1 To sing: μουσάων, αἳ ἄειδον Il. 1.604. …" |
| Cunliffe | μῆνις | "1 Wrath, ire : μῆνιν ἄειδε Ἀχιλῆος Il. 1.1. …" |
| Cunliffe | ἔρχομαι | "1 To go, go or take one's way, proceed: …" |
| Cunliffe | καί | "1 Connecting particle, and Il. 1.15, …" |
| Cunliffe | ναῦς (printed νηῦς) | no sense div; gloss "This form as ablative; A ship"; forms include Acc. νῆα |

## Schema mapping

Entry rows are a superset of production `entries.jsonl`, and every field in
`scripts/audit_lexica.py:ENTRY_FIELDS` is present:

| Field | Middle Liddell | Cunliffe |
|---|---|---|
| `id` | `middle-liddell:<entry@id>` | `cunliffe:<div@xml:id>` |
| `lemma` (NFC) | `beta_to_uni(first <orth>)` | `div/@n`; for `n="crossref"` stubs, the `<head>` text with trailing `,` and homograph digit removed (`lemma_from` records which was used) |
| `lemma_beta` | `<orth>` Beta Code | `null` (the source is Unicode) |
| `gloss` | up to 4 distinct `<tr>` texts, `"; "`-joined (same rule as production LSJ) | up to 4 distinct `<gloss>` texts (same rule as Autenrieth) |
| `entry_text` / `entry_text_encoding` | full entry text, Beta Code / `"Perseus Beta Code for Greek spans"`. `entry_text_unicode` has lang="greek" spans rendered | full entry text / `"Unicode (source)"` |
| `source` | `Perseus Middle Liddell TEI (Hopper open-source texts)` | `Perseus Cunliffe TEI via Homerica` |
| `source_url`, `raw_path`, `raw_sha256`, `license`, `entry_id`, `entry_url` | tarball URL + `#member`; Perseus hopper `1999.04.0058:entry=<key>` | raw.githubusercontent URL at the commit; `entry_url: null` |
| `senses[]` | each `<sense>`: `sense_id`, `n`, `level`, `text` (verbatim), `text_unicode`, `locator{xpath //entry[@id=…]/sense[k], byte_start, byte_end}` | each nested `<div>`: `sense_id`, `n`, `depth`, `text` (its own text without nested divs), `locator{xpath}` |
| extras | `key`, `entry_type` (main/cv), `unresolved_entities` (none occurred) | `headword_printed` (e.g. νηῦς, †*ἀάζω), `paragraphs[]` (entry-level `<p>` with locators) |

"Verbatim" means the text content of the TEI node, with comments dropped and
whitespace runs collapsed to one space. Named entities such as `&mdash;` are
resolved only through the WHATWG HTML5 table (`html.entities.html5`); unknown
names would stay literal and be listed, but none occurred. Beta Code is
rendered only inside `lang="greek"` elements, with the `betacode` package that
production already uses.

Cunliffe form rows use the production `forms.jsonl` schema: `form`, `lemma`,
`lemma_raw`, `analysis`, `analysis_format`, `source`, `source_url`,
`raw_path`, `raw_sha256`, `license`, `citation`, `document_id`, `sentence_id`,
`token_id`, `quality` and `locator`. `analysis` is the nearest preceding
untyped `<term>` in the same `<p>`, copied verbatim (e.g. "Acc.", "3 sing.").
The label is often elliptical relative to the previous paragraph ("2 sing.
aor." then "3 sing."), and nothing is inferred to fill it out. `citation` is the
`bibl/@n` values (e.g. `Perseus:abo:tlg,0012,001:1:141`) up to the next orth
term. `quality = printed_lexicon_form`.

## What is not ingested

- Slater's *Lexicon to Pindar*. There is no open source for it (see above).
- Middle Liddell inflected forms. The TEI has no form tagging. Its 1,012
  `<gramGrp><note>` items are Perseus parser hints (e.g. `diakwlu_s is_ews
  fem`), not printed text, and they were skipped. Middle Liddell has no
  `forms.jsonl`.
- Cross-references were **not** written as form rows. Rows such as ἀαγής →
  ἄγνυμι are etymological or "see" relations, not inflections, so they go to
  `*.xrefs.jsonl` with the relation stated.
- Citations as structured data: Cunliffe `<bibl>`/`<cit>` and ML `<usg>` author
  abbreviations stay inside the sense text and are not split out. The
  exception is Cunliffe form rows, which keep `bibl/@n`.
- Sense headings and labels are not parsed out. Cunliffe sense text starts
  with its `<head>` label ("1 …"), as printed.
- The 3 mis-nested κάρη divs and their 8 forms.

## Merging into production (not done)

1. `backend/morphology.Morphology(entries_path, forms_path)` loads one entries
   file and one forms file. Each file can mix sources, because every row
   carries its `source`. A smoke test loaded a scratch concatenation of the two
   staged entry files plus `cunliffe.forms.jsonl` (46,314 entries, 6,022 forms).
   `analyze("νῆα")` returned ναῦς / "Acc." from Cunliffe with candidate entries
   `middle-liddell:n21910` and `cunliffe:neus-cunliffe-lex`, and `analyze("μῆνις")`
   returned one candidate per source. Merging means appending the staged rows to
   the outputs written by `scripts/ingest_lexica.py`. Either extend its `main()`
   to call this module, or add a concatenation step. Keep sources separate and
   do not dedupe.
2. For a form row, `gloss_row` is the *first* possible entry when no source has
   duplicates (`morphology.py` ~l.566). With three or four lexica per lemma,
   file order decides which gloss is the default. Choose that order on purpose,
   e.g. Middle Liddell before LSJ for short glosses.
3. `backend/lexicon_render._source_path` accepts only XML under
   `data/raw/lexica/`, and `read_entry` looks only for `<entryFree>`. Before
   these records can render, the raw files must move or be copied under
   `data/raw/lexica/` (and `raw_path` updated), or `RAW_ROOT` must be widened.
   The reader must also handle ML `<entry>` and Cunliffe TEI-namespaced `<div>`.
   `lexicon_senses.SOURCES` must gain the new labels, or the staged `senses`
   can be used directly.
4. `backend/publication.PUBLIC_SOURCE_LICENSES` has no keys for the new
   `source` labels. Under a restricted public deployment the rows would be
   filtered out until the owner adds `CC-BY-SA-3.0-US` for Middle Liddell.
   Cunliffe stays `unknown` until its rights are established.
5. The Cunliffe forms' `analysis` is free text, not a treebank postag.
   `describe_postag` correctly ignores it, because it is gated on
   `analysis_format`. UI code that assumes 9-character postags must handle this.
6. Re-run `scripts/audit_lexica.py`, or add a parallel audit, because it
   currently traces only LSJ and Autenrieth.

## Open question: short glosses from Middle Liddell

Production LSJ rows often show no short gloss. `lexicon_senses` uses
fail-closed "definition spans" (`tei-definition-spans-v4`): an LSJ `<tr>` is
accepted only when the context proves it is an English definition, not a
cognate, antonym or example translation. Middle Liddell's `<sense>` texts are
already short. Its `<tr>`s are usually the definition itself ("wrath, anger",
"to come or go"), and its first-sense text is often a usable gloss as printed.
Decisions for the owner:

- Should the short-gloss display prefer the Middle Liddell `gloss` (first `<tr>`s)
  over LSJ when both exist, and if so, by source order or by explicit rule?
- Can ML `<tr>` be trusted without running the span extractor? The same tag
  can still mark example translations ("at the ships" in ναῦς), so the
  extractor would need ML-specific validation rather than reuse of the LSJ
  rules (`DEFINITION_BOUNDARY` etc. depend on LSJ typography).
- Should a first-sense `text_unicode` (truncated at the first `;`/`,` + author
  abbreviation) count as a gloss? That would be a new extraction rule and
  would need its own audit.
