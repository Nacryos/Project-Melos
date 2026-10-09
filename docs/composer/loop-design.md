# Melos composer: loop design (draft for owner review, 2026-10-09)

**Goal.** A live companion for writing authentic Greek verse in a chosen poet's manner: Sappho, Alcaeus,
Anacreon, Pindar, Homer and others. An LLM proposes. Deterministic linters, built on Melos's corpus, lexica,
parser and scanner, accept, warn or reject. Every suggestion cites the passages behind it.

Status of this note: design and exploration only. No backend or js code was touched.

Companion files:
- [loop-diagram.html](loop-diagram.html): the loop drawn, with each linter marked exists / partial / missing
- [exercise-log.md](exercise-log.md): a Sapphic stanza built by hand with the live API (48 calls)

## 1. Lessons from the Troy harness (`C:\Users\alvin\troy-dubbing`)

**The Troy loop.** It runs in stages, and a human approves each one.

1. **Retrieve.** The `homer-search` MCP (FAISS + BM25 over the Iliad and Odyssey) returns about 8 passages, and the
   user prunes them.
2. **Gather vocabulary and grammar.** `autenrieth.py` supplies the Homeric dictionary, `monro.py` the Homeric
   grammar, and formula injection adds formulae. The result is a candidate pool plus constraints.
3. **Generate.** `generate.py` (LiteLLM) fills the `stage_3_generate.md` prompt: hard constraints, a 28-item
   principle checklist, at least 4 kept Homer passages, and the JSON shape `{greek, homer_draws_from, notes}`.
   Several models each give 1–2 variations.
4. **Validate.** `validate.py` is the hard gate. A Morpheus lemma must be in Autenrieth, and the form must be
   positively Homeric: in Autenrieth's text, or tagged epic/Ionic/Aeolic by Morpheus or Wiktionary. Attic-only
   forms are rejected. Particles and names must be attested in both epics. A curated allow-list of rare
   forms, each with its citation, is accepted. The extra state `form_unverified` (lemma fine, form unproven)
   is upgraded if Monro or the Homer corpus attests the form.
5. **Count syllables.** `syllables.py` requires the Greek to be within ±1 syllable of the English.
6. **Critic.** `stage4_critique.py` runs a 10-item rubric on gpt-4o-mini (person, part of speech, frame,
   number concord, register…). Its flags are advisory only.
7. **Repair.** The rejected attempt and its full validation record go back to the model with "Fix the
   rejections above". It stops at the first attempt that passes validation, is within ±1 syllable and parses
   as JSON. After 3 failures it halts, and halted candidates are still shown.
8. **Human gate.** The user chooses from a side-by-side table. Accepting an invalid line needs
   `--override-justification`. A professor's vetting is final (`prof_vetted`). In chunk mode, every stage is
   checkpointed with an append-only `audit.jsonl`.

**What went wrong** (`docs/LESSONS_LEARNED.md`, memory notes):

