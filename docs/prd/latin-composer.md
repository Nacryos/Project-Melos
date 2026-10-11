# PRD: Latin verse composer (Catullan hendecasyllables first)

Owner: Alvin. Written 2026-10-10 (Pacific) by the Latin session on Basecamp, from the owner's brief
(`~/work/latin-composer-brief.md`). Branch: `latin-composer`, based on `composer-w` (release W, live 2026-10-10).
Status: v2 after the adversarial critique (§11, 2026-10-10); building. Mirrors `docs/prd/composer-agent.md`.

## 1. Goal

The owner wants the whole composer experience for Latin, starting with Catullan Phalaecian hendecasyllables:
the same owner-only page at greeklyric.com, the same Fable 5.1 line proposer, the same deterministic linters
(metre, attested vocabulary, frequency/concept/imagery), live metre-agnostic scansion on the board. Target order:
**Catullus, then Horace (Odes, Epodes, Carmen Saeculare), then the minor Roman lyric poets** ranked by their
usefulness to a hendecasyllable composer. Latin is a second **language backend** behind the release W code (scanner, forms reader, evidence index, text filter,
templates, prompts), selected by `language=la`; the Greek paths stay byte-identical when `language` is absent or `grc`.

The two bottlenecks the owner named, and what this PRD does about them:

| Bottleneck | Owner's doubt | What is built |
|---|---|---|
| Latin metre as a decision-tree program | Latin vowels carry no fixed length the way η ω ε ο do; but inherent length plus position fixes most quantities and macronised dictionaries exist. How far does that hold, and what coverage do the resources give? | A Latin sibling of the Greek scanner (same engine, a Latin rules file), a macronised quantity lexicon with per-source provenance, and a **coverage report** on Catullus: what share of syllables the position rules alone decide, what the lexicon adds, what stays open (§4.3) |
| A solid database of Catullus, Horace and the minor lyric poets with a literal interlinear translation | Open translations where they exist; else an Opus subagent writes them | Corpus with source records (URL, edition, fetch time, hash), public-domain literal translations first, Opus-written interlinear stored as `machine_translation` and shown only where no human translation exists (release X convention) |

## 2. What exists (release W) and what Latin reuses

