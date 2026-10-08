# Open lexica supplement: LSJ (Logeion), Middle Liddell, Cunliffe, Dodson

Status (2026-10-08, branch `worktree-agent-afbdaf082f25b911d`): built, audited
and wired into lookup locally. **Not deployed.** Production `entries.jsonl` /
`forms.jsonl` are untouched; everything new is one extra audited file plus the
raw XML it points into. Without that file the backend behaves as before apart
from the code-level changes listed under "Behaviour changes".

Nothing was taken from logeion.uchicago.edu or its API (no licence; private key;
see `docs/plans/logeion-and-form-tables.md`). Every gloss is a literal span of a
pinned, hash-verified source entry; no definition is written by a model.

## Sources

| Dictionary | Source (pinned) | Licence | Attribution recorded on each row | Rows | With an extracted English definition |
|---|---|---|---|---|---|
| LSJ, Logeion edition (H. Dik) | `github.com/helmadik/LSJLogeion` @ `6aa48692192db739fc7377e8783249b044624ac5` (2026-10-04), 86 files `greatscottNN.xml`, 115,663,515 B; each file checked against its git blob SHA-1 | **CC BY-SA 4.0** (LICENSE.md) | Perseus Tufts *and* Helma Dik/Logeion, as the README asks | 117,130 | 85,233 |
| Middle Liddell (Liddell & Scott, *Intermediate*, 1889) | Perseus Hopper open-source tarball, `ml.xml` (see `docs/lexica-perseus-ingestion.md`) | **CC BY-SA 3.0 US** | Perseus Digital Library | 36,493 | 33,820 |
| Cunliffe, *Lexicon of the Homeric Dialect* (1924) | `gregorycrane/Homerica` @ `d71ed43c` (same as Autenrieth) | `unknown` (no licence file; same status as Autenrieth) | Crane / Dik TEI | 9,821 | 6,948 |
| Dodson, *Greek Lexicon* (NT) | `github.com/biblicalhumanities/Dodson-Greek-Lexicon` @ `74f70358d4acfaf2f980bf2feb58ab7115cbbcbc`, `dodson.xml` 1,315,372 B | **CC0 1.0** (LICENSE; README: public domain) | Dodson; Sandborg-Petersen; biblicalhumanities.org | 5,410 | 5,410 |

Not ingested: Slater (copyright, no open edition), Abbott-Smith
(`translatable-exegetical-tools/Abbott-Smith` has no licence file), Logeion's
`shortdefs` and `MiddleLiddell` repositories (no licence), DGE/LMPG (NC), Brill,
Cambridge, GrNe (copyright). Cunliffe printed forms (`cunliffe.forms.jsonl`)
stay staged: their labels are free text, not parses, and must not compete with
the morphology ranking.

Licences are registered in `backend/publication.py` (`PUBLIC_SOURCE_LICENSES`,
`PUBLIC_LICENSES` gains `CC0-1.0`). Cunliffe is `unknown` and is therefore
filtered out under a restricted public deployment (`MELOS_PUBLIC_DEPLOYMENT=1`
without `MELOS_PUBLICATION_POLICY=source-labels`), exactly like Autenrieth.

### LSJ: Logeion edition supplements, and supersedes for display, the Perseus LSJ

The Logeion files are Perseus LSJ re-edited by Dik: Unicode Greek, corrected
text, entries split/merged, English definitions marked `<i>` instead of
`<tr>`. Each Logeion entry keeps its Perseus id as `orig_id`. When that id and
the NFC headword both match a production Perseus LSJ row (113,953 of 117,130),
the supplement row records `perseus_lsj_id` and `Morphology` **hides the
Perseus row from display** whenever its Logeion re-edition is in the same
headword bucket. The Perseus row keeps its id, stays on disk, stays in the
lexical-quotation search (`backend/lexical_quotes.py` reads only Perseus LSJ)
and in the machine-subentry index. 2,164 Logeion entries share an `orig_id` but
print a different headword (split/merged entries) and 1,013 have no Perseus
counterpart; both are shown alongside the Perseus rows, not instead of them.

