# Retrieval evaluation

The reproducible benchmark is [retrieval-queries.jsonl](../data/evaluation/retrieval-queries.jsonl). Its queries are synthetic test fixtures, not ancient evidence or additional corpus rows. Each judgment names one eligible Greek text passage and quotes an exact span of that record. English descriptions also name a linked English commentary record and an exact bridge quote. The evaluator rejects missing IDs, changed quotes, missing raw artifacts, and bridges without an explicit `parent_id` link.

Run from the project root:

```powershell
py -3.13 scripts/evaluate_retrieval.py
py -3.13 -m pytest tests/test_retrieval_eval.py -q
```

The script reads `data/corpus.sqlite` and the local BGE-M3 index, then writes [retrieval-evaluation.json](../data/reports/retrieval-evaluation.json). It does not modify the corpus, embeddings, or running server. It uses the same in-process search implementation as the API and reuses one encoder instance across dense and hybrid runs. The report binds the query file and embedding manifest by SHA-256 and includes every query's source URL, source artifact path and hash, citation, top-five result IDs, and judged rank.

## What is measured

The fixture covers 38 queries over 25 distinct Greek lyric passages: 18 exact Greek phrases, six accent-stripped Greek phrases, six Latin-script transliterations, two isolated forms, and six English descriptions. True spelling errors are not yet tested. The English cases are explicitly *commentary-assisted* queries; the commentary may itself mention a concept absent from the Greek text. Greek-only runs admit Greek text results; assisted runs may retrieve a translation or commentary record, credited to the judged text only through an explicit parent link. This tests retrieval of a passage from its existing evidence, not independent semantic validation of the Greek by the model.

The baselines are literal word search, source-backed form expansion, and BGE-M3 dense cosine search. Hybrid search uses the production word/form/dense candidate fusion and its passage grouping. The same query set is run against each method. Recall@1/5/10 and MRR@10 report the first rank of the single judged target. Other editions with similar wording or citations do not earn credit; there is no inferred cross-edition alignment. An unjudged alternative may also be relevant, so the metric can underestimate usefulness. The first ten displayed results define the evaluation window.

This is a small development benchmark, not a held-out claim of reliable Ancient Greek understanding. Exact phrases originate in the indexed passage, so the literal group is primarily a source-trace and regression check. Transliteration spellings are user-style variants, not source transcriptions. English judgments rely on existing commentary links, especially Digital Sappho; the source distribution is therefore uneven. The benchmark has no comprehensive relevance judgments, word-sense adjudication, rare-versus-common meaning labels, or expert-reviewed hard negatives. Similarity and RRF ranks are retrieval orderings, not evidence of textual influence or probabilities of philological truth. To make a broader quality claim, expand this set with independently judged meanings and parallels, explicit negative examples, and held-out authors and editions.

## Findings

On the pre-second-pass corpus snapshot (104,736 BGE-M3 vectors), top-five retrieval of the judged Greek passage was:

| Method | Greek-only | Commentary-assisted |
| --- | ---: | ---: |
| Literal word search | 27/38 | 29/38 |
| Dense search | 11/38 | 16/38 |
| Hybrid fusion | 26/38 | 31/38 |

Form expansion alone found 25/38 in Greek-only mode. By query type, literal Greek reached 18/18 with both literal and hybrid search; English descriptions reached 3/6 with assisted literal search and 5/6 with assisted hybrid search. Transliteration remained weak at 2/6 for assisted hybrid. Accent-stripped Greek reached 6/6 with literal search but 5/6 with hybrid, a concrete regression worth fixing. These paired counts reflect this selected fixture and cannot be extrapolated to the whole corpus.

The measured category results, MRR, and per-query misses are in the JSON report. Regenerate it after a corpus rebuild or retrieval change; historical scores from an earlier snapshot must not be compared as though the candidate pool stayed fixed.
