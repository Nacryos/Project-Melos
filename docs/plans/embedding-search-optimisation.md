# Embedding search optimisation: what changed 2023–2026, and what Melos should do

Status: **research note, 2026-10-07**. Nothing here is implemented, and no existing file changed.
This note complements [hybrid-retrieval-reranker-design.md](hybrid-retrieval-reranker-design.md), written the same day. That doc holds the architecture, the sense ranker and the ship gates. This one surveys the field and adds new measurements on the real index. Where the two overlap, they agree. Labels: *measured* means measured on the owner's laptop for this note, with BLAS, torch and FAISS limited to 2 threads to stand in for the box; *est.* means an estimate; *[n]* is a source in §9.

## 1. Short answer

There has been real progress since 2023, but most of it targets problems Melos does not have:

- **Speed and scale problems Melos does not have.** ANN indexes, quantisation and Matryoshka (MRL) truncation fix billion-vector scale. Melos has 116k vectors, and a full scan of them takes about 22 ms.
- **Evidence that does not cover Ancient Greek.** The 2024–2025 multilingual encoders and rerankers (BGE-M3, Qwen3-Embedding, EmbeddingGemma, Arctic 2.0, jina-v3/v2-reranker, mxbai v2) are validated on *modern* languages only. No MTEB/MMTEB leaderboard result says anything about Ancient Greek lyric, and none of the sources read here claims Ancient Greek coverage *[13]*.

Three developments do transfer:

1. **Cheap in-domain adaptation of the encoder.** In 2026, de la Selle showed that unsupervised contrastive adaptation on only 4–8k raw in-domain sentences beat every multilingual, specialised and supervised baseline on Latin and Ancient Greek reuse retrieval. Training took "tens of seconds on a laptop GPU" *[18]*. Supervised contrastive fine-tuning with hard negatives is a mature, cheap recipe *[22][23]*, and Melos already holds about 5.5k Greek↔English links that can serve as pairs.
2. **Giving short units context before embedding.** This is the core of Anthropic's "contextual retrieval": 35% fewer top-20 failures from contextual embeddings, 49% with contextual BM25 added *[20]*. In Melos the context can be **deterministic**, namely the neighbouring lines and the poem, so no LLM-generated text is needed.
3. **Hybrid lexical+dense fusion with tuned weights.** Melos already uses RRF. Bruch et al. found that a tuned convex combination beats RRF and needs only a few labelled queries to tune *[11]*.

Melos's measured problem is quality. Dense-only search reaches R@10 0.11 for English queries against Greek, and the hybrid reaches 0.415 (`docs/retrieval.md`). Speed is not the problem.

## 2. Current setup, and two facts that shape everything

| Item | Value | Source |
|---|---|---|
| Encoder | `BAAI/bge-m3` @ `5617a9f6…`, dense output only, 1024-d, ≤512-token windows, length-weighted mean pooling (`token_windows_weighted_mean_v2`) | `backend/semantic.py:19`, `scripts/build_embeddings.py:33,113` |
| Query embedding | Raw query string, `normalize_embeddings=True`, no instruction prefix (correct for BGE-M3), CPU fp32 on the box | `semantic.py:206` |
| Index | 116,191 vectors (grc text 102,206; grc commentary 5,980; eng translation 4,701; eng commentary 2,428; ell 649; lat 227). The corpus has **288,584** rows, but 167k `reference`/lexicon rows are not embedded | `data/embeddings/manifest.json` |
| Storage/search | float32 `.npy`, memory-mapped (454 MiB), exact `vectors @ q`, stable argsort over eligible rows. **No ANN** | `semantic.py:86,209` |
| Fusion | Weighted RRF (k=60) of FTS5 words, attested forms, dense, plus an English BM25 bridge for non-Greek queries | `backend/retrieval.py:16`, `docs/retrieval.md` |
| Box latency | Semantic query 0.18–0.30 s warm; container about 1.9 GiB | `docs/deployment.md:579` |