| # | Lesson | Consequence for Melos |
|---|---|---|
| T1 | There was **no metre scanner**: syllable count only. Line shape came from Homer lifts and a professor's fixes. | Scansion must be a first-class linter that says which unit breaks, not just "fits / does not fit" |
| T2 | Validator false positives: apostrophe glyphs, mixed Morpheus dialect tags, sentence-initial capitals read as names, regular endings with no dialect split | Use Melos's normalisation contract (four apostrophe glyphs, U+1FBF kept). Grade results pass / warn / fail, never a bare reject. |
| T3 | **44 % of segments had semantic errors that no validator sees**: wrong person in a lift, wrong case after a preposition, missing κε, unbalanced μέν/δέ, enclitic at clause start | Agreement and syntax need their own deterministic linters. "Valid forms" ≠ a valid sentence. |
| T4 | The LLM critic produced **~70 % false flags**. The rubric was narrowed with non-examples. | Keep the LLM out of the gate. A critic may annotate, but never block. |
| T5 | LLMs play safe: bland diction, lines kept short on syllables | Score authenticity *positively* (the author's collocations and images), not just the absence of errors |
| T6 | Whole-sentence prompts fail; parallel segments sharing context work | Compose line by line or colon by colon, with the stanza as shared context |
| T7 | Top pick matched the user's choice only 52–68 % of the time; ~32 % of final lines were hand-edited hybrids | The human edit loop *is* the product: make editing instant and well-informed |
| T8 | Pipeline problems: the splitter dropped lines, JSON broke, quota ran out, nested agents were impossible | Use a Python orchestrator with checkpoints and a lenient JSON parser, and give linters no quota |
| T9 | "Attested only" discipline: an Aeolic form not in Homer was banned even for Achilles | Apply attestation **per target author or genre**, with an explicit "generated, unattested" warning |

**What carries over:** the staged orchestrator; checkpoints and audit pairs; the retry loop with the rejection
record fed back; at least 2 candidates; forced justification for overrides; and the triangulation "lemma OK ×
form positively attested in the target dialect", with an upgrade path for `form_unverified`.

## 2. What Melos has now (releases L–R, live 2026-10-09) and its fitness for a composer

| Tool (route) | Composer use | State | Notes from the exercise |
|---|---|---|---|
| Concept diachrony `/api/concept/diachrony` | English theme → Greek headwords | **partial** | Good for "moon". For "longing" it gave noise (μακρός, λέων) and missed ἵμερος. No author or genre filter. 1.4–2.5 s, 180–275 kB. |
| Semantic, theme and hybrid search `/api/search` | RAG: the poet's own images | **exists** | Excellent: Sappho 96/34/154/168B for the moon, 130/48 for longing. Whole passages only, no line span. |
| English → headword `/api/lemma/resolve` | Lexical options | exists | Head-meaning rule (πόθος, ἵμερος) |
| Frequency and distribution `/api/lemma/frequency` | Author/genre attestation and rate | **partial** | Rates with CIs per author. Sappho counts (13) disagree with the concordance (4–5). |
| Lemma search `forms_found` | The author's **form inventory** | **partial** | The most useful attestation tool. Counts are per record (σελάννα ×12 for 4 loci). |
| Concordance `/api/lemma/concordance` | Parallels (KWIC) | exists | Folds editions; one renumbered copy slipped through |
| Collocations, n-grams | Author phrase profile | **partial** | Edition duplicates inflate counts ×3–4 in Sappho. Lemma n-grams only. |
| Proximity `/api/lemma/proximity` | Image-pair parallels | partial | Misses Ἔρος/ἔρος unless `combine_variants=true` |
| Variant groups `/api/lemma/variants` | Dialect alternatives | **partial** | Links dictionary headwords only; does not generate dialect spellings |
| Dictionaries `/api/word?compact=true`, `/api/evidence` | Senses, source claims | exists | Middle Liddell, LSJ, Autenrieth and others, with source quotes |
| Headline parses `POST /api/words/headlines {forms}` | Form-exists (fast, 400 forms) | **partial** | ~300–400 ms. Misses forms with an enclitic-thrown accent (θῦμόν) or psilosis (εὔδω). Aeolic ᾱ-stems are read as duals or plurals. |
| Machine morphology `POST /api/machine-analysis` | Form-exists for unseen forms | partial | Local Morpheus with dialect tags (ὄρησθα: epic Aeolic). Quota of 20 a day per visitor. |
| Passage analysis `POST /api/analyze-passage` | Contextual parse, dialect gates, OdyCy syntax | **partial** | Release R Lesbian/Doric gates. Needs a stored `passage_id`, so a draft cannot be analysed. |
| Internal `dialect_generate.py`, `aeolic_variants.py`, `dialect_rules.py`, `elision.py` | Dialect linter, elision | partial (internal) | Rules run Lesbian → Attic only (for parsing). The composer needs Attic → Lesbian generation. |
| Citations `/api/cite` | Provenance | exists | Fragment-numbering concordance with a strength label. Gives records, not line loci. |
| Scanner (branch `scansion`) | Metre linter | **partial (not live)** | Layer 1: p_long per unit, with rule and reason. Layer 2: templates (Sapphic, Alcaic, glyconic…), violations, responsion. 5–50 ms per stanza. Not aware of Aeolic ᾱ length (a false pass in the exercise). |
| Author profiles (P2) | Style profile seed | partial | Identity and dialect claims only. No lexical or metrical profile. |
| Passage dialect `passage_dialect.py` | Target dialect per author | exists (internal) | Sappho/Alcaeus Lesbian, Alcman Laconian, choral poets literary Doric |

## 3. Gap list from the exercise (ranked by composer impact)

| # | Gap | Evidence (exercise call) | Fix |
|---|---|---|---|
| G1 | **No text-in analysis.** Parse ranking, dialect gates and syntax run only on stored passages. | #47, `PassageRequest` needs `passage_id` | `POST /api/compose/analyze {text, author}`, reusing `PassageAnalysisService` on an ephemeral passage |
| G2 | **No dialect generator** (Attic → Lesbian/Doric spelling). πήλοθεν was found by luck. | #17–20, #37 | Invert the `dialect_generate` rules, then filter by the parser and the author's inventory |
| G3 | **Attestation counts per record, not per locus**: frequency, `forms_found`, collocations and n-grams are inflated ×3–4 for Sappho | #9–16, #21–26 | Fold editions by locus (fragment-concordance key) in every count |
| G4 | **Scanner lacks dialect vowel length** (Aeolic ᾱ < η); false pass on σελάννα | scanner draft 1 | Map η ↔ ᾱ in the quantity lexicon; per-dialect accent rules |
| G5 | **Morpheus quota** (20 a day) blocks form checking at composer volume | #31, #36 | An internal, unmetered parse service for the composer (it is local Morpheus already) |
| G6 | Headline index misses enclitic accents (θῦμόν), psilotic spellings (εὔδω) and Aeolic singular ᾱ-stems (σελάννα read as a dual) | #8, #47 | Accent-normalised lookup key; run the release R gates in the headline index |
| G7 | `combine_variants` is off by default, so Ἔρος/ἔρος parallels are missed (fr. 47, fr. 130) | #40, #44–46 | Composer queries always combine variants |
| G8 | Concept search: no author or genre filter, noisy neighbours, ἵμερος missing, `max_lemmas` ignored | #3–5 | Add `author`/`genre` filters; require gloss support for semantic-only rows |
| G9 | No **slot query**: "headwords of shape ⏑⏑– meaning X, attested in Sappho" (λυσιμέλης cannot fit Sapphics) | scanner draft 2 | Precompute each form's prosodic shape in the index; add `GET /api/compose/slot` |
| G10 | Parallels come back as whole fragments; no line or span locus to cite | #6, #30, #48 | Return line spans and `line_numbers` on search and cite results |
| G11 | Lemma index error: οἶος "alone" has 1 token (absorbed by οἷος) | #29 | Audit breathing and accent homographs |
| G12 | No surface-form or metrical n-grams (style shapes, Aeolic forms) | #24 | A form-level n-gram table with scansion shapes per author |

**Release U (backend, 2026-10-09)** closed these gaps in the API (contract: docs/api-contract.md "Release U additions";
numbers: docs/deployment.md, release U). Design decisions and the open questions in § 7 are unchanged.

| Gap | Release U |
|---|---|
| G1 | `POST /api/analyze-text {text, dialect?, author?}`: a draft analysed like a stored passage (compact response). Latency is about 0.8 s for a warm 4-line stanza, not the 150 ms keystroke budget of § 4.8. |
| G2 | `POST /api/dialectize`: Attic → Lesbian/Doric/Ionic spellings, kept only when attested in the corpus or parsed by local Morpheus, each labelled with its rules (πήλοθεν, σελάννα, ἀέλιος, φέροισα, ἄγην, μόνα) |
| G3 | Each fragment counted once across editions (frequency, `forms_found`, collocations, concordance, n-grams): Sappho σελήνη 13 → 4, πόθος 13 → 4, μόνα 4 → 1 |
| G5 | Local Morpheus has no per-visitor allowance; a per-client rate limit protects it |
| G6 | `/api/words/headlines` forms mode: θῦμόν, εὔδω, σελάννα and μόνα (singular with a Lesbian author), αὖτε, Ἄτθι (the name Atthis) |
| G7 | `/api/lemma/proximity` combines variant groups by default |
| G8 | Concept search scoped by `author` / `genre`, read through head meanings ("longing": πόθος, ἵμερος; no μακρός, λέων); `max_lemmas` honoured |
| G10 | `best_line` on search results, `line` on concept examples, `cited_line` on cite results |
| G4, G9, G11, G12 | Not in release U (scanner branch, slot index, οἶος/οἷος audit, form n-grams) |

## 4. The composer loop

```
input (English poem | theme | owner draft) + target profile (author, metre, dialect)
  → plan: line-by-line meaning slots, metre template per line
  → retrieve: concept → headwords (author-filtered) → parallels (search, proximity, concordance, commentary)
  → propose: LLM, k candidates per line, grounded in the retrieved passages, JSON with draws_from per word
  → lint: deterministic bank (L1–L11) → per-word and per-unit pass / warn / fail with evidence
  → repair: send failures plus slot suggestions back to the LLM; ≤ 3 rounds; deterministic fixes first
  → rank: authenticity score; show ≥ 2 candidates
  → live editor: the owner edits; scan and lint again on each keystroke; slot suggestions
  → output: stanza + scansion + per-word provenance (citations) + audit log
```

### 4.1 Input modes

| Mode | Unit of work | Specifics |
|---|---|---|
| English poem → line by line | One English line → one Greek line (or colon), with the stanza as shared context | Plan step aligns English lines to the metre template's lines. English syllable parity is not used (T1). |
| Free theme | Theme → concept headwords → image parallels → the LLM drafts a stanza | Images must come from the author's own parallels (L7) |
| Owner's draft | Owner text → lint at once; LLM only on request | The main mode for the "live companion"; the LLM is optional |

### 4.2 Style profiles (built offline, per author, one JSON each)

| Component | Source in Melos | State |
|---|---|---|
| Lexicon: headword rate per 10k, with CI, against the genre background (keyness) | `lemma/frequency` tables | partial (G3) |
| Form inventory: forms actually printed, with loci | `lemma/search forms_found` + concordance | partial (G3) |
| Dialect features: rules on or off (psilosis, ᾱ, -οισα, -μμι, recessive accent, πήλοθεν-type labials, ζ for δι, apocope) | `dialect_rules.py`, Campbell pp. 262–4, Hamm | partial (rules exist, used for parsing only) |
| Collocations and phrases (G², with loci) | collocations, n-grams | partial (G3, G12) |
| Images, similes, themes (moon/stars, wind on oaks, apples) | Theme clusters from semantic search and commentary bridges | missing (build from the search index) |
| Metres and line shapes (templates, word-end positions, caesura habits, line-end words) | Scanner over the author's corpus | missing (needs a live scanner) |
| Syntax habits (particles, address forms, vocative + imperative) | OdyCy over passages | missing |

### 4.3 Proposal step

- **Prompt contents:**
  - the target profile summary: dialect rules, metre templates, top keyness words
  - 6–10 retrieved parallels, in Greek, with citation ids
  - the meaning slot for the line
  - hard constraints in Troy style
  - the JSON shape `{greek, words:[{form, lemma, draws_from:[ids]}], notes}`
- **Candidates:** k = 3–5 per line from 1–2 models.
- **The LLM never gets the last word.** Each `draws_from` id is checked against the retrieved set, and any id
  not in that set is flagged "composer recall" (the Troy HQI-8 pattern).

### 4.4 Deterministic linter bank

Each linter returns `{id, verdict: pass|warn|fail, span, evidence:[{passage_id, citation, quote}], fix_hints}`.

| ID | Linter | Rule | Data | Verdict | State |
|---|---|---|---|---|---|
| L1 | Form exists | Parser yields ≥ 1 analysis for the exact spelling (accent-normalised for enclitics) | headline index, then local Morpheus (unmetered), then the dialect generate-and-test | fail if none; warn if only via a generated spelling | **partial** (G5, G6) |
| L2 | Dialect consistency | Every form agrees with the profile's dialect: Lesbian psilosis, ᾱ, -οισα, recessive accent; Ionic η rejected for Sappho (μοῦνα) | `dialect_rules`, Morpheus `dial` tags, author inventory | fail on a contrary dialect tag with no author attestation; warn if unattested | **partial** (G2) |
| L3 | Agreement | Case/number/gender inside the NP; subject–verb person and number; preposition + case; article–noun | OdyCy over draft text + parses | warn (syntax is a model); fail only on parse-certain clashes | **missing** (G1) |
| L4 | Lexical attestation | The headword and the form are attested in the author (by locus), else in the genre, else in the corpus; rate per 10k | frequency, `forms_found` | pass in author; warn genre-only; warn "epic only" (ἄμμορος); fail if unattested | **partial** (G3) |
| L5 | Collocation plausibility | Each content-word pair within ±4 has G² > 0 in the author or genre, or a cited parallel | collocations, proximity (variants combined) | warn on zero-evidence pairs | **partial** (G3, G7) |
| L6 | Concept / image authenticity | Each image maps to ≥ 1 parallel in the author (else the genre), with the quote | hybrid search + proximity | warn "image not in author", with the nearest parallel | **partial** (G8, G10) |
| L7 | Metre | Scanner layer 1 p_long per unit + layer 2 fit to the chosen template. Lists the units that break (needs short, scanner L, rule, reason) and the dichrona left open. | `scansion` branch | fail on a violation; warn on ambiguous units (0.3–0.7) at fixed positions | **partial** (not live; G4) |
| L8 | Elision and hiatus | Elided vowel restorable (`elision.py`); flag hiatus between words unless the following word had digamma (Homer) or the position is the line end | elision model, digamma list (scanner data) | warn on hiatus; fail on an impossible elision (a long vowel) | partial |
| L9 | Accentuation | Recompute the accent from the syllable quantities and the dialect rule (Lesbian recessive; enclitic throw-back), and compare | scanner units + accent rules | warn (editors differ) | **missing** |
| L10 | Particles and word order | Postpositives not first in the clause (Troy T3), μέν/δέ balance, κε/ἄν mood | rules + OdyCy | warn | missing |
| L11 | Novelty / plagiarism | Flag a run of ≥ 4 consecutive author tokens copied verbatim (homage vs copying is the owner's choice) | n-grams / sequence search | info | partial |

The authenticity score used for ranking is the weighted sum of L4–L6 evidence strength. Only L1, L2, L7 and
L8 failures block.

### 4.5 Repair loop and stopping rules

1. **Deterministic fixes first, with no LLM.**
   - L2: the dialect generator swaps the form (τηλόθεν → πήλοθεν, μοῦνα → μόνα).
   - L1/L9: accent and psilosis normalisation.
   - L7: the slot query proposes forms of the right shape and meaning (G9).
2. **LLM repair.** The prompt gets the failing linter records (Troy's `PRIOR ATTEMPT (REJECTED)` block) plus
   the slot suggestions. The LLM may change word order or lexical choice.
3. **When to stop:**
   - accept as soon as there are no blocking fails and every warning is either explained or below its threshold;
   - otherwise halt after 3 LLM rounds, or 90 s a line, or once the authenticity score stops improving over 2 rounds;
   - halted candidates are still shown with their linter records;
   - an override needs a typed justification, which is logged.
4. **Human gate.** The owner picks or edits; the edit re-enters the lint step only, not the LLM.

### 4.6 Live interactive mode

- The owner types or replaces a word, and the client sends the line text (debounced at 120 ms).
- The server returns scansion units, the template fit and the linter verdicts. The UI colours each syllable
  by p_long and marks breaking units with their rule and reason.
- **Clicking a word** opens slot suggestions: forms that (a) fit the metrical shape of the slot, (b) share
  the concept or a synonym, (c) are attested in the author or genre, and (d) agree with their neighbours. They
  are ranked by authenticity, each with its best parallel quote and citation.
- **Clicking a form** offers alternatives: same lemma, other case or dialect spelling that fits the slot.

### 4.7 Provenance

- **Per suggestion:** every candidate word carries `lemma`, the `parse`, `attested_in` (author, loci count,
  top 3 citations with quotes), `dialect_basis` (rule or attested form) and `draws_from`.
- **Per line:** the scansion, with each unit's rule.
- **Audit:** an append-only audit JSONL per composition, as in Troy.
- **Export:** Greek text, scansion, and footnotes with citations.

### 4.8 Latency budgets

| Action | Budget (p95) | Basis today |
|---|---|---|
| Keystroke → scan + L1/L2/L7/L8/L9 | ≤ 150 ms | Scanner 5–50 ms locally; headline index 2–3 ms in-process. The ~300 ms public round trip means this must run in one composer endpoint. |
| Click → slot suggestions (top 10) | ≤ 500 ms | Needs a precomputed shape index (G9) |
| Full lint incl. L3 agreement and L5/L6 evidence | ≤ 1.5 s | OdyCy and search 0.3–1.3 s today |
| Retrieval for a line (concept + 2 searches + proximity) | ≤ 4 s | diachrony 1.4–2.5 s + search 1.3–1.6 s |
| LLM proposal, k = 3–5 | ≤ 20 s | One model call |
| Repair loop per line | ≤ 90 s, ≤ 3 rounds | Troy experience |

## 5. API needs (new routes; all read-only over existing indexes)

| Route | Purpose | Built from |
|---|---|---|
| `POST /api/scan {text, metre?, dialect?}` | Units with p_long, rule and reason; fit, violations, posterior | `backend/scansion` (branch) |
| `POST /api/compose/analyze {text, author, metre}` | One call: tokens, parses (with dialect gates), scan, linter bank L1–L11 with evidence | `PassageAnalysisService` on an ephemeral passage + scanner + lemma index |
| `GET /api/compose/slot?shape=⏑⏑–&concept=&lemma=&author=&case=` | Forms of the right shape, ranked by authenticity, with citations | New shape column in the lemma index |
| `POST /api/compose/dialectize {forms, dialect}` | Attic → Lesbian/Doric spellings, parser-verified and attestation-marked | Inverted `dialect_generate` |
| `GET /api/compose/profile?author=` | Style profile JSON (§4.2) | Offline build script |
| Changes to existing routes | `author`/`genre` on concept diachrony; locus-folded counts everywhere; `combine_variants` default for composer; line spans on search and cite | Lemma index, search |

## 6. Phased build plan

| Phase | Deliverable | Depends on | Size |
|---|---|---|---|
| C0 | Ship the scanner (`/api/scan`) with Aeolic ᾱ lengths and a Lesbian accent rule (G4) | `scansion` branch | M |
| C1 | Locus-folded counts and `combine_variants` defaults (G3, G7); fix the οἶος/οἷος split (G11) | lemma index rebuild | M |
| C2 | `compose/analyze` for text input (G1): L1, L2 (rules only), L4, L7, L8 | C0, C1 | M |
| C3 | Dialect generator and unmetered internal parser (G2, G5, G6) | C2 | M |
| C4 | Style profiles for Sappho, Alcaeus, Anacreon, Pindar and Homer (§4.2); slot index (G9); form/metrical n-grams (G12) | C0–C1 | L |
| C5 | Live editor page (owner only, private mode T), with slot suggestions and provenance panel | C2–C4 | L |
| C6 | LLM proposal + repair orchestrator (Troy port: checkpoints, audit, ≥ 2 candidates, override log) | C2–C5 | M |
| C7 | L3 agreement, L9 accent, L10 particles; evaluate on held-out real stanzas (they must pass) and on corrupted stanzas (they must fail) | C2 | M |

**Evaluation from the start:**
- *Real poems must pass.* Every Sapphic stanza in the corpus should pass L1/L2/L7 at ≥ 95 %.
- *Corrupted poems must fail.* Seeded errors (Ionic η, wrong quantity, bad agreement) must be caught at ≥ 90 %.

## 7. Open questions for the owner

1. **Mixing dialects:** should Sappho mode allow Homeric forms that Sappho herself uses (the epic colouring
   of fr. 44)? Should "attested in Homer" be a warning or a fail?
2. **Copying:** may lines lift ≥ 4-word runs from the author (homage), or should L11 block them?
3. **Which LLM, and where:** Claude via the API key on the box, or local? Does the composer run only in
   private mode T, never public?
4. **Accentuation:** follow Voigt / Lobel-Page conventions (Lesbian recessive), or Attic accents as in
   Campbell?
5. **Metres first:** Sapphic and Alcaic stanzas, glyconics, hexameter? Is Pindaric responsion (strophe ↔
   antistrophe via `metre.responsion`) in scope for v1?
6. **Output form:** text only, or also an audio reading (pitch accent)?
7. **Who audits:** is there a professor-equivalent reviewer, as with Troy (`prof_vetted`)?