| Piece | Greek state | Latin plan |
|---|---|---|
| Scanner engine `backend/scansion/engine.py` | Interpreter of a two-tree YAML grammar with a safe expression language; the feature whitelist `FEATURES` is a Greek global | **Reused with one change:** `load(..., features=)` takes the grammar's own feature set (the Greek call is unchanged). A Latin feature set and rules file (§4) |
| `syllabify.py`, `quantity.py`, `greek.py` | Greek letters, nuclei, units, features | New `latin.py`, `syllabify_la.py`, `quantity_la.py` beside them (same dataclasses, so `metre.py` sees the same `SyllableResult`) |
| `metre.py` templates and `fit_line` | Templates in `- u x F D R X`; parses × priors; violations against near-certain units | **Reused.** Latin templates added (Phalaecian with its decasyllabic variant, then Horace's); a `language` tag on templates so `auto` ranks only the right language's metres |
| `lexicon.py` (`quantities.sqlite`: Morpheus, Wiktionary, LSJ) | per-letter L/S/u/e codes per source | Same table shape in `quantities_la.sqlite` from Latin sources (§4.2); same `Evidence` class |
| `gold.py` (Hypotactic Iliad) | gold loader + `scripts/scansion_eval*.py` | `gold_la.py` over Hypotactic Latin and Pedecerto; `scripts/scansion_eval_la.py` reports per syllable and per line |
| `/api/scan` | `dialect`, `metre`, `lexicon`, `params` | Adds `language: "grc" \| "la"` (default grc); Latin ignores `dialect` |
| Lint bank `backend/composer_lint.py` | L7 metre, L1 forms, L2 dialect, L4 attestation, L11 verbatim | `language` parameter: L7 via the Latin scanner, **fitting prefix + candidate jointly** (a candidate beginning with a vowel elides the prefix's last syllable, so the client's `remaining_template` is advisory for Latin); L1 via a **closed-vocabulary analyser** (Latin Morpheus, Whitaker's Words or Collatinus, chosen in the survey: a statistical lemmatiser always returns a lemma and would make L1 vacuous) with enclitics (-que, -ne, -ue) split for lookups; L2 reports "not applicable"; L4 and L11 over the Latin partition |
| Composer routes and store | settings `{author, metre, dialect, theme}` | settings gain `language`; the slot key stays `v1` and appends `|la` only when the language is not Greek, so every Greek key is byte-identical (both sides, same test vectors) |
| Agent container, sessions, fills, prompts | Greek system prompt, Melos tools | Prompt selected by `settings.language`; tools unchanged but every call carries `language` so search, lemma and headlines routes answer from the Latin data |
| Page `composer.html` | TypeGreek board | `language=la` turns TypeGreek off (plain Latin input, no macrons required), board shading and pop-up unchanged |
| Corpus (`corpus.sqlite`, records carry `language`) | Greek | Latin records with `language: la` in the same contract; the search index and lemma index get Latin partitions. **Dev data only on this branch:** the live `melos-api*` containers and their mounts are never touched |

**What the switch actually touches** (the LA4 work list; from the critique): `engine.FEATURES` (per-grammar feature sets);
`scan_api.grammar()` / `_lexicon()` single caches and the rules view/validate/save routes (keyed by language);
`_scanner` and `composer_lint.target_dialect` / `SCAN_DIALECTS` (Latin ignores dialect instead of 422);
`forms_check` (Greek headline index + Greek Morpheus) and `_attestation` (`get_dialectizer().index`) need Latin readers;
`_phrase_in_corpus` needs a language filter; `textutils.normalize` does no u/v, i/j folding; `metre.TEMPLATES` /
`AUTO` are flat (per-language lists); the API field is literally `greek` (kept, documented as "the verse text"). Each is
behind one `LanguageBackend` object so the Greek path is untouched.

## 3. User experience (differences from the Greek PRD §3 only)

- Toolbar: **Language** (Greek / Latin). Latin sets poet (Catullus, Horace, …), metre (Phalaecian hendecasyllable,
  then Sapphic, Alcaic, Asclepiads, glyconic, pherecratean, Archilochians, iambic trimeter/senarius for Epodes),
  dialect hidden. Typing is plain Latin; `u`/`v` and `i`/`j` are accepted as typed and folded for lookups.
- Board shading is the Latin scanner's `p_long` per unit, with the reason on click ("short vowel before two
  consonants: long by position"; "final -a: nominative short or ablative long, 50 %"; "elision of final -um
  before initial vowel"). Elision is **shown**, not typed: the scanner proposes it at every vowel(+m) | vowel/h-
  boundary with a high prior (Catullus and Horace elide almost always); the metre fit may keep the syllable instead
  (hiatus), but a parse that needs a hiatus is a **violation**, shown and blocking in L7, except after an
  interjection (o, heu, a) and in the semi-hiatus of a long monosyllable (dī ament, Catullus 97.1), which are flagged.
  Typed `v` / `j` and typed macrons are certain evidence (a typed v blocks elision: *multa uiri*).
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

**Vowel tree** (sets `p_vowel`). TYPED-L / TYPED-S (a typed macron or breve) → 1 / 0 · DIPH (ae au oe always;
eu, ui, ei only in listed words or Greek names; a written diaeresis splits) → 1 · MONO (a monosyllable ending in a
vowel: mē tē sē dē nē sī tū quī; A&G §604) → 1, except the enclitics -que -ne -ue → 0 · VOC-ANTE-VOC (a vowel before
another vowel in the word, A&G §603a) → `vocal_before_vowel` (low; exceptions fīō, genitives in -īus, 5th-decl. -ēī,
Greek words) · ENCLITIC-E (-que, -ne, -ue) → 0 · FINAL rules for the ultima with the exception lists as YAML data
before the defaults (A&G §604): -i long (mihi tibi sibi ibi ubi either, listed; nisi quasi short) · -u long · -e
short (long: 5th-decl. abl., 2nd-conj. imperatives *vidē*, adverbs from -us adjectives except bene male, Greek
words, fermē) · -a nom./voc./neut. pl. short vs abl./imperative/adverb long → 0.5 "ending ambiguous" unless the
lexicon or the parse settles it · -o long by default, with the lexicalised short list (ego modo cito duo homo scio
puto nescio; Catullus 85.2 *nesciŏ*) and the iambic-shortening flag · -as -os -es long, -is -us short by default
(A&G §604; the lexicon overrides; they matter only before a vowel or at line end) · LEX-L / LEX-S / LEX-CONFLICT /
LEX-UNMARKED (the macronised lexicon, §4.2) · HIDDEN (two consonants follow: the vowel's own length is hidden; the
unit tree decides) · UNK → `vowel_default`.

**Unit tree** (sets `p_long`). POS (two consonants after the nucleus, in or across words; x z and intervocalic i
(maior) count two; h counts none; qu one; gu only after n (lingua) and su only in the suād-/suāv-/suēsc- family are
glides, otherwise u is a vowel) → 1 · POS-ACROSS-S (final -s after a short vowel before an initial consonant:
Catullus 116.8 *dabi' supplicium*) → 1 − `final_s_drop` · PREFIX-MCL (stop at a prefix boundary + liquid: ab-rumpō,
ob-ruō, sub-lātus) → 1 (A&G §603f) · MCL (stop or f + l/r inside the word after a short vowel: in Catullus and
Horace usually no position) → `p_vowel + (1 − p_vowel)·mcl_word` · S-IMPURA (a short final vowel before initial
s + stop: *pote stolidum* 17.24, *unda Scamandri* 64.357) → `s_impura` (low) · INIT-CLUSTER (next word begins with
another two consonants) → `pos_initial` · ELIDABLE (final vowel, or vowel + m, before a word beginning with a vowel or
h): the unit is an elision candidate (flag ELI-CAND with `elision`, PROD-CAND before est/es, lower before an
interjection or across strong punctuation; SEMI-HIATUS for a long monosyllable: shortened, not elided); if kept, its
weight is `p_vowel` · CONS-VOW (one final consonant before the next word's vowel) → `p_vowel` · OPEN → `p_vowel`.

**Flags.** ELI-CAND, PROD-CAND, SEMI-HIATUS, SYN-CAND (ei eo ii uu inside a word, with the dein/deinde/eidem list
at a high prior), DIAER-CAND (silŭae, solŭit: a consonantal u read as a vowel), IAMB-SHORT (a disyllable ⏑– whose
final may shorten: volo, modo), FIN-ANC (line end), HYPERMETRIC (line-final elidable vowel before a line beginning
with a vowel: Catullus 11.19, 34.11; stanza join deferred to LA5), CAESURA (word end at the metre's usual place;
reported, never scored).

**In the metre layer** (`metre.parses`): an elision candidate is a parse branch that **drops the unit** (it takes no
template position) with prior `elision`; keeping it (hiatus) is the other branch and is reported as a violation
unless its prior says hiatus is normal there. Prodelision is a branch that drops *est* and makes the unit before it
long by position (*bellast*). This is not the synizesis merge (which sets one long unit); the critique was right.
Hypermetric elision joins lines and is deferred.

Everything that differs from Greek is a feature in `quantity_la.py` and a node in the YAML. The metre layer's own
priors (resolution, base realisations, elision, hiatus, split word) move to `backend/scansion/metres_la.yaml`,
validated like the rules file, so nothing the owner would tune is a Python constant.

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

Lookup: exact spelling (u/v, i/j folded for the key only; the typed letter stays a feature), with enclitics split, else
analyser → paradigm form, else unknown (`unknown_word`). The survey records each source's **upstream** (Morpheus
Latin, Lewis & Short, Gaffiot, scanned verse): sources sharing an upstream count as one vote, so "two sources agree"
never means two pieces of evidence. The Wiktionary Latin extraction is **not** on disk (the Greek one is): its size
is checked against the 13 GB free before any download, streamed and filtered, and the owner is told if it is over
2 GB. The coverage report (§4.3) says what each source adds, on hapax forms separately.

### 4.3 Coverage report (answers the owner's doubt)

On the **held-out** Catullus hendecasyllable lines (never the development half), per syllable: share decided by
position alone, by position + finals, by position + lexicon, and what stays open (guess, to be measured: nom./abl.
-a, elision choices, muta cum liquida, unknown stems), with the accuracy on the decided set at each stage. Guessed
shares in this PRD are guesses, not facts. The same table for Horace Odes 1 once Horace is in. It is honest about
both coverage and accuracy, never one without the other.

### 4.4 Gold and evaluation

- **Gold:** Hypotactic Latin (Chamberlain, CC BY 4.0, confirmed by his statement for hypotactic.com including the
  Latin pages; the Catullus and Horace pages fetched directly from the site, one request at a time, robots.txt
  respected, since the Urdatorn mirror holds only Greek) is the **only external hendecasyllable gold**: Pedecerto
  scans dactylic verse only (hexameter, pentameter), so it can serve for Catullus 62-116 at most, and only if its
  terms allow. A second, independent set: about 150 hendecasyllables scanned by hand by an Opus subagent from the
  grammar alone, reviewed by a second agent, **adjudicated** against Hypotactic where they disagree (disagreements
  are scored against the adjudicated label, never dropped). Caveat recorded: Chamberlain's marks are dictionary- and
  scanner-assisted, so lexicon-versus-gold agreement is partly circular; the hand set is the check on that.
- **Split:** development = odd-numbered Phalaecian poems; held-out = even-numbered; out-of-author held-out = Martial
  and Statius Phalaecians if Hypotactic has them. The held-out score is frozen once per milestone and every later
  look is logged in `docs/latin/eval-log.md`.
- **Reported:** per-syllable accuracy on decided units, share ambiguous, Brier, calibration bands, per line "fits the
  Phalaecian without overruling a unit", best parse equal to the gold pattern, auto-detect top-1, the error list by
  hand with its cause. Layer 1 is scored separately on positions the template does not force.
- **Negative control (the composer's purpose is catching errors):** perturbed lines, one word swapped for a
  metrically wrong form or synonym, with the **false-accept rate** reported beside the true-accept rate. A scanner
  that accepts everything scores 100 % on real lines and fails here.
- **Leak / Goodhart check:** no Hypotactic data enters the lexicon or the rules' parameters except the measured shares
  written to `rule_calibration_la.json` from the development half; parameters tuned on Catullus are re-reported on
  Horace (and vice versa) so a tuning that helps one and hurts the other is visible.

### 4.5 Templates (`backend/scansion/metres_la.yaml`; caesurae are metadata, not template symbols)

| Name | Template | Notes |
|---|---|---|
| `phalaecian` | `xx-uu-u-u-F` | Free base in the polymetrics: spondee most frequent, then trochee (already 1.2 *ārĭda*), iamb rarest, pyrrhic never. Base realisation priors are measured per poem from the development half; the pyrrhic prior is ~0, so a pyrrhic base is reported as a violation |
| `phalaecian_decasyllable` | `xx---u-u-F` | 55 and 58b: the dactyl contracted to one long (58b.1 *nōn custōs sī fingar ille Crētum*); 55 mixes 10- and 11-syllable lines, so it is a per-line alternative offered beside the 11-syllable template, not a per-poem setting |
| `sapphic` (Catullus 11, 51) | `-u-x-uu-u-F` ×3, `-uu-F` | Same as the Greek template: position 4 anceps (51.13 *ōtium, Catulle*) |
| `sapphic_horace` | `-u---uu-u-F` ×3, `-uu-F` | Position 4 long; caesura after 5 in Odes 1-3, often after 6 in Odes 4 and the Carmen Saeculare (metadata) |
| `alcaic_horace` | `x-u---uu-uF` ×2, `x-u---u-F`, `-uu-uu-u-F` | Position 5 long; first anceps mostly long |
| `asclepiad_lesser_horace`, `asclepiad_greater_horace`, `glyconic_horace`, `pherecratean_horace` | base fixed `--` | Odes 1.1, 1.3, 1.5, 1.11, 3.9, 3.13, 4.1 …; Catullus 30 (greater asclepiad), 34 and 61 (glyconics with a free base) get their own entries |
| `choliambic` | `x-u-x-u-u--F` | Catullus 8, 22, 31, 37, 39, 44, 59, 60 |
| `iambic_trimeter_pure`, `iambic_trimeter` | `u-u-u-u-u-uF`, Greek `XRuRXRuRXRuF` | Catullus 4, 29 (pure); 52; Horace's Epodes follow Greek practice (not the comic senarius) |
| `priapean`, `galliambic` | 17; 63 | later |
| `hexameter`, `elegiac` | shared with Greek | Catullus 62-68, 69-116 |

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
Catullus/Horace" linter (L4), the form inventory, concordance, collocations, n-grams and frequency tools (the
"word and form suggestions by author usage" of the brief) read this index. L1 (does the form exist) is **not** the
lemmatiser's job (§2). Licences are recorded per row for code, data and training data (UD Latin treebanks are
partly CC BY-NC-SA): the owner's policy records rights and does not gate, but the brief's "open sources only" binds
for texts; tools run server-side and nothing derived from GPL data is redistributed.

### 5.3 Interlinear translation (Opus subagents)

- Public-domain literal translations are stored first (Smithers, Cornish, Bennett, Smart), linked line by line
  where the source's line numbering allows, else by poem.
- For the interlinear: **one Opus subagent per batch of about 10 poems** writes a literal line-by-line English
  (Latin word order kept where English allows, every word rendered, nothing added; a note where the Latin is
  obscene or textually doubtful), from the stored Latin only. An **independent auditor subagent** (Opus) checks
  each line against the Latin and marks disagreements; disagreements go back to a writer with the auditor's note;
  what still disagrees after one round is stored with a `disputed` note. Stored with quality `machine_translation`,
  shown only where no human translation exists (release X convention). Estimated cost for Catullus (about 2,300 lines,
  writer + auditor): under $40; for Horace Odes, Epodes and Carmen Saeculare (about 3,740 lines): under $70. The owner is told before each
  batch set starts.

## 6. Workstream 3: the composer loop for Latin

- `language` on the poem settings, carried to the lint, the agent, the tools and the page. The Greek paths are
  untouched when `language` is absent or `grc` (tests assert the Greek slot keys and lint results are unchanged).
- Lint bank for `la`: L7 (Latin scanner; prefix and candidate fitted jointly because of elision across the caret),
  L1 (closed-vocabulary analyser, enclitics split, u/v i/j folded for the key), L4 attestation by author over the
  Latin index, L11 verbatim over the Latin partition. L2 reports "not applicable". The corpus proposer
  (`/api/compose/suggest`) serves Latin lines when `language=la`.
- Research tools for Latin (the agent's evidence): `search` (Latin partition, themes through the English
  translations), `lemma_search` / `forms_found` / `concordance` / `collocations` / `ngrams` / `lemma_frequency` over
  the Latin lemma index, `headlines` and `word` over the analyser and Lewis & Short, `scan` with `language=la`;
  `dialectize` and `morpheus` (Greek) are turned off for a Latin poem. Author-style rephrasing in Catullus's manner
  is the agent's job with these tools (as for Sappho), checked by L4/L11; it is not a separate linter.
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
| LA0 | This PRD pushed; `docs/latin/STATUS.md`; adversarial critique folded in; prior-art and sources survey with licences (`docs/research/latin-scansion-prior-art.md`, under 8 pages) | survey table complete; every row's licence quoted or marked unverified, with upstream |
| LA1 | Scanner core (no lexicon): letters, syllabifier, features, `rules_la.yaml`, elision/prodelision branches in the metre layer, Phalaecian templates with base priors, Hypotactic Latin gold loader, eval script with the negative control; `/api/scan language=la` | per-syllable and per-line accuracy and false-accept rate on the development half; held-out frozen once; error list by hand |
| LA2 | Quantity lexicon from admitted sources (upstream recorded); LEX nodes; coverage report (§4.3) on the held-out half | the owner's doubt answered with numbers; audit of 100 rows per source |
| LA3 | Catullus **text** with source records (Perseus/Wikisource), L1 analyser, Latin partition in the corpus and FTS for L4/L11; the lemmatiser bake-off for the index. In parallel (subagents): PD translations; Opus interlinear with auditor, stored `machine_translation` | 116 poems, every record traced; a second agent's sample check; translation coverage table |
| LA4 | `language=la` through lint, routes, store, agent, page (the §2 work list); Latin research tools; one Catullan hendecasyllable proposed, linted and accepted end to end | Greek tests unchanged; new Latin tests; measured seconds and dollars |
| LA5 | Horace: Odes, Epodes, Carmen Saeculare text and translations; Horatian templates; hypermetric/stanza join; gold evaluation on Odes 1 | per-metre accuracy table |
| LA6 | Minor poets by rank; style profiles (Catullus, Horace); concept and imagery tools over the Latin translations; macron overlay; choliambic, priapean, galliambic | owner check |

LA1-LA3 run in parallel (subagents at tiered effort: Opus for translation, hand scansion and critique; cheaper
models for fetch and convert; the coordinator is this session). The brief's deliverable order (survey, scanner,
Catullus with translations, one line end to end) is kept; the translations run as background subagent work so the
end-to-end line does not wait on them.