**Fact 1: the units do not match.** *Measured* on 2,000 random rows each, BGE-M3 tokens per record:

| Kind | p50 | p90 | p99 |
|---|---|---|---|
| Greek `text` | 25 | 44 | 515 |
| English `translation` | 209 | 733 | 1,379 |
| `commentary` | 57 | 181 | 556 |

A Greek "passage" is mostly **one verse line**: the median is 44 characters. An English translation is usually a **whole poem**. The lab's translation→Greek queries therefore compare a poem-sized English vector with line-sized Greek vectors, and a 25-token line rarely carries the theme a reader searches for. This alone plausibly explains much of the R@10 0.11. No model swap fixes it; changing the unit does (§5).

**Fact 2: tokenisation is poor.** XLM-R tokenisation of polytonic Greek averages **1.74 characters/token** (*measured*), against 3.6 for English. Words are fragmented into subword pieces, which is the usual sign of weak pre-training coverage. Encoders with a Greek-trained vocabulary (GreBERTa, SPhilBERTa) avoid this *[15][16]*.

## 3. Embedding models

Throughout this table, "CPU encode" is relative to BGE-M3. The estimate scales by *non-embedding* parameters, because vocabulary tables cost RAM but almost no compute. BGE-M3 measures about 0.5 s per short query on 2 laptop threads and 0.18–0.30 s end to end on the box.

| Model (date) | Size / dim | Greek evidence | CPU encode vs BGE-M3 (*est.*) | RAM fp32 | Licence | Verdict for Melos |
|---|---|---|---|---|---|---|
| **BGE-M3** (2024-02) *[1]* | 568M / 1024 | Modern languages only. MIRACL nDCG@10: dense 69.2, all three modes 71.5. Cross-lingual MKQA R@100: dense 75.1, all modes 75.5 | 1× (*measured* 0.53 s laptop) | 2.3 GB | MIT | Keep as the base and fine-tune it (§7) |
| multilingual-e5-large-instruct (2024-02) *[2]* | 560M / 1024 | Modern only; instruction prefixes | ~1× | 2.2 GB | MIT | Lab A/B only |
| jina-embeddings-v3 (2024-09) *[3]* | 572M / 1024, MRL | Modern only; task LoRA, MRL down to 32-d | ~1× | 2.3 GB | Non-commercial (verify) | Avoid: licence, and no Ancient Greek gain expected |
| mGTE / gte-multilingual-base (2024-07) *[4]* | 305M / 768 | Modern only | ~0.4× | 1.2 GB | Apache-2.0 | Cheap lab arm |
| Arctic-embed-l-v2.0 (2024-12) *[5]* | 568M / 1024, MRL + quantisation-aware | Modern only; good at 128 bytes per vector | ~1× | 2.3 GB | Apache-2.0 | Lab arm, if storage ever matters |
| Nomic-embed-text-v2-moe (2025-02) *[6]* | 475M (305M active) / 768, MRL | Modern only (~100 languages) | ~0.4× | 1.9 GB | Apache-2.0 | Lab arm |
| Qwen3-Embedding-0.6B (2025-06) *[7]* | 0.6B / 1024 (32–1024 MRL) | MMTEB mean 64.33, close to Gemini-Embedding. Instruction-aware. No Ancient Greek data; byte-level BPE on polytonic Greek is untested | ~1.4× | 2.4 GB | Apache-2.0 | Best general-purpose candidate for an A/B |
| Qwen3-Embedding-4B/8B (2025-06) *[7]* | 4–8B | As above | ~10–25× (1.5–6 s per query) | 16–32 GB | Apache-2.0 | **Infeasible** on 2 cores / 8 GB |
| EmbeddingGemma-300M (2025-09) *[8]* | 308M / 768, MRL | Best text-only multilingual MTEB model under 500M. No Ancient Greek data | ~0.35× | 1.2 GB | Gemma terms | **Fastest credible general candidate** |
| mmBERT (2025-09) *[9]* | Encoder (not an embedder) | 1,800+ languages, beats XLM-R | — | — | MIT | Possible fine-tuning base, not a retriever |
| Ancient-Greek-BERT (2021) *[14]* | base | Masked-LM and POS only | ~0.3× | 0.5 GB | — | Not a sentence encoder |
| GreBERTa / PhilBERTa (2023-05) *[15]* | base | State of the art for Ancient Greek morphosyntax; Greek-trained vocabulary; not retrieval-trained | ~0.3× | 0.5 GB | (check) | Base for unsupervised adaptation (§7) |
| SPhilBERTa (2023-08) *[16]* | base | grc/lat/eng sentence encoder trained on parallels and evaluated on allusion detection | ~0.3× | 0.5 GB | (check) | **First lab A/B**: the only retrieval-trained Ancient Greek encoder that is cheap on CPU |
| Krahn et al. AG models (2023-09) *[17]* | base | Ancient Greek translation search, similarity and retrieval evaluated; the authors document translation bias | ~0.3× | 0.5 GB | (check) | Lab A/B; released parallel data is useful for fine-tuning |

