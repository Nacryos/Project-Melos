# Deployment handoff

## Current: release P — citations, sourced dates and genres, n-grams, calibrated confidence, lemma UI gaps (2026-10-09)

Public backend: image `melos-api:20261009p`
(`sha256:cdd0a3dce06c6c39d1be386a776308e8fe4f998237985af5f304253377932f9d`), built on Basecamp with
`deploy/Dockerfile.patch` atop the O image from the P source tarball (`git archive` of `bbbe6a7`, sha256
`0fa8d8ebcb83e11b21275118b74dd7724103e61f5d65bdbe21fe6818ec8cd190`, unpacked in `/home/alvin/melos-p/src`).
Recipe: `deploy/release_p.sh build|dev|canary|stop-canary|promote|rollback`; checks `deploy/canary_checks_p.sh`.
O is kept stopped as `melos-api-before-p`, the P canary as `melos-api-canary-p` (stopped). **Rollback:**
`sh /home/alvin/melos-p/src/deploy/release_p.sh rollback` (stops P, renames it `melos-api-failed-p`, restarts O
with its own mounts; the Morpheus sidecar is untouched). No frontend change in this release.

Data (read-only mounts): O's `corpus.sqlite` and `embeddings/` (unchanged, from `/home/alvin/melos-o/data`), and
under `/home/alvin/melos-p/data`: `lemma_index.sqlite` (280 MB, rebuilt), `citation_index.sqlite` (46 MB),
`ngrams.sqlite` (4.8 MB), `lemma_calibration.json`, `tlg_catalogue.json` (summary), and `metadata/`
(`chronology.json`, `attributions.json`, `genre_sources.json`, mounted at `/p-metadata`; `chronology.json` also
over `/app/data/metadata/chronology.json`).

**What P adds** (details: `docs/api-contract.md` "Citations (release P)" and "Headword index additions
(release P)", `docs/lemma-index.md` "Release P additions"):

- **Citations.** `scripts/build_citation_index.py`: 158,163 stored passages with a printed locus in 394 work groups.
  TLG author/work numbers for 180 work groups (35 authors), each with its source: the record's own CTS URN 111,
  the PerseusDL / First1KGreek CTS catalogue (`__cts__.xml`, tree shas in the index manifest) 45, the same verse
  lines as URN-carrying records 23, the OGC README 1; 94.3 % of edited tokens lie in a mapped work. Nothing from
  the TLG website. `/api/cite` resolves line/book citations (LSJ/OCD abbreviations, `Eur. Med. 1`-style title
  prefixes), CTS URNs and fragments; the home search box answers a citation with the cited passages
  (`mode: citation`). Fragment-number equivalences only where one record prints both numbers: 70 rows (Archilochus
  Diehl↔West 38, Stesichorus Finglass↔SLG/PMGF, SLG↔Page, Ibycus Page↔SLG and Campbell↔Page). Voigt / Lobel-Page →
  Campbell: one record carries it (Digital Sappho "178 Campbell (= Voigt, and Lobel & Page 168A)"); the Campbell GLP
  (1967) records carry only their own numbers, so no GLP↔Voigt/L-P concordance is given.
  **Citation test (30 citations, `scripts/eval_citations.py`): 30/30** resolve to a passage containing the
  expected words (Iliad, Odyssey, Theogony, Works and Days, Pindar O./P./N., Argonautica, Idylls, Dionysiaca,
  Posthomerica, Phaenomena, Musaeus, Alexandra, Halieutica, Bacchylides, AP 7.1, Medea, Antigone, four CTS URNs,
  Sappho 1/16/31, Alcaeus 346, Anacreon 348, Sappho 168A L-P via the equivalence).
- **Dates.** `scripts/collect_chronology.py`: Wikidata CE century and decade precision now read (release O read
  only BCE ones: Nonnus "5th century", Quintus, Musaeus were undated); claim order birth → floruit → work period →
  death → inception; 36 Greek Anthology poets named by the epigram records (`metadata.attributed_author`) mapped
  to Wikidata items where the label is unambiguous; anonymous collections (Homeric Hymns, Orphica, Anacreontea)
  looked up on their own items (no referenced date claim: still undated). A passage takes its author's date, else
  its attributed poet's. **Dated share of searchable edited Greek tokens: 74.0 % (O) → 90.9 % (P)** (1,259,366 of
  1,386,111; 43,234 tokens through attributed Anthology poets). All Greek records: 36.4 % (scholia and anonymous
  OCR are undated). Still undated: Greek Anthology epigrams by anonymous or ambiguous poets (87k tokens), the
  Homeric Hymns (28k), Orphica, Anacreontea, Semonides, Diodorus Periegetes.
- **Genres.** A source edition's own label first (CGL anthology sections ΜΕΛΙΚΟΙ ΠΟΙΗΤΕΣ / ΕΛΕΓΕΙΟΓΡΑΦΟΙ ΚΑΙ
  ΙΑΜΒΟΓΡΑΦΟΙ and subsections, Greek Wikisource titles: 17 authors), then Wikidata P136, else the editorial table
  (`genre_source`). Alcman, Stesichorus, Ibycus and Simonides move from the editorial "choral lyric" to the source's
  "melic lyric"; Solon is "elegy and iambus"; Pindar and Bacchylides stay editorial "choral lyric".
- **N-grams** (`/api/lemma/ngrams`): 2–4 headwords, 73 groups (authors, genres, periods, corpus), one collection per
  TLG work, refrains once, Dunning G². Examples: Homer ἀλλά ὅτε δή (77), ὡς ἄρα φωνέω (58), θυμός ἐν στῆθος (47);
  Sappho γῆ μέλας (10), πρόσθεν ἄμβροτος (6); Pindar Ζεύς πατήρ (10), ἑπτάπυλος Θῆβαι (4); Nonnus ἔνθα καί ἔνθα (56);
  melic lyric ἠχώ θεσπέσιος, δινήεις Ἀχέρων; tragedy φεῦ φεῦ (50).
- **Proximity across passages** (`cross_passages=true`): continues into the next stored passages of the same
  collection when the line numbers continue (σελήνη + ἀστήρ within 8 words: 2 extra matches across line records in
  Nonnus and Theocritus).
- **Contextual model on every Greek record**: OdyCy on the 176,037 records release O skipped (scholia, commentary,
  OCR pages): 5 shards × 3 CPUs, 60 min, texts in length order. Context agreements 1.02 M → 2.84 M tokens,
  changes 57,881 → 159,784 (all in non-edited records; edited text unchanged). English search readings keep
  release O's frequency prior (`lemma_prior`), so search ranks exactly as in O.
- **Calibrated confidence** (`scripts/calibrate_lemma_confidence.py`, report `/home/alvin/melos-p/eval/calibration-report.json`):
  gold = PerseusDL treebank tokens of Homer, Hesiod, Sophocles, Aeschylus aligned to the Perseus passages (251,966
  aligned); evaluation index assembled with those works' treebank tokens removed from the form lists; isotonic
  fit per evidence class on half the 25-line blocks, reported on the other half (131,011 tokens). Held-out
  agreement with the gold lemma 95.7 %. Expected calibration error 0.021 (raw score) → 0.001 (calibrated).

  | Calibrated probability | Tokens | Mean predicted | Observed |
  |---|---|---|---|
  | < 0.50 | 2,823 | 0.27 | 0.28 |
  | 0.50–0.60 | 1,468 | 0.60 | 0.62 |
  | 0.60–0.70 | 1,646 | 0.64 | 0.65 |
  | 0.70–0.80 | 365 | 0.73 | 0.72 |
  | 0.80–0.90 | 1,444 | 0.88 | 0.85 |
  | 0.90–0.95 | 21,563 | 0.94 | 0.94 |
  | 0.95–0.98 | 15,913 | 0.97 | 0.97 |
  | ≥ 0.98 | 85,789 | 0.997 | 0.997 |

  Raw score bins, for comparison: 0.70–0.80 predicted 0.75, observed 0.90; ≥ 0.98 predicted 0.999, observed 0.984.
  By evidence: context agrees 99.1 % (102,289 tokens), context chose 92.3 % (6,745), no context signal 80.9 %
  (21,970). Commonest disagreements: elided particles (τ’ read as σύ for τε, ἀλλ’ as ἄλλος for ἀλλά), εἶδον
  vs ὁράω, ἦ vs εἰμί, and convention differences (ἠέλιος/ἥλιος, μίγνυμι/μείγνυμι). Caveats: OdyCy was trained on
  treebanks of these texts, so the context classes are optimistic; the gold is edited epic and drama, not OCR or
  scholia.
- **Lemma UI gaps** (`docs/audits/lemma-ui-2026-10-09.md`): headline dictionaries in the batch payload
  (`dictionary=true`: Anacreon 348 13.7 → 22.9 KB, 0.06–0.16 s; a cold 90-word poem 0.7 s, then cached);
  `/api/word … &compact=true` (φαίνω 439 KB → 7 KB); excerpts and match offsets in `/api/lemma/search`; edition
  folding in concordance and proximity; `period=` / `undated=true` on the concordance; examples per period and
  undated collocates in diachrony; 95 % intervals and `small_sample` on every rate; head-meaning concept lists
  ("moon" no longer brings Ἰώ or Οὐρανία; "love" is ἔρως, ἀγαπάω, φιλέω before φίλος; "sea" brings θάλασσα, not
  ναύτης) weighted by the meaning index, whole matched words; 3,839 dictionary variant links (ἔρος poet. for ἔρως,
  πότνα shorter form of πότνια) with `combine_variants`; work order in chronological lists; collocations count a
  refrain once and one collection of each text (σελήνη's Hellenistic collocates no longer led by πότνα, ὅθεν);
  main entry before a homograph or cross-reference for short glosses (ὁδός "a way", was "a threshold").

Canary (8792) before promotion: smoke pass; `verify_campbell_glp.py --analyze sample`: 237/237 identical, 214
translations, 50 lines analysed, 0 failures; `check_span_parses.py --random 30`: 227 spans, 816 word rows, **0
failures**. Search evaluation (42 queries): **identical to O on every query** (nDCG@10 development 0.707, held out
0.577, all 0.664). Sampler vs O: seed 101 (421 rows) and held-out seed 20261008 (487 rows) identical on every
metric, no row gains or loses. Citation test 30/30. Memory: canary 4.3 GiB of 8 GiB (O 3.5 GiB at the same time).
Backend tests: 1,985 pass; 5 fail as on O's HEAD (`test_commentary_relevance_packet`, `test_linked_sense_integration` and `test_run_commentary_relevance` snapshots, `test_sense_ranker…keep_other_unambiguous…`,
and `test_release_o_parser_rules::test_printed_headword_is_not_overridden…`, which fails on `54c9580` too).

Verified on https://greeklyric.com after promotion (`deploy/canary_checks_p.sh`, output in
`/home/alvin/melos-p/prod-checks`): smoke pass; 237/237 identical, 0 failures; span check 227 spans, 816 rows,
0 failures; search evaluation 0.707 / 0.577 / 0.664 (as O); citations 30/30; every new endpoint 200 through the
public route (80–160 ms; diachrony 0.9–1.0 s; `/api/cite` for a fragment 0.9 s). Memory: P 3.2 GiB of 8 GiB,
sidecar 28 MiB.

Known gaps: the frontend does not yet read `dictionaries`, `compact`, `probability`, `variant_group`, n-grams or
`/api/cite` (the search box already shows citation results as ordinary results); Greek Anthology epigrams by
ambiguous or anonymous poets and the anonymous collections remain undated; frequency tables still count both
collections of a text (concordance, collocations and n-grams count one); the calibration is fitted on edited
epic and drama and applied unchanged to OCR pages and scholia.

## Historical: release O — corpus headword index, lemma features, search quality, parser fixes (2026-10-09)

