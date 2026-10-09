# Corpus headword index and lemma features (releases O and P)

Every Greek word token of the corpus carries its ranked headword(s). The index is a
SQLite file (`data/lemma_index.sqlite`, env `MELOS_LEMMA_INDEX`) built as a batch job by
`scripts/build_lemma_index.py` (runner: `deploy/lemma_index_build.sh`); the read API is
`backend/lemma_index.py`, the HTTP routes `backend/lemma_routes.py`.

## How a token gets its headword

1. **Tokens.** `backend/lemma_tokens.py`: a run of Greek letters and marks, with brackets or
   underdots inside it and one final elision mark. Offsets are code points in the stored
   `passages.text`; the lookup spelling drops brackets/underdots (release N rule) and writes
   the elision mark as U+2019. Words printed with brackets or underdots are flagged.
2. **Parser.** Each distinct spelling is parsed once by local Morpheus (the release N build,
   run as a separate batch container). Forms of edited text that Morpheus does not know go
   through the release N generate-and-test spellings (dialect rules and elision completion;
   at most three rules, fifty spellings).
3. **Headwords.** Parser lemmas are read to dictionary headwords with the release M/N rules
   (exact headword, folded headword when unambiguous, elided lemma restored, lemma as a recorded
   form, Lesbian psilosis, dialect correspondences). Lemmas recorded for the spelling in the
   source annotations (treebank / lexicon form lists) are added; a printed form that is itself
   a headword (ἴψοι) counts as one.
4. **Ranking.** Candidate headwords of one spelling are scored by evidence (parser 1.0,
   recorded 1.0 more when it agrees with the parser, 0.6 alone, generated spelling 0.5,
   printed headword 0.8) times a corpus prior estimated by EM over token counts.
5. **Context.** For edited Greek text the contextual model (OdyCy, the reader's syntax
   model) was run once; its lemma (×4) and POS (×2 / ×0.5) rescore the candidates of each
   token. It never displaces the only recorded/headword reading unless it names that lemma
   itself (same rule as the release O parser fix for ἴψοι).
6. **Stored per token:** headword id, form id, confidence (0–255; the normalised score, not a
   calibrated probability), source bits (1 parser, 2 recorded form, 4 generated spelling,
   8 printed headword, 16 context agrees, 32 context changed the choice, 64 damaged word),
   start offset, length. Every spelling keeps up to six ranked readings (`form_lemma`).

## Scope and honesty rules

- Default scope of every endpoint: searchable edited Greek text (kind `text`, quality
  `source_text` or `machine_corrected_ocr`), as passage search. `include_reference=true`
  widens it to every indexed Greek record (OCR pages, scholia, apparatus).
- Dates are author biography claims from Wikidata (`data/metadata/chronology.json`,
  55 authors), never composition dates. Each date carries `approximate` and
  `crosses_period_boundary`; authors without a claim are reported as `undated` and never placed
  in a period. Genres are an editorial classification (`backend/author_catalogue.py`), labelled
  as such.
- Counts are top-ranked readings; `possible_additional_tokens` gives the upper bound of tokens
  whose spelling has the headword only as a lower-ranked reading.

## Endpoints

All take `include_reference` (bool). Headword choice: `q` (Greek headword or printed form, an
English word, or `lemma:ἔρως`) or `lemma_id`. Responses carry `resolution` (the readings of
`q`, first one used) so a client can offer the alternatives.

| Endpoint | Parameters | Returns |
|---|---|---|
| `GET /api/lemma/status` | – | index version, sizes, token coverage, method |
| `GET /api/lemma/resolve` | `q` | ranked headword readings (`via`: headword, headword_without_accents, printed_form_reading, english_dictionary_gloss) |
| `GET /api/lemma/search` | `q`/`lemma_id`, `author`, `genre`, `order` (frequency \| chronological), `limit`, `offset` | passages with any inflected form; `forms_found` facet with counts |
| `GET /api/lemma/frequency` | `q`/`lemma_id` | tokens, passages, rate per 10,000, rank, `by_author` (with date, genre), `by_genre`, `by_period` |
| `GET /api/lemma/distribution` | `q`/`lemma_id` | the `by_author` / `by_genre` / `by_period` tables only |
| `GET /api/lemma/concordance` | `q`/`lemma_id`, `author`, `genre`, `order` (chronological \| author), `width`, `limit`, `offset` | KWIC lines: `left`, `keyword`, `right`, `offset`, `confidence`, `source`, citation fields |
| `GET /api/lemma/collocations` | `q`/`lemma_id`, `window` (±1–20, default 5), `min_count` (default 3), `measure` (log_likelihood \| pmi), `author`, `genre` | collocates with count, expected, G², PMI, example passage |
| `GET /api/lemma/proximity` | `q` (2–6 words), `window` (extra words, 0 = phrase), `ordered`, `author`, `genre` | passages where the headwords occur within the window, with the matched span |
| `GET /api/concept/diachrony` | `q` (concept), `semantic`, `max_lemmas` | headwords expressing the concept; for each: counts and rate by period, by dated author, undated count, collocates per period, `semantic_support` |

