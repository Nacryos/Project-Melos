# Hybrid retrieval and reranking: design and evaluation protocol

Status: **proposal, 2026-10-07**. Nothing here is implemented except the lab script
`scripts/lab_vector_bench.py` (experimental, unused by the server). Figures marked
*measured* were measured for this document on the owner's laptop with BLAS/torch
limited to 2 threads to approximate the Hetzner box. They were **not** measured on the box,
and its CPU will differ. Figures marked *est.* are estimates to be replaced by box measurements.

## 1. Current state

| Area | What exists now | Reference |
|---|---|---|
| Encoder | `BAAI/bge-m3` pinned to rev `5617a9f6…`, **dense output only**, 1024-d, max 512 tokens per window. The model is loaded on CPU in float32 on the box | `backend/semantic.py:19-20`, `:152-171` |
| Passage vectors | Each passage is split into ≤512-token windows. Window vectors are averaged with token-count weights and L2-normalised (`token_windows_weighted_mean_v2`). Eligible records are `text`/`translation`/`commentary` with `source_text` or `machine_corrected_ocr` quality. Built on the laptop GPU and checkpointed in `checkpoint.sqlite` | `scripts/build_embeddings.py:33-40`, `:113-169`, `:201` |
| Index size | Local manifest: **116,191 vectors** (grc text 102,206; grc commentary 5,980; eng translation 4,701; eng commentary 2,428; ell 649; lat 227) out of 288,584 corpus rows. 167,288 rows are Greek `reference` (lexicon) and are not embedded | `data/embeddings/manifest.json` |
| Storage/search | A float32 `.npy` matrix, memory-mapped, plus a JSON row list. Search is an **exact brute-force** `vectors @ q` over eligible rows with a stable argsort. No ANN index and no quantisation | `semantic.py:86`, `:209-212` |
| Lexical | SQLite FTS5 `passage_fts(normalized, citation, author, work)`, `unicode61 remove_diacritics 0`, BM25. Modes are `words` and source-backed `forms` (from `data/lexica/forms.jsonl`). There is a conservative Latin-script→Greek fallback (≤16 terms, ≥80% coverage gate) | `backend/query_expansion.py:17-22`, `:209`; `docs/retrieval.md:71-101` |
| Fusion | **Weighted reciprocal-rank fusion**, `w/(60+rank)`, with at most one vote per list per passage group. Translation/commentary hits project to the Greek parent only through an explicit `parent_id`. Mirrors collapse by identical words. Pools are 400 word + 400 form + 1,000 dense, plus 400 English-bridge BM25 hits for non-Greek queries. Weights are `{"semantic":1.0,"bm25_bridge":1.0}` | `backend/retrieval.py:15-16`, `:93-237`; `backend/server.py:1478-1539`; `backend/bridges.py:39` |
| Retrieval lab | `lab_build_eval.py` builds judged queries from existing links: each English translation or commentary record names its Greek parent, so the English text becomes the query and the parent passage plus its copies become the target. Families: `translation_to_greek`, `commentary_to_greek`, and 38 `fixtures`. `lab_eval.py` excludes the query record and its siblings, credits parents and copies, and reports R@1/5/10 and MRR@10 only. `rank_of` stops at `--limit` | `scripts/lab_build_eval.py:1-20`; `scripts/lab_eval.py:43-79`, `:307-335` |
| Lab findings | On 195 queries, R@10 was 0.11 for Greek-vector dense alone, 0.385 for the hybrid and 0.415 for the hybrid plus English BM25 bridge. Cross-encoders (mMiniLM, bge-reranker-v2-m3) **lowered** recall, and the large reranker cost about 1.3 s per pair on CPU | `docs/retrieval.md:108-131` |
| Sense ranker | Builds one Jev packet per token (≤3 per selection). The packet contains **every** extracted LSJ/Autenrieth sense (≤254 choices plus abstain), morphology alternatives, ≤2 whole-passage English translations (≤1,800 characters each, *not token-aligned*), a ≤12-row dependency neighbourhood from odyCy, and the whole Campbell commentary for the five Alcaeus poems. Experimental commentary retrieval cues are off (tested 2026-10-07, no gain). Choice IDs are shortened. A sense is proposed only when the full probability vector is present, p≥0.75, margin≥0.2 and the sense is form-compatible | `backend/sense_ranker.py:20-30`, `:250-323`, `:403-409`; `backend/passage_ranker.py:30-48` |
| Parse ranking | Deterministic `_affinity` against the odyCy prediction (+1 agree, −1.5 disagree, agreement partners ±0.75, …). Optional Jev ranking goes through `PassageRanker` | `backend/interlinear.py:227`; `docs/morphology.md:173-187` |
| Jev | `POST api.typesafe.ai/v1/systemone`, one `choice` question with abstain, 8 s timeout. Durable SQLite cache (30-day TTL). Budgets: 500/day global, 60/day and 10/min per visitor. Price quoted 2026-09-30: $0.042 per M input tokens | `backend/classifier.py:23-27`, `:632-705`; `backend/jev_gateway.py:23-25`, `:72-74`; `docs/context-classifier.md` |

