# Reader API (implementation contract)

Python FastAPI server at port 8791 serves static root and JSON APIs. SQLite index
is rebuilt from collector JSONL; raw/processed files remain authoritative.

- `GET /api/status`: `{passages, authors, author_labels, works, sources, languages, embeddings, evidence, classifier, warnings}`; the statistics `authors` count folds Unicode/case-equivalent labels, while `author_labels` counts raw distinct labels. The author chooser may merge further verified identities.
- `GET /api/authors`: `{authors:[{author,count,labels:[],identity_id?,merged}],method}`; `author` is the merged display name from `backend/author_aliases.json` (or an accepted identity profile), `labels` lists every exact source label folded into it. Labels naming several poets with ` / ` are separate entries. See [decisions](decisions.md).
- Search and listing results carry `mirror_count` and `mirrored_ids`: records with the same merged author, language, kind, quality label and words are shown once, with the collapsed copies' IDs listed. Totals count groups. `quality` may be `machine_corrected_ocr`, which is searched by default alongside `source_text`; `machine_ocr`, `mixed_content` and `needs_review` need `include_reference=true`. `/api/status` lists `searchable_qualities`.
- `GET /api/works?author=...`: `{works:[{id,author,work,edition,language,count}]}`
- `GET /api/passage?id=...`: full passage plus `previous_id`, `next_id`, `related`, `author_canonical` and `mirrors` (compact records of other indexed copies of exactly this text).
- `GET /api/passages?work_id=...&offset=0&limit=20`: `{results:[],total}`
- `GET /api/search?q=...&mode=words|forms|themes|hybrid&author=&language=&include_reference=false&offset=0&limit=30`: `{results:[passage + score + match_reason],total,mode,method,warnings}`. Lexical totals count all distinct filtered matches; theme totals count a fixed first-1,000 ranked-candidate pool. Hybrid uses bounded lexical/form/dense candidate pools and exposes `matched_evidence`; its total is not every potentially relevant corpus passage. `commentary_assisted=false` restricts hybrid to direct Greek-text evidence.
- `GET /api/word?form=...&passage_id=...`: generic lexical candidates and occurrences plus `structured_evidence`, `contextual_candidates:[]`, `context_analysis_status` and `author_profile`. Source-linked claims and model judgements are separate; missing morphology or senses are not filled from memory.
- `GET /api/evidence?form=&passage_id=&claim_id=&limit=20`: source claims at their declared scope, with exact quotations and locators. Large paradigms are compacted for lookup; `GET /api/claim?id=...` returns the full source claim.
- `POST /api/machine-analysis`: JSON `{form,passage_id?}` explicitly requests computational morphology for one intact Greek word (at most 80 characters). An optional `passage_id` must exist but does not make an engine analysis an annotation of that passage. The response has `status`, `form`, complete `machine_candidates` and `machine_entries`, `warnings`, and a raw-response `receipt` when one was stored. Candidates preserve separate literal dictionary and inflection fields, alternatives, and raw JSON pointers; they are not accepted source claims, attested forms, dictionary senses, or contextual decisions. This route does not call Jev or alter corpus/evidence indexes.
- `POST /api/classify-context`: JSON `{form,passage_id}` defaults to the unchanged source-candidate comparison and returns `status=proposed|abstained`, `decision_stage`, an existing `candidate_id` if selected, source evidence IDs, inspectable packet and raw uncalibrated provider signals. An explicit `{candidate_basis:"machine",machine_receipt_id}` instead uses only a server-reloaded, rehashed and reparsed cached machine receipt for the exact form; client-supplied candidates, URLs or proof flags are not accepted. A selected machine option returns `status=machine_proposed`, `candidate_basis=machine`, `machine_evidence` (receipt and raw entry/inflection pointers), and no source `evidence_ids`. Source-claim and incomplete-source preflight guards remain in force. Supplying a receipt on the source path, or omitting one on the machine path, returns 422. Jev is server-side and never changes corpus evidence. Public deployments require the explicit `MELOS_PUBLIC_CLASSIFIER=1` opt-in and use the durable quota/cache gateway described in `docs/deployment.md`; preflight rejection makes no provider request.
- `GET /api/wiktionary?form=...`: independently gated `{ready,query,results,total,warnings}` reference lookup. Entry, sense, and listed-form tags retain their separate scopes; listed forms do not assert corpus attestation or unattestation.
- `GET /api/usage-space?q=...&author=&limit=80`: `{points:[{id,x,y,z,text,author,work,citation,source_url,date_start,date_end,match_reason}],method,retrieval_method,warnings}`. Coordinates derive from actual passage features and are not historical facts. Any thematic fallback is disclosed and need not contain the queried word.
- `GET /api/sources`: collection reports and counts.

