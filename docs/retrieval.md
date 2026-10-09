# Hybrid passage retrieval

`backend.retrieval.fuse` combines three independently ranked candidate lists:
word/citation matches, source-backed form matches, and local dense matches. The
caller bounds and retrieves each list, passes corpus records through
`fetch_record(id)`, and applies `limit`/`offset` to the grouped results. The
function has no model dependency and never writes to the corpus.

```python
fuse(query, lexical, forms, semantic, fetch_record,
     author="", author_labels=None, language="", edition="",
     include_reference=False, limit=30, offset=0,
     commentary_assisted=True)
```

Each list contains records or lightweight hits with an `id`, ordered best first.
The dense list may carry its original cosine `score`; lexical lists may carry
FTS scores. Fusion uses reciprocal rank fusion (RRF, `1 / (60 + rank)` per
signal), not a sum of incomparable raw scores. A passage receives at most one
vote per list, including when multiple linked notes or mirrored copies match.
The returned `score` is only a ranking value within the retrieved pool. A
bounded pool's `total` is not a whole-corpus recall estimate or an influence
probability.

Linked translation and commentary hits project to a Greek `text` parent only
through their explicit `parent_id`. The match remains in `matched_evidence`,
which includes the matched record ID, signal, kind, language, author, edition,
citation, source URL, parent ID, original reason, and raw score. The displayed
parent retains its own author and source fields. Unlinked notes stay separate;
a page-level association without an explicit parent is not promoted by this
module. A direct Greek hit and two English supporting hits can therefore form
one result, with `retrieval_ranks` showing one vote for each contributing list.
The `match_reason` names contributing signals and discloses linked support.

`commentary_assisted=False` accepts only Greek `text` candidates. This is a
strict Greek-only comparison, even if English records appear in an input list.
In assisted retrieval, a requested language or edition is checked against the
*returned* passage after projection. If the parent does not meet the filter,
the original supporting record may still appear when it meets the filter.
Author filtering accepts the exact label or explicit `author_labels` supplied
by a separate, source-verified alias service; the fusion code invents no
author identities. All modes exclude `machine_ocr`, `mixed_content`, and
`needs_review` records. Reference and apparatus records require
`include_reference=True`.

Copies collapse when merged author, language, record kind, quality label and
actual words agree, whatever their edition labels (owner decision 2026-09-30, see
[decisions](decisions.md)). Aggregator mirrors of a Perseus or DCC text and
distinct editions printing identical words therefore form one result, whose
`mirrored_ids` and `mirror_count` list the collapsed copies; `matched_evidence`
keeps every contributing hit. Records whose words differ are never merged.
Author matching uses the alias table's canonical keys, so a filter for one
poet reaches every spelling of that poet and any joint attribution naming them.

For integration, retrieve a fixed candidate pool separately for each signal,
then call `fuse` once before paginating. Fetching a supporting record's parent
must use the same accepted corpus index as the hits. Report pool sizes and
unavailable signals in the API's warnings. A missing dense index can yield a
word/form result, but its absence should be disclosed. A Greek word query can
use source-backed form expansion; an English description should rely on word
and dense candidates unless an independently sourced form analysis exists.

The regression fixtures in `tests/test_retrieval.py` are synthetic and never
become historical passages. Source-derived retrieval evaluation should report
Greek-only and commentary-assisted results separately and count same-edition
mirrors once. The current RRF constant and candidate pool sizes are baseline
choices, not tuned performance claims. A learned hierarchy would require
demonstrated gains on held-out, source-traceable judgments before replacing
this inspectable baseline.

## Latin-script Greek fallback

`backend.query_expansion.fallback_tokens(query, normalized_variants, vocabulary)`
accepts the existing morphology converter's folded variants and a collection
of `vocabulary.normalized` terms from the accepted corpus index. It returns at
most 16 indexed Greek terms for a likely multiword transliteration. The terms
can be added to a bounded FTS fallback when literal query variants miss. They
never replace the original query's native-script terms.

The existing [ALA-LC-inspired input converter](morphology.md) deliberately accepts plain Latin
`o` and `e`, which can stand for either ο/ω or ε/η. The fallback considers one
of those substitutions near a word ending only when the resulting Greek token
is already indexed. Expansion requires at least two distinct exact vocabulary
anchors and indexed support for at least 80% of the substantial query words.
This is a conservative retrieval heuristic, not a calibrated language detector:
two accidental matches from an English description must not redirect its entire
lexical search into Greek. Short or Greek-letter queries do not use this
multiword Latin fallback. Printed terminal signs remain part of their tokens.
When every substantial token already matches, it leaves the terms exact.
Each original word must convert to exactly one token; a dropped word and a
split word cannot cancel each other to manufacture coverage. Accepted native
and Greek alternatives are grouped by their original word. Lexical results
rank by the number of these groups matched, then BM25, over the full filtered
FTS result set before pagination. Several alternatives for one word count
once. Chronological ordering still takes precedence when requested.
The API discloses the groups and per-result coverage; hybrid search retains
the fallback provenance under its contributing channel. These counts are not
confidence scores or evidence of an occurrence-specific interpretation.
These are lossy spelling suggestions, never inflections, translations, or
claims that a Greek word belongs to a particular author. A result still needs
its actual passage text and source record as evidence.

The six frozen transliteration evaluation queries each produced terms present
in their judged passage in a read-only vocabulary check. This demonstrates
candidate reachability only; ranking must be measured again after server
integration without rewriting the frozen baseline report.