## Dictionary order and the short gloss

`backend/short_gloss.py: DICTIONARY_ORDER` fixes the order in which entries are
listed (`lexicon_entries`) and tried for the gloss:

1. Middle Liddell, 2. Autenrieth, 3. LSJ (Logeion), 4. LSJ (Perseus),
5. Cunliffe, 6. Dodson (New Testament usage; last resort).

The first sense comes from the first dictionary in that order that has exactly
one entry for the headword and an extracted English definition. A dictionary
that prints several homograph entries for the headword is skipped, never
guessed. When the parse is not a numeral (`POS` particle, conjunction, noun,
verb …), an entry whose own opening words define a letter or numeral
("letter of the Gr. alphabet", "as numeral") is not used.

Each gloss now carries `short_text` (and `short_text_method`), the head phrase
of the chosen definition **in the dictionary's own words**
(`short_head`): cut at the first printed delimiter (`; : , ( —`); if that is
still longer than four words, cut before the first modifier word (relative,
preposition other than *of*, participle); otherwise the first four words with
an ellipsis. `text`/`full_text` keep the complete source definition. The
reader's short-gloss slot should show `gloss.short_text`.

Alcaeus 129 regressions (UI report, `tests/test_open_lexica.py`): τε now
"and" (Middle Liddell; previously the LSJ example translation "the eleventh or
twelfth"), Διόνυσος "Dionysus" (previously LSJ `<tr>a</tr>`, now rejected as a
bare article), τέμενος short "a piece of land" (full ML definition kept).

## Lemma -> headword meaning when nothing was joined

`backend/lemma_glosses.py` runs after the interlinear projection, only for word
rows that have a parse lemma (or one lemma shared by the top-ranked tied parses)
and no gloss. It looks the lemma up as a printed headword
(`Morphology.headword_entries`: exact NFC, else accent-folded, labelled) and
applies the order above. Additional, labelled rules:

- grave accent written as the dictionary acute (καὶ -> καί);
- a Morpheus homograph number (ἐρύω2) is matched only to the Logeion LSJ entry
  whose key carries the same number (`e)ru/w2`; Morpheus numbers homographs with
  the Perseus LSJ keys); otherwise a numbered lemma with split dictionary
  entries stays unresolved;
- one explicit source cross-reference is followed when the lemma's own entries
  have no English definition ("γᾶ, Dor. for γῆ", "= X", "v. X", "see X"); the
  printed relation is returned in `lemma_dictionary.cross_reference`.

The gloss is labelled `parser_lemma_dictionary_headword_first_sense_not_contextual`
(or `…cross_referenced…`). It is a dictionary first sense, not a contextual
meaning. `limits.lemma_dictionary` reports lookups/filled/unresolved per request
(at most 80 headword lookups).

## Extraction details per source (`backend/lexicon_render.SOURCE_FORMATS`)

| Source | Entry element / locate | Greek | Definition markup | Example rule |
|---|---|---|---|---|
| Perseus LSJ, Autenrieth | `entryFree`, id scan (unchanged) | Beta Code | `tr gloss def title` | LSJ rules (unchanged) |
| Middle Liddell | `entry`, byte range from the row + id check | Beta Code | `tr` (inside `trans`) | a Greek example must be in the same `<sense>`; Latin cognates and etymology/form preambles never own a translation; "poet. for X, wild" is a reference, not an example |
| LSJ (Logeion) | `div2`, byte range + id check | Unicode (no conversion) | `<i>` without a non-English `lang` | LSJ rules + the same reference-lead exemption |
| Cunliffe | top-level TEI `div`, byte range (nesting-aware, computed at build) + `xml:id` check | Unicode | `gloss` (sense heads only) | none (Cunliffe never translates its quotations); senses scoped to their own `div` |
| Dodson | `entry`, byte range + `n="… | number"` check | Unicode | `def role=brief/full` | none; adjacent definitions not merged |

All sources: a definition must contain a word other than an article ("a,"
alone is rejected — LSJ Διόνυσος). Comments are not rendered.

## Coverage: before vs after