## 9. Grader rules as hypotheses (metacognition)

Every parameter is a named hypothesis with a default, a rival, the share measured on the development half, and a
Goodhart check; the table lives in `docs/latin/hypotheses.md` and starts as:

| Parameter | Default (hypothesis) | Rival | Measured on | Goodhart check |
|---|---|---|---|---|
| `elision` | 0.98: Catullus and Horace elide whenever the environment allows | hiatus common after strong punctuation | dev half, by punctuation class | the same rate on Horace Odes 1; false-accept rate on perturbed lines |
| `mcl_word` | 0.2: muta cum liquida mostly short in neoteric and Augustan verse | 0.5 (Greek default) | dev half | Horace vs Catullus separately |
| `s_impura` | 0.15 | 0.9 (Greek POS-INIT) | dev half (few cases: reported, not tuned) | — |
| `final_o` short list | ego modo cito duo homo scio puto nescio | all verb -ō long | dev half | Catullus vs Horace |
| `vowel_default` | 0.5 (honest) | measured share of unknown open vowels | dev half | Brier on held-out |
| base priors (phalaecian) | spondee ≫ trochee > iamb, pyrrhic 0 | flat | dev half per poem | out-of-author (Martial) |
| `synizesis` / `diaeresis` | 0.05 / 0.02 with word lists | none | dev half | — |
| L11 verbatim run | 4 words (or 3 with 15 letters), as Greek | 5 words | — | — |