Public backend: image `melos-api:20261009o`
(`sha256:77f70495fa90eaa99d5033085e6f3c0474e9850c2f56bf22a3ea2f7c6fc4d127`), built on Basecamp with
`deploy/Dockerfile.patch` atop the N image from the O source tarball (`git archive` of `54c9580`, sha256
`3475f711d44d291de6f6c8a3dbb37bb99341102ecd7d9023911de61e24c2747a`, unpacked in `/home/alvin/melos-o/src`).
Recipe: `deploy/release_o.sh build|dev|canary|stop-canary|promote|rollback`. N is kept stopped as
`melos-api-before-o`, the O canary as `melos-api-canary-o` (stopped). **Rollback:**
`sh /home/alvin/melos-o/src/deploy/release_o.sh rollback` (stops O, renames it `melos-api-failed-o`, restarts N
with its own mounts: L corpus, L manifest, old chronology; the Morpheus sidecar is untouched).

New read-only data, all under `/home/alvin/melos-o/data` (the live data mount is unchanged):
- `corpus.sqlite` (1.71 GB): the L corpus (288,821 passages) with two repairs by `scripts/stage_corpus_o.py`: the
  edition sign "⊗" printed before a poem's first line removed from the start of 77 stored texts (Digital Sappho,
  DCC Sappho via OGC, CGL anthology; recorded in each record's metadata; signs inside a text kept), and author
  columns recomputed with the extended alias table (108 merged authors; `apollonius-rhodius-epic` = Apollonius
  Rhodius, OGC slugs, scholia collections).