### Five Alcaeus poems (34a, 129, 130b, 326, 350), word by word

`scripts/audit_alcaeus_occurrences.py` over `/api/analyze-passage`, counting
the display row of every intact word segment.

| Run | Intact words | Rows with a parse lemma | …of which with a dictionary meaning | All intact words with a meaning |
|---|---|---|---|---|
| Production K3 (greeklyric.com, `runtime/dev/audit-13-production`, 2026-10-07) | 305 (+16 damaged pieces) | 288 | 201 | 201 |
| Local, branch base `b0934b4` (same data, no supplement), `runtime/dev/audit-lexica-before-local` | 321 | 292 | 203 | 203 |
| Local, this branch + supplement, `runtime/dev/audit-lexica-after` | 321 | 293 | **283** | **288** |

(The local dev corpus does not carry the approved commentary bundle, so the 16
letter-runs that production labels "damaged piece" count as intact words
locally; compare the two local rows with each other.) Gloss sources after:
Middle Liddell 266, LSJ Logeion 12, Autenrieth 9, LSJ Perseus 1. Parse fields
are unchanged (317/321 complete in both local runs).

Remaining 10 rows that have a parse lemma but no meaning, with the reason:

| Word | Lemma | Reason |
|---|---|---|
| Αἰολήαν | Αἰόλειος | proper adjective; its LSJ entry has no English definition |
| Λ[εσβί]αδες | Λεσβιάς | proper name; entries print no English definition |
| Ὀνυμακλέης | Ὀνομακλῆς | proper name; in no dictionary |
| ἀ]λλαλοκάκων | ἀλλαλόκακοι | hapax (Alcaeus); in no dictionary |
| καγγ[ε]γήρασ’ | κατά-γηράω | Morpheus prints the compound with a hyphen; no headword is spelled so (not joined by guesswork) |
| ἀντίαον | ἀντίαος | Aeolic lemma from the parser; in no dictionary |
| κεμήλιον | κεμήλιος | parser lemma; in no dictionary under that spelling |
| συνόδοισί | σύνοδος | homographs (ML and LSJ each print two entries); not resolved |
| α | εἶμαι | a letter-run beside a lacuna (damaged piece in production) |
| δ᾽ | δ᾽ | the source lemma is itself elided (δέ or δή); not resolved |