**Strategies for English queries:**

- *Embed the English translation* already ships: 4.7k translation vectors plus the BM25 bridge. Its ceiling is coverage, since only about 5% of Greek lines have a linked translation.
- *Machine-translate the other 95% and embed the English.* Translate-then-retrieve is a standard way to cross a language gap, but no study measures it for Ancient Greek lyric. Under the project's source-only rule it would be invented text, so it stays a labelled lab arm and needs an owner decision.
- *Instruction prefixes* (e5-instruct, Qwen3) give small gains on modern benchmarks *[2][7]*. BGE-M3 needs none.

## 4. Retrieval structure, compression and indexes (*measured* on the real 116k BGE-M3 vectors)

The method: 300 corpus vectors were used as queries, excluding self-matches. Each score is recall@10 against the exact top-10. Doc-as-query is a proxy for real queries, and recall is relative to the current model, not to relevance.

| Option | Recall@10 vs exact | Latency per query | Memory | Build | Note |
|---|---|---|---|---|---|
| Exact fp32 scan (current) | 1.00 | **22 ms** at 116k → ≈55 ms at 288k | 454 MiB (1.13 GiB at 288k) | 0 | Already a small share of the 0.2–0.5 s query |
| FAISS int8 scalar quantiser | 0.987 | 18 ms | 113 MiB | 0.2 s | Worth it only if RAM gets tight |
| Binary (sign), no rescore | **0.51** | 4 ms | 14 MiB | 0 | Unusable alone |
| Binary + fp32 rescore of top 100 / 400 | 0.91 / 0.983 | ~1 ms + rescore | 14 MiB, plus fp32 on disk | 0 | Matches the ~96% retained reported in *[10]* |
| MRL-style truncation of BGE-M3 to 512 / 256 dims | **0.68 / 0.50** | 2× / 4× faster scan | ½ / ¼ | 0 | BGE-M3 is not MRL-trained, so **do not truncate** *[12]* |
| HNSW (FAISS, M=32, efC=100), ef=64 / 256 | 0.960 / 0.984 | 1.0 / 3.3 ms | ≈ +60 MiB graph | **96 s** (≈4 min at 288k) | Saves about 20 ms per query and costs recall |
| IVF-PQ (1,024 lists, 128 B per vector), nprobe 16 / 64 | **0.57 / 0.61** | 0.3 / 0.8 ms | 14 MiB | 28 s | Too lossy at this scale |
| sqlite-vec `vec0` *[24]* | brute force by default; ANN (DiskANN, IVF) is alpha (2026 releases) | ≈ exact scan | in SQLite | minutes | Convenience, not speed |
| usearch / hnswlib *[25]* | HNSW, same trade-off as above | ~1 ms | +graph | minutes | Not needed below about 10⁶ vectors |