Machine analysis is a separate, explicitly clicked service request, not a
background fallback for an unmatched word. Its receipt records the exact NFC
form, fixed upstream request URL, HTTP status, receipt time, raw SHA-256 and
parser version. `engine_revision` is null when the hosted service does not
supply it; no engine or stem-library revision is inferred. Cached raw bytes are
rechecked and parsed again before machine candidates can enter a Jev packet.
The cache is bounded (default 64 MiB and 10,000 receipts), with a 256 KiB
response limit, eight-second request timeout, at most two in-flight misses,
and durable default limits of 200 global/20 per visitor per day and 10
global/3 per visitor per minute. A signed visitor cookie supports convenience
throttling, not authentication; the global limit remains authoritative across
cookie resets. Failed requests have a five-minute backoff and no automatic
retry. Invalid forms or receipts return 422; busy requests 409, rate limits
429, disabled/full cache 503, and upstream or invalid-response failures 502.
The explicit lookup requires JSON with a body of at most 2,048 bytes (415 for
another media type, 413 for a missing or oversized declared length).
No error silently supplies a guessed analysis. These operational bounds and
machine labels are not claims of morphological accuracy or complete coverage.
The frontend groups only exact displayed headword, full feature object and
dictionary-field matches. Every original candidate ID and raw inflection
remains available in the disclosure and in the complete Jev inventory; a
shared display is not an assertion that the underlying analyses are identical.

All query values URL-encoded. Passage IDs opaque. `work_id` is a stable hash of
source, author, work, edition, language. Text stays original; HTML is escaped in
reader. Theme search may use translations/commentary as retrieval bridges but
must disclose which text was indexed and must not label that as Greek semantic
understanding. Return missing capability plainly, never fake successful results.
An author filter matches case/Unicode-equivalent labels and independently
accepted source-backed identity aliases, plus
commentary explicitly linked to that author's text by `parent_id` or by a
page-scoped or `source_section` note sharing a source URL within the same collection. A linked
commentary result retains its modern `author` and adds `author_scope_reason`.
This page association is not a `parent_id` or an occurrence-level alignment;
hybrid retrieval does not project such notes onto a guessed poem.

Source metadata may preserve `source_page_title`, `source_heading`,
`source_section`, and `source_subtitle`. Separate source-labelled columns are
returned as separate records, with exact-reference coverage `section_text`,
not whole-fragment scope. `source_citation_aliases` are explicit same-page
body/sidebar heading links, with raw labels and locators; they do not establish
global Greek/Latin suffix equivalence or a numbering concordance.
Edition-qualified primary headings retain their parenthetical notes, but the
reference resolver does not mine those notes for assumed edition identities.

`source_footnote_links` preserves extracted marker/link information and plain
`description` where supplied. The reader displays descriptions as text and
resolves links against the source URL; it never renders `title_html` or turns
an array `line_index` into a verse citation. Duplicate UI line labels are
suppressed only when an identical explicit printed prefix remains in the
unchanged line text.

### Printed word boundaries

Derived occurrence tokens retain combining marks and a single attached terminal
apostrophe. The recognized apostrophe glyphs `'`, `’`, `᾽`, and `ʼ` share a folded
lookup key; the original glyph remains in the source and displayed token. No
missing ending is supplied. Internal apostrophes do not split a word, whereas
repeated signs form a boundary after the first attached sign.