`docs/decisions.md` records the owner's doubts against what was implemented, with dates.

## 10. Open points for the owner

1. **Where Latin lives:** `composer.html?lang=la` on greeklyric.com (proposed) or a separate domain later (owner's
   later decision, per the brief).
2. **Parameter defaults:** keep honest 0.5-style defaults where the grammar is silent (as in Greek), or ship the
   measured Catullan shares (muta cum liquida, the elision rate, final -o)?
3. **Macron overlay** on the board: show the lexicon's quantities by default, or only on request?
4. **Interlinear register:** literal with Latin word order kept where possible (proposed) versus smooth English
   with the line alignment; obscene passages rendered plainly (proposed) or softened.
5. **Horace order:** Odes 1-4 before Epodes and the Carmen Saeculare (proposed), Satires/Epistles later.
6. **Pedecerto:** use as a second gold set only if its terms allow; skip otherwise (proposed).
7. **Cost:** translation and critique subagents at Opus; estimated under $120 for Catullus + Horace lyric; pool
   measurements as for Greek. No hard cap unless the owner sets one.

## 11. Critique log

**2026-10-10, PRD v1 → v2.** Critic: a Claude Opus subagent reading the brief, both PRDs, the scanner and lint code;
32 items. Folded in (29): elision as a drop branch in the metre layer, prodelision making the unit before *est* long,
hiatus as a reported violation except after interjections and for the semi-hiatus of long monosyllables; Pedecerto
is dactylic only, so Hypotactic is the only hendecasyllable gold and a hand-scanned adjudicated set is added;
template strings corrected (decasyllable `xx---u-u-F`, Horace's Sapphic `-u---uu-u-F`, Alcaic enneasyllable
`x-u---u-F`, no `/` in templates, caesurae as metadata); free base with measured priors and the pyrrhic as a
violation; monosyllable, final -i/-e/-o exception lists as YAML data; muta cum liquida split into in-word, prefix
boundary (position) and initial cluster, plus s impura; gu/su as lexical glides and a diaeresis flag; semi-hiatus;
hypermetric elision and stanza join (deferred to LA5, named); elision across the caret (prefix and candidate fitted
jointly); the honest "language backend" naming with the call-site list; metre priors moved to a YAML; L1 on a
closed-vocabulary analyser, not the lemmatiser; enclitic splitting; the negative control (false-accept rate);
disagreements adjudicated, held-out frozen and looks logged, out-of-author set; shared-upstream lexicon sources as
one vote and hapax coverage; coverage reported on held-out only; licence columns for code, data and training data;
the Wiktionary Latin dump is not on disk; senarius naming and the missing Catullan metres; slot key stays v1;
typed v/j and macrons as certain features; unsourced numbers labelled, Horace line count corrected (~3,740);
re-sequencing so the end-to-end line does not wait on translations; the Latin research tools and author-usage
suggestions listed in LA4; the "How we work" rules restated (§12); the hypothesis table (§9).