The other 23 rows without a meaning have no single parse lemma: 7 letter-runs
beside lacunae that production labels damaged pieces (ρά, ἔπικ, ην, δέ̣δ̣, γεγρᾶ,
κρ, χλι), αις, ς̣βιότοις̣, Μύρσιλ̣[ο (conditional boundary), names/hapax with
ending-only parses (Ὕρραον, Ὦγεσιλαΐδα, τυνδέων, λυκαιμίαις, ἀγροϊκωτίκαν,
ἄγκονναι) and tied parses of different lemmas (κά[τε]σσαν, δᾶμον, ἀλλὰ, ἀ, ζώω,
ἔχει, ἤδη) where choosing a lemma would be choosing the reading.

### Every lemma the parser has proposed (wider than the five poems)

`scripts/report_lemma_gloss_coverage.py`: all 860 distinct Greek lemmas in the
two local Morpheus receipt caches plus every display/candidate lemma of the
production audit, each looked up with the same headword rules, with the core
dictionaries only vs with the supplement (`runtime/dev/lemma-gloss-coverage.json`).

| | Lemmas | With any entry | With a short English gloss |
|---|---|---|---|
| Core (Perseus LSJ + Autenrieth) | 860 | 804 | 662 (77 %) |
| + supplement | 860 | 817 | **743 (86 %)** |

After: Middle Liddell supplies 631 of the 743 glosses. Remaining 117 misses:
41 proper names (19 in no dictionary, 22 whose entries define no English word),
24 not a headword anywhere (mostly Aeolic/Morpheus-normalised spellings and
hapax), 17 unresolved homographs, 35 whose entries contain no English
definition the extractor accepts (per-lemma reasons in the JSON report).

The whole Campbell corpus was not run: the laptop corpus does not hold it
(`scripts/dev_corpus_campbell.py` builds only the five poems) and its parses
need the hosted Morpheus service. On the box, the same script can be pointed at
the production receipt cache (`--machine-cache`) to measure every lemma parsed so far.

## Rebuild

```
python -I scripts/ingest_perseus_lexica.py --download     # Middle Liddell + Cunliffe -> data/staging/lexica
python -I scripts/ingest_logeion_lsj.py --download        # -> data/raw/lexica/lsj-logeion-6aa48692192d/, staging
python -I scripts/ingest_dodson_lexicon.py --download     # -> data/raw/lexica/dodson-74f70358d4ac/, staging
python -I scripts/build_lexica_supplement.py              # -> data/lexica/supplement-entries.jsonl (+ .manifest.json), ~5 min
python -I scripts/audit_lexica_supplement.py              # -> data/reports/audit-lexica-supplement.json (PASS required), ~1.5 min
python scripts/report_lemma_gloss_coverage.py --machine-cache runtime/dev/machine_morphology.sqlite --output runtime/dev/lemma-gloss-coverage.json
```

`backend/server.py` loads the supplement only when
`data/reports/audit-lexica-supplement.json` says `PASS` for the file's current
SHA-256; otherwise it silently runs on the core files (unlike the core files,
a bad supplement never takes lookups down).

## Deploy (for the owner; nothing was deployed)

Files to put on the box, relative to the backend `ROOT` (the data mount):

| Path | Size | SHA-256 |
|---|---|---|
| `data/lexica/supplement-entries.jsonl` | 225,947,691 B | `aacdddbec624daae4acce18ca1f16c9c323fee89ff49be8aea5631f7f60db511` |
| `data/lexica/supplement.manifest.json` | 16,912 B | (build record) |
| `data/reports/audit-lexica-supplement.json` | 12,346 B | PASS: 168,854 rows, 0 failures, 131,411 glosses found verbatim in their entry |
| `data/raw/lexica/lsj-logeion-6aa48692192d/` (86 XML + LICENSE.md, README.md, download-manifest.json) | 111 MB | per-file in `download-manifest.json` |
| `data/raw/lexica/dodson-74f70358d4ac/` (`dodson.xml`, LICENSE, README.md, manifest) | 1.3 MB | `dodson.xml` `39c6cb80…4639` |
| `data/raw/perseus-lexica/hopper-2011-05-27/Classics/LSJ/opensource/ml.xml` | 19,138,674 B | `cff0a7e5…1d7c` |
| `data/raw/perseus-lexica/homerica-d71ed43cc912d3e053cbb0dd6341f798ea058378/cunliffe.lexentries.unicode.xml` | 14,898,460 B | `4c4dd040…7a7d` |

Total ≈ 370 MB (Basecamp disk was at 98 %: free space first, or put the raw
XML on the planned Storage Box and mount it at the same relative paths). The
staging JSONL (`data/staging/lexica/`, 330 MB) and the Hopper tarball (125 MB)
are **not** needed at runtime. Memory: the backend holds the supplement rows in
the `Morphology` index, roughly +0.6–0.8 GB resident.

Code to ship: `backend/{lexicon_render,lexicon_senses,morphology,interlinear,
passage_analysis,passage_routes,server,publication,short_gloss,lemma_glosses}.py`,
`js/dictionary-preview.js` (source labels). The handoff note about re-adding the
gzip middleware to `backend/server.py` still applies (this branch does not touch it).
Smoke after promotion: `/api/word?form=μῆνις` lists Middle Liddell first with
"wrath, anger"; Alcaeus 129 shows τε "and", Ζόννυσσον "Dionysus".

## Behaviour changes even without the supplement file

- `lexicon_entries` are listed in `DICTIONARY_ORDER` (Autenrieth before LSJ);
  `_gloss` takes the first sense from the earliest dictionary in that order.
- LSJ definitions that are only an article ("a,") are rejected.
- Letter/numeral entries are skipped for non-numeral parses.
- Glosses carry `short_text`.
- The lemma -> headword fallback fills glosses from the core LSJ/Autenrieth.