Greek exact-word searches and contextual occurrence checks distinguish a form
with a terminal apostrophe from the same letters without it. Greek paired
single quotes are consequently conservative/literal: bare `α` does not exactly
match `'α'`, while `α'` does. The system cannot infer whether an attached mark is
quotation punctuation or elision. English/Latin description searches retain
their previous ordinary quotation-boundary behavior.

Reader commentary previews compare literal complete Greek tokens with folded
accents, sigma and the four apostrophe glyphs. They preserve the source excerpt
and do not join words over gaps or infer a parse. Explicit printed line-end
divisions are joined only for passage-word lookup, with source text unchanged.

Spacing psili (`᾿`, U+1FBF) is a separate retained printed sign. It is not folded
to an ordinary apostrophe: copying `κἄμμ᾿` from Sappho 27 preserves that spelling
in word lookup, contextual checks, commentary matching and exact search. This
does not identify the editorial function of every spacing breathing sign.

Latin-letter queries retain apostrophes in both romanization and Beta Code
paths. A Greek-block punctuation character alone does not make a query Greek
script. Unsupported punctuation/digits separate query words instead of silently
joining their letters. The partial Beta decoder strips the supported accent,
breathing, case, iota-subscript, diaeresis and underdot syntax only; it is not a
full Beta Code document importer. Character handling was checked against the
[TLG Quick Reference, pp. 3–4](https://stephanus.tlg.uci.edu/encoding/quickbeta.pdf).

Persistent evidence and Wiktionary indexes declare a lookup-normalization
version. A version mismatch fails closed until their derivative lookup keys
are rebuilt or repaired against unchanged, independently accepted source data.
Corpus-token, evidence-key, and dictionary-key repairs must be deployed as a
coordinated snapshot with the corresponding backend code.

Word lookup exposes `observed_form_groups`, not a pooled paradigm for every
spelling suggestion. Inventories retain source lemma identity, homograph
markers, source references, query-match relationship, and explicit truncation
counts. They are source annotations across the index, not attestations in the
selected author or an adjudication of that occurrence. The reader does not
fall back to an unscoped `attested_forms` list from an older backend.
Inventory source references retain their recorded token locators, including
verbatim CTS citations where supplied and document/sentence/token IDs. Several
tokens in one source file remain distinct after morphological-reading
deduplication. Locator totals and preview limits are explicit; absent citations
are not reconstructed from sentence metadata or model knowledge.

Latin-script multiword fallback keeps original query terms and may supplement
them with indexed Greek spelling alternatives. `fallback_terms` records
`original`, `transliterated`, original-word `groups`, `covered_words`,
`substantial_words`, and `exact_anchors`. Eligible lexical results expose
`query_term_coverage`; alternatives within a group count once. Coverage ranks
before BM25, after chronological ordering if requested, over all filtered
lexical candidates before pagination. Hybrid responses nest this provenance
under `fallback_terms.lexical` and/or `.forms`. These are retrieval mechanics,
not calibrated language, morphology, or sense confidence.

Reader developer owns `reader.html`, `js/reader.js`, `css/reader.css`; visualization
developer owns `js/usage-space.js` and exposes `window.MelosUsageSpace.open(query,
author)` plus `close()`. Main owns server, database and integration. Morphology
developer owns `backend/morphology.py` and communicates callable contract. Encoder
developer owns `backend/semantic.py` and `scripts/build_embeddings.py`; coordinate
input schema and index paths with main before launching encoding.

## POST /api/words/headlines (release O)

Headline data for every word of a passage in one call, for prefetching in the reader. Read from
the corpus headword index (`docs/lemma-index.md`); no parser or model runs per request, so a
warm call takes a few milliseconds (measured 2–3 ms for Anacreon 348 on the box; the first call
after start-up also opens the index).

Request (JSON): `{"passage_id": "campbell-glp:anacreon:348"}` or `{"forms": ["σ’", "ἐλαφηβόλε", ...]}`
(at most 400 forms; forms without a passage give context-free readings). `GET
/api/words/headlines?passage_id=...` returns the same payload for caching proxies.

Response headers: `ETag` (= `hash`) and `Cache-Control: public, max-age=3600`.

```
{passage_id, index_version, index_built_at, hash, method,
 tokens: [{i, start, end, printed, form, form_status,
           lemma, lemma_id, gloss, gloss_source, pos, parses: [...], confidence, basis: [...],
           alternatives: [{lemma, lemma_id, gloss, form_probability, parses: [...]}], tie}]}
```

- One entry per Greek word token of the stored passage text, in order. `start`/`end` are code
  points in `/api/passage` `text` (the same text the reader renders); `printed` is that slice
  (brackets and underdots included), `form` the lookup spelling (brackets/underdots removed,
  elision as U+2019).
- `lemma` is the headline headword (always given when any reading exists, also for ties);
  `parses` are the parser's compact parses of this spelling for that headword (for example
  `["acc. 2nd sg."]`), possibly several when the spelling is ambiguous; a parse from a generated
  dialect/elision spelling says `(from <spelling>)`.
