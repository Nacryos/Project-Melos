# PRD: Latin verse composer (Catullan hendecasyllables first)

Owner: Alvin. Written 2026-10-10 (Pacific) by the Latin session on Basecamp, from the owner's brief
(`~/work/latin-composer-brief.md`). Branch: `latin-composer`, based on `composer-w` (release W, live 2026-10-10).
Status: draft for adversarial critique (§11), then build. Mirrors `docs/prd/composer-agent.md`.

## 1. Goal

The owner wants the whole composer experience for Latin, starting with Catullan Phalaecian hendecasyllables:
the same owner-only page at greeklyric.com, the same Fable 5.1 line proposer, the same deterministic linters
(metre, attested vocabulary, frequency/concept/imagery), live metre-agnostic scansion on the board. Target order:
**Catullus, then Horace (Odes, Epodes, Carmen Saeculare), then the minor Roman lyric poets** ranked by their
usefulness to a hendecasyllable composer. Everything is a `language=la` switch on the release W code, not a fork.

The two bottlenecks the owner named, and what this PRD does about them:

| Bottleneck | Owner's doubt | What is built |
|---|---|---|
| Latin metre as a decision-tree program | Latin vowels carry no fixed length the way η ω ε ο do; but inherent length plus position fixes most quantities and macronised dictionaries exist. How far does that hold, and what coverage do the resources give? | A Latin sibling of the Greek scanner (same engine, a Latin rules file), a macronised quantity lexicon with per-source provenance, and a **coverage report** on Catullus: what share of syllables the position rules alone decide, what the lexicon adds, what stays open (§4.3) |
| A solid database of Catullus, Horace and the minor lyric poets with a literal interlinear translation | Open translations where they exist; else an Opus subagent writes them | Corpus with source records (URL, edition, fetch time, hash), public-domain literal translations first, Opus-written interlinear stored as `machine_translation` and shown only where no human translation exists (release X convention) |

## 2. What exists (release W) and what Latin reuses

| Piece | Greek state | Latin plan |
|---|---|---|
| Scanner engine `backend/scansion/engine.py` | Language-neutral interpreter of a two-tree YAML grammar with a safe expression language; features are supplied by the quantity module | **Reused unchanged.** A new feature set and rules file for Latin (§4) |
| `syllabify.py`, `quantity.py`, `greek.py` | Greek letters, nuclei, units, features | New `latin.py`, `syllabify_la.py`, `quantity_la.py` beside them (same dataclasses, so `metre.py` sees the same `SyllableResult`) |
| `metre.py` templates and `fit_line` | Templates in `- u x F D R X`; parses × priors; violations against near-certain units | **Reused.** Latin templates added (Phalaecian with its decasyllabic variant, then Horace's); a `language` tag on templates so `auto` ranks only the right language's metres |
| `lexicon.py` (`quantities.sqlite`: Morpheus, Wiktionary, LSJ) | per-letter L/S/u/e codes per source | Same table shape in `quantities_la.sqlite` from Latin sources (§4.2); same `Evidence` class |
| `gold.py` (Hypotactic Iliad) | gold loader + `scripts/scansion_eval*.py` | `gold_la.py` over Hypotactic Latin and Pedecerto; `scripts/scansion_eval_la.py` reports per syllable and per line |
| `/api/scan` | `dialect`, `metre`, `lexicon`, `params` | Adds `language: "grc" \| "la"` (default grc); Latin ignores `dialect` |
| Lint bank `backend/composer_lint.py` | L7 metre, L1 forms, L2 dialect, L4 attestation, L11 verbatim | `language` parameter: L7 via the Latin scanner; L1 via the Latin lemma index + lemmatiser (no Morpheus); L2 skipped (reports "not applicable"); L4 and L11 over the Latin corpus; new L8-la elision/hiatus notes (never block) |
| Composer routes and store | settings `{author, metre, dialect, theme}` | settings gain `language`; slot key version `v2` includes it (v1 keys stay valid for Greek poems) |
| Agent container, sessions, fills, prompts | Greek system prompt, Melos tools | Prompt selected by `settings.language`; tools unchanged but every call carries `language` so search, lemma and headlines routes answer from the Latin data |
| Page `composer.html` | TypeGreek board | `language=la` turns TypeGreek off (plain Latin input, no macrons required), board shading and pop-up unchanged |
| Corpus (`corpus.sqlite`, records carry `language`) | Greek | Latin records with `language: la` in the same contract; the search index and lemma index get Latin partitions. **Dev data only on this branch:** the live `melos-api*` containers and their mounts are never touched |

## 3. User experience (differences from the Greek PRD §3 only)

- Toolbar: **Language** (Greek / Latin). Latin sets poet (Catullus, Horace, …), metre (Phalaecian hendecasyllable,
  then Sapphic, Alcaic, Asclepiads, glyconic, pherecratean, Archilochians, iambic trimeter/senarius for Epodes),
  dialect hidden. Typing is plain Latin; `u`/`v` and `i`/`j` are accepted as typed and folded for lookups.
- Board shading is the Latin scanner's `p_long` per unit, with the reason on click ("short vowel before two
  consonants: long by position"; "final -a: nominative short or ablative long, 50 %"; "elision of final -um
  before initial vowel"). Elision is **shown**, not typed: the scanner proposes it at every vowel(+m) | vowel/h-
  boundary and the metre fit decides whether it happened; the unit stays visible, greyed, when elided.
- A **macron overlay** toggle writes the lexicon's quantities over the board (never required for typing, never
  stored in the poem; a quantity the lexicon does not know is left bare).
