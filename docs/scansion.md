# Scansion: a metre-free syllable-quantity scanner (branch `scansion`)

Status (2026-10-09): built and validated in the worktree `C:\Users\alvin\melos-scansion`; **not mounted in
`backend/server.py` and not deployed**. Everything here runs locally.

```
# local preview (worktree only)
set MELOS_DATA_DIR=C:/Users/alvin/melos/data        # where the lexicon and corpus live
python scripts/scansion_dev_server.py               # http://127.0.0.1:8795/scan.html  and  /rules.html
python -m pytest -q tests/test_scansion.py          # 27 tests
```

## 1. What it does

The scanner takes **any Greek text, verse or prose**, and gives every *scansion unit* a probability of
being long (0 to 1), with the rule that decided it, a one-line reason and a citation. It assumes no
metre: a line that does not scan is shown as it is. A metre (or an antistrophe) can be added as an
optional second layer that re-weights the probabilities; the metre-free result is always returned
beside it.

* **Unit** = one vowel nucleus (a vowel or a diphthong) + the consonants after it up to the next
  nucleus on the line. Spaces and punctuation are ignored; word boundaries are kept only as features.
  The onset does not matter. (Owner decision, 2026-10-09.)
* **The rules are data**: `backend/scansion/rules.yaml`, a two-tree meta-grammar interpreted by
  `backend/scansion/engine.py`. Editing the file changes the scanner with no code change; the file is
  validated when it loads (unknown names, bad probabilities, missing reasons or citations are reported).
* **Lexical vowel lengths are an optional hook** (`lexicon=`): Morpheus, Wiktionary and LSJ marks for
  α ι υ. The core grammar works without it.

## 2. Prior art (what was checked, what was borrowed)