- `alternatives` lists every other reading of the spelling with its own parses and its
  spelling-level probability; `tie` is true when the second reading scores at least 0.8 of the
  first. A tie is never returned as "no headword".
- `confidence` is the normalised evidence score of the headline for this token (0–1, not a
  calibrated probability); `basis` names the evidence (`parser`, `recorded_form`,
  `generated_spelling`, `printed_headword`, `context_agrees`, `context_chose`, `damaged_word`).
- `form_status`: `parsed`, `generated`, `recorded`, `headword` or `unknown` (no reading:
  `lemma` null, `alternatives` empty).
- `hash` changes when the index is rebuilt or the passage text changes; cache on it.
- 404 when the passage is not in the index (not Greek, or unknown id); 503 when the index is not
  deployed. `/api/word` remains the full, contextual analysis of a clicked word.

## /api/word (release O)

`GET /api/word?form=...&passage_id=...&lemma=...`. All earlier fields are unchanged; release O
adds the headline headword so no second request is needed (rules: `docs/morphology.md`,
"Release O parser fixes").

- `headline_lemma`: one headword, never null when any exact-form candidate exists (null only
  when there is none). With `lemma=` it is that lemma.
- `headline_basis`: `caller_lemma`, `passage_source_analysis`, `recorded_analysis_of_form`,
  `dictionary_reading_of_printed_form` (the printed form is a dictionary headword: its reading,
  e.g. ἴψοι → ὑψοῦ), `parser_analysis`, `dictionary_headword_of_form`, `most_supported_reading`,
  or for a tie `tie_broken_by_frequency_prior` / `tie_broken_by_evidence_count` /
  `tie_broken_by_listing_order`.
- `headline_tie_broken`: true when several headwords tied (same evidence weight, at least half
  the best row count) and one was chosen; the others are not hidden.
- `headline_alternatives`: the other headwords, ranked (strings).
- `headline_evidence`: labels such as `elided_before_vowel`, `elided`,
  `printed_form_is_dictionary_headword`, `capitalised_printed_form_proper_headword`.
- `alternatives`: every ranked headword, headline first: `{lemma, rank, headline, readings:
  [{restored_form, parse}], weight, rows, attested_forms}`. For an elided word the readings are
  the spellings with the elided vowel or diphthong restored (α ε ι ο αι οι, plain or acute;
  nothing else is generated) that the parser analyses as that headword: σ’ → σύ {σε/σέ acc.
  2nd sg., σοι dat.}, σός {σέ voc. masc. sg., σά nom./acc. neut. pl., …}. Otherwise the readings
  are the parser parses of the printed form (`restored_form` null).
- `lookup_mode`: `form_analysis` (the full lookup) or `lemma_dictionary_fast_path`.