**Late interaction (ColBERTv2/PLAID, Jina-ColBERT-v2, BGE-M3 multi-vector).** PLAID reaches tens to a few hundred milliseconds on CPU at 140M passages, with heavy residual compression *[26]*. Jina-ColBERT-v2 adds MRL down to 64-d per token *[27]*. Late interaction costs storage per *token*, not per passage. With Greek at 1.74 characters/token and translations at ~200 tokens, the uncompressed BGE-M3 multi-vector index is tens of GB (the sibling doc estimates about 47 GB). PLAID-style compression would need a separate engine (PyLate *[28]*), and PyLate's own guidance assumes a GPU. The quality case is also weak: in BGE-M3's paper, adding multi-vector and sparse to dense gains only 75.1→75.5 R@100 on **cross-lingual** MKQA *[1]*, and English→Greek is the cross-lingual case.

**Learned sparse retrieval (SPLADE, BGE-M3 sparse).** Sparse alone scores 53.9 on MIRACL and 45.3 on MKQA *[1]*, and recent work notes that learned sparse retrieval struggles on MMTEB *[29]*. Melos's Greek→Greek lexical channel (FTS5 plus attested forms) already does what sparse weights would do, and does it inspectably. BGE-M3's sparse output is nearly free (same forward pass), so keep it as a lab arm only.

**Fusion.** RRF *[30]* is robust and needs no labels. A convex combination of normalised scores beats RRF in- and out-of-domain and tunes from a small labelled set *[11]*. Tune it on DEV once the harness exists.

## 5. Context, chunking and lexical expansion

| Technique | Evidence | Melos version | Cost | Expected value |
|---|---|---|---|---|
| **Line windows and poem vectors** (chunk by strophe or poem) | Contextual embeddings cut top-20 failures by 35% *[20]*; standard chunking practice | For each Greek line, also embed a window of the ±2 neighbouring lines within the same `work_id` ordered by `sequence`, and the whole poem when it is ≤512 tokens. Score a line as max(own, window, poem·α) and credit the line. Strophes are known in Sappho and Alcaeus, so windows can follow them where marked | ≈100k window vectors plus ~5k poem vectors; ≈10–20 min on the laptop GPU (*est.*); +0.4–0.8 GB fp32 or +0.1–0.2 GB int8 | **Highest per hour of work.** Directly attacks Fact 1 |
| Deterministic header | Same source *[20]* | Prefix `author · work · citation` before embedding (as the sibling doc proposes) | Re-embed only | Moderate; helps author-scoped queries |
| LLM-generated context (Anthropic style) | 35–49% fewer failures, up to 67% with a reranker *[20]* | Would inject generated summaries into the index | API cost is trivial (≈$1 per M tokens) | Conflicts with the source-only rule; lab only |
| doc2query / doc2query-- | Generated queries can hallucinate; filtering improves effectiveness by up to 16% and halves the index *[21]* | Generated questions per poem | GPU-hours | Same invented-text problem, and filtering needs a relevance model Melos lacks. Skip |
| **Lemma-expanded lexical search** | Standard for inflected languages; the AG reuse work uses morphological re-inflection *[19]* | Expand a Greek query to all attested forms of its lemma(s). The existing `forms_for_lemma` does this from source lexica. Add an offline `machine_lemma` FTS column (odyCy or a Morpheus batch over the 182,692 distinct `vocabulary` forms), labelled machine | One offline pass over 183k forms, then an FTS rebuild | High for Greek queries; zero risk to the dense path |
| English→lemma gloss bridge | — | LSJ short definitions → headwords → forms (sibling doc, L5) | Small | Raises coverage beyond the 5% of lines with translations |

## 6. Rerankers on 2 CPU cores

The proxy: BGE-M3 shares the XLM-R-large backbone of `bge-reranker-v2-m3`. A forward pass over 50 passages of 218 tokens took **44 s** (*measured*, 2 laptop threads), about 4 ms per token. Greek lines are short, though. Fifty line-sized pairs come to about 2,000 tokens, which projects as follows:

| Reranker (date) | Size | 50 line pairs (*est.*) | 50 poem pairs (*est.*) | Evidence on this corpus |
|---|---|---|---|---|
| bge-reranker-v2-m3 (2024) | 568M | ~8 s (~3 s int8) | ~45 s | Lab: **lowered recall**, ~1.3 s per pair (`docs/retrieval.md`) |
| jina-reranker-v2-base-multilingual (2024-06) *[31]* | 278M | ~2 s (~0.7 s int8) | ~12 s | None; reported as 15× faster than bge-reranker-v2-m3 |
| mxbai-rerank-base-v2 (2025-03) *[32]* | 0.5B (Qwen2.5) | ~4–6 s | ~30 s | None; RL-trained, 100+ languages |
| Qwen3-Reranker-0.6B (2025-06) *[7]* | 0.6B | ~5–8 s (GGUF Q8 somewhat faster) | ~40 s | None |
| ColBERT as reranker (BGE-M3 multi-vector of candidates) | — | Needs candidate token vectors stored, or re-encoding at ~0.5 s per 10 lines | — | Cross-lingual gain ≈0 *[1]* |
| Hosted LLM listwise (e.g. Jev/Claude) | — | 1–3 s network | same | Plausibly the best Ancient Greek reader available, but costs money and sends text off-box |