## English queries: bridges (2026-09-30)

`scripts/lab_build_eval.py` builds judged queries from the index's own
translation and commentary links (an English record names its Greek parent),
and `scripts/lab_eval.py` scores search variants on them in-process, excluding
the query's own record from every pool. On 195 such queries over the live
index, Greek-vector similarity alone found the judged passage for an English
query with Recall@10 0.11; the hybrid reached 0.385; adding a BM25 pass over
linked English records 0.415. Cross-encoder reranking (a small multilingual
model and BGE-reranker-v2-m3) lowered recall and the large model costs about
1.3 s per pair on CPU, so no reranker is used. Greek phrase, accentless and
transliterated fixtures score 1.0 in the hybrid.

For a query without Greek letters that has not already matched the exact
wording path, `hybrid_search` adds BM25 over linked English translations and
commentary (`backend.bridges.bm25_bridge_hits`) to the word, form and dense
lists. Fusion projects supporting records only through explicit parent links.
Both the dense and English-bridge lists keep weight 1.0. English-only dense
retrieval and rare-word pseudo-relevance feedback (`prf_hits`) remain lab
experiments, not production signals. Weights are in
`backend.bridges.ENGLISH_QUERY_WEIGHTS`; change them only with a lab run.
The remaining limit is coverage: with one translation per passage there is
nothing to bridge on, which is why translation sources (Edmonds, Paton, the
CGL anthology) count as retrieval improvements.

## Release S: stacked retrieval (2026-10-09)

`backend/search_stack.py` adds ranked lists to hybrid fusion, and every list's weight is read from
`backend/search_stack_weights.json`, fitted on the development queries of
`data/evaluation/search-eval-s.json` by `scripts/search_lab_s.py fit` (coordinate ascent on nDCG@10 over the
grid 0–6, separately for queries with Greek letters and for the rest). Held-out queries were never read by the
fit. Fusion is still weighted reciprocal-rank fusion (`backend.retrieval.fuse`); translation, commentary and note
hits reach a Greek passage only through an explicit link. Lab figures: `docs/audits/search-lab-s.json`.

| List | What it ranks |
|---|---|
| `keyword` | BM25 (FTS5) over normalised Greek text for the query's Greek words, plus at most 8 spelling variants per word found in the corpus vocabulary (Aeolic/Doric/epic vowel and consonant correspondences, single/double consonants, movable nu, then one-letter edits for words of six letters or more). Variants add candidates at weight 0.6 and fill at most 40 % of the list. |
| `headword` | The query's headwords (Greek words read as headwords; English through dictionary head meanings), each widened to its dictionary variant group and capitalisation variants (weight 0.8 for a variant). |
| `dense_<model>_<kind>` | Cosine between the query and the passage vectors of one record kind: `grc` Greek text, `eng` English translation, `comm` commentary (scholia and English notes). |
| `notes` | BM25 over the commentary notes index (`backend/commentary_context.py`), projected to the passages each note is linked to. |

**Encoders compared** (all 116,428 indexed records embedded with each; word windows of 160, word-weighted mean;
nDCG@10 on all 120 queries with the Greek-text list alone): Krahn et al.'s Ancient Greek–English model
`kevinkrahn/shlm-grc-en` (MIT) **0.453**; BGE-M3 (MIT, the release O vectors) 0.318; Qwen3-Embedding-0.6B
(Apache-2.0) 0.269; SPhilBERTa (Apache-2.0) 0.123. Deployed: shlm-grc-en (768 dimensions, float16, 179 MB of
vectors, 90 M parameters) and BGE-M3. Qwen3 also needs a newer `transformers` than the image has; SPhilBERTa
was weakest on every split.

**Rerankers compared** on the first 50 stacked results, blended with the fused rank (weight fitted on the
development queries): mMiniLMv2-L12 mMARCO (Apache-2.0) and BGE-reranker-v2-m3 (Apache-2.0) both lowered
development nDCG@10 at every weight (0.610 → 0.601 / 0.602 at 0.1), so the fitted weight is 0 and no reranker
runs; BGE-reranker also costs 2.4 s a query on the laptop GPU. Qwen3-Reranker-0.6B could not be loaded with
the image's libraries. `backend/search_rerank.py` stays available behind a `rerank` entry in the weights file.

**Commentary notes** (`scripts/build_commentary_context.py` → `data/commentary_context.sqlite`, status at
`/api/commentary/status`, notes per passage at `/api/commentary/notes?passage_id=`): public-domain commentaries
from Perseus (Gildersleeve, Pindar 1885; Allen & Sikes, Homeric Hymns 1904; Cholmeley, Theocritus 1901; Perseus
encoding CC BY-SA 3.0 US) and the Internet Archive (Smyth, Greek Melic Poets 1900; Jebb, Bacchylides 1905;
Wharton, Sappho 1887, whose OCR has no Greek and so no links). A note is linked to a passage of its poets when the
passage contains at least two of the Greek word pairs the note quotes (or one pair and a rare word). Owner PDFs
go in `data/commentary_inbox/` (`name.pdf`, optional `name.json` with title, author, year, licence, url,
poets); one note per page with its page number. Display rule: a public-domain note may be shown in full; any
other note feeds only search signals and links, and the API returns at most a 30-word quotation with the full
citation and link (`commentary_context.display_note`).