**`lemma=` fast path.** When `lemma` is given and `form` is that same headword (the reader's
dictionary lookup of a headline headword: `form=<lemma>&lemma=<lemma>`), the response is built
from the dictionary alone (the headword's entries, plus the same letters with the other initial
case, e.g. νύμφη / Νύμφη) without the form analysis (occurrences, source claims, parallel texts,
parser): ~10 ms instead of a full lookup. Every top-level field of the full response is present
(empty lists / null / `not_requested`), `lexicon_entries` carries the entries, `selected_lemma`
and `headline_lemma` are the lemma. With a different `form` (the clicked word plus the passage
headline as `lemma=`) the full analysis runs as before and `lemma` only leads the headline,
entries and candidates.

## Citations (release P)

Citation index: `data/citation_index.sqlite` (env `MELOS_CITATION_INDEX`), built by
`scripts/build_citation_index.py` from the corpus. Code: `backend/citations.py`, routes `backend/citation_routes.py`.

- `GET /api/cite?q=...&include_reference=false&limit=20` resolves a citation:
  - line/book citations with conventional (LSJ/OCD) author and work abbreviations or names: `Il. 1.1`,
    `Hom. Il. 6.146`, `Hes. Th. 116`, `Pind. O. 1.1`, `Pi. P. 8.95`, `A.R. 1.1`, `Nonn. D. 1.1`, `Q.S. 1.1`,
    `AP 7.1`, `Bacchylides 3.1`; any other title abbreviation is matched against the author's stored titles
    (`Eur. Med. 1` → Medea; several matches → a warning, no guess);
  - CTS URNs `urn:cts:greekLit:tlg0012.tlg001[.edition][:1.1[-1.5]]` (a URN naming an edition lists that
    edition first; a URN without a passage returns the work's `first_passage`);
  - fragments `Sappho fr. 31`, `Sappho 31`, `Sapph. fr. 31 V`, `Alc. 130b`, `Sappho fr. 168A LP`: the release O
    exact-reference lookup (only explicit recorded citations; numbering edition-specific) plus `equivalents`.

  Response: `{query, parsed{kind: locus|urn|fragment, author, work, work_prefix, locus, locus_end, scheme,
  tlg_author, tlg_work, edition}, results[], total, warnings[], method}`. Locus results:
  `{id, author, work, citation, source, edition, kind, quality, locus_start, locus_end, contains_locus, tlg,
  text_preview, language}`: every collection whose printed range contains the locus, edited text first.
  Fragment results are the release O reference records; `equivalents[]` =
  `{scheme, number, from_scheme, record, evidence, results[]}` only where one record prints both numbers
  ("178 Campbell ( = Voigt, and Lobel & Page 168A)"); no concordance is inferred. A query that is not
  citation-shaped returns `parsed: null`.
- `GET /api/cite/catalogue?author=` lists every work group with its TLG author/work number and the source of
  that number: `record_urn` (the record's CTS URN), `ogc_readme`, `cts_catalogue` (PerseusDL canonical-greekLit /
  First1KGreek `__cts__.xml`, rule `title`, `title_stem` or `edition_only`), `text_match` (≥ 60% of at least 15
  sampled verse lines found in Perseus records carrying the URN); `authors` maps each author to TLG author
  numbers. Nothing comes from the TLG website.
- `GET /api/cite/status`: index version, works, loci, mapped works, equivalences.
- `/api/search` (any mode): a line/book citation or URN (without an author filter) returns `mode: "citation"`
  with the cited passages as ordinary result records (`match_reason`, `citation_match{locus_start, locus_end,
  contains_locus, tlg}`, `citation` = the parsed citation). An abbreviated fragment citation is rewritten to the
  release O reference syntax (`Sapph. fr. 31 V` → `Sappho fr. 31 Voigt`) and answered by the reference lookup
  (`mode: "reference"`). A word with digits (`a123b`) is not a citation: a space or full stop must precede the locus.

## Headword index additions (release P)

- **Calibrated probability.** `probability` beside `confidence` on `/api/words/headlines` tokens and
  `/api/lemma/concordance` lines: the raw score mapped through isotonic regression fitted on treebank gold
  lemmas (`data/lemma_calibration.json`, env `MELOS_LEMMA_CALIBRATION`; method in `docs/lemma-index.md`). Null
  when no calibration is deployed. `/api/lemma/status` → `calibration` (method, classes, fit counts).
- **Headline dictionaries.** `POST /api/words/headlines` with `{"passage_id": ..., "dictionary": true}` (or GET
  `&dictionary=true`) adds `dictionaries: {lemma: {id, lemma, dictionary, gloss, senses[{label, text}] (first
  three, source order), sense_count, entry_url, license} | null}`: the first dictionary (site order) with a gloss
  or senses, for every headline lemma. The `hash`/ETag differs from the plain payload. Cold 0.2–0.7 s for a poem
  of 30–90 headwords, then cached (~10 ms).
- **Compact dictionary lookup.** `/api/word?form=L&lemma=L&compact=true[&senses=6]`: the lemma fast path with
  each entry reduced to `{id, lemma, dictionary, source, gloss, senses (first N), sense_count, entry_excerpt (400
  characters), entry_url, license, attribution}`; `lookup_mode: "lemma_dictionary_compact"` (φαίνω 439 KB → 6.6 KB
  uncompressed).
- **`/api/lemma/search`** results add `excerpt{left, keyword, right, offset}` (first occurrence) and
  `match_offsets[[start, end], …]` (up to 20; code points in `/api/passage` text). `order=chronological` uses the
  work order below.
- **Concordance** (`/api/lemma/concordance`): `period=<label>` or `undated=true`; `fold_editions` (default true):
  a second collection of a TLG work that another collection holds in more cited passages (Perseus 20-line chunks
  beside OGC lines) is not listed again: its overlapping passages become the line's `editions[{id, source,
  citation, quality, work, display_work}]`; among unnumbered texts (fragments) a line with the same headwords
  around the keyword in another collection is folded the same way; a formula repeated within one collection
  stays. `edition_count`, `folded_other_collections`. Chronological order = author date, then work order (TLG
  work number where known, else after), then the passage's place in its collection (Iliad before the Epigrams).
- **Proximity** (`/api/lemma/proximity`): `cross_passages=true` lets a match run on into the following stored
  passages of the same collection when their line numbers continue (same book; fragments never continue);
  such results carry `crosses_passages: true`, `match_passages[]`, `match_end_passage`, and `match_text` joins the
  pieces with " / ". Editions are folded as in the concordance (`editions`, `edition_count`,
  `folded_other_collections`).
- **Rates.** Every `by_author` / `by_genre` / `by_period` row and every diachrony period adds `per_10k_ci95`
  (95% Wilson interval) and `small_sample` (group under 50,000 words).
- **Variant groups.** `variant_group{lemma_ids, members[{lemma_id, lemma, gloss, tokens_all_records, links[{lemma_id,
  lemma, direction variant_of|has_variant, relation, dictionary, evidence}]}], note}` on `/api/lemma/frequency`,
  `/api/lemma/resolve` (first three readings) and diachrony lemmas; `GET /api/lemma/variants?q=`. Links come from
  the dictionaries ("ἔρος … poet. for ἔρως", "πότνα = πότνια"); the headwords stay separate.
  `combine_variants=true` on search, frequency, distribution, concordance, proximity and diachrony counts the
  group together. A headword without its own gloss shows its variant target's (`gloss_via_variant`).
- **Collocations** count an identical context repeated within one work once (`repeated_contexts_skipped`) and
  read one collection of each text.
- **N-grams.** `GET /api/lemma/ngrams?kind=author|genre|period|corpus&name=...&n=0|2|3|4&q=&include_function_words=false&limit=30`
  → `{group{kind, name, passages, tokens}, ngrams[{n, lemmas[], lemma_ids[], count, expected, g2, per_10k,
  function_only, example_passage}], statistic, scope, min_count}`; `q` keeps n-grams containing that headword.
  `GET /api/lemma/ngrams/groups` lists the groups. Built by `scripts/build_ngrams.py` (`data/ngrams.sqlite`, env
  `MELOS_NGRAM_INDEX`).
- **Concept diachrony v2** (`/api/concept/diachrony`): English concepts are read through dictionary sense head
  meanings (`resolution_rule: head_meaning`, fallback `gloss_terms`); `matched_words` are whole words;
  `concept_score` weights the gloss match by enrichment in the meaning index's nearest passages
  (`semantic_support.enrichment`); weak dictionary-only readings without semantic support are listed in
  `dropped_without_semantic_support`. Each `by_period` entry (now including `undated`) has collocates (≥ 2
  co-occurrences) and `examples[]` (one KWIC line from each of the three authors using the headword most there).
- **Dates and genres on records.** `author_period` and lemma records use the passage's date: the author's claim,
  or for a Greek Anthology epigram its attributed poet's (`attributed_date` on lemma records), or for CTS tlg0013
  records filed as "Anonymous" the Homeric Hymns' (undated in Wikidata). Author records add `genre_source`
  (`source_edition_label` | `wikidata_p136` | `editorial`) and `genre_labels[]`.

## Release Q additions

- **Elided words** (`/api/words/headlines`, index built with `data/elision_model.json`). A token whose reading the
  elision model ranked carries `basis` containing `elision_model`. When its second reading is genuinely possible
  here (at least half as probable as the first, and not the same word in another case), the token has
  `tie: true`, `tie_basis: "elision_model"` and `tie_alternative{lemma, lemma_id, gloss, token_probability}`, and
  that reading is first in `alternatives`. The headline is still given; both readings should be shown.
  Other tokens keep the release O spelling-level `tie`.
- **Frequency tables count each text once.** `/api/lemma/frequency`, `/api/lemma/distribution`,
  `/api/concept/diachrony` (counts, rates, period and author totals) and the background frequencies of
  collocations count one collection of each TLG work (the collection holding most of the work's words inside
  the scope) and a passage repeated word for word within one work once; n-grams use the same rule.
  `counting_note` on frequency responses says so. `scope_tokens` is the counted total (searchable edited Greek:
  1,067,763 words, was 1,386,111). Search, concordance and proximity are unchanged (they fold editions).
  `tokens_all_records` on headword briefs is unchanged (every record).
- **Fragment numbering** (`/api/cite`). A fragment number in a named numbering, written after the number
  (`V`, `Voigt`, `L-P`, `LP`, `L.P.`, `C.`, `Campbell`) or before it (`Sappho Campbell 16`, `Alc. Lobel & Page 346`),
  returns the records citable by that number in that numbering, then those citable by an equal number in another
  numbering. Each result adds `numbering{author, scheme, number, strength (query | printed | source | convention),
  basis, basis_text, evidence, equivalence[]}`; `equivalents[]` add `strength`, `evidence[]` (the printed record or
  the cited source with its quotation) and `passage_ids`. `convention` = only a source's general statement that two
  numberings agree (Voigt follows Lobel-Page "with minor variations"), labelled with a warning. A number without a
  poet that several poets share returns all of them with a warning. Data: `data/fragment_concordance.json`.
- **Dates.** The Homeric Hymns (750–550 BC?), the Anacreontea (150 BC – AD 550) and Semonides (650 BC, approximate)
  are dated from Edmonds' *Lyra Graeca* pages stored in the corpus (passage id and quotation in
  `chronology.json`, `basis` names the edition); Orphica stays undated.
- **English headword lookup** (`/api/lemma/resolve` and every lemma endpoint's `q`, hence the lexicon/lemma
  page): an English word is read through dictionary sense head meanings first: readings with
  `via: "english_dictionary_head_meaning"` (a sense whose head phrase is the word, whole words, singular: "the
  moon" → σελήνη, μήνη; not Ἰώ "identified with the moon" or Οὐρανία), `matched_terms`, `gloss_match` (relative
  to the best); only when no sense has the word as its head meaning does the release O stem match answer
  (`via: "english_dictionary_gloss"`). A Latin-letter word that spells a Greek headword stays first
  (`transliterated_headword`). Hybrid search keeps the release O stems.
- **Phrases by headword** (`/api/lemma/ngrams?q=`): with `q`, phrases are read from a per-headword table (up to 40
  per group, length and headword, from every n-gram that passes the group's minimum count and association), no
  longer only from the group's top 400; the whole-corpus list for σελήνη or ἔρως is no longer empty. Every author
  with at least 50 counted words has a list (the Greek Anthology included: its in-scope collection is counted).
- **Variant groups** name every headword counted with them: capitalisation variants (ἔρως / Ἔρως) are members with
  a `capitalisation_of` link. Concept diachrony with `combine_variants=true` returns one row per group (the
  first-ranked member) with `counted_lemma_ids` and `counted_lemmas`; other members are not repeated with the
  group total. Links need the two headwords' meanings to agree and a "= B" to name the headword itself
  (ἅλιος "fruitless" is no longer a Doric ἥλιος; Δίιος is not "= Ζεύς"; κοῦρος "loppings" not κόρος).
- **Line numbers.** `left` / `right` / `match_text` of concordance lines, search excerpts, proximity results and
  diachrony examples no longer contain an edition's printed line numbers (a number standing alone between words);
  they are returned as `line_numbers` (strings, in text order).
- **Headwords.** A lemma recorded for a spelling in a source annotation is kept only when it is a dictionary
  headword or a lemma the parser gives somewhere (removes "οτηερ", a treebank placeholder).

## Release R additions

`/api/analyze-passage` interlinear word rows (all optional; present when they apply):

| Field | Meaning |
|---|---|
| `passage_dialect` | `lesbian`, `doric` or `boeotian` (`backend/passage_dialect.py`). |
| `dialect_rules` | Readings a dialect or orthography gate removed: `[{rule, lemma, parse_short}]` (`iota_subscript`, `accented_proclitic`, `dialect_label`, `elision_vowel`, `aeolic_infinitive_in_en`, `prohibitive_me`, `article_head`, `lesbian_accusative_plural_in_ais`, `dual`, `psilosis_fallback_only`). |
| `derived_from` | `{headword, base, relation, printed, entry_id, source}`: the row is shown under the base of a derived form (ταχέως → ταχύς). |
| `variant_of` | `{headword, relation, entry_id}`: a dialect pointer headword shown as its target (πώνω → πίνω). |
| `lemma_read_as` | `{parse_lemma, headword[, rule]}`: a parse lemma shown as the headword it reads to (ὀ → ὁ, δᾶμος → δῆμος, Lesbian ἄρμα → ἅρμα). |
| `form` | For a word divided at a line end, the whole word (also `hyphenated_word`, `hyphen_part: first/second` on the token). |

`morphology_ranking` items may carry `lemma_as_parsed` (the parser's own lemma when the item is shown under a
linked headword). Parses state `Degree` (`comp.`, `sup.`).

`/api/words/headlines`: `probability` uses the passage's calibration group (genre and dialect);
`/api/lemma/status` → `calibration.groups` lists the fitted groups. `/api/lemma/resolve` answers an alias headword
with `via: alias_<relation>`. The index has a table `lemma_alias(alias, lemma_id, relation, entry_id)` and
token_flag bit 2 (`dialect_rule` calibration class).

## Release S additions

- `/api/search?mode=hybrid`: fused lists and weights per query class come from `backend/search_stack_weights.json`
  (see `docs/retrieval.md`, "Release S"). Results carry the new list names in `retrieval_ranks` and
  `matched_evidence` (`keyword`, `headword`, `dense_bge-m3_grc|eng|comm`, `dense_shlm_grc|eng|comm`, `notes`); the
  response adds `stack.seconds` (time per list) and `stack.keyword_variants` / `stack.headwords` when used.
  `MELOS_SEARCH_STACK=0` restores release R's fusion.
- `GET /api/commentary/status`: commentary sources (title, author, year, licence, repository, note and passage
  counts) and the display rule.
- `GET /api/commentary/notes?passage_id=…&limit=20`: notes linked to a passage: `source`, `author`, `year`,
  `locator`, `page`, `url`, `licence`, `citation`, `display` (`full` for public domain, else `quotation`) and
  `text` (at most 30 words unless public domain).