Rerankers are the biggest jump in modern RAG pipelines (Anthropic's 49%→67% *[20]*). Here they are unproven in Ancient Greek, measured *negative* on the lab set, and slow on 2 cores. Only a base-size int8 model on the top 20 lines fits a ≤1.5 s budget, and only as an opt-in "deep search".

## 7. Fine-tuning

| Recipe | Data Melos already has | Compute | Evidence of gain | Risk |
|---|---|---|---|---|
| **Unsupervised in-domain contrastive training (SimCSE-style CSE, TSDAE)** | 102k raw Greek lines (no labels) | Minutes on the laptop RTX 3070 | Beat multilingual, specialised and supervised baselines on Ancient Greek and Latin reuse retrieval with 4–8k sentences *[18]*; TSDAE+GPL +1.4 nDCG *[23]* | Optimises Greek↔Greek similarity, not English→Greek |
| **Supervised contrastive fine-tune of BGE-M3** (MultipleNegativesRanking plus mined hard negatives, LoRA or full with gradient checkpointing) | ≈5,481 translation→parent links, commentary→parent links, and Krahn et al.'s released parallel data (check licence) *[17]* | 1–3 GPU-hours on the laptop 8 GB card (LoRA) or ≈$2–5 rented (*est.*) | Domain fine-tuning typically adds about 5–10 points; GPL gains up to 9.3 nDCG@10 *[23]*; hard-negative work reports +15–19% MRR *[22]*; a June 2024 tutorial shows gains from ~6k pairs *[33]*. **None of these is Ancient Greek** | Leakage (the same links build the eval set), forgetting of English |
| Contrastive fine-tune with linguistically generated positives (Ancient Greek WordNet paraphrase, re-inflection) | Morphology tooling partly exists | GPU-hours | Promising on Homeric-formula reuse; qualitative *[19]* | Pipeline effort |

Hard negatives should come from the same poem's other lines, the same author's other poems, and BM25-top non-targets. Mirrors are dropped by `text_key`. Positives should pair the **poem/window vector**, not single lines, with the translation, to match the unit fix in §5. After any fine-tune, re-embedding the index takes about 20–40 min of GPU time (*est.*). The box only needs to load new weights, and query cost is unchanged.

## 8. Evaluation: a cheap, reliable gold set

| Gold source | Judgments | Cost | Caveat |
|---|---|---|---|
| Translation alignment (exists: 195 queries) | English translation → Greek parent | Free | Measures translation search, not themes. Expand by splitting translations into **sentence-level** queries credited to the whole parent poem (likely ≈10–20k queries) |
| Commentary cross-references | "cf. Alc. 34", line parallels in commentary text → Greek↔Greek relevant pairs | Script plus spot-check | Citation parsing; the Campbell material is small (63 lemma notes) |
| Known parallels (Loci-Similes-style *[34]*) | Expert-verified intertexts | Owner time | Small, but the only true "semantic" Greek→Greek test |
| `thematic_short` (sibling doc) | 60–100 owner queries; pooled top-20 from every method, graded 0/1/2 | ≈1 owner-day | Decides reranking and model swaps |
| LLM-assisted judging (UMBRELA *[35]*) | LLM grades the pooled candidates; owner audits 20% | Low $ | LLM Ancient Greek competence is unverified; report agreement with the owner |

**Metrics.**

- nDCG@10, graded where judgments are graded.
- MRR@10 and R@10.
- **R@50 or R@100**, which is the ceiling any reranker can reach.
- Results per family (Greek phrase, transliteration, English theme, Greek→Greek parallel).
- p50/p95 latency on the box.
- Paired bootstrap 95% CIs.

**Protocol.**

- Split by `work_id` into DEV and TEST and freeze the split.
- Exclude every TEST poem and its `text_key` copies from fine-tuning pairs.

## 9. Recommendation (ranked, staged)

| When | Do | Why / gate |
|---|---|---|
| **This week** | 1. Harness: DEV/TEST split by work, R@50, nDCG, bootstrap CIs, sentence-level translation queries, a first 30 `thematic_short` queries | Every later step needs this. Hours of work |
| | 2. **Line-window and poem vectors** with max-pooling to the line (§5); re-embed on the laptop GPU; A/B against current dense | Fixes the unit mismatch. Expect the largest dense gain per hour (*est.*, unproven) |
| | 3. Tune the fusion weights (or a convex combination) on DEV | Free; *[11]* |
| **This month** | 4. Lemma channel: batch-lemmatise the 183k distinct forms offline; add a `machine_lemma` FTS column and a weighted RRF list | Helps Greek queries without model risk |
| | 5. Fine-tune BGE-M3 contrastively on the translation/commentary pairs with hard negatives (LoRA, laptop GPU), pairing poem/window vectors; separately try unsupervised CSE on Greek lines *[18]* | The only route with direct ancient-language evidence of beating off-the-shelf models |
| | 6. A/B SPhilBERTa (cheap, Ancient Greek-specific) as a second dense list | ~0.3× CPU cost; tests whether a Greek vocabulary matters |
| **Later / conditional** | 7. A/B EmbeddingGemma-300M and Qwen3-Embedding-0.6B (instruction prompts) | Only if 5–6 plateau; ~30–60 min GPU re-embed each |
| | 8. Opt-in "deep search": jina-reranker-v2-base int8 on the top 20 **windows** | Must win on `thematic_short`; p95 ≤ 1.5 s |
| | 9. Machine-translation bridge for the 95% untranslated, or LLM context | Owner decision on invented text; labelled and never displayed as a source |
| | 10. int8 vectors (FAISS SQ8, 0.987 recall) | Only when windows or a second model push RAM |

## 10. What will NOT help on this corpus

- **ANN indexes (HNSW, IVF-PQ, DiskANN, sqlite-vec ANN, usearch).** The exact scan is about 22 ms (≈55 ms at 288k) out of a 200–500 ms query, which is dominated by encoding the query. HNSW trades about 20 ms for 1.6–4% recall loss and a 96 s build. IVF-PQ measured 0.57–0.61 recall.
- **Truncating BGE-M3 dimensions.** It is not MRL-trained: recall@10 falls to 0.68 at 512-d and 0.50 at 256-d (*measured*).
- **Binary vectors without rescoring.** 0.51 recall (*measured*).
- **ColBERT/PLAID or BGE-M3 multi-vector.** The index runs to tens of GB, PyLate assumes a GPU, and the published cross-lingual gain is +0.2 R@100 *[1][28]*.
- **Learned sparse (SPLADE, BGE-M3 sparse) for English queries.** Lexical matching cannot cross English→Greek (MKQA sparse 45.3 *[1]*). For Greek queries, FTS5 plus forms already covers it.
- **Large cross-encoders live.** About 8 s per 50 lines and about 45 s per 50 poems on 2 cores, and they *lowered* recall in the lab.
- **Swapping to the current MTEB leader and expecting a gain.** No MTEB/MMTEB task targets Ancient Greek lyric retrieval *[13]*. Modern-Greek results (e.g. ORPHEAS *[36]*, the CUP benchmark *[37]*) do not transfer, and 4B/8B models are 10–25× slower on the box.
- **Longer context windows (8k/32k).** Greek lines are 25 tokens at the median.
- **doc2query and LLM summaries as default index text.** They are invented text, and hallucinated expansions are known to hurt retrieval *[21]*.

**Where the evidence is thin.** Every quality claim above, except the de la Selle (2026), D'Angelo et al. (2025), Krahn et al. (2023) and SPhilBERTa (2023) results, comes from modern languages. The size of the gain for Melos must come from the harness in §8, not from the literature.

## Sources (publication dates; accessed 2026-10-07)

1. Chen et al., *BGE M3-Embedding*, arXiv 2402.03216, 2024-02 (v4 2024-06-28). https://arxiv.org/abs/2402.03216
2. Wang et al., *Multilingual E5 Text Embeddings: A Technical Report*, arXiv 2402.05672, 2024-02-08. https://arxiv.org/abs/2402.05672
3. Sturua et al., *jina-embeddings-v3*, arXiv 2409.10173, 2024-09-16. https://arxiv.org/abs/2409.10173
4. Zhang et al., *mGTE*, arXiv 2407.19669, 2024-07. https://arxiv.org/abs/2407.19669
5. Yu et al., *Arctic-Embed 2.0*, arXiv 2412.04506, 2024-12; blog https://www.snowflake.com/en/engineering-blog/snowflake-arctic-embed-2-multilingual/
6. Nussbaum & Duderstadt, *Training Sparse Mixture of Experts Text Embedding Models* (Nomic v2), arXiv 2502.07972, 2025-02. https://arxiv.org/abs/2502.07972
7. Zhang et al., *Qwen3 Embedding*, arXiv 2506.05176, 2025-06. https://arxiv.org/abs/2506.05176
8. Vera et al., *EmbeddingGemma*, arXiv 2509.20354, 2025-09-24. https://arxiv.org/abs/2509.20354
9. Marone et al., *mmBERT*, arXiv 2509.06888, 2025-09 (ICML 2026). https://arxiv.org/abs/2509.06888
10. Hugging Face / mixedbread, *Binary and Scalar Embedding Quantization*, 2024-03-22. https://huggingface.co/blog/embedding-quantization
11. Bruch, Gai & Ingber, *An Analysis of Fusion Functions for Hybrid Retrieval*, ACM TOIS 2023 (arXiv 2210.11934). https://arxiv.org/abs/2210.11934
12. Kusupati et al., *Matryoshka Representation Learning*, NeurIPS 2022. https://proceedings.neurips.cc/paper_files/paper/2022/hash/c32319f4868da7613d78af9993100e42-Abstract-Conference.html
13. Enevoldsen et al., *MMTEB*, ICLR 2025 (arXiv 2502.13595, 2025-02). No Ancient Greek retrieval task was found in its language table; Koine Greek may occur only in Bible-derived bitext mining (not verified). https://arxiv.org/abs/2502.13595
14. Singh, Rutten & Lefever, *A Pilot Study for BERT Language Modelling and Morphological Analysis for Ancient and Medieval Greek*, LaTeCH 2021-11. https://aclanthology.org/2021.latechclfl-1.15
15. Riemenschneider & Frank, *Exploring Large Language Models for Classical Philology*, ACL 2023 (arXiv 2305.13698, 2023-05). https://arxiv.org/abs/2305.13698
16. Riemenschneider & Frank, *Graecia capta ferum victorem cepit* (SPhilBERTa), ALP 2023 (arXiv 2308.12008, 2023-08). https://arxiv.org/abs/2308.12008
17. Krahn, Tate & Lamicela, *Sentence Embedding Models for Ancient Greek Using Multilingual Knowledge Distillation*, ALP 2023-09. https://aclanthology.org/2023.alp-1.2/
18. de la Selle, *From transcription to semantic corpus analysis: unsupervised learning of sentence representations for ancient languages*, arXiv 2607.24542, 2026-07-27. https://arxiv.org/abs/2607.24542
19. D'Angelo, Taddei & Lenci, *Detecting Semantic Reuse in Ancient Greek Literature: A Computational Approach*, CLiC-it 2025-09. https://aclanthology.org/2025.clicit-1.34
20. Anthropic, *Introducing Contextual Retrieval*, 2024-09-19. https://www.anthropic.com/news/contextual-retrieval
21. Gospodinov, MacAvaney & Macdonald, *Doc2Query--: When Less is More*, ECIR 2023 (arXiv 2301.03266). https://arxiv.org/abs/2301.03266
22. *Hard Negative Mining for Domain-Specific Retrieval in Enterprise Systems*, arXiv 2505.18366, 2025-05. https://arxiv.org/abs/2505.18366
23. Wang et al., *GPL: Generative Pseudo Labeling*, NAACL 2022. https://aclanthology.org/2022.naacl-main.168
24. sqlite-vec releases (ANN alpha: rescore/IVF/DiskANN, 2026). https://github.com/asg017/sqlite-vec/releases
25. USearch (PyPI). https://pypi.org/project/usearch/
26. Santhanam et al., *PLAID*, arXiv 2205.09707, 2022-05. https://arxiv.org/abs/2205.09707
27. Jha et al., *Jina-ColBERT-v2*, MRL Workshop 2024 (arXiv 2408.16672, 2024-08-29). https://arxiv.org/abs/2408.16672
28. Chaffin & Sourty, *PyLate*, arXiv 2508.03555, 2025-08. https://arxiv.org/abs/2508.03555
29. SemBridge / SPLARE learned-sparse multilingual work, arXiv 2602.20986, 2026-02. https://arxiv.org/abs/2602.20986
30. Cormack, Clarke & Büttcher, *Reciprocal Rank Fusion*, SIGIR 2009. https://dl.acm.org/doi/10.1145/1571941.1572114
31. Jina AI, *jina-reranker-v2-base-multilingual*, released 2024-06-25. https://jina.ai/models/jina-reranker-v2-base-multilingual/
32. Mixedbread, *mxbai-rerank-v2*, 2025-03-13. https://www.mixedbread.com/blog/mxbai-rerank-v2
33. Schmid, *Fine-tune Embedding models for RAG*, 2024-06-04. https://www.philschmid.de/fine-tune-embedding-model-for-rag
34. Schelb et al., *Loci Similes: A Benchmark for Extracting Intertextualities in Latin Literature*, arXiv 2601.07533, 2026-01-12. https://arxiv.org/abs/2601.07533
35. Upadhyay et al., *UMBRELA*, arXiv 2406.06519, 2024-06. https://arxiv.org/abs/2406.06519
36. *ORPHEAS: A Cross-Lingual Greek–English Embedding Model* (Modern Greek), arXiv 2604.20666, 2026-04. https://arxiv.org/abs/2604.20666
37. *A Comparative Evaluation of Embeddings and LLMs in a Greek* book-retrieval benchmark (CUP), arXiv 2607.21274, 2026-07. https://arxiv.org/abs/2607.21274

*Local measurement scripts (not committed) were run from the session scratchpad: `bench.py` (scan, quantisation and encoder latency) and `bench_index.py` (FAISS recall and build on the real 116k vectors).*