- Pop-up, versions row, back-translation, chat: unchanged. The chat's answers cite Catullus and Horace loci.
- Metre-locking is never applied in the composer (owner rule, unchanged): the scan exists to catch the owner's errors.

## 4. Workstream 1: the Latin scanner

### 4.1 Decision tree (`backend/scansion/rules_la.yaml`)

Same meta-grammar: a `vowel` tree sets `p_vowel` (the nucleus's own length), a `unit` tree sets `p_long` (the
syllable's weight), `flags` annotate. Every node has a reason and a citation (Allen & Greenough §§10-12, 603-612;
Gildersleeve & Lodge §§703-720; Raven, *Latin Metre*; Halporn-Ostwald-Rosenmeyer). First draft of the nodes, each
a versioned, falsifiable hypothesis with a rival and a measured share from the gold set (§4.4):

**Vowel tree.** DIPH (ae au oe ei eu ui as diphthongs where the lexicon or the spelling allows) → 1 · LEX-L /
LEX-S (macronised lexicon marks, per source) → `lex_long` / `lex_short` · MORPH-END (an ending whose quantity the
paradigm fixes, from the lemmatiser's parse: -ōrum, -ās, -īs, -ō abl.; -a nom./voc. short vs abl. long stays
open) · FINAL-O (final -o of verbs and 3rd-decl. nom.: long in Catullus with few exceptions; `final_o`) · FINAL-I /
FINAL-U long by default; FINAL-E short except abl. 5th decl. and adverbs (lexicon) · HIDDEN (the vowel stands before
two consonants: its own length is hidden and irrelevant to the metre; p_vowel recorded but the unit tree decides)
· UNK → `vowel_default`.

**Unit tree.** POS (two consonants, or x / z, after the nucleus, in or across words; h never counts; qu, gu, su
before a vowel count one; consonantal i/u (iam, uideo, maior = mai-ior double) by rule) → 1 · MCL (stop + liquid
l/r inside a word: in Catullus and Horace usually **no** position; `mcl_word`, default 0.2 pending measurement;
across a word boundary → no position, `mcl_boundary` 0.05) · ELISION (final vowel or vowel+m before a word
beginning with a vowel or h-: the unit is elided with probability `elision`, flag ELI-CAND; the metre layer takes
the merge the way Greek synizesis is taken) · PRODELISION (final vowel/-m + est/es → the e is lost; `prodelision`)
· HIATUS (no elision at the boundary: rare, flagged, `hiatus_keep`; after a monosyllabic interjection o / heu kept)
· BREVIS-BREVIANS (iambic shortening of a final long after a short syllable in disyllables: `iambic_shortening`,
low; Catullus is not Plautus) · FINAL-S (final -s after a short vowel before a consonant may not make position in
Catullus 116.8 and Lucretius: `final_s_drop`, very low for Catullus, 0 for Horace) · SYNIZESIS (ei, eo, ii, uu
inside a word: flag with `synizesis`) · OPEN → `p_vowel`.