- `embeddings/`: the L vectors plus the 237 Campbell GLP poems that were pending and the 77 re-encoded texts
  (`scripts/embed_release_o.py`, encoded on the laptop's CUDA in float16 with the pinned BGE-M3 contract): 116,428
  rows = every eligible record.
- `lemma_index.sqlite` (273 MB): the corpus headword index (`docs/lemma-index.md`), mounted at `/lemma`.
- `chronology.json`: Wikidata author date claims for 55 authors (was 10; `scripts/collect_chronology.py`).

**Headword index build** (`deploy/lemma_index_build.sh`, batch containers on the N image, own Morpheus container
with 10 CPUs, removed afterwards): 277,602 Greek passages, 3,899,386 word tokens, 395,102 distinct spellings.
Forms 9 s; Morpheus 32 min (257,301 spellings analysed, 137,608 not, 193 invalid); generate-and-test 11 min
(12,542 unknown spellings of edited text, 2,277 resolved); contextual model (OdyCy) 45 min on 102,206 edited Greek
passages in three 3-CPU shards; assembly 74 s. 53,797 headwords. Coverage, searchable edited Greek text
(1,386,111 tokens): **98.9 % of tokens have a headword**, 98.4 % from an exact parse, 91.1 % with confidence ≥ 0.8.
By genre: epic 99.6 %, tragedy 99.6 %, epigram 98.9 %, melic lyric (Sappho 84.3 %, Alcaeus 92.8 %, Corinna
81.7 %: fragments and Aeolic/Boeotian spellings), choral lyric (Pindar 99.4 %, Bacchylides 93.4 %). All Greek
records, including OCR pages and scholia: 93.6 %. Per-author table: `/home/alvin/melos-o/eval/coverage.json`.

**What O adds** (details: `docs/lemma-index.md`, `docs/api-contract.md`, `docs/morphology.md` "Release O parser fixes"):
- Lemma API: `/api/lemma/{resolve,search,frequency,distribution,concordance,collocations,proximity,status}`,
  `/api/concept/diachrony`, `POST|GET /api/words/headlines` (headline headword, gloss, parses and alternatives for
  every word of a passage; 2–3 ms warm).
- Search: a headword signal in hybrid fusion (Greek words read as headwords; English through dictionary glosses,
  e.g. moon → σελήνη, μήνη; weight 3 English / 2 Greek, chosen on the development queries); word and form lists
  ranked by query-word frequency with length normalisation (they were in catalogue order, which put Aeschylus and
  Aristophanes first); an English word matching only English translations is treated as English; editions of one
  passage folded under the first-ranked copy (`editions`, `edition_count`); hub correction of dense scores
  (weight 0.5); `display_author`, `display_work`, `author_genre`, `author_period` on results and passages.
- Parser: the printed-headword reading (ἴψοι → ὑψοῦ "aloft") is kept over a model POS guess when a parse of it
  exists; capitalised names take the sense naming the being (Νύμφαις "a Nymph"); every row and `/api/word` carry
  a headline headword with ranked alternatives and restored readings (σ’ → σύ, alternative σός); `/api/word`
  `lemma=` dictionary fast path (~10 ms).

**Search evaluation** (`scripts/search_eval.py`, 42 queries in `data/evaluation/search-eval-o.json`: English concepts,
Greek headwords, epithets and phrases; every third held out; relevance = the concept's Greek vocabulary is in the
passage, other editions of a counted passage gain nothing), hybrid search, nDCG@10:

| Split | N (production) | O (canary) |
|---|---|---|
| Development (28) | 0.365 | **0.707** |
| Held out (14) | 0.401 | **0.577** |
| All (42) | 0.377 | **0.664** |
| English concepts / epithets / Greek headwords / Greek phrases | 0.197 / 0.297 / 0.990 / 0.519 | 0.557 / 0.769 / 1.000 / 0.530 |

Sappho fr. 34 is now 2nd for "moon" (was 11th); "rose-fingered" returns only passages with ῥοδοδάκτυλος. Sappho
fr. 96 still ranks high for moon, rose-fingered, sun and sea, because it contains βροδοδάκτυλος σελάννα, ἀελίω and
θάλασσαν; it no longer appears for eros or night. The hub correction barely moved it (development nDCG 0.688 at
weight 0, 0.679 at 0.5); it is kept for the meaning-only mode. One held-out query (bittersweet) exposed a compound
spelling gap ("bitter-sweet"); the general fix (hyphenated and joined English compounds are one term) went in after
the held-out run, so the held-out figure above is the clean one.

Canary (8792) before promotion: smoke pass (the edition notice added to the smoke's expected warnings);
`verify_campbell_glp.py --analyze sample`: 237/237 identical, 214 translations, 50 lines analysed, 0 failures;
`check_span_parses.py --random 30`: 227 spans, 816 word rows, **0 failures** (the first build had 5, all ἄχω in
Alcaeus 130b left without a parse by the new printed-headword rule; fixed generally in `54c9580`: the rule applies
only when a parse of the headword's reading exists). Sampler vs N: seed 101 (421 rows) parse 96.9 → 96.9 %, lemma
96.4 → 96.4 %, plausible lemma 94.3 → 94.5 %, all checks 89.1 → 89.3 % (1 row gains: ἴψοι; none loses);
held-out seed 20261008 (487 rows) identical on every metric, no gains or losses. Endpoint timings on the canary:
frequency 5 ms, concordance 9 ms, collocations 29 ms, proximity 10 ms, diachrony 0.7 s, headlines 2 ms. Memory:
canary 3.3 GiB of 8 GiB (N 3.8 GiB at the same time).

Frontend deploy `d089138` (other agent, same day): https://project-melos-is0wyjwyz-nacryos-projects.vercel.app;
rollback `vercel rollback project-melos-fiu97xnc9-nacryos-projects.vercel.app --yes`.

Verified on https://greeklyric.com after promotion (run from Basecamp, `deploy/canary_checks_o.sh`, output in
`/home/alvin/melos-o/prod-checks`): smoke (288,821) pass; `verify_campbell_glp.py`: 237/237 identical, 0 failures;
`check_span_parses.py --random 30`: 227 spans, 816 word rows, 0 failures; search evaluation live: nDCG@10 0.664
all, 0.577 held out (same as the canary); every lemma endpoint 200 (60–100 ms through the public route, diachrony
0.8 s); "moon": Sappho 154, fr. 34, fr. 96 in the first three. Memory: O 3.1 GiB of 8 GiB, sidecar 26 MiB.

Known gaps: dates exist for 45 of 55 catalogued authors (Nonnus, Quintus, Musaeus, Callinus, Semonides and others
have no Wikidata birth/floruit claim and are reported as undated: 26 % of edited tokens); genres are an editorial
table; the contextual model ran on edited text only (not scholia or OCR pages); headword confidence is a normalised
score, not a calibrated probability; proximity search stays inside one stored passage.

## Historical: release N — local Morpheus, generate-and-test normalisation, word-panel fixes (2026-10-08)

Public backend: image `melos-api:20261008n`
(`sha256:a0ecd6baf572ee96974445ebd40bd2329d703970877da3261f8deedec519dbf4`), built on Basecamp with
`deploy/Dockerfile.patch` atop the M image from the N source tarball (`git archive` of `0d29a21`, sha256
`751f9c08750dec3a890264b8bea5d81be9efb361b93fafd53b10b3a191c10e72`, unpacked in `/home/alvin/melos-n/src`).
Same mounts as M, plus the user-defined Docker network `melos-morpheus` and
`MELOS_MORPHEUS_LOCAL=http://melos-morpheus:8080/api/v1/analysis/word`. Sidecar `melos-morpheus` (image
`melos-morpheus:2f1a30d`, built by `release_n.sh morpheus` from `deploy/morpheus-local`: alpheios-project/morpheus
`2f1a30d65ed7ae9c6120dbf64d730b863be412e4` with its CI build and `dist/stemlib`, morphsvc
`264ad78feae7efcb23255736f7ed624f673db1e4` envelope code; CC BY-SA 3.0 US and GPL-3.0, run as a service;
read-only, 1 GiB, 127.0.0.1:8793). Recipe: `deploy/release_n.sh morpheus|build|warm|canary|canary-nogen|stop-canary|promote|rollback`.
M is kept stopped as `melos-api-before-n`; the N canary as `melos-api-canary-n` (stopped). **Rollback:**
`sh /home/alvin/melos-n/src/deploy/release_n.sh rollback` (stops N, renames it `melos-api-failed-n`, restarts M;
the sidecar keeps running and M ignores it). No frontend change in this release.

What N adds (design in `docs/morphology.md`, "Local Morpheus and generate-and-test normalisation"):
- Local Morpheus transport: every cache miss is parsed locally (no courtesy quota; Alpheios caps kept for the
  remote engine); receipts labelled `morpheus-local-v1` with the build commits; cached Alpheios receipts keep
  precedence. Agreement with all 1,357 cached Alpheios forms: **1,347 identical (99.3 %)**, lemma sets 99.7 %, core
  parses 99.6 %; the ten differences are stem-library data, not encoding.
- Receipts: live cache backed up to `/home/alvin/melos-n/machine_morphology.before-n.sqlite` (1,631 receipts),
  then `release_n.sh warm` added 7,797 local receipts (absent keys only). GLP coverage: 6,885 distinct forms,
  1,357 cached before → **6,477 parsed exactly (94.1 %)**; of the 406 the parser does not know (mostly letters
  beside lacunae and split words) 84 parse through the older Aeolic variants and 39 through generated spellings.
  The rest of the corpus (~406,000 forms) is parsed on demand (~25 ms per word), not pre-warmed.
- Generate-and-test dialect and elision normalisation; `/api/word` strips editorial brackets inside a word, adds
  parser candidates (same path as in-poem analysis), the parsed headwords' dictionary entries, `parse_source`,
  NFC lemmas, optional `lemma=`; word tokens keep an edge bracket they close/open (`[σ]ὸν`); readable
  `source_label`; the occurrence query no longer overflows `/tmp` (HTTP 500 for καὶ, δ’: all 33 errors in M's log).
- General rules from the live audit: participle/imperative endings and iota subscript in the last tier; lemma
  ties settled by attestation (κάτεσσαν → καθίζω); gloss corroboration (ἀλλά "but", θεός "god"), short glosses
  lower-case for common headwords; capitalised words prefer proper-name headwords and never borrow a common
  noun's entry unless it names the being; ranked parses deduplicated by breathing/case; a single recorded
  reading is kept when the contextual prediction contradicts every candidate; Middle Liddell `n="Perseus"`.
- Also ships the committed cross-reference follow-up (αὔως → ἠώς "daybreak").

Canary (8792) before promotion: smoke pass; `verify_campbell_glp.py --analyze sample`: 237/237 identical, 214
translations, 50 lines analysed, 0 failures; `check_span_parses.py --random 30`: 227 spans, 816 word rows, **0
failures**. Memory: canary 2.9 GiB of 8 GiB, sidecar 26 MiB. Backend tests 1,942 pass (the three known snapshot
failures plus `test_sense_ranker::…keep_other_unambiguous…`, which also fails on M's HEAD).

Development seed 101 (120 spans, 421 rows), live M → N canary: complete parse 94.5 → 96.9 %, lemma 84.8 → 96.4 %,
short gloss 83.4 → 93.6 %, plausible gloss 83.4 → 93.6 %, plausible lemma 84.1 → 94.3 %, all checks 77.9 → 89.1 %;
64 rows gain, none loses a lemma or gloss. Four rows lose a metric: three wrong M parses now left open by tied
parses with a better lemma (τρῖς "thrice" → τρεῖς "three", Ὡρᾶν "acc. masc. sg." → Ὥρα, ἔσ beside a gap), and
ἴψοι, where the contextual model's wrong VERB prediction now picks the parser's ἴπτομαι "to press hard" over the
dictionary's ἴψοι "aloft" (not patched). Three rows only change label to the full printed bracket (`[ἀ]θανάτων`).

Held-out sample (seed 20261008, 150 spans, 484 aligned rows), recorded production M → N canary. Note: the held-out
failures were inspected during this release and two general fixes followed (capitalised headwords and lower-case
entries, Νύμφαι read through νύμφαι); the numbers are from the final build.

| Metric | M | N without generation | N |
|---|---|---|---|
| Complete parse fields | 94.4 % | 99.0 % | **99.0 %** |
| Lemma present | 83.9 % | 96.3 % | **96.7 %** |
| Short gloss present | 82.0 % | 93.2 % | **93.4 %** |
| Plausible gloss | 81.8 % | 93.0 % | **93.2 %** |
| Plausible lemma | 80.0 % | 92.2 % | **92.6 %** |
| Rows passing every check | 74.2 % | 87.9 % | **88.1 %** |

(The "without generation" column is live M's code and cache replaced by local Morpheus, measured from today's M,
which had itself gained 2.4 points of lemma from Alpheios receipts fetched since release M.) 86 rows gain; two lose
a metric: θαρσύνῃ (wrong pattern "nom. fem. sg." → θαρσύνω with the parse left at "sg."), Ἁρμόδιε (M's wrong gloss
"fitting together" for the name is no longer shown). Νύμφαις now shows Νύμφαι "bride" (Middle Liddell's first
sense; "nymph" would be better). Remaining failures: words beside lacunae, tied parses of different lemmas, words
with no English definition in any open dictionary.

Verified on https://greeklyric.com after promotion (run from Basecamp, `/home/alvin/melos-n/prod-checks`): smoke
(288,821) pass; `verify_campbell_glp.py`: 237/237 identical, 0 failures; `check_span_parses.py --random 30`: 227
spans, 812 word rows, 1 failure, an HTTP 502 from the public route for 34a [71:104]. The same request retried at
once returned 200 on both greeklyric.com and 127.0.0.1:8791, and the API log has no error, so this was a transient
proxy failure, not a parse failure. `/api/word` for δ’, καὶ, σελάννα and κ[άλ]λιστος returns 200. Memory: N 2.9 GiB
of 8 GiB, sidecar 26 MiB.

Frontend follow-ups (js/, not in this release): the machine-analysis card still says "Morpheus via Alpheios" (read
the receipt's engine instead); pass the headline lemma as `lemma=` to `/api/word` (σ’: σύ vs σός); show
`source_label` and `parse_source`.

## Historical: release M — general lemma/gloss fixes measured by random sampling over all GLP poems (2026-10-08)

Public backend: image `melos-api:20261008m`
(`sha256:fe1b6e8369b8c1d87bd02f19b0d5630552d73992a14d74056bc883dce47383f6`), built on Basecamp with
`deploy/Dockerfile.patch` atop the L image `melos-api:20261008l` from the M source tarball (`git archive` of
`40859d2`, sha256 `716895cd53f63c710ee3e9e9303758d6a59a1f6146ab5c9f9461a880519e7e1f`, unpacked in
`/home/alvin/melos-m/src`). Same mounts as L (L's staged corpus `/home/alvin/melos-l/data`, 288,821 passages;
live data mount with the open-lexica supplement; live runtime). Recipe: `deploy/release_m.sh
receipts|build|canary|stop-canary|promote|rollback`. L is kept stopped as `melos-api-before-m`; the M canary
as `melos-api-canary-m` (stopped). **Rollback:** `sh /home/alvin/melos-m/src/deploy/release_m.sh rollback`
(stops M, renames it `melos-api-failed-m`, restarts L with its own mounts). No frontend change (no Vercel deploy).

What M adds (commits `14e5d4f`, `f782cf6`, `67ec5f5`, `40859d2`; design in `docs/morphology.md`, "Random-sample
fixes"): the sampler `scripts/sample_glp_quality.py`; lemma → headword normalisation (length marks, stray
breathings, elided lemmas, lemma-as-recorded-form, Lesbian psilosis, a dialect correspondence table); the
contextual model's lemma when it is a printed headword sharing the word's letters; recorded-form lookups of
labelled spelling variants (elision restored, crasis second word, Doric/Aeolic ᾱ for η, parser
normalisations) when nothing analyses the printed form; gloss choice that skips grammatical-label senses,
respects prep./adv. sense labels and prefers the head phrase another dictionary confirms; the model's
SCONJ/PROPN/AUX/INTJ classes kept. Morpheus receipts: **870 new** (487 → 1,357) for the most frequent GLP forms
(`scripts/warm_morphology_forms.py --order frequency`, bundle `runtime/dev/glp-receipts-m.json`, sha256
`a8c57b19…d5d4`), imported with `release_m.sh receipts` (absent keys only; L reads the same cache).

Canary (8792) before promotion: `smoke_backend.py --expected-passages 288821` pass; `verify_campbell_glp.py
--analyze sample`: 237/237 identical, 214 translations, 50 lines analysed, 0 failures; `check_span_parses.py
--random 30`: 227 spans, 816 word rows, **0 failures** (as L). Sampler, development seed 101 (120 spans, 421
word rows), L with the new receipts → M canary: complete parse 93.6 → 93.8 %, lemma 72.9 → 83.8 %, short
gloss 70.8 → 82.4 %, plausible gloss 70.3 → 82.4 %, plausible lemma 72.7 → 83.1 %; no word row lost a lemma
or gloss; 3 rows lost a parse that was only the model's (wrong) "adv." guess (ἄμμ’ ×2, ἒν), now shown as a
parser/model conflict. Memory: canary 2.9 GiB of 8 GiB.

Verified on https://greeklyric.com after promotion (run from Basecamp, `/home/alvin/melos-m/prod-checks`):
smoke (288,821) pass; `verify_campbell_glp.py`: 237/237 identical, 0 failures; `check_span_parses.py --random
30`: 227 spans, 816 word rows, **0 failures**.

Held-out sample (seed 20261008, 150 spans, 484 word rows; never inspected before this point), production L
(before receipts) → production M:

| Metric | L | M |
|---|---|---|
| Complete parse fields | 91.9 % | **94.4 %** |
| Lemma present | 71.9 % | **83.9 %** |
| Short gloss present | 69.8 % | **82.0 %** |
| Plausible gloss | 69.4 % | **81.8 %** |
| Plausible lemma | 68.4 % | **80.0 %** |
| Rows passing every check | 61.4 % | **74.2 %** |

No held-out row lost any metric. By dialect group (lemma present, L → M): Aeolic 67 → 81 %, Doric/choral 68 →
85 %, Ionic elegy/iambus 84 → 92 %, Attic/popular 71 → 80 %.

Remaining held-out failures (125 rows): 70 words with no lemma because the parser has no receipt for them yet
and no recorded form or variant matches (Lesbian/Doric forms and compounds such as σελάνναν, φόβαισιν,
ἀελλοδρόμαν, παραμελορυθμοβάταν; names Πιττακὸς, Μυτιλήνας, Κυδώνια); 19 flagged lemma-implausible, mostly
suppletive or ablaut verbs the heuristic cannot see (μολεῖν/βλώσκω, ἄμβροτε/ἁμαρτάνω, ἕπεται/ἕπομαι); 18
parse rows left with a feature open (indeclinable numerals ἑπτά, ἑξήκοντ’; tied candidates); 7 Morpheus-known
words whose candidates tie on different lemmas (οὐ/οὔτε, ὅτε/ὅτι); 9 rows whose lemma has no English definition
in any open dictionary (see below); 1 crasis the parser does not analyse (δηὖτέ); 1 noun sense on a verb
(μέδεις → μέδω "a guardian", Middle Liddell's only sense).

Data limitations (no open dictionary supplies an English definition for the lemma): Ἀριστογείτων (no
headword), ἄνητον (no headword; ἄνηθον is the usual spelling), ναῦον (LSJ's ναῦον is a different word, an
Egyptian measure), αὔως (LSJ points to ἀώς, ἠώς; followed by the follow-up below), καγγεγήρασ’ (parser lemma
κατά-γηράω, no compound headword), μαλίδες/μηλίς (homographs), ἀρι (letters beside a gap). The 70 parser-coverage words need Morpheus
receipts: 6,885 distinct GLP forms, 1,357 now cached; the module's 1,000-fetch daily ceiling means about six
more days of `warm_morphology_forms.py --order frequency` to cover all of them.

Not in the image: `lemma_glosses` follow-up that tries every target a pointer entry prints ("Aeol. for ἀώς,
ἠώς"), found while reading the held-out failures (committed after `40859d2`; ship with the next release).

## Historical: release L — open lexica, every Campbell GLP poem, word-panel headline (2026-10-08)

Public backend: image `melos-api:20261008l`
(`sha256:57cb205cfaf725323b867ebe20c465eea6911a5641b87d474408d258558b0851`), built on Basecamp with
`deploy/Dockerfile.patch` atop QA29 from the L source tarball (`git archive` of `3f8de60`, sha256
`6399af11e2fe0b1a7dce947af3363e415d1a542d1e0d18fd6313e3ac8ce3f9bb`, unpacked in `/home/alvin/melos-l/src`).
Recipe: `deploy/release_l.sh lexica|stage-docker|receipts|build|canary|promote|rollback`, which combines
`release_k.sh` (image) and `release_glp.sh` (staged corpus). K3 is kept stopped as `melos-api-before-l`;
the L canary as `melos-api-canary-l`. **Rollback:** `sh /home/alvin/melos-l/src/deploy/release_l.sh rollback`
(stops L, renames it `melos-api-failed-l`, restarts K3 with its own K3 mounts).

What L merges (lyric-corpus-reader merges `e54527c`, `39fc913`, `e7526da`, then `3f8de60`, `eaa6211`):
- Open lexica supplement (`docs/lexica-open-supplement.md`): LSJ Logeion, Middle Liddell, Cunliffe, Dodson;
  dictionary order; `gloss.short_text`. Files copied into the live data mount
  `/home/alvin/services/melos/data` (alvin-owned; K3 code ignores them): `lexica/supplement-entries.jsonl`
  (sha256 `aacdddbe…b511`, audit PASS), `lexica/supplement.manifest.json`,
  `reports/audit-lexica-supplement.json`, `raw/lexica/lsj-logeion-6aa48692192d/`,
  `raw/lexica/dodson-74f70358d4ac/`, `raw/perseus-lexica/…/ml.xml`, `raw/perseus-lexica/…/cunliffe.lexentries.unicode.xml`.
- Campbell GLP (section below): corpus staged at `/home/alvin/melos-l/data/corpus.sqlite` (sha256
  `43020900dd53…3382`) + rebound `manifest.json` (`63099801574d…dbaf`). The live corpus directory
  `releases/campbell-20261007b/candidate-data` is root-only, so `stage-docker` runs the GLP `stage` step in an
  unprivileged uid-1000 container with the live corpus and manifest bind-mounted as files. Receipts: corrected
  five 3 rows, already-corrected 2 (326, 350), 232 added, 288,589 → **288,821**, verify 237/237 identical,
  0 failures. Morpheus receipts bundle (`glp-receipts-bundle.json`, sha256 `bb8fccc3…5211`) imported:
  408 receipts.
- Frontend: word panel headline (headword → short gloss → printed form + parse) showing `gloss.short_text`
  when present, else `gloss.text`; a capitalised headword is labelled "(proper name)" only when no gloss is
  available. Vercel `project-melos-hje17bxan-nacryos-projects.vercel.app` aliased to https://greeklyric.com
  (`vercel deploy --prod --yes --build-env MELOS_READER_ONLY=1`; `.vercelignore` now excludes `.claude/`).

Canary (8792) before promotion: `smoke_backend.py --expected-passages 288821` pass;
`verify_campbell_glp.py --analyze sample`: 237/237 identical, 214 translations expected, 50 lines analysed,
0 failures; `check_span_parses.py --random 30`: 227 spans, 816 word rows, 0 failures; `/api/word?form=μῆνις`
lists Middle Liddell first ("wrath, anger"), then Autenrieth, LSJ Logeion, Cunliffe; Alcaeus 129 τε "and",
Ζόννυσσον Διόνυσος "Dionysus" (Middle Liddell). Memory: canary 3.25 GiB (K3 2.7 GiB) of the 8 GiB limit.

analyze-passage size/latency (80-word chunks, `fetch_machine`/`rerank` off), K3 → L:

| Request | Decoded | gzip on the wire | Time (gzip) |
|---|---|---|---|
| 34a, 50 words | 40.6 → 47.2 MB | 5.34 → 5.52 MB | 10.6 → 9.0 s |
| 129, words 1–80 | 76.6 → 79.7 MB | 11.0 → 9.7 MB | 17.9 → 15.0 s |
| 129, words 81–112 | 31.0 → 32.7 MB | 4.46 → 4.03 MB | 8.7 → 7.1 s |
| single word (reader headline), e.g. Ζόννυσσον | 106 KB | | 0.7 s |

The whole-poem payload problem (documented since G) remains; L adds about 4–16 % decoded.

Verified on https://greeklyric.com after promotion:
- smoke (288,821) pass; `verify_campbell_glp.py --analyze sample`: 237/237 identical, 0 failures.
- `check_span_parses.py --random 40`: 277 spans, 982 word rows, **0 failures** (a first run concurrent with
  the other checks had one HTTP 429 "Passage analysis is busy", not a parse failure).
- Production audit (`runtime/dev/audit-L-production`, corrected texts): **303 of 303 intact words with
  complete parse fields**, 18 damaged pieces labelled, **282 intact words with a display gloss** (K3: 201 of
  305), 289 with any candidate gloss.
- Browser (Edge via Playwright), Alcaeus 129: τε → τε / and / part.; Ζόννυσσον → Διόνυσος / Dionysus /
  acc. masc. sg.; τέμενος → a piece of land / acc. neut. sg.; ἔθηκαν → τίθημι / to set / 3rd pl. aor. ind. act.
  Sappho 1 (Edmonds) and Archilochus 1 (Yonge) show their comparison translations.

Backend tests (main checkout, with the supplement data present): 1889 pass after syncing the two re-anchored
runtime sidecars (`runtime/alcaeus-translations/translation-comparisons.public.json`,
`runtime/campbell-commentary/edition-commentary.public.json`; previous copies kept as `*.pre-release-l`).
Three expected failures: the frozen-manifest `test_run_commentary_relevance`, and two saved snapshots that
embed the pre-correction Alcaeus 129 text (`test_commentary_relevance_packet[…129…]`,
`test_linked_sense_integration::test_real_full_packet_ready[129…]`). Frontend: 440 pass.

## Shipped in release L: GLP — every poem in Campbell's *Greek Lyric Poetry* (prepared 2026-10-08)

Adds the 232 remaining Campbell poems (`campbell-glp:*`; audit `docs/audits/campbell-glp-full.md`),
public-domain comparison translations for 209 of them, and corrects 11 lines of the five live Alcaeus
passages (34a, 129, 130b) to the page images. Deployed as part of release L (above), with
`deploy/release_l.sh` in place of `release_glp.sh`.

What ships (branch `worktree-agent-a6e935236d3ca4e7c`, on top of K3 source `b0934b4`):
- Corpus: `scripts/correct_campbell_five.py corpus` rewrites the five approved rows to
  `data/campbell_glp/alcaeus_five_corrected.jsonl` (idempotent; refuses a row that is neither the approved
  original nor the corrected text), then `scripts/import_campbell_glp.py` adds
  `data/campbell_glp/campbell_glp.jsonl` (idempotent; refuses to overwrite a differing row). Passages
  **288,589 → 288,821**. Semantic manifest rebound to the new corpus (existing vectors kept; the 232 new
  ids listed as pending embedding: found by word search and reading, not yet by semantic search).
- Backend code and sidecars, all re-pinned: `translation_comparisons.py` + `translation_comparisons_data.json`
  (re-anchored) + `translation_comparisons_glp_data.json` (new), `edition_commentary.py` +
  `edition_commentary_data.json`, `source_line_english.py` + `source_line_english_data.json`,
  `editorial_readings.py`. No frontend change.
- Morpheus receipts for the corrected forms (e.g. ὤς): `runtime/dev/glp-receipts-bundle.json` in the laptop
  worktree (sha256 `bb8fccc3…`), exported with `deploy/sync_morphology_receipts.py export`.

Steps on Basecamp (needs ~1.7 GB free; disk was 98 % full on 2026-10-07):
1. `git archive` this branch, copy it to the box and unpack into `/home/alvin/melos-glp/src`; copy the
   receipts bundle to `/home/alvin/melos-glp/receipts-bundle.json`.
2. `sh /home/alvin/melos-glp/src/deploy/release_glp.sh stage` — copies the live corpus
   (`releases/campbell-20261007b/candidate-data/corpus.sqlite`) to `/home/alvin/melos-glp/data/`, corrects
   the five rows, imports the 232, rebinds `manifest.json`, then
   `verify_campbell_glp.py --corpus … --expected-passages 288821` must report all **237** identical and
   `failures: 0` (receipts `correct-five-receipt.json`, `import-receipt.json`, `verify-corpus.json`). Do not
   copy or touch the staged corpus afterwards (the manifest is bound to its mtime and size).
3. `… release_glp.sh receipts` (imports absent Morpheus receipts only).
4. `… release_glp.sh build` (image `melos-api:20261008glp` from `Dockerfile.patch` atop QA29, as K).
5. `… release_glp.sh canary`, then on the box:
   `python3 deploy/smoke_backend.py --origin http://127.0.0.1:8792 --expected-passages 288821`,
   `python3 scripts/verify_campbell_glp.py --origin http://127.0.0.1:8792 --expected-passages 288821 --analyze sample`
   and `python3 scripts/check_span_parses.py --base http://127.0.0.1:8792 --random 30` (expect 0 failures).
6. `… release_glp.sh promote` (K3 kept stopped as `melos-api-before-glp`; `rollback` restores it).
7. From anywhere: `python deploy/smoke_backend.py --origin https://greeklyric.com --expected-passages 288821`
   and `python scripts/verify_campbell_glp.py --origin https://greeklyric.com --expected-passages 288821`.
   From then on the production smoke expectation is **288,821**.

Local checks (2026-10-08, dev server on the corrected texts): all 237 passages identical to the verified
texts; `check_span_parses.py --random 30`: 227 spans, 816 word rows, **0 failures** (3 failures on ὤς
until its Morpheus receipt was warmed, hence step 3); five-poem audit (`runtime/dev/audit-glp-corrected`):
303 of 303 intact words with complete parse fields, 18 damaged pieces labelled (glosses are not
measurable locally: the laptop dev corpus has no dictionary index).

Not in this release: BGE-M3 vectors for the 232 new passages (the five keep their existing vectors,
computed on the pre-correction text; the differences are diacritics and three letters).

## Historical: release K3 — every intact word fully parsed (2026-10-07, night)

Public backend: image `melos-api:20261007k3`, same recipe and mounts as K
(`MELOS_K_TAG=k3 sh /home/alvin/melos-k/src/deploy/release_k.sh …`, source tarball
sha256 `e602bef35e4e0796e41fa020cf9279ec65955367b63cf5c9ec46d4cd0fbc66ee`). K2 kept
stopped as `melos-api-before-lexical-20261007k3`; canary as `melos-api-lexical-canary-k3`.
Adds over K2: second ranking pass from neighbours' resolved parses (τὼ ξίφεος,
ἄχω θεσπεσία), precedents from settled readings of the same form (νᾶϊ), fullest
same-lemma row across a wrongly predicted feature (ἄεθλον acc. neut. sg.), genitive
patronymics, labelled top-ranked proposals for tied nominals (γλαύκας), open
supplements at a line end labelled conditional (Μύρσιλ̣[ο).

Verified on https://greeklyric.com:
- Production audit (`runtime/dev/audit-13-production`): **305 of 305 intact words
  with complete parse fields**, 16 damaged letter-runs labelled, 201 words with a
  selected gloss.
- `scripts/check_span_parses.py --random 30`: every printed line plus 150 random
  2–5 word spans across the five poems, 227 multi-word selections, 821 word rows,
  **0 failures**.

## Current: release K2 — last tier, damaged pieces, ranking refinements (2026-10-07, later)

Public backend: image `melos-api:20261007k2` (`sha256:6f6086d02cd5…`), built on
Basecamp from the K2 source tarball (sha256
`0414035862ce771454d2cfbeaea80c22de93e3625b01a16957fdf58c079a9091`) with the same
recipe and mounts as K (`MELOS_K_TAG=k2 sh /home/alvin/melos-k/src/deploy/release_k.sh …`).
K is retained stopped as `melos-api-before-lexical-20261007k2`; the K2 canary as
`melos-api-lexical-canary-k2`. Canary passed `smoke_backend.py --expected-passages 288589`
and the probes; public origin verified after promotion (ἴφθ]ιμοι voc. masc. pl.,
Ὕρραον acc. masc. sg. by ending pattern, ἔοι̣ 3rd sg. pres. opt. act. conditional,
ς̣βιότοις̣ dat. masc. pl. of βίοτος conditional, ἤπειτα adv. via ἔπειτα).
Morpheus cache: 350 receipts (empty-result receipts and the new normalisation
variants imported). Frontend: Vercel `project-melos-39qawr5j0` aliased to
greeklyric.com (labels for damaged pieces and ending-only analyses).

What K2 adds over K (`docs/morphology.md`, "Last tier"): ending-based pattern
analyses for words no lexicon knows; `damaged_piece` labels for letter-runs beside
lacunae (excluded from word counts); uncertain-edge-letter variants; more Aeolic
rules and a Lesbian lexical table; ranking: nom./voc. folding except under a
vocative prediction, adjacent-nominal agreement, featureless predictions treated as
none, fuller same-lemma rows win, exact attestations outrank parser guesses,
POS filled from the prediction; the syntax provider now waits up to 20 s for a
concurrent analysis instead of dropping the prediction (audit chunks had lost
their predictions to `provider_busy`).

Dev audit 8 (`runtime/dev/audit-8`): 298 of 306 intact words complete, 15 damaged
pieces labelled, 194 words with a selected gloss (109 at K). Backend tests: 1880
pass, 1 expected frozen-manifest failure. Production audit after promotion
(`runtime/dev/audit-9-production`, through https://greeklyric.com): 299 of 306
intact words complete, 15 damaged pieces labelled, 195 words with a selected
gloss. The seven residual words: Ὦγεσιλαΐδα and τυνδέων (ending-pattern parses
without a determinable gender), γλαύκας and τὼ (genuine ties left as consensus),
Μύρσιλ̣[ο and ἄχω (model prediction only), ον̣ beside a lacuna, νᾶϊ and ἄεθλον
(prediction conflicts in the 80-word audit window).

## Historical: full parses for every printed word, release K (2026-10-07)

Public backend: image `melos-api:20261007k`
(`sha256:f441cca71f37bc12d4d523a5b40b379494918dd90f2da92ac40a1577e319d90c`), built
on Basecamp with `deploy/Dockerfile.patch` atop the verified QA29 base
`melos-api:20261005-qa29` from the K source tarball (sha256
`ab0007aa1c353b0d92ba27dc39aa7ad2ea73a0462694038f58549bfe4266c7f0`, unpacked in
`/home/alvin/melos-k/src`; `releases/` is root-owned). Unlike E–I, K carries the
whole `backend/` package in the image with **no per-module bind overlays**; the
data, models, syntax-model, runtime, corpus (`campbell-20261007b`) and secrets
mounts are the live I mounts. New environment: `MELOS_MACHINE_GLOBAL_DAILY=1000`,
`MELOS_MACHINE_GLOBAL_MINUTE=30`, `MELOS_MACHINE_VISITOR_DAILY=100`,
`MELOS_MACHINE_VISITOR_MINUTE=10`. Recipe and rollback:
`deploy/release_k.sh build|receipts|canary|promote|rollback`.

Promotion path: canary `melos-api-canary` on 8792 passed
`deploy/smoke_backend.py --expected-passages 288589` and the five-poem probes;
`qa_regressions.py` fails identically against I (stale "Ibycus 286" expectation
without `--cgl`), so it is not a K regression. I is retained stopped as
`melos-api-before-lexical-20261007k`; the K canary is retained stopped as
`melos-api-lexical-canary-k`. Verified through the public origin after
promotion: ἦλθες `2nd sg. aor. ind. act.`, νᾶ̣]σον `acc. fem. sg.` (νῆσος),
λίποντε[ς `nom. masc. pl. aor. act. ptcp.`, εὐρύσαο `2nd sg. aor. ind. mid.`
(via ἐρρύσαο), ῤήα adv. (via ῥήα).

Morpheus cache: 331 receipts in `runtime/machine_morphology.sqlite` (was 26):
every printed word of Alcaeus 34a, 129, 130b, 326, 350 plus the labelled
Aeolic normalisations, imported with `deploy/sync_morphology_receipts.py import
--apply` from `runtime/dev/receipts-bundle.json` (sha256
`0c10830a0ee0fe00bf3016907e08b9f757131248e2569a12199de8d2abf4b48f`; empty-result
receipts are now exported too).

Frontend: Vercel production `project-melos-nfdrtedjl-nacryos-projects.vercel.app`,
aliased to https://greeklyric.com (`vercel deploy --prod --yes --build-env
MELOS_READER_ONLY=1`). The reader now opens each Greek text with a
`POST /api/passage-morphology/warm` call, requests a parser fetch on single-word
clicks, shows the editor's reading of bracketed words and "Parses ranked by fit
to the context".

Local five-poem audit (`scripts/audit_alcaeus_occurrences.py` against the dev
server, `runtime/dev/audit-4`): 301 of 321 printed words have complete parse
fields (baseline: 227 of 269 intact segments, with 119 bracket fragments
unparsed); the 20 remaining are damaged pieces beside lacunae (labelled
conditional) and a few proper names/hapax forms the parser does not know. Design
and ranking rules: `docs/morphology.md`, "Full parses for every printed word".

Backend tests at promotion: 1876 pass; the only failure left is
`tests/test_run_commentary_relevance.py` (its frozen manifest pins the previous
`sense_ranker.py` hash; the commentary-relevance cues are now gated behind
`MELOS_COMMENTARY_RELEVANCE=1`, off in production).

## Historical: gzip backend and grouped reader I (2026-10-07)

Public backend: `f888ab8692593446a2495b3543be2ce7274bfcd672cc0d5f8379083af8f50a19`,
release `/home/alvin/services/melos/releases/lexical-20261007i`, unchanged QA29 image.
I adds only negotiated large single-body JSON gzip and its four-line server
registration. No dictionary, corpus, runtime cache, parser or vector changes.
Independent review passed 79 relevant tests; actual private HTTP checks proved
byte-exact identity/gzip equivalence, explicit gzip refusal, and non-JSON/small
response passthrough. The sampled dictionary response shrank from 717,597 to
119,024 transferred bytes. Compression does not reduce lookup CPU or decoded
browser payload size; no general latency claim is made.

Root approved the exact private canary in
`runtime/lexical-release-i/canary-promotion-pass.json` (SHA256
`601ece8f5170c67da0f260599471cc2f9fc5c6afbca959a4f67d188d553a5781`).
Guarded promotion verified preserved resources, environment, source databases,
semantic coverage and routes. H is retained stopped as
`melos-api-before-lexical-20261007i`; private I is also retained stopped.
Root repeated all nine raw-transport probes against the public backend
`https://basecamp.taila44c41.ts.net:8443`: PASS, matching the private decoded
bytes exactly. Final receipt `runtime/lexical-release-i/live-verify.json`, SHA256
`ff5108c9c7bc42023878fff8afbf0d7488a6ce3b7251f99a2b90c8efa83bc07c`,
binds those bodies, exact deployed modules, retained rollback, unchanged
environment/resources and preserved routes. This raw-transport test targets
the backend endpoint; the separate browser check below targets greeklyric.com.

Reader-I frontend: `dpl_4t9JqwmbUUAtJsKqXAoghEKVrRY1`,
https://project-melos-8bypsq3yq-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Root verified the public reader using computer use:
the complete aorist parse and “come or go” remain visible; duplicate source
records group together and expand to their original incomplete analyses.
Distinct noun/adjective readings remain separate in the private checks.
This verifies the tested grouping and default dictionary presentation, not
universal parsing or contextual meaning accuracy.

Optional isolated CPU diagnostic completed with network disabled, read-only
mounts, one CPU, 4 GiB and a 120-second limit. No serving worker was modified.
`runtime/lexical-release-i/isolated-word-profile-r3.json` records 12.99 seconds
of initial warmup and 2.288 seconds across five second-pass profiled lookups;
70 source-entry renders consumed 1.472 cumulative seconds (about 64% of the
profiled lookup time). These are diagnostic-process timings with profiler
overhead, not HTTP latency or a philologically representative benchmark.
The automatic selector included `ις`, which is not independently certified
as an intact word. No rendering optimization was deployed with I.

## Historical: source-tense dictionary headlines H (2026-10-07)

Public backend: `e37c1e216b508388caa8d9260298390b59edc9b5bf07b3d825fc5d3fb3b68eda`,
release `/home/alvin/services/melos/releases/lexical-20261007h`, unchanged QA29 image.
Immutable H-r2 reader frontend: `dpl_BiSgFewQxH9JPQ4UyE3BgqZmPzLk`,
https://project-melos-8vw4pzmdi-nacryos-projects.vercel.app. Root verified
the four live JavaScript files against the frozen H-r2 artifact during this
completed rollout; the dirty working tree was not deployed.
Root also reloaded the public reader and clicked `ἦλθες`: both the searched-form
card and the separate source-definition excerpt visibly showed “come or go”,
with the complete aorist parse. This verifies that default dictionary correction
in the live UI, not universal contextual sense accuracy.

Only `lexicon_senses.py` and `interlinear.py` changed in the backend, with 282
exact-stage tests passing. The narrowly audited LSJ backward-reference note
marks two senses as present-only. For known aorist candidates, those senses
no longer supply the dictionary headline. No missing tense is inferred, and
all 14 literal LSJ senses remain available in the expanded source inventory.
The visible `ἦλθες` compact meanings now start with “come or go”; its full
second-person singular aorist indicative active parse is retained.

Final verification: `runtime/lexical-release-h/live-verify.json`, SHA256
`774feeebfadd6b6682580efcd982adaa0b3976de83b53fa61d5ed69594884b80`.
Eleven bounded live HTTP probes verified the exact two-response tense case,
five contextual parses and both linked inventories (15/11 senses). Exact
source text, 88 commentary paragraphs and five English comparisons remain
unchanged, as do environment, resources, routes and the original runtime.
No cached receipts, counters, corpus rows or vectors were imported or replaced
for H. No paid calls or upstream morphology fetches were requested.

G is retained stopped as `melos-api-before-lexical-20261007h`, ID
`b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb`.
Private H `07f6ceacbe94e4f509aee1ce3ce8b54fc430d44d39d5ff18072f93acf5026ae9`
is retained stopped after production warmup. This fix does not resolve every
candidate identity: a single interlinear gloss may remain unavailable while
compatible candidate meanings are shown separately. The large whole-poem
payload/performance problem documented under G also remains unresolved.

## Historical: contextual alternatives and editorial readings G (2026-10-07)

Public backend: `b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb`,
release `/home/alvin/services/melos/releases/lexical-20261007g`, unchanged QA29 image.
Reader-only frontend: `dpl_74H2frBj2KHABBc8LGrfzXbyRuKX`,
https://project-melos-nr5bfctdd-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. This is the immutable reviewed G frontend, not the newer
H working files. Discovery pages remain unpublished.

Ten narrow backend overlays passed 410 exact-stage tests. G adds source-owned
noun gender, unresolved homograph inventories, ranked uncertain sense alternatives,
documented elision transport, and separately displayed conditional editorial
readings. Larger sense packets retain all alternatives through reversible short
IDs. Capacity limits are character proxies, not a guarantee of Jev token fit.
The commentary instruction was clarified after the eight-call experiment;
thresholds remain unchanged and no accuracy improvement is claimed.

Final public verification: `runtime/lexical-release-g/live-verify.json`, SHA256
`0173d2319ab11cd5453b0d0d6738e84f4c3a522d0a105d9e0e081643ad225f00`.
It binds all ten module hashes, unchanged environment/resources/routes, the five
exact Greek texts, 88 commentary paragraphs and five English comparisons.
Public probes preserve full `ἦλθες` parsing, all 15/11 linked senses, and verify
eight cached source forms against exact receipt IDs and candidate counts.
Eight editorial API chunks retain 54 source rows, with 26 eligible conditional
projections and 10 having source-backed analysis. Missing analyses remain missing;
printed supplements are not promoted to securely transmitted text.

Public whole-poem analysis is functionally correct in these checks but still
too heavy: some raw responses were roughly 38–46 MB and took tens of seconds.
This known repeated-provenance payload problem is not fixed by G. No low-latency
or universal philological accuracy claim is made.

Eight audited Morpheus receipts were imported after preview using G's validator.
Independent audit `runtime/lexical-release-g/public-import-audit.json` (SHA256
`1311e6cbd84469163ee544a616fa0ee84ddfa234be8f606225a57145759d2099`)
proves the previous 18 cache entries, 18 receipts and 15 attempt records remain
unchanged, including the separate maintenance additions; cache/receipt totals
are now 26/26. No operational counters or in-flight records were imported.
No paid calls or upstream parser fetches were requested by release verification.

F is retained stopped as `melos-api-before-lexical-20261007g`, ID
`e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52`.
Private G `bc0e2210c9dd78928250b875bbb861cc5ad4b35d7ba5608c33f1e87f4474e8ed`
is stopped; its separately audited SQLite snapshot/import never replaced the
production runtime. Source databases, corpus, vectors, quotas, secrets and
Basecamp/private routes were preserved. Five Campbell embeddings remain pending.
The optional H tense-restriction change is not included in this release.

## Historical: source-linked dictionary and comparison release F (2026-10-07)

Public backend is `e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52`,
release `/home/alvin/services/melos/releases/lexical-20261007f`, on the unchanged
QA29 image. Frontend is reader-only deployment
`dpl_GQjuM5iMG9pHRLtWtXmGCdV1VhHG`, aliased to https://greeklyric.com.
The rejected discovery pages remain unpublished.

Nine exact backend overlays add source-linked dictionary alternatives and
five source-bound English comparisons from other editions. The comparisons
remain explicitly unaligned with Campbell's Greek, retain translator/source/
license labels, and are reader context rather than model translation evidence.
No corpus, vector, evidence index, source index, secret, resource or route
changes were made. All five Campbell Greek texts and 88 commentary paragraphs
match the approved artifacts. Existing 116,191 semantic vectors remain ready;
the five Campbell poems remain explicitly pending embeddings.

Independent module approval: `docs/audits/lexical-context-backend-f.json`.
Root's public promotion authorization:
`runtime/lexical-release-f/canary-promotion-pass.json`, SHA256
`6095acc72e42937180e5423a0b951d606d44ebce979d1ddde2b7421b2a19f4b9`.
Post-promotion verification: `runtime/lexical-release-f/live-verify.json`, SHA256
`8705c33914134eacfbc3596f26c19a55737f49f852f03e4203c9110d9edc9524`.
That receipt binds exact live module hashes, retained E, stopped private F,
unchanged resources/environment/routes, all five source/comparison checks,
and nine public HTTP probe receipts without paid ranking or parser fetching.

Public probes preserve the full `ἦλθες` second-person singular aorist indicative
active parse. All 15 source-linked senses for `παχέων` and 11 for `δᾶμον` reach
the ranking input. Root separately checked the live browser: the English
comparison expands with attribution, and the cubit dictionary path appears
alongside distinct competing adjective entries. This demonstrates source
coverage and functionality, not universal parsing or sense accuracy.
The one authorized private Jev trial favored the cubit sense at an uncalibrated
0.57 and remained uncertain; no further paid calls were made for deployment.
Conflicting predictions for `τάλαις` and `ὄππᾳ` remain suppressed. The subsequently
identified prompt contradiction is not fixed by F and belongs to follow-up work.

E is retained stopped as `melos-api-before-lexical-20261007f`, ID
`0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5`.
Private F `36de860ef7770eeb649f1a5e522c76cd5eb275c984ca570c775ae5f6b0b1f4d6`
is retained stopped after the production warmup. Funnel 8443 still serves
localhost 8791; Basecamp 80/443 remain private and unchanged.

The following sections are historical release snapshots, not current status.

## Historical: commentary-ready reader display (2026-10-07)

Live frontend: `dpl_HFbuHTZF2kbEJB14k15kqYWrnh1o`,
https://project-melos-knym4dnfb-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Reader-only build; 378 frontend tests pass.
Live `reader.js` and `passage-analysis.js` bytes match independently reviewed
hashes `045e53ce9bf7cc9713162fc073a7aebb95e721163a737b9118e799db30baee22`
and `7719a2c97a0893b4633e6b2c6a9d42301de5ae23e8c90bb8173661bccfb617c9`.

Exact lexical variants no longer trigger false dictionary-absence copy when
only a complete morphological parse is unavailable. New source-bound
commentary rendering is backward compatible with the current D backend:
whole-poem notes stay collapsed, while literal NFC printed-heading matches
can appear beside an intact clicked word. No accent folding, substring
matching, cross-poem binding or inferred word attestation is permitted.
Uncertain OCR paragraphs cannot become these heading matches.

E backend is live: `0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5`,
release `/home/alvin/services/melos/releases/lexical-20261007e`. It adds an exact
neighboring syntax window for long poems and the audited commentary sidecar.
Independent staged review: 360 application tests and 31 deployment guards.
Root approval: `runtime/lexical-release-e/canary-promotion-pass.json`.
Final verification: `runtime/lexical-release-e/live-verify.json` (SHA256
`ab4a5e0f28830117d169df1ce437cb8ee98f3ba902251298429afd65ed49ed77`).
Root independently repeated the five public context checks in
`runtime/lexical-release-e/live-root/`; all five Greek texts and all 88 reader
commentary paragraphs remain bound to approved sources. The model receives
87 paragraphs, excluding the uncertain OCR paragraph. Browser verification
confirmed the immediate Campbell note on clicked `στάσιν` and the expanded
whole-poem commentary panel on live fragment 326.

The old local test tunnel had expired; its failed request receipt is preserved
under `runtime/lexical-release-e/operational/`. The replacement tunnel was
verified before the explicit successful retry in `operational-restored-tunnel/`.
D is retained stopped as `melos-api-before-lexical-20261007e`; private E is
retained stopped. Existing corpus, vectors, resources and routes are unchanged.

Newer 23-sense saved `στάσιν` packets initially exceeded the unchanged 32k
classification budget. Lossless common-field sharing now retains all 23
choices and the eligible commentary at 30,817 characters. One actual paid
Jev sense call completed in 2.293 seconds: it favored the literal LSJ sense
"position in relation to the compass" at an uncalibrated 0.68, below the
decisive threshold; no definitive gloss was substituted. The morphology
comparison abstained before a provider call. See `jev-stasin/` receipts.

This is not universal accuracy: long-window predictions for `τάλαις` and
`ὄππᾳ` still conflict with source lexical identity and remain suppressed.
`δᾶμον` now has a compatible contextual prediction but no resolved meaning.
`παχέων` retains a possible `παχύς` analysis; Campbell's royal-cubit discussion
exposes the missing alternative. Source investigation found explicit Kaikki
links from quantity-marked `πᾱχέων` to `παχέων#Ancient_Greek`, and from
`πᾶχυς` to `πῆχυς`; source-link alias support is being developed separately.
The separately audited five English translation comparisons remain staging
only, without reader/model integration or exact Campbell alignment.
The independently audited `backend/dictionary_crossrefs.py` resolver is also
staged only. Do not claim its source-backed alternative meanings are live.

## Exact-form dictionary display cleanup (2026-10-07)

Live frontend: `dpl_5ZaetrW4yGf9hnbHyanUABzMZ1Ze`,
https://project-melos-cumk6reie-nacryos-projects.vercel.app, aliased to
https://greeklyric.com. Explicit `MELOS_READER_ONLY=1` build; `/lexicon`,
`/authors`, and `/themes` remain 404. All 365 frontend tests pass; the three
changed live JavaScript files match local reviewed hashes. Exact NFC form
scope now separates normalized matches from exact grammatical evidence.
Inherited headword form-of prose from the actual Wiktionary `ἦλθον` payload
no longer appears as a meaning of table-matched `ἦλθες`. Exact lexical
variant display is now backed by release D's live API fields.

Public backend is release D (`71c6555a265f83a01f781e3673a815a073c2ed9bc7f8153d36297b8f6797b0c0`),
release directory `/home/alvin/services/melos/releases/lexical-20261007d`.
Five exact module overlays passed 301 application and 23 deployment guard
tests; audit: `docs/audits/lexical-context-backend-d.json`. Root's separate
canary approval is `runtime/lexical-release-d/canary-promotion-pass.json`.
Production verification: `runtime/lexical-release-d/live-verify.json` and
root's independently repeated public probes in `runtime/lexical-release-d/live-root/`.
The five approved Campbell texts, corpus, vectors, and Basecamp routes are
unchanged. B is retained stopped for rollback as
`melos-api-before-lexical-20261007d`; C and D canaries are retained stopped.

Exact source features now survive incomplete or conflicting model parses:
`ἦλθες` shows `2nd sg. aor. ind. act.` and `δᾶμον` sourced `acc. sg.`.
Exact lexical variants retain meanings without a fabricated full parse.
Contradictory standalone model parses for `ὄππᾳ` and `τάλαις` are suppressed;
the raw model predictions remain separate. Never promote the older C release:
its operational probes exposed these contradictions. C artifacts are frozen.
The audited surrounding-context window helper is not yet integrated or live.

Fresh source-occurrence baseline: 388 segments, 119 API-flagged damaged
segments and 269 unflagged (not independently certified intact words).
Only 47 selected English glosses, 120 occurrences with any candidate gloss,
and 137 with exact-surface source/contextual candidates. These are coverage
counts, not accuracy scores. See `runtime/alcaeus-occurrences/baseline/`.

New source packages remain STAGING ONLY, not live context:

- `runtime/campbell-commentary/commentary-candidates.jsonl`: five records,
  88 retained paragraphs, package SHA256
  `3e33ec114f43058f62553d4f6764f65c0e7bc655b204376c7ac82b063c07335a`.
  Independent pixel/package approval under its `audits/` directory. Two
  unreliable OCR paragraphs excluded; one documented unreadable glyph remains
  unsuitable for exact lexical evidence.
- `runtime/alcaeus-translations/translation-candidates.jsonl`: five audited
  English comparisons, Edmonds for 34a/326/350 and Lowell Edmunds for 129/130b.
  None is asserted to be an exact translation of the Campbell Greek. Preserve
  edition differences, translator attribution and original rights labels.

The goal of accurate contextual meanings and full source-backed analyses for
all words/spans remains incomplete. Do not report successful requests or
passing code tests as universal linguistic accuracy.

## Contextual dictionary and complete-parse repair (2026-10-06)

Live frontend: `dpl_8z6qJU4nuhg78NRvGZaJ4HghSWmJ` at
https://greeklyric.com, built explicitly with `MELOS_READER_ONLY=1`.
The rejected discovery routes still return 404. All 348 frontend tests pass.

Live backend: `ec2cdc5176ed0f747cb03de0037d7bfb1bc00e93644fae7fbf761822e6eb6aa5`,
release `/home/alvin/services/melos/releases/lexical-20261007b`, with five
hash-verified module overlays on the unchanged QA29 image: `classifier.py`,
`interlinear.py`, `lexicon_senses.py`, `passage_analysis.py`, `sense_ranker.py`.
The prior Campbell container is retained stopped as
`melos-api-before-lexical-20261007b`; both lexical canaries are stopped and
retained. Corpus, embeddings, secrets, environment, resource limits and
private Basecamp routes are unchanged. Independent module approval:
`docs/audits/lexical-context-backend-b.json` (274 tests, canary eligibility only).
Actual operational promotion evidence:
`runtime/lyric-context-eval/canary-b-promotion-pass.json` and
`runtime/lyric-context-eval/live-b-verify.json`.

Hyphenated Wiktionary person tags now survive projection. Coarse UD Past no
longer incorrectly contradicts a source's explicit aorist; it never supplies
an aorist by inference. Partial source analyses cannot displace an otherwise
compatible fuller analysis. When exact source alternatives agree on a complete
parse but lexical identity remains unresolved, the parse can be displayed
without choosing a dictionary homograph or inventing a gloss.

The new explicit **Read in context** word action uses Jev to choose an existing
English dictionary sense independently of resolving every morphological
alternative. Full passage hashes, source-entry/sense/candidate bindings and
stale-response guards are checked. No automatic paid calls on word selection.
Shared packet-local references reduce repeated metadata without dropping
meaning choices; source coordinates stay bound in the server inventory hash.

Bounded actual canary results: ἀνέμων → "wind", κῦμα → "wave, billow", and
ἦλθες → "come or go"; στάσιν remained uncertain with all 23 senses retained.
These are three useful proposals and one abstention, not an accuracy benchmark.
Live browser verification confirmed the four-word phrase ἦλθες ἐκ περάτων γᾶς
shows **2nd sg. aor. ind. act.** for ἦλθες, and its word inspector's explicit
context action shows "come or go" with that full parse.

Known gaps remain: default phrase analysis does not automatically run Jev;
περάτων still lacked an English preview in that phrase; source-order dictionary
previews and form-of headword descriptions can still be unhelpful. Do not claim
universal morphology or contextual-meaning accuracy. The staged 717-entry LSJ
subentry index was NOT shipped: its independent audit found a source-tagging
error producing a truncated definition, documented in
`docs/audits/lyric-subentries.json`.

## Campbell Alcaeus assignment release (2026-10-06)

Frontend: `dpl_B9ZWF9NfiHe6nu4RyiwEZxEYgemj`, aliased to
https://greeklyric.com. Explicit reader-only production build; rejected discovery
routes remain 404. Includes five source-facsimile pages, immutable excerpt-image
caching, and editorial-segment lookup guards. All 330 frontend tests pass.

Backend candidate: `/home/alvin/services/melos/releases/campbell-20261007b`.
Five IDs: `campbell-glp:alcaeus:{34a,129,130b,326,350}`. Campbell prints the
assignment's 130b as 130; citation metadata explicitly indexes both references.
Source JSONL SHA256: `afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b`.
Independent acceptance: `runtime/campbell-assignment/integration-pass-v2.json`.
Production promotion passed the final canary gate. Live container:
`99ac41bf357439a2e07bb69cde3f279b6bf8ae8b89690c8cc7d9ee28be517460`.
Original QA29 container `cc62bec35b7b...` is retained stopped as
`melos-api-before-campbell`; routes, environment and resource limits preserved.
Both private Campbell canaries are stopped and retained. Promotion receipt:
`/home/alvin/services/melos/releases/campbell-20261007b/promotion-receipt.json`.
Public UTF-8 API verification matched all five exact Greek text hashes and
all five reference searches after promotion.

The immutable QA29 image is retained with exactly two audited read-only module
overlays: `passage_analysis.py` and `interlinear.py`. These preserve damaged
Greek segments, attach exact dictionary entries to machine lemma hypotheses,
and avoid displaying a sole syntax prediction when explicit candidates
contradict it. Machine alternatives do not become source attestations.

Scope limitations: tiny glyphs in 34a remain explicitly uncertain; source
facsimiles are available for comparison. These records have no aligned English
translation. Existing 116,191 semantic vectors are unchanged; the five new
records are explicitly pending embedding. Do not claim complete contextual
parsing accuracy or complete dictionary coverage from HTTP/offset tests.

QA artifacts live under `runtime/alcaeus-assignment-qa/`. The baseline full run
tested 227 distinct printed lookup segments (not necessarily complete words):
149 had exact indexed parses; 166 had displayable sourced English dictionary
previews. All 60 sampled phrase analyses preserved source text and offsets;
28 literal phrase searches and 10 intact Forms searches retrieved their target.
Editorial/lacuna barriers are reported separately, not repaired for matching.

Final V2 QA report SHA256:
`1916a8e4b5f7160caa00878b7fe8183a80a30d9945a1092148d60bb44d6b6bef`.
Word/Wiktionary results were reused only after checking unchanged code/image
and all 227 exact source-context hashes; all 60 phrase checks and reference
navigation checks were freshly repeated against V2. Three additional cached
Morpheus projections were rechecked without new external model/parser calls.

Live browser verification covered fragment 326 word lookup, endpoint-based
four-word selection, successful analysis, Same wording retrieval (Campbell
plus a separately labelled other edition), and fullscreen artwork. Important
unresolved semantic regressions: the word preview for `στάσιν` leads with
source-order senses "erection" and "standing stone, pillar", not an adjudicated
meaning in this poem; OdyCy proposes adverb for `ἀσυννέτημμι` when no exact
indexed candidate is available. Operational QA is not philological approval.

## Fullscreen artwork and touch selection fix (2026-10-06)

Live: `dpl_EVjdaLHk6ahtiXTcDmh4q1yz9EoU` at https://greeklyric.com.
Built with `vercel deploy --prod --yes --build-env MELOS_READER_ONLY=1`.
The old hero/reader remain; discovery navigation is absent and `/lexicon`,
`/authors`, `/themes` return 404. Discovery source remains local. Backend QA29
was not changed. Do not use ordinary preview promotion for this profile:
promotion rebuilt using production settings and dropped the one-off build
environment; the explicit production build above corrected that immediately.

Fullscreen loads a real decorative image eagerly, preserves the CSS fallback,
uses one dark overlay, and has a fixed-overlay fallback for missing/failing
native dialog support. Touch-friendly Select phrase lets readers tap endpoints;
native selection remains available. The selection dock tracks the exit toolbar
height and becomes nonsticky on short landscape screens to avoid covering text.

327 frontend tests pass, including missing/throwing modal APIs, image failure
fallback, selection ranges, and reader-only build isolation. Browser QA verified
artwork and four-word selection at 390x844 and 844x390 in Chromium. Actual iOS
Safari hardware testing was not available; do not claim all-device verification.

## Discovery frontend rolled back at owner request (2026-10-06)

The owner rejected the current lexicon arrangement and author portraits/names.
Live Vercel was restored to the pre-discovery nature-header deployment
`dpl_GXF8m6Md3c8xdpzw9KxmrQNAv4vF`. The discovery implementation is retained
locally, not discarded, at http://127.0.0.1:8792/ with its local API on 8791.
The exact pre-discovery QA29 backend container `cc62bec35b7b...`, image
`sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777`,
was restored and publicly verified; new discovery API routes again return 404.
`tools/serve_timeline_preview.py` now serves the three discovery routes and
their public assets. Do not redeploy this design without the owner's approval.
The earlier release descriptions below are historical, not current live state.

## Discovery routes release (2026-10-06 Pacific)

Production `dpl_4YFGiy5cncWfMaK8k5GYBno1QwSU` is aliased to
https://greeklyric.com. The original hero/reader remain, with three new entry
cards and `/lexicon`, `/authors`, `/themes`. Vercel builds use their own API
rewrite, avoiding cross-origin production calls from preview deployments.

The author catalogue contains 13 source-extracted Wikipedia biographies,
10 image-backed profiles, and two DCC commentary excerpt instances. Original
images are unchanged; CSS framing provides portrait details. Expanded pictures
precede biographies. Revision, license and image provenance remain accessible.
The old local timeline preview remains intact.

Browser checks covered English `love` lookup, Greek `ἄνθρωπος`, Sappho's
expanded portrait/biography and real work-to-passage navigation, garden category
results, line-level `love and longing` within Sappho, and phone-sized layouts.
The last query exposed editorial-only semantic hits; a focused backend fix
excludes spans with no printed Greek letters without changing source texts.
See `discovery-release.md` for backend image identities, tests and rollback.

Limits: English definitions currently inspect up to 256 source-entry candidates.
Child semantics encode a bounded sample on demand (at most 64 spans across 16
retrieved parents), not a complete materialised hierarchical index. Stanzas
require explicit blank lines; sentence/phrase boundaries are heuristic. Literary
categories launch discovery searches, not certified poem classifications.
Ancient Greek semantic rankings remain exploratory, especially for lacunose text.

## Nature-header preset release (2026-10-05 Pacific)

Production deployment `dpl_GXF8m6Md3c8xdpzw9KxmrQNAv4vF` is aliased to
https://greeklyric.com. Five owner-approved landscape images are served as
content-hashed 960px and 480px WebPs from `/assets/nature-presets/`, with
one-year immutable caching. Originals and portrait favourites remain local.

`tools/build_nature_presets.py` rebuilds the selected images;
`tools/build_nature_assignments.py` exports only existing source-validated
positive aesthetic annotations (247 records: 169 Greek, 78 translations).
Both support `--check`. The public export contains IDs, hashes and theme IDs,
not source text or private file paths. Runtime matches exact record ID and
SHA-256 of the returned text; missing/stale annotations use a decorative grove
default, not a new theme classification.

The plain reading view stays white. Only fullscreen poem headings consume
the image under the existing dark overlay. `js/nature-presets.js` exposes a
reusable preset registry and lazy assignment accessor. Background images warm
sequentially at low priority after the hero painting queue; data-saver/2G skips
speculative warming. Opening fullscreen explicitly warms the selected image.
No backend deployment, paid inference, corpus edit or runtime generation is
required. Existing Hetzner service remains unchanged.

Checks: 272 frontend tests, 14 annotation/export tests, deterministic asset
verification, production asset/cache checks, and live fullscreen browser QA.

Melos has two deployable parts. Vercel serves the static reader and design studio. A separate persistent Python service serves `/api/*` from the accepted corpus, dictionary, and search indexes. Deploying the frontend alone does not make the reader functional.

## Static frontend

Create a Vercel project from the public Melos GitHub repository, with the repository root as the project root. `vercel.json` runs `npm run build` and serves only `dist/`. The build copies an explicit set of HTML, CSS, JavaScript, and generated painting assets. It places the research reader at `/`, the original design studio at `/legacy` (also `/design-studio`), and keeps `/reader.html` as a reader alias. No `data/`, Python code, source paintings, reports, model files, or credentials are in the output.

Set `MELOS_API_ORIGIN` in the Vercel project's environment variables to the public HTTPS origin of the separately hosted API, such as `https://api.your-domain.example`. This is a public address embedded into `dist/js/config.js`, not a secret. The production build fails if it is absent, local, or HTTP. Set it for each Vercel environment that should build. Do not set it to the Vercel frontend origin unless that origin actually routes `/api/*` to the live service.

For a local static artifact check without a deployed API, run `npm run build:preview`. It generates a same-origin API configuration for local preview only. For a production build check, set `MELOS_API_ORIGIN` to the intended public HTTPS API origin and run `npm run build`.

To publish the design before backend hosting is available, explicitly set `MELOS_FRONTEND_ONLY=1` instead of `MELOS_API_ORIGIN`. This produces a labelled frontend preview with search disabled and no API network requests. It is not a functioning public corpus reader. When the API is ready, remove `MELOS_FRONTEND_ONLY`, set `MELOS_API_ORIGIN`, and redeploy. Conflicting settings fail the build. Run `npm run test:frontend` to check the configuration guards and API routing.

## Persistent API service

Host `backend.server:app` on a service with persistent storage for the accepted indexes and enough memory and CPU for search and embedding loads. Build and audit the corpus and indexes using the procedures in [reader.md](reader.md) before making the API public. The API host must serve over HTTPS, expose a health/status endpoint at `/api/status`, and be reachable from browsers visiting the Vercel domain. Do not put the corpus, SQLite databases, downloaded source records, model weights, or API credentials in the public GitHub repository or the Vercel static artifact. Arrange backups and a documented index rebuild path for the persistent data.

Configure the API's `MELOS_CORS_ORIGINS` with the exact Vercel production and preview origins that should access it, and set `MELOS_PUBLIC_DEPLOYMENT=1` on the public API host. Browser CORS must allow the reader's read requests. Verify the API status, author/work listing, search, passage, word lookup, and usage space from the deployed frontend origin. A local browser test against `127.0.0.1` does not establish that public users can reach the API.

Any hosted classification credential (`TYPESAFE_API_KEY` or `JEV_API_KEY`) belongs only on the API host. The frontend never contains it or calls TypeSafe directly. Public `/api/classify-context` requires explicit `MELOS_PUBLIC_CLASSIFIER=1`; otherwise it remains local-only. The enabled route accepts only small JSON requests naming an existing corpus passage and form, constructs the source evidence server-side, and passes paid decisions through durable cache/quota checks. CORS and browser-session cookies are not authentication; the global persistent quota bounds new provider attempts even when cookies are reset or the Funnel endpoint is called directly.

## Release check

1. Complete the accepted corpus and indexes, and verify local backend tests and `/api/status` report the intended coverage.
2. Provision the persistent HTTPS API service and set its exact allowed frontend origins. Check read endpoints and operational limits.
3. Configure `MELOS_API_ORIGIN` in Vercel. Build the static artifact and inspect `dist/` for only the allowed frontend paths. `dist/` is Git-ignored.
4. Deploy a Vercel preview and test reader searches, passage navigation, word inspection, usage space, design studio, and unavailable-service states in a browser. Confirm contextual comparisons are labelled as model proposals, repeat decisions use the cache, quota errors are clear, and no keys or corpus files appear in deployed assets.
5. Promote only after the preview checks pass and the operator has selected and documented the publication policy. Extraction acceptance does not itself establish redistribution permission.

Vercel project configuration follows its [build and output directory](https://vercel.com/docs/builds/configure-a-build) and [routing configuration](https://vercel.com/docs/project-configuration/vercel-json) documentation.

## Published frontend (2026-09-30)

- Vercel project: `nacryos-projects/project-melos`, connected to `Nacryos/Project-Melos` on GitHub.
- Custom domain: <https://greeklyric.com>; Vercel alias: <https://project-melos.vercel.app>.
- Production and Preview environments set `MELOS_API_ORIGIN=https://greeklyric.com`. `MELOS_FRONTEND_ONLY` is removed; the generated configuration sets it to `false`. No Jev credential is installed in this frontend project.
- `vercel.json` proxies only `/api/*` to the hosted Melos service. Browser traffic uses ordinary HTTPS on greeklyric.com, without requiring a tailnet connection or access to outbound port 8443. API responses are `no-store`.
- HTTPS root, design studio, configuration script, and a fingerprinted painting asset returned HTTP 200. JavaScript is `no-cache`; fingerprinted paintings have the one-year immutable cache policy. The connected configuration removes the preview notice and enables corpus controls.
- `.env`, `.env.local`, database files, source paintings, and model/index files were excluded from the CLI upload. The static build uses its own explicit output allowlist.

The frontend and backend are connected. Public API checks run with `python deploy/smoke_backend.py --origin https://greeklyric.com`. The desktop/mobile design was visually checked before connection; the final connected-browser automation attempt timed out, so it is not recorded as a completed visual click-through test.

## Basecamp backend (2026-09-30)

The backend now runs on the existing Hetzner Basecamp machine in `/home/alvin/services/melos`, container `melos-api`, image `melos-api:20260930-jev`. The stopped `melos-api-before-jev` container retains the pre-Jev version for rollback. Host port `127.0.0.1:8791` is intentionally loopback-only. No other Basecamp services or firewall rules were changed.

- Runtime: 125 files, 6,433,058,045 source bytes; all transfer hashes verified and all three SQLite quick checks passed. The original local corpus remains intact.
- Coverage: 287,536 source records and 111,578 embedded records. Read endpoints, sourced word analysis, Wiktionary lookup, dense search, and usage-space projection passed `deploy/smoke_backend.py` on the host.
- Warm measured container memory: about 1.87 GiB. Repeated semantic queries took 0.18–0.30 seconds in the bounded smoke test; this is not a concurrent-load benchmark.
- Limits: two CPU cores, low CPU scheduling weight, 8 GiB memory with no container swap, eight concurrent HTTP connections, one worker, and bounded logs. Corpus and model mounts remain read-only; only separate operational classifier state is writable. No access to other projects or Docker's socket is provided.
- Encoder: CPU BGE-M3, pinned model revision in `deploy/cache_model.py`; runtime downloads are disabled.
- Publication: the owner explicitly selected `MELOS_PUBLICATION_POLICY=source-labels`. This overrides only conservative publication filtering. Source labels, including unknown rights, are preserved; provenance/hash acceptance checks remain enforced. This selection is not a conclusion that every public source grants redistribution permission.
- Paid classification: enabled with pinned `jev-1.13.0`. The existing key is stored in owner-only `secrets/jev.env`, mounted read-only at `/run/secrets/jev.env` and loaded by Uvicorn. It is not shipped in the image, Docker environment configuration, Vercel, Git, or logs. The transfer helper selects only the Jev key from the local environment; it never uploads the entire local `.env`.

### Jev cache and budgets

- `runtime/classifier.sqlite` is operational state, not source evidence. Cache identity includes the exact evidence packet, configured model, and explicit prompt/schema version. Changed evidence does not reuse an older decision. Entries expire after 30 days; maximum 20,000 cached decisions.
- Defaults: 500 new provider attempts per UTC day site-wide; 10 per minute and 60 per day per signed browser session; at most two concurrent calls. Each attempt is reserved atomically before contacting Jev, including failed attempts. Duplicate in-flight packets do not start another call. Cached results remain available after quota exhaustion.
- Session cookies are HttpOnly, Secure in production, SameSite=Lax, and contain no key or raw IP. Visitors can reset cookies, so they are a convenience throttle, not user authentication. Global quotas persist across restarts. The provider's own capped key is an additional limit, not a replacement for these checks.
- API outcomes: 429 with Retry-After for busy/quota conditions; 503 for unavailable model/cache state; invalid or oversized requests fail before a paid call. The model can choose a sourced candidate or abstain; its preference signals are not calibrated philological probabilities.
- Verify without spending: `python deploy/smoke_backend.py --origin https://greeklyric.com`. Explicit paid check: `python deploy/smoke_jev.py --allow-paid`, which requests a real Sappho comparison and verifies a cache hit on repetition. Initial live verification returned `jev-1.13.0`, one new comparison, then a cached repeat.
- Set `MELOS_PUBLIC_CLASSIFIER=0` when recreating the container to disable new public comparisons without changing corpus access. Adjust `MELOS_CLASSIFIER_DAILY_LIMIT`, `MELOS_CLASSIFIER_VISITOR_MINUTE_LIMIT`, `MELOS_CLASSIFIER_VISITOR_DAILY_LIMIT`, and `MELOS_CLASSIFIER_CONCURRENCY` in the container configuration as needed. Back up the runtime database alongside deployment state if preserving usage accounting across host recovery is required.

### Public network route

The owner enabled Tailscale Funnel. The public endpoint `https://basecamp.taila44c41.ts.net:8443` forwards only to `http://127.0.0.1:8791`. Basecamp's existing port-443 console was verified to remain tailnet-only. Never replace that private console with a default Funnel command.

Activation used existing key-based administrator access, without changing any password or granting new operator privileges: `tailscale funnel --bg --https=8443 --yes http://127.0.0.1:8791`. The public relay was checked independently of tailnet DNS, followed by the Vercel proxy at `https://greeklyric.com/api/status`. Only the Melos Funnel can be stopped with `tailscale funnel --https=8443 off`; this leaves port 443 unchanged. The persisted background configuration and container restart policy keep Melos running independently of the local computer.

### Maintenance

### Live QA repair release (2026-09-30)

`melos-api:20260930-qa1` adds exact author/fragment navigation, conservative
ambiguous-lemma expansion guards, and distinct classifier preflight outcomes.
The previous container is retained as `melos-api-before-qa1`. A loopback-only
canary on port 8792 passed the hosted read smoke checks before production was
replaced; that canary is stopped after promotion.

`scripts/repair_search_layout.py` produced a separate accepted-index snapshot:
413 passage search representations changed, 9,621 vocabulary keys checked,
all source-bearing passage fields compared unchanged, SQLite quick check passed.
Only explicit Greek line-end hyphenation is joined in derived search fields.
Displayed Greek, edition metadata, raw sources, claims and embeddings are not
rewritten. Host `data/corpus-before-qa1.sqlite` retains the previous index;
local rollback copy is `.benchmarks/corpus-before-qa1.sqlite`.

The migration changes SQLite's file identity and therefore correctly trips the
semantic stale-index guard. Before declaring the release healthy, run
`scripts/rebind_search_embeddings.py` against the previous and current corpus
and the prior embedding manifest. It verifies every source-bearing field and
the previous manifest identity before writing a separate rebound manifest;
promote that manifest atomically and retain the old one. The live repair checked
all 287,536 records unchanged; no vectors were recalculated or relabelled.
Then repeat semantic search and usage-space checks through the public origin.

Run `python deploy/qa_regressions.py --origin https://greeklyric.com` for the
specific read-only regressions, without provider calls. These checks and unit
tests are engineering evidence, not a philological accuracy benchmark.
Conflicting lemma attributions remain visible; withholding automatic expansion
also affects legitimate homographs until a headword is explicitly selected.
Reference lookup does not infer numbering equivalences, and catalogue pointers
remain labelled as missing Greek reading text.

For a code-only patch use `deploy/Dockerfile.patch` with `BASE_IMAGE` set to an
existing verified local image. `deploy/start_backend.sh` accepts explicit
`MELOS_IMAGE`, `MELOS_CONTAINER_NAME` (production or canary only), and
`MELOS_HOST_PORT` (8791 or 8792 only), and refuses to replace an existing
container. Preserve rollback state and validate before promotion.

### Combining-mark search repair (qa6, 2026-09-30)

`scripts/repair_search_tokens.py` rebuilds mismatched derived word tokens in a
separate SQLite snapshot. Attached combining marks, including editorial
underdots, remain part of the surface word; accent-folded lookup keys remain
separate. It does not supply missing letters or resolve uncertain readings.

The local and Hetzner migrations each scanned 103,171 eligible text/translation
records, repaired 318 tokenized passages, and checked 3,653 affected vocabulary
keys. All 287,536 source records, work metadata, normalized search text, and FTS
rows compared unchanged. SQLite integrity and input-stability checks passed.
The existing embeddings were rebound only after verifying unchanged inputs;
no vectors were regenerated. Run this workflow on quiescent snapshots.

For qa6 rollback, restore the paired previous corpus and embedding manifest,
not just the old container. Local backups are
`.benchmarks/corpus-before-qa6.sqlite` and
`data/embeddings/manifest-before-qa6.json`; host backups use
`data/corpus-before-qa6.sqlite` and the same manifest filename. Stop the Melos
service before swapping the pair. Retain the previous image/container until
the public smoke checks and live reader checks pass.

The read-only regression probe includes the original underdotted form
`βασί̣λ̣η̣αν` in `dcc-sappho:brothers-poem`: its source transcription must retain
the marks, and its word occurrence lookup must include that same passage.
This is a token-boundary regression, not an adjudication of the word's reading,
parse, dialect, or sense.

### Attached-apostrophe search repair (qa7, 2026-09-30)

Tokenizer version 3 retains a printed terminal apostrophe rather than indexing
only its bare preceding letters. The local and independent Hetzner rebuilds
each repaired 3,622 of 103,171 eligible passages and checked 50,819 affected
vocabulary keys. All 287,536 source records, normalized search text, FTS and
work metadata compared unchanged; existing embedding inputs were verified and
their manifest rebound without regenerating vectors.

The paired rollback is local `.benchmarks/corpus-before-qa7.sqlite` plus
`data/embeddings/manifest-before-qa7.json`, and host
`data/corpus-before-qa7.sqlite` plus that manifest filename. Restore the pair
with the previous qa6 image/container if rolling back the tokenizer.

The public read-only regression checks now require `κἄμμ’` to find its own
Brothers Poem occurrence and require bare `κἄμμ` exact-word search not to claim
that passage. The frontend also compares whole printed tokens for linked
commentary previews, so the original DCC note is discoverable without creating
new structured claims. See `docs/api-contract.md` for the conservative Greek
single-quotation boundary tradeoff.

### General maintenance

- Inspect: `docker stats --no-stream melos-api`, `docker logs --tail=50 melos-api`, and `python3 deploy/smoke_backend.py` from the service directory.
- Restart without changing data: `docker restart melos-api`. Stop only this service with `docker stop melos-api`.
- Rebuild: package a frozen local runtime with `scripts/package_runtime.py`, transfer it privately, verify with `deploy/verify_runtime.py`, build `deploy/Dockerfile`, and cache the pinned model with `deploy/cache_model.py` before starting offline. Do not package databases while a collector/indexer is writing them.
- `deploy/start_backend.sh` deliberately refuses to replace an existing container. Review the old image and mounts and arrange rollback before explicitly replacing it. Retain the previous verified runtime snapshot for data rollback; no automatic backup job has been configured.
- To restore conservative publication filtering, recreate only the Melos container without `MELOS_PUBLICATION_POLICY=source-labels`. Do not weaken source validation or the separate paid-classifier guard.