Concept headwords come from dictionary glosses (English → Greek headwords whose glosses use the
words; `gloss_match`, `matched_terms`) or the headword index (Greek), plus up to five
`semantic_neighbourhood_and_shared_gloss_word` headwords: over-represented (log-likelihood,
≥ 3× expected, ≥ 5 occurrences) in the 1,000 Greek passages nearest the concept in the meaning
index and sharing a gloss word with the concept.

## Search fields added in release O (for the frontend)

`/api/search` (hybrid, themes) results now carry:

- `display_author` (merged canonical name), `display_work` (readable title of a collector slug:
  "theogonia" → "Theogony", "tlg0199-tlg001" → "Epinicians"), `author_genre`, `author_period`.
  The stored `author` and `work` labels are unchanged. `/api/passage` carries the same fields.
- `editions`: other editions of the same passage folded under the first-ranked copy (same
  author and language, at least half of the shorter text's words shared), each with `id`,
  `edition`, `source`, `citation`, `quality`, `work`; `edition_count` = 1 + len(editions).
- Hybrid responses add `query_lemmas`: the headwords used by the new headword signal
  (`retrieval_ranks.lemma` on each result says where it ranked in that list).

## Release P additions

### Contextual model on every Greek record

Release O ran OdyCy on edited Greek text only. Release P ran it on the other 176,037 Greek records as well
(scholia, commentary, apparatus, OCR pages; `build_lemma_index.py context --all-records`, five 3-CPU shards,
texts processed in length order so a batch is not padded to its longest page) and reassembled the index. Edited
text is unaffected (its predictions were already stored and the corpus prior does not use the model); for the
other records the model's lemma and POS now rescore ambiguous spellings exactly as for edited text. The model
was trained on edited literary Greek; on OCR pages with Latin apparatus and broken words its agreement is lower
(see the calibration by evidence class).

### Calibrated confidence

`scripts/calibrate_lemma_confidence.py`. Gold: PerseusDL Greek Dependency Treebank v1.6 tokens (already in the
lexica form lists) of the works that are stored as Perseus passages with line citations: Iliad, Odyssey, Theogony,
Shield, Sophocles and Aeschylus. Each gold token is aligned to the index token of the Perseus passage whose
range contains its line (folded forms, longest-common-subsequence alignment).

Leakage control: the index uses lemmas recorded for a spelling in the source annotations, which include these
treebanks. The evaluation index is assembled from the same staging data with every treebank token of the gold
works removed from the form lists (`filter-lexica`), so no gold token's own annotation supports its prediction.
The contextual model was trained on UD treebanks derived from the same texts, so the `context_agrees` and
`context_chose` classes are optimistic on this gold set.

Split: gold tokens are grouped in blocks (work, book, 25-line group); a fixed hash assigns each block to the
fitting half or the held-out half. Fit: isotonic regression (pool-adjacent-violators) of agreement with the gold
lemma on the raw 0–255 score, per evidence class (`damaged_word`, `generated_spelling`, `context_chose`,
`context_agrees`, `no_context_signal`) with at least 300 fitting tokens, else pooled. Correct = the predicted
headword equals the gold lemma after homograph digits, length marks, accents and breathings are removed;
treebank lemma conventions that differ from the dictionaries' headwords count as errors. The map is stored in
`data/lemma_calibration.json` and applied to the production index; `probability` is null without it.

### Variant groups, glosses, head meanings (assembly)

- `lemma_variant`: a dictionary entry of headword A that says it is a dialect/poetic form of headword B
  ("= B", "Ep./Ion./Dor./Aeol./Att./poet./Lesb./… for|of B") links A to B when both are corpus headwords. Both stay
  headwords; the API offers the group and `combine_variants`.
- Short gloss: within one dictionary the main entry is read first; an entry whose gloss is only a cross-reference
  ("= οὐδός") or a shorter homograph is read after the fuller one (ὁδός "way", not ὁδός (B) "threshold"). A headword
  with no gloss of its own shows its variant target's (πότνα → πότνια), labelled `gloss_via_variant`.
- Head meanings (`lemma_gloss_term` field 3, terms `=word`): each dictionary gloss is cut into sense phrases at
  ; , : and "or"; a phrase of one or two words gives its content words, a longer phrase only its first. Concept
  diachrony reads English through these whole words; search keeps the release O stems (fields 1–2), unchanged.

### Dates, genres, works

- A passage's date: its author's sourced claim; for a Greek Anthology epigram the claim of the poet its record
  names (`metadata.attributed_author`, 36 unambiguous poets mapped to Wikidata items); for CTS tlg0013 records
  filed as "Anonymous" the Homeric Hymns' item (no referenced claim: undated). `data/metadata/attributions.json`.
- Wikidata century and decade precision for CE dates is now read (release O read BCE ones only, which left
  Nonnus "5th century", Quintus, Musaeus undated); claim order birth → floruit → work period → death → inception.
- Genre: a source edition's own collection/work label first (`data/metadata/genre_sources.json`: the CGL anthology's
  sections ΜΕΛΙΚΟΙ ΠΟΙΗΤΕΣ / ΕΛΕΓΕΙΟΓΡΑΦΟΙ ΚΑΙ ΙΑΜΒΟΓΡΑΦΟΙ and their subsections, Greek Wikisource collection
  titles), deciding when one genre covers at least two thirds of the author's labelled records ("elegy and iambus"
  when only those two occur); then the author's Wikidata genre (P136) statements; else the editorial table
  (`genre_source: editorial`).