Rejected (3): a new base symbol `B` (the same effect comes from priors keyed by template, with no change to the
template symbol set or the page's slot logic); reordering the brief's deliverables to put the end-to-end line
before the Catullus ingestion (the owner's order is kept; translations run in parallel instead); treating the
owner's "coverage over caution" policy as overridden for tools (it governs texts and rights records; the brief's
"open sources only" binds for texts, and server-side use of GPL or NC-trained tools without redistribution is
recorded, not refused).

## 12. How we work (the brief's binding rules, restated)

PRD first and pushed, then adversarial critique of the PRD and of each implementation brief, folded in and logged
here. Bias to action: POCs built directly. Reasoning summaries logged in every agent run, including survey,
translation and critique subagents (flag-guarded, default on, in each manifest). Subagent effort tiering: Opus for
translation, hand scansion and critique; cheaper models for fetch and convert; one coordinator. Updates in plain
language, Pacific time, no metric codes; a Telegram ping (send-only from this box) for decisions and significant
findings; never contact third parties on the owner's behalf. Research reports under 8 pages with dense tables.
Git: own files only on this branch, pushed often, no `Co-Authored-By` lines; never deploy to production or touch
the running containers. Disk at 97 %: `df -h /` before any pull, data under `data/open/latin/` and `data/private/`,
the owner told before anything over 2 GB. `docs/latin/STATUS.md` kept current and never rolled back. Fetches use
the project User-Agent, respect robots.txt, one request at a time; no logins or paywalls.
