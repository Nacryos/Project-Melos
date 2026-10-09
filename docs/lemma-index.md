# Corpus headword index and lemma features (release O)

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