**Flags.** ELI-CAND, PROD-CAND, HIA, SYN-CAND, FIN-ANC (line end: brevis in longo), CAESURA (word end at the
template's usual place: Sapphic after 5, hendecasyllable none fixed; reported, never scored).

Everything that differs from Greek is a feature in `quantity_la.py` (initial `h`, `qu`, consonantal i/u, `x`/`z`,
`-m` elision, `est` prodelision, no accent features, no digamma, no correption) and a node in the YAML; nothing is
hard-coded in Python that the owner would want to tune.

### 4.2 Lexical layer (`data/scansion/quantities_la.sqlite`)

Same table as the Greek lexicon (`key, akey, source, marks, lemmas`), one row per source per spelling; codes L/S
per letter, `u` unmarked. Candidate sources, each admitted only after its licence is quoted in the survey
(`docs/research/latin-scansion-prior-art.md`) and its marks audited on 100 random rows:

| Source | What it gives | Expected licence (to verify) |
|---|---|---|
| Wiktionary Latin (Kaikki dump, already on disk for Greek) | headwords and full inflection tables with macrons | CC BY-SA 4.0 / GFDL |
| Collatinus lexicon (lemmes.la, with quantities) | 11k+ lemmas with quantities and paradigms | GPL (data: check) |
| Johan Winge's macroniser (Alatius) word list / Morpheus Latin stems | stems with quantities, endings | check (code GPL; data derived from Morpheus Latin, Lewis & Short) |
| Perseus Lewis & Short `<orth>` with quantity marks | headword lengths | CC BY-SA 4.0 |
| CLTK `prosody.lat` macroniser dictionary (`macrons.txt`) | 100k+ forms with macrons | MIT (data provenance: check) |
| Hypotactic Latin word table (gold only) | per-form patterns from hand scansion | CC BY 4.0; **never** used in the lexicon (it would leak into the evaluation) |

Lookup: exact spelling (u/v, i/j folded), else lemmatiser → paradigm form, else unknown (`unknown_word`). Elided and
prodelided spellings are restored before lookup. The coverage report (§4.3) says what each source adds.

### 4.3 Coverage report (answers the owner's doubt)

On the Catullus hendecasyllable gold lines, per syllable: share decided by position alone (expected ~40 %), by
position + fixed endings, by position + lexicon (expected ~90 %), and what stays open (expected: nom./abl. -a,
hidden-vowel homographs that do not matter, elision choices, muta cum liquida), with the accuracy on the decided
set at each stage. The same table for Horace Odes 1 once Horace is in. This table is the PRD's first deliverable
after the survey; it is honest about both coverage and accuracy, never one without the other.

### 4.4 Gold and evaluation

- **Gold:** Hypotactic Latin (Chamberlain, CC BY 4.0, confirmed by his statement for hypotactic.com including the
  Latin pages; Catullus and Horace pages fetched directly from the site since the Urdatorn mirror holds only Greek)
  and Pedecerto / Musisque Deoque (licence to confirm; used as a second, independent gold set if its terms allow
  evaluation use, else not at all). Where the two disagree, the line is reported, not scored.
- **Protocol as for Greek:** rules are edited against a development half only (hendecasyllable poems with odd
  numbers); the held-out half (even numbers) is scored once per report. "Decided" = p ≤ 0.1 or ≥ 0.9; the line-final
  unit is not scored; elided units are scored as elided/not.
- **Reported:** per-syllable accuracy on decided units, share ambiguous, Brier score, per-line "fits the Phalaecian
  without overruling a unit", calibration bands, and the error list by hand with its cause. Then the metre layer:
  lines that parse, lines fitting, best-parse exact match with the gold pattern, auto-detect top-1.
- **Leak / Goodhart check:** no Hypotactic or Pedecerto data enters the lexicon or the rules' parameters except the
  measured shares written to `rule_calibration_la.json` from the development half; the held-out half is scored once.

### 4.5 Templates

| Name | Template | Notes |
|---|---|---|
| `phalaecian` | `xx-uu-u-u-F` | Catullus's base: spondee predominant; trochee and iamb attested in poems 2-26; the base `xx` is two anceps with a measured prior per realisation |
| `phalaecian_decasyllable` | `xx--u-u-F` (variant) | 55 and 58b: the dactyl contracted to a spondee in some lines; a template variant with a low prior, offered only for those poems or when the owner selects it |
| `sapphic_la` | `-u--x-uu-u-F` ×3, `-uu-F` | Horace: 4th position long, caesura after 5 (Catullus 11, 51 looser) |
| `alcaic_la` | `x-u--/-uu-uF` ×2, `x-u--u-F`, `-uu-uu-u-F` | Horace |
| `asclepiad_lesser`, `asclepiad_greater`, `glyconic_la`, `pherecratean_la` | as Greek with Horace's fixed base `--` | Odes 1.1, 1.3, 1.5, 1.11, 3.9, 3.13, 4.1 … |
| `iambic_trimeter_la` (senarius), `iambic_dimeter`, Archilochian and Alcmanian systems | Epodes; Odes 1.4, 1.7, 1.28, 4.7 | phase LA5 |
| `hexameter`, `elegiac` | shared with Greek (same shape) | Catullus 62-68, 69-116 epigrams |

### 4.6 Speed

Same budget as Greek: scansion of a typed line < 150 ms end to end, 1-3 ms server-side; a new Latin line never
depends on another line.

## 5. Workstream 2: corpus, lemma index, translations

### 5.1 Texts (open sources only; every record traces to a source record with URL, edition, fetch time, sha256)

| Poet | Text source(s) to verify in the survey | Translation(s) |
|---|---|---|
| Catullus (116 poems) | Perseus (E. T. Merrill 1893, CC BY-SA 3.0), Latin Wikisource; Catullus Online (D. Kiss) for the apparatus if its terms allow; Hypotactic Latin for scanned text alignment | Smithers 1894 prose (PD, Gutenberg), Cornish 1913 Loeb (PD in the US; check the scan's terms), then Opus interlinear |
| Horace (Odes, Epodes, Carmen Saeculare; Satires/Epistles later) | Perseus (Shorey & Laing 1919 or the Perseus Latin text; CC BY-SA), Wikisource | Bennett 1914 Loeb (PD), Smart 1836 prose (PD, Gutenberg), then Opus interlinear |
| Minor poets, ranked for a hendecasyllable composer | Martial (Phalaecians throughout; Perseus/Wikisource), Statius *Silvae* (hendecasyllables 1.6, 2.7, 4.3, 4.9), Catullan circle fragments (Calvus, Cinna, Laevius: FPL / Courtney via Wikisource or Perseus where open), Sulpicia (DCC, CC BY-SA), Priapea, Pervigilium Veneris, Seneca's choral lyrics, Ausonius | PD where found; else Opus |

PHI Latin Texts: its terms allow personal non-commercial use only; **not** a source unless the survey finds a
different licence. The Latin Library states no licence; not used. No paywalled or pirate copies. Brackets and
editorial marks are preserved verbatim; the `data-extraction` discipline applies (nothing authored from memory,
raw bytes and hashes saved, a second agent checks a sample).

### 5.2 Lemma index for Latin

The Greek index pipeline (`scripts/build_lemma_index.py`, `docs/lemma-index.md`) with a Latin parser in place of
Morpheus. Candidates: LatinCy (spaCy, MIT; models `la_core_web_lg/trf`), CLTK Latin lemmatiser, Collatinus,
Whitaker's Words, UDPipe/Stanza Latin models (check the training-data licence). Choice by evidence: each candidate
is run over 300 hand-checked Catullus tokens (the session checks them against Lewis & Short, a second agent audits
the check); the winner's held-out accuracy is written into `docs/latin/lemma-index.md`. The "attested in
Catullus/Horace" linter (L4) and the form inventory reads this index.

### 5.3 Interlinear translation (Opus subagents)

- Public-domain literal translations are stored first (Smithers, Cornish, Bennett, Smart), linked line by line
  where the source's line numbering allows, else by poem.
- For the interlinear: **one Opus subagent per batch of about 10 poems** writes a literal line-by-line English
  (Latin word order kept where English allows, every word rendered, nothing added; a note where the Latin is
  obscene or textually doubtful), from the stored Latin only. An **independent auditor subagent** (Opus) checks
  each line against the Latin and marks disagreements; disagreements go back to a writer with the auditor's note;
  what still disagrees after one round is stored with a `disputed` note. Stored with quality `machine_translation`,
  shown only where no human translation exists (release X convention). Estimated cost for Catullus (2,300 lines,
  writer + auditor): under $40; for Horace Odes/Epodes/CS (4,100 lines): under $70. The owner is told before each
  batch set starts.

## 6. Workstream 3: the composer loop for Latin

- `language` on the poem settings, carried to the lint, the agent, the tools and the page. The Greek paths are
  untouched when `language` is absent or `grc` (tests assert the Greek slot keys and lint results are unchanged).
- Lint bank for `la`: L7 (Latin scanner, same `remaining_template` contract), L1 (Latin lemma index, then the
  lemmatiser; u/v and i/j folded), L4 attestation by author over the Latin index, L11 verbatim over the Latin
  corpus, L8-la elision and hiatus notes (never block). L2 reports "not applicable". The corpus proposer
  (`/api/compose/suggest`) serves Latin lines when `language=la`.
- Agent: a Latin system prompt (poet's forms and loci, elision rules, "propose early, the checks scan"), the same
  tools with `language` set by the service, back-translation prompt for Latin. Research turn and chat stay Fable
  5.1 `xhigh`; pool fills at the release W default (`medium`) until measured for Latin.
- Measurement, as in `docs/composer/agent.md`: seconds and dollars to the first passing candidate and per
  accepted line, lint pass rate, for one Catullan poem written from an English source; reported before any
  default is changed.
- Reasoning summaries logged per agent run (flag-guarded, default on, in the manifest: `COMPOSER_LOG_REASONING`).

## 7. Architecture (what changes)

```
browser  composer.html?lang=la  ──►  melos-api (dev build on this branch; never the live container)
            no TypeGreek              /api/scan {language: la}      backend/scansion/{latin,syllabify_la,quantity_la,rules_la.yaml,gold_la}
            macron overlay            /api/composer/* {settings.language}   composer_lint.check(language=la)
                                      /api/search|lemma/* {language}        corpus + lemma index with Latin partitions
                                                  │
                                                  ▼
                                      melos-composer-agent (same image; prompt by language; tools pass language)
```

Data on this box: `data/open/latin/<source>/` (manifests as in the Greek open survey), `data/private/` for anything
rights-restricted, `data/scansion/quantities_la.sqlite`. Disk is at 97 % (13 GB free): `df -h /` before every pull;
the owner is told before anything over 2 GB. No model downloads beyond a spaCy/LatinCy model (< 1 GB) without asking.

## 8. Phases

| Phase | Deliverable | Check |
|---|---|---|
| LA0 | This PRD pushed; `docs/latin/STATUS.md`; adversarial critique folded in; prior-art and sources survey with licences (`docs/research/latin-scansion-prior-art.md`, under 8 pages) | survey table complete; every row's licence quoted or marked unverified |
| LA1 | Scanner core (no lexicon): letters, syllabifier, features, `rules_la.yaml`, Phalaecian templates, Hypotactic Latin gold loader, eval script; `/api/scan language=la` | per-syllable and per-line accuracy on the Catullus hendecasyllable dev half; held-out scored once; error list by hand |
| LA2 | Quantity lexicon from admitted sources; LEX nodes; coverage report (§4.3) | the owner's doubt answered with numbers; audit of 100 rows per source |
| LA3 | Catullus corpus with source records; PD translations; lemma index with the chosen lemmatiser (held-out accuracy); Opus interlinear with auditor, stored `machine_translation` | 116 poems, every record traced; translation coverage table; a second agent's sample check |
| LA4 | `language=la` through lint, routes, store, agent, page; one Catullan hendecasyllable proposed, linted and accepted end to end | Greek tests unchanged; new Latin tests; measured seconds and dollars |
| LA5 | Horace: Odes, Epodes, Carmen Saeculare text and translations; Horatian templates; gold evaluation on Odes 1 | per-metre accuracy table |
| LA6 | Minor poets by rank; style profiles (Catullus, Horace); frequency/concept/imagery linters over Latin | owner check |

Phases LA1-LA3 can run in parallel (subagents at tiered effort: Opus for translation and critique, cheaper models
for fetch/convert); the coordinator is this session.

## 9. Grader rules as hypotheses (metacognition)

Every scanner parameter (`mcl_word`, `elision`, `final_o`, `iambic_shortening`, `final_s_drop`, `vowel_default`)
is a named hypothesis with a default, a rival, the share measured on the development half, and a Goodhart check
(a parameter tuned on Catullus must not silently reshape Horace: both are reported). The same holds for lint
thresholds (verbatim-run length, attestation counts). `docs/decisions.md` records the owner's doubts against what
was implemented, with dates.

## 10. Open points for the owner

1. **Where Latin lives:** `composer.html?lang=la` on greeklyric.com (proposed) or a separate domain later (owner's
   later decision, per the brief).
2. **Parameter defaults:** keep honest 0.5-style defaults where the grammar is silent (as in Greek), or ship the
   measured Catullan shares (muta cum liquida, elision rate ≈ 1 per 2 lines in Catullus, final -o)?
3. **Macron overlay** on the board: show the lexicon's quantities by default, or only on request?
4. **Interlinear register:** literal with Latin word order kept where possible (proposed) versus smooth English
   with the line alignment; obscene passages rendered plainly (proposed) or softened.
5. **Horace order:** Odes 1-4 before Epodes and the Carmen Saeculare (proposed), Satires/Epistles later.
6. **Pedecerto:** use as a second gold set only if its terms allow; skip otherwise (proposed).
7. **Cost:** translation and critique subagents at Opus; estimated under $120 for Catullus + Horace lyric; pool
   measurements as for Greek. No hard cap unless the owner sets one.

## 11. Critique log

Adversarial critique of this PRD (Codex or a Claude critic subagent) and of each implementation brief before
building: what was raised, what was folded in, what was rejected and why. Filled in during LA0.