| Work | Approach | Licence | Accuracy claimed | Use here |
|---|---|---|---|---|
| CLTK `prosody/grc.py` (tag v1.5.0; removed from master) | needs pre-macronized input; position + muta cum liquida | MIT | none | not used (no dichrona, correption, synizesis) |
| J. Tauber, `greek-accentuation` (`syllabify`, `syllable_length`) | η ω diphthongs long, ε ο short, α ι υ unknown | MIT | none | specification only (same nature rules) |
| Papakitsos (Dactylo); Schoisswohl & Papakitsos 2020 | dactyl search from foot 5 | not stated | 0.98 recall / 0.80 precision on 700 verses (quoted by Schumann) | not used (needs the metre) |
| Schumann, Beierle & Blößner, DSH 37 (arXiv 2101.11437), `anetschka/greek_scansion` | regex quantity rules + finite-state automata | CC BY-NC-SA 4.0 | F 0.98 on 346 verses | error taxonomy only (licence blocks reuse) |
| Hypotactic (D. Chamberlain) | hand-checked scansion, Greek and Latin | CC BY 4.0 | — | **gold data** (Iliad CSV; 93,215 lines via `data/open/hypotactic`) |
| A. Conser, `greek_scansion`, `MeterDict` | prosody, trimeter, macronizing tools | MIT | none | not inspected in depth |
| Leo-Y-Zhang/GreekScansion | hexameter; carries "either" forward, lets the metre decide | proprietary | — | specification only: the "carry ambiguity forward" idea matches this design |
| threedlite/hesiod | hexameter DP; synizesis/weak-position retries; digamma stems | CC BY-SA 4.0 | TTS metric only | not used |
| alevatri/diorisisscan | any text, metre optional; `mCl` switch; scanned-forms dictionary | MIT | none | not used: its `greekScansions.json` has undocumented provenance (possibly derived from Hypotactic, which would leak into the evaluation) |
| storey/Odikon 2.0 | trimeter, anapaests | MIT (per API) | ~400 Euripides lines | not used |
| Urdatorn/grc-macronizer; oga-macronizer-char; Stoicheia (arXiv 2608.07249) | rule-based / neural macronizers | GPL-3.0 / GPL-3.0 / CC BY paper | not stated | not used (owner: no heavyweight model) |
| **homer-bard `src/homerbard/scan.py`** (owner's own) | rules + Viterbi over the 32 hexameter templates, costs from Iliad 1-12 | owner's | 99.3 % feet on the Iliad | its error classes were compared; nothing copied (the owner asked that the tree not borrow a hexameter scanner's tuning) |

Rules were taken from grammars, cited per node: Smyth, *Greek Grammar* (1920, Perseus 1999.04.0007)
§§5, 8, 11, 30, 60, 62, 70, 76, 140-148, 163-171, 181-186; Monro, *Homeric Grammar* (1891, Dickinson
College Commentaries edition, CC BY-SA) §§366, 369-386 (position, lengthening before ρ λ μ ν σ δ, elision,
crasis, synizesis, hiatus, correption, doubtful syllables, metrical licence) and §§390-395 (digamma).
West's *Greek Metre* and Maas could not be checked online; no section numbers are cited from them.

## 3. Design

### 3.1 The decision tree (`backend/scansion/rules.yaml`)

Two trees, evaluated top to bottom, first match wins at each level; then flags.

**Vowel tree** (sets `p_vowel`): CRA-1 crasis → 1 · NAT-DIPH diphthong → 1 · NAT-ISUB iota
subscript/adscript → 1 · NAT-CIRC circumflex → 1 · NAT-ETA η ω → 1 · NAT-EO ε ο → 0 · DICH α ι υ:
ACC-PROPAROX (final α ι υ of a proparoxytone) → 0 · ACC-PROPERISP (after a circumflexed penult) → 0 ·
ACC-PAROX-LONG (acute on a long penult) → 1 · ACC-PAROX-SHORT (acute penult before short ultima, φίλος)
→ 0 · ACC-PAROX-SHORT-AIOI → 0.05 · LEX (optional hook): LEX-L / LEX-S / DIA-ETA / LEX-CONFLICT /
LEX-ENDING / LEX-UNMARKED / LEX-OTHER · DICH-UNK → `dichronon_default`. Accent rules are skipped for an
elided word and for a word ending in an enclitic written with it (οὔτις, ὥστε, ὅδε; Smyth §186).

**Unit tree** (sets `p_long`): POS (two consonants or ζ ξ ψ, not muta cum liquida): POS-DOUBLE,
POS-ACROSS (consonants on both sides of a word boundary), POS-INIT (next word begins with two),
POS-WORD → 1 · MCL (stop + liquid/nasal): MCL-LONGV → 1, MCL-WORD `p_vowel + (1-p_vowel)·mcl_word`,
MCL-INIT `… mcl_boundary` · HIATUS (vowel before the next word's vowel): DIG-HIA `p_vowel·digamma_keep`,
COR-EXT `p_vowel·correption`, HIA-SHORT → 0 · COR-INT (long vowel before a vowel in the word) →
`internal_keep` · OPEN: DIG-LEN, EPL-RHO, EPL-INIT (epic lengthening before initial ρ / λ μ ν σ δ),
CONS-VOW, NATURE → `p_vowel`.

**Flags** (never change `p_long`): SYN-CAND (ε/η + vowel in a word may merge, with `p`), ELI-1,
DIG-WORD (next word once had ϝ), FIN-ANC (last unit of a line: brevis in longo, not tested by a metre).

The rules file's expression language: feature and parameter names, strings, numbers,
`== != < <= > >= in`, `and or not`, parentheses, `+ - *`. It is parsed with Python's `ast` and only
those node types are accepted (a rules file cannot run code). The features (31) are listed with their
meaning in `engine.FEATURES` and on `rules.html`.

### 3.2 Probabilities

Certain grammar rules give 0 or 1. Owner defaults: correption 0.5, unknown dichronon 0.5, muta cum
liquida 0.5 (word-internal and across a boundary, separately tunable). Every parameter is in the
`params:` block of the rules file; `rules.html` shows next to each the share measured on the gold Iliad
(Books 1-12, `backend/scansion/data/rule_calibration.json`):

| Parameter | Default | Measured in Homer (n) | Note |
|---|---|---|---|
| correption (long final in hiatus kept long) | 0.5 | 0.230 (2,890) | -αι 0.07, -οι 0.14, η 0.70 (finer leaves are possible) |
| digamma_keep | 0.85 | 0.788 (184) | Monro list, see §3.4 |
| internal_keep | 0.95 | 0.997 (4,440) | Attic drama shortens more (τοιοῦτος) |
| mcl_word | 0.5 | 0.990 (892) | Homer makes position; Attic usually not (Smyth §145) |
| mcl_boundary | 0.5 | 0.822 (623) | |
| dichronon_default | 0.5 | 0.148 (21,214, core) | unknown α ι υ are mostly short in Homer |
| lex_long / lex_short / lex_unmarked | 0.9 / 0.05 / 0.1 | 0.915 / 0.010 / 0.045 | |
| digamma_lengthening | 0.3 | 0.239 (255) | |
| epic_lengthening / _rho | 0.1 / 0.4 | 0.021 / 0.36 | |
| synizesis (merge) | 0.05 | 0.055 (3,431 candidates) | εω 0.19, ηω 0.26 |
| dialect_alpha_long | 0.95 | — | not testable on Homer (Ionic) |

The defaults are the owner's; the measured column is what Homer says. Results are reported for both.

### 3.3 Lexical hook (optional)

`data/scansion/quantities.sqlite` (850,615 rows; rebuilt by `scripts/scansion_build_lexicon.py`):

| Source | Rows | What it gives | Licence |
|---|---|---|---|
| Morpheus (alpheios-project/morpheus @ 2f1a30d, CI stem library), run locally over all 168,158 Greek spellings of `data/corpus.sqlite` | 144,720 | stems and endings with `_` / `^`; an unmarked ending vowel is coded "e" (the tables mark long ones) | CC BY-SA 3.0 US |
| Wiktionary (Kaikki dump, same file as `data/open/wiktionary-quantities`) | 660,049 | headwords and inflection tables with macrons/breves | CC BY-SA 4.0 / GFDL |
| Perseus LSJ `<orth>` with `_` `^` | 11,125 | headword lengths | CC BY-SA 4.0 |
| Logeion LSJ `orth_orig` | 34,745 | headword lengths | CC BY-SA 4.0 |

Lookup: exact spelling, then accent-less spelling (not used for decisions), and an elided word is
looked up through the project's elision restorations (`backend/elision.restorations`).
Audit (separate agent, 100 random rows, 25 per source): 100/100 trace exactly to a mark in the raw
source; fixes applied (Logeion ano teleia and prefix stems, unconverted Beta Code, meta row counts).
Known loss: 157 Morpheus terms where an augment absorbs a long vowel lose the mark (never a wrong value).

**Dialect ᾱ for η (DIA-ETA, Smyth §30).** When the caller states `dialect: "aeolic" | "doric"`, an α
counts long (`dialect_alpha_long`) where the project's dialect correspondence rules
(`backend/dialect_generate.generate`: ᾱ for η, gemination, psilosis, recessive accent …) turn the
word into an attested Attic-Ionic spelling with η at that place, sharing a lemma. An α before an
Aeolic double consonant is excluded (σελάννα: the first α answers Attic η by compensatory
lengthening, but is itself short). The node fires only for words the lexicon does not itself know:
on known words it produced coincidences (τά/τή, ἀλλά, πύκνα) in Sappho and Alcaeus. The composer case
νῦν σελάννα now scans the final α long (Morpheus marks it; test `test_aeolic_selanna_final_alpha_is_long`).

### 3.4 Digamma

`backend/scansion/data/digamma_monro.json`: 100 words extracted by `scripts/scansion_fetch_digamma.py`
from Monro §§390-395 (DCC pages saved under `data/raw/scansion/monro/`, sha256 recorded). A next word
counts as once-ϝ-initial when its spelling or (with the lexicon) its lemma is on the list. The
possessive ὅς is listed but not matched (spelling identical to the relative pronoun). Audit: rows and
quotes trace to the pages; footnoted ῥυτός, ῥητός, ῥητήρ added after the audit; effect labels follow
Monro's wording ("nearly always" for ῥινός, ῥίζα).

### 3.5 Metre layer (optional; `backend/scansion/metre.py`)

Templates use `- u x F D R X` (long, short, anceps, line end, biceps, resolvable long, resolvable
anceps): hexameter, pentameter, elegiac, iambic trimeter, trochaic tetrameter, Sapphic stanza
(hendecasyllable ×3 + adonean), Alcaic stanza (11, 11, 9, 10), glyconic, pherecratean, hipponactean,
telesillean, reizianum, aristophanean, lesser and greater asclepiad. Every parse of a line has
probability Π p(weight) × priors (resolution 0.08, spondaic fifth foot 0.05, synizesis `p` of the
flag); the best parse is returned with the posterior longness of each unit (probability-weighted over
all parses) and the positions where it overrules a near-certain unit (violations, with the rule).
`auto` ranks the templates; `segment` divides running text into verses of a metre (Viterbi, verse end
inside a word at a cost); `responsion` aligns strophe and antistrophe (one long may answer two shorts)
and resolves each side's ambiguities from the other.

## 4. API (contract for later; router in `backend/scansion/api.py`)

`POST /api/scan`

```json
{"text": "…", "metre": null | "auto" | "<template>", "responsion_with": null | "…",
 "lexicon": true, "dialect": "none" | "aeolic" | "doric" | "ionic" | "attic",
 "params": {"correption": 0.3}, "segment": false}
```

Response: `units[]` (`i, line, word, start, end` code-point offsets of the unit, `nucleus [start,end]`,
`text, p_long, label` L/S/A (≥0.9 / ≤0.1 / between), `certain, rule, path, vowel {rule, path, p_long},
reasons[] {id, text, detail, cite, tree}, flags[] {id, text, cite, p?}`), `lines[] {line, units,
pattern}`, `lexicon`, `rules {file, params}`, `ms`; with a metre `fit[]` per line `{metre, template, ok,
pattern, assignment[], posterior_p_long[], violations[], message, log_likelihood}` or `auto[]`; with
`responsion_with`, `responsion {antistrophe_units, lines[] {pairs, strophe_posterior,
antistrophe_posterior, mismatches, strophe_pattern, antistrophe_pattern}}`. Errors: 422 for an unknown
metre, dialect, parameter or a value outside 0..1. Text limit 20,000 characters.

`GET /api/scan/rules` (tree, params, features, calibration, examples, the YAML),
`POST /api/scan/rules/validate {yaml}` (errors or tree), `POST /api/scan/rules/save {yaml}` (only with
`MELOS_SCANSION_DEV=1`). The server re-reads `rules.yaml` when it changes and keeps the last good file
if an edit is invalid.

## 5. Live use in the verse composer (design)

* A unit depends only on its own word, the consonants up to the next nucleus (the next word's initial
  letters) and the next word's first vowel (hiatus, digamma). Editing one word can therefore change at
  most: the last unit of the previous word, the units of the edited word, and nothing after it (the
  next word's own units do not depend on the edited word). A line never depends on another line.
* Client: debounce keystrokes (~120 ms), send only the edited **line** (`POST /api/scan {text: line}`),
  keep the other lines' results; render optimistically with the previous colours until the reply.
  Typical server time is 1-3 ms per line (§6.6); the round trip dominates.
* Server: word-level results are cacheable by (word spelling, next word's first two letters, dialect,
  rules version); the lexicon lookups are already cached per spelling (LRU 200k). An incremental API
  is not needed at this speed; if it is, `scan(text, changed=(start,end))` can re-run only the units from
  the previous word's last nucleus to the next word's first nucleus.
* Metre feedback: run `fit` for the composer's chosen metre on the edited line only (a few ms); show
  violations inline ("ος needs long: short by nature, NAT-EO"). Stanza position comes from the line
  index.

## 6. Validation

Gold sources: Hypotactic Iliad CSV (Chamberlain, CC BY 4.0, confirmed on the Homer page: "Audio and
text annotations licensed as CC-BY, © 2016, 2017 by David Chamberlain"); Hypotactic open corpus
(`data/open/hypotactic`, 93,215 lines, CC BY 4.0); Norma Syllabarum Graecarum (`data/open/norma`,
GPL-3.0, independent of Hypotactic; used only as test data); the owner's scansions in
`homer-bard/data/scansion` (read only). The owner's Iliad scansion agrees exactly with Hypotactic on
93.7 % of lines (777 of 15,676 lines differ in syllable count); the other eight works were produced by
homer-bard's rule-based hexameter scanner (`scripts/scan_work.py`, 99.3 % feet accuracy on the Iliad),
so they are metre-fitted machine output, and their `_auto` copies are byte-identical (sha256 checked).

Protocol: rules were edited only against dev data (Hypotactic Iliad 1-12, the owner's dev chunks, the
open corpus's dev chunks). Held-out sets were scored once at the end: Hypotactic Iliad 13-24; 8 random
chunks of 20 lines per owner work (Iliad held-out from Books 13-24); half of the open corpus's 20-line
chunks (hexameter capped at 40 chunks); Norma; the hand-check set. Chunk manifests:
`backend/scansion/data/eval_chunks.json`, `eval_open_chunks.json`. "Decided" = p ≤ 0.1 or ≥ 0.9; the
line-final unit is never scored. Full reports: `docs/scansion-eval/*.json`; all tables:
`docs/scansion-eval/tables.md`.

### 6.1 Hexameter

| Set | Setting | Units | Decided | Accuracy on decided | Ambiguous | Brier |
|---|---|---|---|---|---|---|
| Hypotactic Iliad 13-24 | core, rules as written | 119,412 | 73.6 % | 99.62 % | 26.4 % | 0.067 |
| | + lexicon | | 90.0 % | 99.29 % | 10.1 % | 0.029 |
| | measured parameters, + lexicon | | 92.8 % | 99.25 % | 7.2 % | 0.022 |
| Owner's 9 works, held-out (1,440 lines) | core | 20,587 | 74.1 % | 99.80 % | 25.9 % | 0.065 |
| | + lexicon | | 91.5 % | 99.32 % | 8.5 % | 0.025 |
| | measured parameters, + lexicon | | 94.7 % | 99.26 % | 5.3 % | 0.017 |
| Hypotactic open, hexameter held-out | core | 12,992 | 73.9 % | 99.78 % | 26.1 % | 0.065 |
| | Wiktionary only | | 86.0 % | 99.58 % | 14.0 % | 0.035 |
| | + full lexicon | | 90.9 % | 99.34 % | 9.1 % | 0.026 |

Per owner work (core / + lexicon, accuracy on decided): Iliad 99.65 / 99.52, Odyssey 99.65 / 99.48,
Hymns 99.88 / 99.28, Theogony 99.94 / 99.36, Works and Days 99.76 / 99.42, Shield 99.45 / 98.35,
Argonautica 99.88 / 99.53, Quintus 99.94 / 99.52, Nonnus 100.00 / 99.36.

### 6.2 Non-hexameter (Hypotactic open corpus, held-out chunks)

| Class | Lexicon | Lines | Units | Decided | Accuracy on decided | Ambiguous | Brier |
|---|---|---|---|---|---|---|---|
| elegiac pentameter | none | 617 | 7,373 | 74.5 % | 99.76 % | 25.5 % | 0.065 |
| | full | | | 93.5 % | 99.22 % | 6.5 % | 0.022 |
| iambic / trochaic / anapaestic (drama, Lycophron, Semonides) | none | 2,348 | 25,184 | 78.8 % | 99.89 % | 21.2 % | 0.055 |
| | full | | | 93.4 % | 99.18 % | 6.6 % | 0.023 |
| lyric and other (Pindar, choral, Theocritus …) | none | 1,852 | 22,538 | 72.0 % | 99.91 % | 28.1 % | 0.071 |
| | Wiktionary only | | | 84.8 % | 99.62 % | 15.2 % | 0.040 |
| | full | | | 92.5 % | 99.21 % | 7.5 % | 0.025 |

**Norma** (vowel length of α ι υ, scored on the vowel tree; 4,374 marked vowels in 1,378 rows):
core 546 decided, 98.72 % right (87.5 % ambiguous: without a lexicon most dichrona stay open);
Wiktionary only 2,868 decided, 97.91 %; full lexicon 3,593 decided, 96.47 %. Alcman's Partheneion
89.7 % (29 decided of 30), Bacchylides 95.0 % (322 of 360). Morpheus adds coverage but is less exact
than Wiktionary on these texts.

**Hand check** (`backend/scansion/data/handcheck.json`; texts read from the corpus by passage id;
gold = the metrical scheme's fixed positions; anceps and line end not scored; lines that do not fit
their scheme are reported, not scored):

| Passage | Lines | Fixed positions | Core: decided / right | + lexicon: decided / right |
|---|---|---|---|---|
| Sappho 1 (Lobel-Page; line 19 corrupt, excluded) | 27 | 208 | 154 / 154 | 188 / 186 |
| Sappho 31 (lines 13, 17 excluded) | 15 | 115 | 86 / 86 | 103 / 103 |
| Alcaeus 346 (lines 2, 6 excluded) | 4 | 52 | 35 / 35 | 50 / 48 |
| Sophocles, OT 1-15 | 15 | 121 | 93 / 92 | 111 / 110 |
| Archilochus 19 W | 4 | 32-33 | 26 / 26 | 28 / 28 |
| **Total** | 65 | 528-529 | 394 / 393 (99.7 %), 25.5 % ambiguous | 480 / 475 (99.0 %), 9.1 % ambiguous |

The six errors, checked by hand: τοιάνδε (OT 13, Attic inner correption of οι: the rule gives 0.95);
ἀθανάτωι (Sappho 1.14, ᾱ metri causa, Monro §386); ἰμέρρει (1.27, ῑ not marked in Morpheus);
λαθικάδεον (Alc. 346.3, ᾱ < κῆδος, unknown to the lexicon's marks); ἔνα (346.4, Morpheus ᾱ wrong for
Aeolic ἔνα). Auto-detect put the right metre first on every hand-checked line (Sapphic lines 20 of 20,
adoneans 7 of 7, Alcaeus 4 of 4, trimeters 19 of 19).

**Pindar, Olympian 1** (4 strophes + 4 antistrophes, 11 lines): a position's gold is the length a rule
settles with certainty in some responding line, with none saying the opposite (122 of 134 positions;
12 conflict = anceps or a scanner error). Core: strophe 1 + antistrophe 1, 166 units decided, all right,
70 ambiguous; **responsion of strophe 1 with antistrophe 1 resolved 46 of the 70, all correctly**,
24 stay ambiguous. With the lexicon: 217 right, 3 wrong, 16 ambiguous, 13 resolved by responsion.

**Prose** ([Plutarch], *Vita Homeri* 1.1, 119 units): core 57 certain long, 34 certain short,
4 likely long, 24 ambiguous (14 unknown α ι υ, 7 correption, 2 muta cum liquida, 1 digamma);
with the lexicon 9 ambiguous.

### 6.3 Metre layer (held-out open corpus)

| Metre | Lexicon | Lines | Fits without overruling a unit | Every weight right | Unit accuracy | Ambiguous before → after | Auto-detect top-1 |
|---|---|---|---|---|---|---|---|
| hexameter | none | 871 | 97.5 % | 96.6 % | 99.64 % | 26.1 → 0.3 % | 99.3 % |
| pentameter | none | 617 | 99.4 % | 98.4 % | 99.66 % | 25.5 → 0.2 % | 99.5 % |
| iambic trimeter | none | 930 | 99.1 % | 60.3 % | 95.53 % | 20.7 → 5.9 % | 99.4 % |
| iambic trimeter | full | 930 | 98.7 % | 82.0 % | 98.30 % | 6.8 → 2.3 % | 99.4 % |
| trochaic tetrameter | full | 59 | 94.9 % | 74.6 % | 98.23 % | 5.8 → 1.8 % | 94.9 % |

The trimeter's anceps positions cannot be settled by the metre, so unknown α ι υ there stay open; the
lexicon closes most of them.

### 6.4 Calibration (Hypotactic Iliad 13-24, + lexicon)

| p band | Units | Observed long, rules as written | Observed long, measured parameters |
|---|---|---|---|
| 0.0-0.1 | 47,002 / 55,094 | 0.006 | 0.010 |
| 0.1-0.2 | 8,092 / 84 | 0.035 | 0.083 |
| 0.2-0.3 | 84 / 3,470 | 0.083 | 0.246 |
| 0.5-0.6 | 9,924 / 3,664 | 0.442 | 0.173 |
| 0.8-0.9 | 183 / 1,045 | 0.743 | 0.844 |
| 0.9-1.0 | 53,373 / 55,702 | 0.995 | 0.995 |

The certain bands are well calibrated. The owner's 0.5 defaults are honest "undecidable" marks, but in
Homer the units at 0.5 are long only 44 % of the time (correption 23 %, unknown dichrona 15 %); the
measured parameters move them to 0.17-0.25 and the Brier score drops from 0.029 to 0.022. The 0.5-0.6
band under measured parameters (17 % long) is muta cum liquida across a boundary combined with an
unknown dichronon; a finer node would separate them.

### 6.5 What stays ambiguous, and why (core, Hypotactic lyric held-out, 28 % of units)

α ι υ with no accent rule (4,612 + 544 units: the bulk); muta cum liquida (562 in the word, 200 across
a boundary); epic lengthening before λ μ ν σ δ (245; only an epic tendency); correption (112);
digamma (32). With the lexicon the residue is mostly correption, muta cum liquida, conflicting
lexical marks and dichrona the sources leave unmarked.

### 6.6 Speed

Hypotactic Iliad, 500 lines, one line per call: core 1.2 ms median (p95 1.4, max 2.2); with the
lexicon 1.7 ms (p95 2.1); with the lexicon cache cleared before every line 2.1 ms (p95 2.9, max 3.9).
The first call of a process loads the rules file and opens the lexicon (~70 ms + ~30 ms, once).
`auto` (17 templates) adds 1-2 ms per line, ~20 ms for a long hexameter.

## 7. UI (spec; prototypes `scan.html`, `rules.html`)

* Units are coloured on a red (short) – purple (ambiguous) – blue (long) spectrum by `p_long`; a
  toggle shows the percentage under each unit; the unit boundaries are the owner's (vowel + following
  consonants, spaces included).
* Clicking a unit opens a popover: the percentage, the vowel and unit reasons ("long by position:
  ν τ inside the word", "possible correption: long diphthong before a vowel", "α ι υ of unknown
  length"), each with rule id and citation, the possible phenomena (synizesis p, digamma, line end) and
  the rule path.
* Options: lexicon on/off, dialect, metre (none / auto / template), "colour by metre fit" (posterior).
* `rules.html` renders the whole tree (collapsible, with connectors), each rule's condition, value,
  reason, citation, measured share (core and with lexicon) and real example units from Iliad 1 and the
  hand-check texts; sliders tune the parameters for a live preview line; the YAML can be edited,
  validated (errors listed by rule) and saved on the local dev server.

## 8. Open questions for the owner

1. **Defaults vs measured values.** Keep 0.5 for correption, muta cum liquida and unknown dichrona
   (honest, but in Homer they are long far less often), or ship measured values, perhaps per genre
   (epic: mcl_word 0.99; drama: lower)? A `genre` input would let one rules file hold both.
2. **Finer correption nodes.** -αι (7 % kept long) and η (70 %) behave very differently; split
   COR-EXT by nucleus? It is a general rule, measured, not hexameter tuning.
3. **Line-final unit.** Now flagged FIN-ANC and scored by its own rules (so σελάννα shows ᾱ); the metre
   layer ignores it. Should the UI grey it out instead?
4. **Dialect statement.** DIA-ETA needs the caller to say "aeolic"/"doric". Infer it from the author
   (Sappho, Alcaeus, Pindar) when the text comes from the corpus?
5. **Morpheus vs Wiktionary.** On Norma, Morpheus marks raise coverage but lower accuracy (96.5 % vs
   97.9 %). Rank Wiktionary above Morpheus when they conflict?
6. **Epic lengthening and digamma** fire in any text; restrict them to a stated epic genre?
7. **Synizesis across words** (μὴ οὐ, ἐπεὶ οὐ) is not flagged yet; add a node?

## 9. To ship

1. Mount `backend.scansion.api.router` in `backend/server.py` (one `include_router` line) and add
   `pyyaml` to `requirements.txt` (the rules file needs it; it is installed locally but not listed).
2. Ship `data/scansion/quantities.sqlite` (125 MB; built from local files in ~1 min with
   `scripts/scansion_build_lexicon.py` once Morpheus has been run over the corpus spellings, see the
   script) or let the API run without the lexicon (`lexicon` reported false).
3. Decide §8.1 (parameters) and freeze `rules.yaml`; keep `MELOS_SCANSION_DEV` unset in production
   (saving rules is refused without it).
4. Rate-limit `/api/scan` like the other text endpoints; it is cheap (ms) but `auto` and `segment`
   are heavier.
5. Turn `scan.html` into the reader/composer component; keep `rules.html` for editors only.
6. Attribution on the page: Hypotactic (Chamberlain) is used only for evaluation; Monro (DCC,
   CC BY-SA), Wiktionary (CC BY-SA), Morpheus (CC BY-SA 3.0 US) and LSJ (CC BY-SA 4.0) data are used at
   run time and need credit lines.

**Shipped in release V (2026-10-09):** items 1, 2 (the lexicon is a read-only mount, `MELOS_SCANSION_LEXICON`;
SQLite `immutable=1`, so its pages live in the OS page cache; the in-process lookup cache is bounded at 50,000
forms), 4 (`/api/scan` and `/api/scan/rules/validate` are in the per-client limit of `backend/rate_limit.py`),
5 (the composer canvas and the reader overlay below) and 6 (credit line on the composer page). §8's open
questions keep their defaults (0.5 parameters, no genre input, no correption split, FIN-ANC as now).

## 10. Release V: palette, reader overlay, metre-locked resolution

### 10.1 Palette (shared tokens)

`css/scansion.css` defines `--scan-short`, `--scan-mid`, `--scan-long` (RGB triples) for the reader and the composer.
The spectrum runs from the site's saffron (deepened to `#a66000` for 4.9:1 text contrast on white) through slate
(`#6c727a`, the uncertain middle) to the site's sea blue (`#2b5a87`); colours between are interpolated, so the
probability stays continuous. Dark stops (composer only; the reader has no dark theme): `#f0b048`, `#9ea6b0`,
`#7ab0eb`. Colour-vision check (Machado et al. 2009, severity 1, CIELAB ΔE76 between stops):

| Theme | Vision | short–long | short–mid | mid–long |
|---|---|---|---|---|
| light | normal / protanopia / deuteranopia / tritanopia | 89 / 78 / 89 / 72 | 65 / 56 / 61 / 51 | 29 / 27 / 32 / 25 |
| dark | normal / protanopia / deuteranopia / tritanopia | 97 / 94 / 98 / 73 | 68 / 67 / 68 / 45 | 29 / 28 / 31 / 28 |

The dev page's red→purple→blue had mid–long ΔE 11 under protanopia. Metre violations in the composer are a
wavy underline in the error colour (shape, not hue, carries it).

### 10.2 Reader overlay (`js/reader-scansion.js`, `GET /api/scan/passage?id=`)

- Two toggles above a Greek poem: **Scansion** (marks above syllables) and **Syllable breaks** (bold `|` between
  syllables). Each is remembered per viewer (`localStorage`, wrapped in try/catch). Off by default.
- The poem is scanned on demand when a toggle is first turned on: the server scans the stored text itself (the
  printed lines joined by newlines, the same offsets the reader's word buttons carry), with the author's dialect
  (Lesbian → aeolic, Doric), and caches 512 passages. The reader checks the returned text equals what it prints.
- **Marks:** `–` long (p ≥ 0.5), `⏑` short, `×` anceps (only where a recorded metre puts an anceps or the line end).
  Uncertain syllables (30–70 %) are drawn lighter. The mark is anchored over the syllable's vowel; for a
  diphthong over its second vowel (the nucleus's last letter, skipping combining marks). It sits above the line
  box's top, clear of breathings, accents and circumflexes (checked on ἆ ᾄ ῗ Ἄ Ὦ ᾯ ΐ at 34 px).
- **Bars** sit between the letters at the scanner's unit boundaries (vowel + following consonants, the owner's
  units), inside words only. Marks and bars are CSS generated content inside the word's `<button>`: a click
  anywhere on the word, bars included, still inspects the whole word, and selection/copy never include them.
  Turning both toggles off restores the reader's original DOM.
- **Gaps:** a word containing an editorial sign (`[ ] ⟨ ⟩ { } < > † …`, a dotted letter U+0323, or a dotted lacuna)
  gets no marks, so nothing is invented across a lacuna; its bars still show where letters survive.
- Clicking a word shows its syllables with % long and the deciding reason under the poem (beside the usual word
  panel), including any metre adjustment.

### 10.3 Metre-locked resolution (reader only)

Only for stored poems whose metre is **recorded** (`backend/scansion/recorded_metres.py`; the corpus has no metre
field): Sappho frr. 1–42 (Book 1 of the Alexandrian edition, Sapphic stanzas; L–P/Voigt numbering), Homer's Iliad
and Odyssey and Hesiod's Theogony and Works and Days (hexameter). Nothing is guessed from a scan.

Per line, the scanner fits each of the metre's line templates and keeps the best one that parses; lines with
editorial signs, and lines that parse in no template, are left alone. Then, for each syllable at a position whose
quantity the parse fixes (long or short; `x`, `X` and the line end `F` are anceps and never adjusted):

- p_long in [0.30, 0.70] → moved 0.50 toward the required quantity, clamped to 0..1 (70 % where short is required →
  20 %; 40 % where long is required → 90 %);
- p_long outside the band and against the metre (e.g. 95 % where short is required) → **not** moved; flagged as a
  conflict (textual or responsion problem), shown with a wavy underline under its mark.

The click reason says it: "metre: Sapphic hendecasyllable, position 2 requires short; 50% → 0% (scanner 50%)".
Sappho 1 (Campbell): 28 lines locked, 13 syllables adjusted, 1 conflict; Sappho 31: 15 of 17 lines locked (2 with
gaps), 16 adjusted, 4 conflicts; fr. 96 (not Book 1): nothing adjusted.

**The composer never applies it.** `/api/scan` has no passage input and no lock; `backend/compose_routes.py`,
`backend/scansion/api.py` and `js/composer.js` never import or call the lock (`tests/test_scansion_lock.py`
asserts both the unchanged probabilities and the absence of any call). The composer's scans exist to catch the
writer's errors.