**Diagnosis.** Three problems sit behind "simple cosine similarity is not accurate enough":

1. **Coverage.** Only about 5% of Greek texts have an English bridge (4.7k translations against 102k texts). For the other 95%, an English thematic query depends entirely on BGE-M3's zero-shot English→Ancient Greek alignment, and that alignment scored R@10 0.11.
2. **What the lab measures.** Its English queries are whole translations, which makes them a translation-retrieval benchmark rather than a test of short thematic queries. The negative reranker result was obtained on this query type, so it does not settle the question for short thematic queries.
3. **Sense ranking context.** The sense ranker sees the whole translation, not the English words that render the target. It also has no local, free pre-ranking signal, so every comparison is a paid, rate-limited Jev call.

## 2. Proposed architecture

```
                         ┌───────────── query analysis ─────────────┐
 query ─► script/lang ─► │ Greek: forms + lemma expansion (forms.jsonl → lemma)        │
                         │ English: gloss bridge (LSJ short defs → headwords → lemmas) │
                         └───────────────────────────────────────────┘
   candidate lists (each bounded, ranked independently)
   L1 FTS5 words · L2 forms · L3 lemma-BM25 [new] · L4 English-bridge BM25 (existing)
   L5 gloss-bridge lemma-BM25 [new, EN queries] · D1 BGE-M3 dense (existing, re-embedded with header)
   D2 BGE-M3 sparse [stage 3] · D3 fine-tuned dense [stage 3]
                │
                ▼  weighted RRF (k=60; weights per query class, tuned on DEV only)
        fused top-50 ──► (opt-in "deep") rerank top-20: small cross-encoder on English bridge
                │                          or Jev listwise choice; never default until it wins in the lab
                ▼
        passage groups + matched_evidence (unchanged provenance contract)

 Sense/parse for a clicked token
   inventory (unchanged) ─► form filter (sense_form_compatible) ─► local scorer [new]
     s1 bi-encoder cos(gloss, context)  s2 aligned-English-word ↔ gloss  s3 source priors
     (LSJ sense cites a lyric/Aeolic author; Campbell lemma note string match)
   ─► local ranking + margin shown as "local similarity, uncalibrated"
   ─► if margin < τ or user asks: existing Jev packet (unpruned, order unchanged) ─► existing gates
```

Key choices and their reasons:

- **Keep exact search; do not add an ANN.** *Measured:* a float32 scan of 116k×1024 vectors takes a **29 ms** median with 2 BLAS threads. Projected to 288k rows, that is about 75 ms. HNSW (usearch, hnswlib, FAISS) only pays off at roughly ≥10⁶ vectors. sqlite-vec is optional for operations, not for speed.
- **Quantise only when a second index is added.** *Measured* agreement with the exact top-100:
  - int8 (114 MB): **99.2%**
  - binary + float32 rescore of 400 candidates (14 MB): **94.4%**

  This is consistent with the Hugging Face report of about 96% of retrieval performance kept with binary + rescoring ([HF blog, 2024-03-22](https://huggingface.co/blog/embedding-quantization)). BGE-M3 is not Matryoshka-trained, so truncating its dimensions is not an option. Arctic-embed-l-v2.0 is MRL-trained ([arXiv 2412.04506, 2024-12](https://arxiv.org/abs/2412.04506)).
- **Contextual chunk augmentation, deterministic version first.** Re-embed each passage with a header: `author · work · citation` plus the first ≤300 characters of its linked English translation, when one exists. Anthropic reports that contextual embeddings cut top-20 retrieval failures by 35%, contextual embeddings plus contextual BM25 by 49%, and adding a reranker by 67% ([Anthropic, 2024-09-19](https://www.anthropic.com/news/contextual-retrieval)). Their context is LLM-generated. Here, generated summaries would be **invented text**, which conflicts with the project's source-only stance. They therefore stay a lab arm with labelled provenance, never displayed, and never ship without an owner decision.
- **Gloss bridge (new, addresses coverage).** Map English query words to LSJ headwords whose *first* definition span (`backend/lexicon_senses.py`, Perseus LSJ TEI) contains them, weighted by IDF. Search those lemmas' attested forms over all 103k Greek texts with FTS5. This needs no translation and no model. The risk is polysemy noise, so the channel gets its own RRF weight.
- **Lemma channel.** Add a machine-lemma FTS column, built offline with the existing odyCy pipeline (`backend/syntax_provider.py:21`) and labelled `machine_lemma`. Greek queries then match across inflection, not only through attested `forms`. Today, full parses exist only for the five Alcaeus poems (331 Morpheus receipts, `docs/deployment.md`), so this is new offline work.
- **Encoder upgrade by fine-tuning, not by swapping models.** No candidate model has a published Ancient Greek retrieval benchmark (table §3). The direct evidence is for distilled Greek sentence encoders: Krahn et al. ([ALP 2023-09](https://aclanthology.org/2023.alp-1.2/)) and SPhilBERTa ([arXiv 2308.12008, 2023-08](https://arxiv.org/abs/2308.12008)).

  Plan: fine-tune BGE-M3 with LoRA on Greek↔English pairs (corpus translation links plus Krahn's released parallel data, licence to be checked). Hard negatives come from:
  - the same work's neighbouring passages;
  - BM25-top non-targets;
  - other-author passages with high cosine.

  Mirrors are excluded via `text_key`. In the lab, compare against SPhilBERTa (base size, so roughly 3–4× cheaper on CPU, *est.*).
- **BGE-M3 sparse output (learned sparse).** The dense, sparse and multi-vector outputs come from one forward pass ([Chen et al., arXiv 2402.03216, 2024-02](https://arxiv.org/abs/2402.03216)). Only the sparse output is adopted, stored as an SQLite inverted table. No multilingual SPLADE checkpoint with credible Greek coverage turned up in this research.
- **Reranking is opt-in only, until proven.** Rerank the top 20 with a base-size multilingual cross-encoder (jina-reranker-v2-base-multilingual, 278M params, XLM-R base, [Jina, accessed 2026-10-07](https://jina.ai/models/jina-reranker-v2-base-multilingual/), int8 ONNX), scored against the English bridge text. The alternative is Jev listwise: one `choice` question over 20 candidate IDs, about 6k input tokens, roughly $0.00025 at the quoted price. Because Jev returns a probability vector, a listwise ranking falls out of the existing adapter. Neither arm ships unless it wins on the *short thematic* family.

## 3. Model options (CPU, 2 cores, 8 GB)

| Model | Params | RAM fp32 / int8 | CPU query (*est.* unless marked) | Greek evidence | Verdict |
|---|---|---|---|---|---|
| BGE-M3 (current) | 568M | ~2.3 GB / ~0.6 GB | **0.41 s** short query (*measured*, 2 threads); passages 0.38/s at 410 tokens (*measured*) | none for Ancient Greek; R@10 0.11 dense-only in the lab | keep; add sparse; LoRA fine-tune |
| SPhilBERTa | ~125M (RoBERTa base) | ~0.5 / ~0.15 GB | ~0.1 s | trained for grc/lat/eng cross-lingual parallels | **lab A/B as a second dense list** |
| Krahn et al. AG sentence models | base | ~0.5 GB | ~0.1 s | AG translation search and retrieval evaluated | lab A/B (check licence) |
| Ancient-Greek-BERT (Singh et al. [2021](https://aclanthology.org/2021.latechclfl-1.15)) | base | ~0.5 GB | — | MLM and POS only; not a sentence encoder | token embeddings for word alignment only |
| GreBERTa / PhilBERTa ([Riemenschneider & Frank, 2023-05](https://arxiv.org/abs/2305.13698)) | base | ~0.5 GB | — | morphosyntax SOTA; not retrieval-trained | fine-tune base candidate (stage 3+) |
| Qwen3-Embedding-0.6B / Reranker-0.6B ([arXiv 2506.05176, 2025-06](https://arxiv.org/abs/2506.05176)) | 0.6B | ~2.4 GB | ≈BGE-M3 | strong MMTEB; no Ancient Greek data | lab only |
| multilingual-e5-large, Arctic-embed-l-v2.0, Nomic v2 | 0.3–0.6B | 1–2.3 GB | ≈BGE-M3 | modern-language benchmarks only | lab only if cheap to try |
| jina-embeddings-v3 | 572M | ~2.3 GB | ≈BGE-M3 | — | licence reported as non-commercial; verify before any use |
| LaBSE | 471M | ~1.9 GB | ~0.3 s | bitext mining | alignment helper, not thematic search |
| bge-reranker-v2-m3 | 568M | ~2.3 / ~0.6 GB | 20 pairs × ~300 tokens ≈ 25–40 s (consistent with the lab's 1.3 s/pair) | — | **reject for live use** |
| jina-reranker-v2-base / gte-multilingual-reranker-base | 278–306M | ~1.1 / ~0.3 GB | 20 short pairs ≈ 2–6 s | — | opt-in "deep" arm only |
| ColBERTv2/PLAID, BGE-M3 multi-vector | — | index ≈ 116k × ~200 tokens × 1024 × 2 B ≈ **47 GB** uncompressed | PLAID: ~136 ms CPU at MS MARCO scale with 1-bit residuals ([arXiv 2205.09707, 2022](https://arxiv.org/abs/2205.09707)) | — | **reject**: compression engineering and RAM do not fit the box |

**RAM budget on the box** (resident alongside odyCy, the API and the page cache): BGE-M3 fp32 is about 2.3 GB, vectors are 0.45 GB (0.11 GB as int8), and the sparse table is about 0.2 GB on disk (*est.*). A second base encoder adds about 0.5 GB, and a base reranker in int8 adds about 0.3 GB. Two concurrent large models would push the box toward swap, which is why the large reranker is excluded.

## 4. Index build cost

| Job | Where | Cost |
|---|---|---|
| Dense (+ sparse) re-embed of 116k eligible passages with header | laptop RTX 3070 | about 124 passages/s was reported before full-window pooling (`docs/semantic-models.md`), so ≈ 20–40 min *est.* On the box CPU it would take about **85 h** (0.38 passages/s *measured*), so never build there |
| Same, if all 288k rows were embedded (lexicon included) | laptop GPU | ≈ 1–1.5 h *est.*; not recommended, since `reference` rows are lexicon entries |
| LSJ sense-gloss vectors (~126k entries in `data/lexica/entries.jsonl`; sense count unknown, perhaps 3–5×) | laptop GPU | short spans, ≈ 10–20 min *est.*; int8 ≈ 0.4–0.6 GB, binary ≈ 60 MB |
| odyCy lemma column over 103k Greek texts | laptop GPU | unknown; measure on 1k passages first |
| LoRA fine-tune of BGE-M3 (seq 256, fp16) | laptop 8 GB GPU or vast.ai | a few GPU-hours *est.*; pairs ≈ 5k corpus links plus external parallel data |
| Box deployment | — | copy the `.npy`/rows/sparse table; manifest-hash bound as today |

## 5. Contextual sense and parse ranking

| | Current packet approach | Proposed definition matching (local, free) |
|---|---|---|
| Inputs | all senses, whole translations, syntax, commentary | the same inventory, form-filtered |
| Context for the target | the whole passage | the line with the target marked, plus the **aligned English word(s)**, found by embedding-argmax word alignment (SimAlign-style, BGE-M3 token states). Keersmaekers et al. use translation alignment to source Ancient Greek WSD data and report good results for frequent words ([ALP 2023](https://aclanthology.org/2023.alp-1.18)) |
| Scoring | Jev choice probabilities, uncalibrated | s1 bi-encoder cos(context, gloss) (BEM-style: [Blevins & Zettlemoyer, ACL 2020](https://aclanthology.org/2020.acl-main.95), largest gains on rare senses); s2 cross-encoder(aligned English span + line translation, "lemma: gloss") for ≤30 senses; s3 priors: the LSJ sense cites a lyric or Aeolic author, or a Campbell lemma note for this line contains the gloss or a "(=…)" equation |
| Cost / latency | ≤3 paid calls per selection, 8 s timeout, budgeted | precomputed gloss vectors plus one ~0.4 s encode; cross-encoder ≈ 1–3 s *est.* |
| Abstention | p≥0.75 and margin≥0.2 | local margin threshold τ, set on LOO-dev to a target selective accuracy |

Rules:

- The local scorer **never prunes or reorders the Jev packet**. The packet states that "the listed order is not a contextual ranking" (`sense_ranker.py:295`), and showing Jev local scores risks anchoring it.
- The lab compares Jev arm A (packet unchanged) against arm B (local scores added as a labelled field).
- Jev is called only when the local margin is below τ, which saves budget.
- Parse ranking keeps `_affinity`. The local scorer adds s2 (aligned English carries number/tense cues) only if it improves parse acc@1 on the gold set.

## 6. Staged rollout

| Stage | Ships | Model risk | Gate |
|---|---|---|---|
| 0 Harness (no prod change) | `lab_eval` gains nDCG@10, R@50 (`--limit 50`), bootstrap CIs, a Greek-only-target slice and a `thematic_short` family; sense gold set (§7) and batch sense evaluator | none | — |
| 1 Cheap channels | gloss bridge (L5), forms→lemma expansion for Greek queries, weighted-RRF re-tune, header re-embedding, int8 copy kept for A/B | low | §7 search gate |
| 2 Local sense scorer | s1+s3, displayed as "local fit, uncalibrated"; Jev gated by margin | low | sense gate |
| 3 Encoders | odyCy lemma column (L3), BGE-M3 sparse (D2), LoRA BGE-M3 vs SPhilBERTa (D3) | medium (leakage, forgetting) | search gate on TEST |
| 4 Opt-in deep rerank | base cross-encoder or Jev listwise, behind a button | medium (latency/cost) | must win on `thematic_short` |

## 7. Evaluation protocol

**Search data.**

- Reuse `/lab/eval-queries.jsonl` from `lab_build_eval.py` (195 queries; `exclude_ids` kept).
- Split by `work_id` into DEV and TEST (50/50, frozen hash). Tune weights and τ only on DEV. Touch TEST once per stage.
- Add `thematic_short`: 60–100 owner-written English (and some Greek) queries of ≤8 words, judged by pooling the top-20 of every method and grading each pooled passage 0/1/2. These are synthetic fixtures under `docs/retrieval-evaluation.md` rules.
- Add `greek_only_target`: queries whose target has no English bridge after exclusion.
- **Leakage control:** fine-tuning pairs exclude every TEST parent and its `text_key` copies, and every query's source record.

**Search metrics** (per family and overall):

- nDCG@10: graded for `thematic_short`, binary (1/log₂(1+rank)) elsewhere
- MRR@10
- R@10 and R@50: R@50 is the candidate-stage ceiling for any reranker
- p50/p95 latency **on the box**
- 1,000× paired bootstrap 95% CI on the difference from `hybrid_prod`

**Search ship gate:**

- TEST nDCG@10 improves by ≥0.03 absolute, with the CI excluding 0
- no family regresses by more than 0.02
- literal fixtures stay 18/18
- default-path p95 ≤ 1.5 s on the box

**Sense gold set** (Alcaeus 34a, 129, 130b, 326, 350):

- **Items:**
  - every printed word with ≥2 parse candidates (parse items);
  - every content word with ≥2 form-compatible senses (sense items).
- **Labels:** the owner records, blind to system outputs:
  - the set of acceptable parse IDs and acceptable sense IDs (multiple allowed);
  - `undecidable`, meaning abstention is correct;
  - or `not_in_inventory`.
- **Evidence:** cite the supporting Campbell paragraph ordinal from `backend/edition_commentary_data.json` (63 lemma-anchored notes, e.g. 34a.8 "ζακρυόεντος (=δια-)", 34a.9 "ἐπ’: ὂν (=ἀνά) is possible").
- **Review:** a second pass a week later. Report disagreement with the first pass as a self-consistency rate.
- **Size:** unknown until the inventories are dumped; likely ~150–250 parse items and ~50–120 sense items (*est.*). This is a dev/regression set, not evidence of general accuracy. Tuning uses leave-one-poem-out.

**Sense metrics:**

- **acc@1** over decidable items
- **MRR** over the sense list
- **coverage** (share of items not abstained)
- **selective accuracy** at that coverage
- **abstention-calibrated accuracy** = (correct proposals + abstentions on `undecidable`/`not_in_inventory`) / all items
- the **risk–coverage curve and AURC**
- **ECE** of Platt-scaled local margins (LOO)
- **Jev calls and input tokens per item**

All metrics carry Wilson 95% CIs.

**Baselines:**

- B0: dictionary order (first compatible sense)
- B1: current Jev packet, run as a bounded paid run with receipts, like `scripts/evaluate_lyric_context.py`, which needs a batch mode beyond its 3-form cap
- B2: local s1+s3
- B3: B2 with Jev gating, arms A and B

**Parse metric:** acc@1 of `_affinity` against Jev against local+`_affinity`.

**Sense ship gate:**

- B2 or B3 must exceed B0 and B1 on abstention-calibrated accuracy, with non-overlapping CIs or at least a pre-registered margin of ≥0.05
- no increase in wrong proposals at equal coverage

## 8. Risks and open questions

| Risk / unknown | Mitigation |
|---|---|
| Gold sets are tiny and single-annotator, so CIs will be wide | report CIs, treat results as directional, and add a second annotator if one is available |
| Lab queries are translations, not themes; past reranker failure may not transfer either way | the `thematic_short` family decides reranking |
| Fine-tuning on the same links the lab uses causes leakage | work-level split and `text_key` exclusion |
| Aeolic, fragmentary and bracketed text weakens alignment and embeddings | run on `token.form`; evaluate fragments separately; abstain on `editorial_fragment` |
| The gloss bridge and lemma channel add polysemy noise | separate RRF weight, plus an ablation |
| Translation bias: English bridges reflect the translator's interpretation (Krahn et al.) | keep provenance in `matched_evidence`; Greek-only mode is unchanged |
| LLM-generated context or summaries would be invented text | lab only, labelled, owner decision required |
| Box latency and RAM differ from laptop measurements; odyCy and Morpheus compete for 2 cores | measure on the canary container before any stage ships |
| Licences (Krahn data, SPhilBERTa, jina-v3) are not yet confirmed | check before training or shipping |
| Is an English translation linked to each Alcaeus poem in the production corpus? (The local corpus has none; Edmonds/CHS material sits in `runtime/alcaeus-translations/`) | confirm; without one, s2 alignment is unavailable for the gold set |
| Jev listwise reranking is outside its documented choice use and its probabilities are uncalibrated | lab only |

*Sources accessed 2026-10-07; dates are publication dates.*