- Work order and collections: from the citation index (TLG work numbers). Chronological lists sort by author
  date, then work number, then position; a second collection of a TLG work that another collection holds in more
  cited passages is folded under the primary (concordance, proximity, collocations, n-grams).

### N-grams

`scripts/build_ngrams.py` → `data/ngrams.sqlite`: 2–4 consecutive top-ranked headwords inside one stored passage
(searchable edited text; a token without a headword breaks the sequence), per author, genre, period and the whole
corpus; one collection per TLG work; a passage repeated word for word within one work counted once. Minimum count
3 (author), 5 (genre, period), 10 (corpus). Statistic: Dunning G² of the last headword after its (n−1)-headword
prefix against its frequency in the group; positive associations only; top 400 per group and length;
function-word-only n-grams flagged and hidden by default.

## Release Q additions

### Elided words

`backend/elision.py`, model `data/elision_model.json` (`scripts/train_elision_model.py`), applied by
`build_lemma_index.py assemble --elision-model`. Rules and ranking: `docs/morphology.md` "Release Q". Source bit 128
(`elision_model`) marks a token whose reading the model ranked; its calibration class is `elision_model`. A genuine
second reading is stored per token in `token_alt(pid, i, lemma_id, prob)`; the spelling's `form_lemma` order is the
average of its tokens' readings.

Evaluation (held-out treebank half, 131,011 tokens; evaluation indexes assembled with the gold works' treebank
tokens removed from the form lists; the elision model trained on the other half only):

| | Release P | Release Q |
|---|---|---|
| All held-out tokens, agreement with the gold lemma | 95.7 % | 96.7 % |
| Elided tokens (13,095) | 88.2 % | 98.0 % |

τ’ → τε (was σύ in 292 of 663 held-out cases), ἀλλ’ → ἀλλά (375 errors → 0), ἔνθ’ → ἔνθα, θ’ → τε, ποτ’ → ποτέ,
αὖτ’ → αὖτε. Remaining elided errors are mostly genuine ambiguities (ὅτ’ ὅτε/ὅτι), which are kept as ties.

### Counting each text once

`LemmaIndex.count_mask`: frequency, distribution, concept diachrony and collocation background counts use one
collection of each TLG work (the collection holding most of its words inside the scope, so a collection outside
the scope never removes the in-scope copy) and count a passage repeated word for word within one collection and
work once (`passage_repeat` table, built at assembly). N-grams use the same rule. Searchable edited Greek:
1,386,111 → 1,067,763 counted words (293,066 in second collections of the same work, chiefly the Perseus and OGC
copies of Homer, Hesiod, Apollonius, Theocritus, Pindar, Callimachus; 25,282 in word-for-word repeats).

### Other

- Recorded lemmas must be a dictionary headword or a parser lemma: 612 annotation strings dropped, chiefly treebank
  placeholders written in Greek letters ("υνκνοων" = "unknown", "οτηερ" = "other") and malformed lemmas (τὁ, είμί).
- Calibration classes (`backend/lemma_calibration.py`): `context_disagrees` (token_flag bit 1: the contextual model
  named another reading of the spelling, not the same word under another lemmatisation convention such as
  μάλιστα / μάλα) and `recorded_form_no_context` split out of `no_context_signal`; lyric reliability is reported on a
  small gold set from LSJ entries that cite a Campbell poem and line (`data/evaluation/lyric-lemma-gold.json`,
  report only, never fitted).
- Variant links need agreeing meanings; "= B" must name the headword itself.
- N-gram phrases are indexed per headword (`ngram_lemma`: up to 40 per group, length and headword, minimum count 3
  in every group), so a headword's phrases are found beyond the group's top 400.
- English `q` is read through sense head meanings before stems.
- Display contexts drop printed line numbers (`line_numbers`).
- Dates: periods from the floruit, else the middle of the active life (never the birth year); the Homeric Hymns,
  Anacreontea and Semonides dated from Edmonds' *Lyra Graeca* pages in the corpus.
