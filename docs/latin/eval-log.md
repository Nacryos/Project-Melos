# Latin scanner: evaluation log

Gold: Hypotactic Latin (David Chamberlain, CC BY 4.0), Catullus's Phalaecian hendecasyllables, 552 lines in 43 poems
(`data/open/latin/hypotactic/`, ingested 2026-10-10). Split: odd poem numbers development (263 lines), even held-out
(289). Scorer: `scripts/scansion_eval_la.py`. "Decided" = p_long ≤ 0.1 or ≥ 0.9; the line-final unit is not scored;
Hypotactic's prodelision (the syllable before *est* marked elided) counts as our prodelision. Poems 55 and 58b may use
the decasyllabic template beside the hendecasyllable (PRD §4.5). Reports: `docs/latin/eval/*.json`.

## LA1 milestone: core scanner, no lexicon (rules_la.yaml v1, metres_la.yaml v1)

Scored 2026-10-10 19:45 PDT. The held-out half was scored **once** after the development errors were fixed; it is frozen for this
milestone. Every later look at the held-out half is logged below.

| Set | Spelling | Lines | Misaligned | Units | Decided | Accuracy on decided | Brier | Elision right (candidates) | Lines fitting | Best pattern = gold | Negative control: swap / replace rejected |
|---|---|---|---|---|---|---|---|---|---|---|---|
| development | as typed (v, j written) | 263 | 0 | 2615 | 52.5 % | 99.93 % | 0.115 | 98.4 % (125) | 261/263 | 160/263 | 78 % / 77 % |
| development | u and i only (owner's typing) | 263 | 1 | 2605 | 52.4 % | 99.93 % | 0.115 | 98.4 % (125) | 260/262 | 159/262 | 78 % / 77 % |
| held-out (frozen) | as typed (v, j written) | 289 | 4 | 2848 | 51.6 % | 99.59 % | 0.120 | 99.3 % (148) | 281/285 | 186/285 | 77 % / 77 % |
| held-out (frozen) | u and i only (owner's typing) | 289 | 10 | 2788 | 51.5 % | 99.58 % | 0.120 | 99.3 % (143) | 275/279 | 182/279 | 75 % / 78 % |

What the numbers mean: without a lexicon the scanner decides about half the syllables (position, finals, monosyllables,
diphthongs) and is right on 99.6 % of them held-out; the other half are open vowels inside words (`vowel_default`),
which the lexicon phase (LA2) must settle. The metre layer then accepts almost every genuine line (the four held-out
rejections are below) but matches the gold pattern on only 65 %, because open syllables are placed by the base
priors rather than by knowledge; that is also why the negative control rejects only about three perturbed lines in
four. Both figures are the lexicon's job to raise, and both must be reported again after LA2 on the same held-out
half.

**Held-out errors on decided units (not tuned on):**
- 10:14 `e t` p=0.05 gold L (NATURE / FIN-E): ‘at certe tamen,' inquiunt ‘quod illic
- 36:10 `e l` p=0.05 gold L (NATURE / FIN-E): jocose lepide vovere divis.
- 36:10 `e v` p=0.05 gold L (NATURE / FIN-E): jocose lepide vovere divis.
- 36:13 `a Cn` p=0.95 gold S (INIT-OTHER / FIN-A): quaeque Ancona Cnidumque harundinosam
- 38:2 `e` p=0.98 gold kept (ELISION / ): malest, me hercule, et laboriose,
- 46:11 `e v` p=0.05 gold L (NATURE / FIN-E): diversae varie viae reportant.
- 56:3 `e qu` p=0.05 gold L (NATURE / FIN-E): ride quidquid amas, Cato, Catullum:

**Held-out misaligned lines (syllable count differs from gold; not scored):**
- 10:8 12 units vs 11 gold: et quonam mihi profuisset aere.
- 46:3 12 units vs 11 gold: jucundis Zephyri silescit aureis.
- 46:9 12 units vs 11 gold: o dulces comitum valete coetus,
- 50:21 13 units vs 12 gold: est vehemens dea: laedere hanc caveto.

Causes: adverbs in -ē and 2nd-conjugation imperatives not in the YAML list (certē, lepidē, variē, iocosē, ridē) and
Greek initial *Cn-* (Cnidum, no position) are for the lexicon or a later rule; *me hercule, et* is a hiatus after an
interjection-like phrase; the misalignments are lexical syllable counts (vehemens as two syllables, aureis with
synizesis, aere as the diphthong) that the lexicon or a synizesis prior settles.

**Development-half errors remaining:** 3.16 *male! o* (hiatus kept, our elision prior 0.6, no violation); 55.4 *te in*
(gold semi-hiatus); 55.9 *avelte* (an emended reading).

## LA2 milestone: core + quantity lexicon (quantities_la.sqlite, built 2026-10-10)

Lexicon: Winge's macron table (812,588 rows), Wiktionary via Kaikki (1,988,775 form rows), Lewis & Short headwords
(58,160); 1,069,819 distinct keys; codes and licences in `docs/latin/lexicon.md`. Explicit marks decide; a vowel the
sources leave unmarked is short by their convention (`LEX-S-CONV`, 0.1); a form with readings of both lengths
(nom./abl. -a, basia/basiā, homographs) is a `LEX-CONFLICT` at 0.5 and left to the metre. The held-out half was scored
**once** for this milestone after the development half was clean.

**Development half** (as typed; the folded run differs by one misaligned line, *eluentur*):

| Setting | Decided | by position | by diphthong / monosyllable | by finals and lists | by lexicon | Accuracy on decided | Brier | Elision right | Lines fitting | Best pattern = gold | Perturbed lines rejected (swap / replace) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| core | 52.5 % | 33.7 % | 4.5 % | 14.3 % | 0.0 % | 99.93 % | 0.115 | 98.4 % | 261/263 | 230/263 | 78 % / 77 % |
| lexicon | 87.5 % | 33.7 % | 4.5 % | 9.0 % | 40.3 % | 99.87 % | 0.034 | 98.4 % | 259/263 | 242/263 | 84 % / 79 % |

**Held-out half (frozen)**:

| Setting | Decided | by position | by diphthong / monosyllable | by finals and lists | by lexicon | Accuracy on decided | Brier | Elision right | Lines fitting | Best pattern = gold | Perturbed lines rejected (swap / replace) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| core | 51.6 % | 33.3 % | 4.9 % | 13.4 % | 0.0 % | 99.59 % | 0.120 | 99.3 % | 281/285 | 253/285 | 77 % / 77 % |
| lexicon | 87.9 % | 33.3 % | 4.9 % | 7.1 % | 42.7 % | 99.96 % | 0.032 | 99.3 % | 284/285 | 275/285 | 79 % / 81 % |

What the numbers say about the owner's doubt (PRD §4.3): position alone fixes a third of the syllables; diphthongs,
monosyllables, finals and the word lists another fifth; the macronised lexicon decides a further two fifths and is
right 99.9 % of the time; what stays open (12 %) is mostly genuine lexical ambiguity (`LEX-CONFLICT`: 30 % long on the
development half), which the metre then settles: the best parse equals the gold pattern on 96.5 % of held-out lines,
and genuine lines are accepted at 99.6 % while four perturbed lines in five are rejected. Latin quantity is therefore
lexical plus positional in practice, as the owner supposed, and the open resources cover Catullus well; the residue is
the poet's licence (Ītalorum, Cnidum without position) and hiatus after an interjection-like phrase.

**Held-out errors on decided units (not tuned on):**
- 36:13 `a Cn` p=0.95 gold S (INIT-OTHER / LEX-CONFLICT): quaeque Ancona Cnidumque harundinosam
- 38:2 `e` p=0.98 gold kept (ELISION / ): malest, me hercule, et laboriose,

Calibration (held-out, lexicon): 0.0-0.1: 0.00 long (n=537); 0.1-0.2: 0.00 long (n=413); 0.2-0.3: 0.25 long (n=24); 0.4-0.5: 0.08 long (n=25); 0.5-0.6: 0.36 long (n=280); 0.6-0.7: 0.83 long (n=12); 0.9-1.0: 1.00 long (n=1557).

Measured shares on the development half (lexicon run), for `docs/latin/hypotheses.md`: LEX-CONFLICT units are long
0.302 of the time (n=212); FIN-O-IAMB
long 0.9 (n=10); MCL-WORD with a lexical short vowel long
0.2 (n=5); VAV-SHORT long 0.0 (n=212);
elision happened on 1.0 of ELI-CAND units (n=103), 0.9 of long monosyllables
(n=10), 0.667 before interjections (n=3); synizesis happened on 0.0 of
232 candidates.


## LA5: Horace's Odes 1 on the Hypotactic gold (every metre, all 876 lines; core + lexicon, as typed)

The first look at Horace. No split was held out: Odes 1 is one book, the templates were written from the handbooks
before the run, and the only tuning after the first pass was six word-list entries and one new hypothesis read off the
misaligned and mis-scored lines below (then re-scored; the Catullus held-out numbers did not move). The eval picks the
template of a stanza line by its position (`scripts/scansion_eval_la.py`, `TEMPLATE_FOR` maps Hypotactic's labels).

| Hypotactic metre | Template | Lines | Misaligned | Decided | Accuracy on decided | Brier | Lines fitting | Best pattern = gold | Perturbed accepted (swap / replace) |
|---|---|---|---|---|---|---|---|---|---|
| alcaic | alcaic_horace | 240 | 3 | 88.8 % | 99.79 % | 0.032 | 237/237 | 233 | 16 % / 17 % |
| sapadon | sapphic_horace | 220 | 0 | 87.4 % | 99.88 % | 0.035 | 220/220 | 220 | 7 % / 21 % |
| asc1 | asclepiad_lesser_horace | 36 | 0 | 87.1 % | 100 % | 0.032 | 36/36 | 36 | 19 % / 17 % |
| asc2 | asclepiad_second_horace | 96 | 1 | 86.9 % | 99.73 % | 0.038 | 95/95 | 95 | 10 % / 23 % |
| asc3 | asclepiad_third_horace | 92 | 0 | 84.6 % | 99.61 % | 0.042 | 92/92 | 91 | 9 % / 17 % |
| asc4 | asclepiad_fourth_horace | 64 | 1 | 86.0 % | 100 % | 0.036 | 63/63 | 63 | 20 % / 23 % |
| asc5 | asclepiad_greater_horace | 24 | 1 | 85.2 % | 100 % | 0.038 | 23/23 | 23 | 13 % / 39 % |
| arch4 | archilochian_fourth_horace | 20 | 0 | 86.3 % | 100 % | 0.036 | 20/20 | 19 | 15 % / 25 % |
| alcmanic_strophe | alcmanic_horace | 68 | 0 | 88.5 % | 99.71 % | 0.034 | 66/68 | 61 | 32 % / 37 % |
| sapphic2 | sapphic_greater_horace | 16 | 0 | 85.0 % | 100 % | 0.038 | 16/16 | 16 | 13 % / 20 % |
| **all** | | **876** | **6** | **87.5 %** | **99.8 %** | | **868/870** | **857 (98.5 %)** | |

Reading: Horace scans as well as Catullus did on the held-out hendecasyllables (decided 88.9 % at 99.96 %, 284/285
fitting, 96.5 % pattern): the quantity lexicon and the position rules carry over without a Horace-specific rule. The
Alcaic and the Alcmanic strophe accept more perturbed lines than the Phalaecian (the Alcaic's two ancipitia and the
hexameter's bicepses give a swapped line more room), so the negative control is weaker there; the Sapphic rejects
93 % of swaps. Elision is right on 94-100 % of candidates per metre; the misses are interjection hiatus (heu, heu)
and two gold hiatuses before a vowel.

What the first pass taught (16 misaligned lines, now 6): Greek names and bronze. `aena`, `aenea` (bronze) are
trisyllabic (ă-ē-na) while `Aenēās` keeps its diphthong, so the ae split applies to `aen-` only when the word is not
capitalised; `Lāertēs`, `Pholoē`, `coēmptōs` split; `Teucer` has a Greek eu; `anteit` is one syllable by synizesis;
`āerius` and `chorēa` keep their Greek long vowels before a vowel; `aeque` is an adverb in -ē, not ae + -que. One
new hypothesis, INIT-GREEK: a short final vowel before a Greek initial cluster (cn-, pn-, ps-, pt-, ct-, tm-, bd-)
seldom makes position (Catullus 36.13 `Cnidumque`, Horace 1.15.17 `Cnosii`, both short in the gold; p 0.15 like
s impura). The six lines still misaligned are genuine ambiguities the scanner cannot see from the spelling:
`aera` (bronzes, ae-ra) against `āera` (air), `antehac` as one syllable, and three where the gold reads a diphthong
in a Greek name the lists do not know.

Decided-unit errors worth a note, not fixed: Alcaic and Asclepiad line-initial ancipitia where the gold marks a
short syllable as long by position in the metre (`olentis` 1.17.7, `magus` 1.27.22: brevis in longo, the same gold
convention the pattern metric already ignores at line end); `Tyndari` (Greek vocative in short -ĭ, the lexicon's -ī).

Reports: `docs/latin/eval/odes1-<metre>.json`; the Catullus regression run `catullus-hendecasyllables-held_out-lexicon-v3.json`
(decided 88.9 %, accuracy on decided 100 %, 284/285 fitting, 275/285 pattern: unchanged except the `Cnidumque` unit now right).

## 2026-11-15: every Catullan hendecasyllable in the gold, dev and held-out together (core + lexicon, as typed)

All 552 lines the gold labels `hendecasyllables` (43 poems; 263 dev, 289 held-out), run by
`scripts/validate_phalaecian_gold.py`; poems 55 and 58b may take the decasyllabic template. Counts are over all
lines, misaligned ones included (the milestone tables above leave misaligned lines out of the fit counts, which is
why 285 there is 289 here). Per-line result: `docs/latin/eval/catullus-hendeca-all-2026-11-15.json`.

| | Lines | Same syllable count as gold | Accepted | Best pattern = gold | Accepted and = gold |
|---|---|---|---|---|---|
| All, before | 552 | 548 | 546 | 521 | 520 |
| All, after the fix | 552 | 549 | 547 | 522 | 521 |
| Dev, before and after | 263 | 263 | 259 | 243 | 242 |
| Held-out, before | 289 | 285 | 287 | 278 | 278 |
| Held-out, after | 289 | 286 | 288 | 279 | 279 |

**THIS SPENDS THE HELD-OUT SET.** The one fix below was found on a held-out line (46.9), and this entry reads every
held-out miss line by line. From today the held-out half of the Catullan hendecasyllables is no longer an unseen
test for the scanner: its numbers are development numbers. A clean test now needs lines the scanner has never been
tuned on (another author's hendecasyllables, e.g. Martial or Statius, or the Priapea).

The fix: `coet` taken out of `SPLIT_OE` (`backend/scansion/latin.py`). `coetus` keeps its diphthong (coe-tūs) in all
five places of the gold: Catullus 46.9, 64.34, 64.386, 64.408, 66.37. The split made 46.9 one syllable too long.

Lines rejected after the fix (5 of 552), each with its cause; none fixed:

| Line | Cause |
|---|---|
| 1.5 | `Ītalōrum`: Catullus lengthens the I; the lexicon has it short (as in prose), so the 6th place fails. A lexicon override would be right for verse only |
| 38.2 | gold hiatus `hercule, et` (editors often emend), and `malest` unknown to the lexicon |
| 55.9 | `avelte`: a textual crux, not a Latin word |
| 55.10 | `Camerium`: resolved base, 12 syllables; no template covers it |
| 55.11 | a 7-syllable fragment (lacuna) |

Lines accepted but with a best pattern unlike the gold (26). Every one differs in the first or second syllable
only: the scanner reads a spondaic base where the gold has an iamb or trochee. The base prior (spondee 0.80) beats
a syllable the scanner already thinks is probably short.

| Cause | Lines |
|---|---|
| vowel before vowel, short at p 0.1 (VAV-SHORT), overruled by the base prior | 1.4, 3.17, 7.2, 32.2, 35.9, 53.3 |
| lexicon short by convention at p 0.1 (LEX-S-CONV), overruled | 35.2, 42.1, 45.10, 49.1 |
| lexicon gives both lengths, p 0.5 (final -a nominative or ablative, homographs: LEX-CONFLICT) | 35.18, 36.7, 36.14, 40.7, 41.2, 41.3, 42.11, 42.19, 45.6, 45.25, 58.2 |
| vowel unknown or a name, p 0.4-0.5 | 33.2 `Vibenni`, 38.1 `Malest`, 35.1 `Poetae`, 41.1 `Ameana` |
| muta cum liquida, lexicon short at p 0.24 | 27.7 `migrate` |

Tried and not adopted, because none is free of regression (lines accepted / pattern = gold; Horace Odes 1 = 876 lines):

| Change | Dev (263) | Held-out (289) | Horace Odes 1 |
|---|---|---|---|
| none (after the coet fix) | 259 / 243 | 288 / 279 | 870 / 860 |
| `vocal_before_vowel` 0.1 -> 0.05 | pattern 248 | pattern 280 | accepted 868 (2 lost) |
| that, and `lex_short_convention` -> 0.05 | 255 / 251 | 285 / 281 | accepted 864 (6 lost) |
| base priors as measured on dev (spondee 0.862, trochee 0.061, iamb 0.077) | pattern 237 | pattern 272 | not run |

Regression check with `scripts/scansion_eval_la.py --lexicon` (the milestone metric, misaligned lines left out):

| | Misaligned | Decided | Accuracy on decided | Brier | Elision | Lines fitting | Pattern = gold | Perturbed accepted (swap / replace) |
|---|---|---|---|---|---|---|---|---|
| Dev | 0 | 88.2 % | 99.87 % | 0.0325 | 98.4 % | 259/263 | 243/263 | 42/263, 55/263 |
| Held-out, before | 4 | 88.9 % | 100 % | 0.030 | 99.3 % | 284/285 | 275/285 | 58/284, 55/284 |
| Held-out, after | 3 | 88.9 % | 100 % | 0.0298 | 99.3 % | 285/286 | 276/286 | 61/285, 57/285 |

Dev fitting is unchanged from LA2 (259/263); dev pattern is 243 against the 242 logged at LA2 (already 243 before
this fix; not caused by it). Held-out gains the one line. The negative control moves from 20.4 % / 19.4 % of
perturbed lines accepted to 21.4 % / 20.0 %. One seeded random stream runs through the lines in order, so the line
that joined (46.9) changes the perturbation of every later line; whether the move is that redraw or a real
loosening was not separated, and it is not an improvement. Still misaligned on held-out: 10.8 `aere`, 46.3
`aureis`, 50.21 `vehemens` (synizesis). Horace Odes 1 is unchanged by the fix (870 accepted, 860 = gold of 876).

Known and open: the base prior's overruling of p 0.1 shorts (10 lines) is the largest single cause and wants a
principled change to how the prior combines with unit evidence, not a threshold nudge.

## 2026-11-15, refinement round: iambus, aes, Ītalia, and the size of the "free long" hole

Four defects reported by the other checks. Evidence is counted on the Hypotactic gold for Catullus, Virgil and
Horace (`lines.jsonl.gz`, `lines-virgil.jsonl.gz`). No gold-derived quantity layer exists or was on in any run here.

| Defect | Finding | Change |
|---|---|---|
| `iambos` 40.2, `iambis` 54.6 rejected when typed without j | the initial i was read as a consonant | `GREEK_INITIAL_I` gains the stems vocalic in every place of the gold: iamb- (4), Iacch- (4), Iāpy- (8), Īapet- (1), Iarb- (3), Ioll- (4), Iōpa- (1), Iaer- (1), iaspi- (1), ier- (1) |
| `aere` 10.8 split a-e-re | `SPLIT_AE` split every word in aer- | diphthong : split in the gold: aere 28 : 6, aera 14 : 11, aeris 3 : 2, aerat- 12 : 0, aere- + vowel 11 : 2; aeri- + vowel 0 : 20, aer 0 : 2. Now only aeri- + vowel, `aer` and `aerem` split. The six `āere` (air) and eleven `āera` are now read wrongly: the spelling cannot tell them apart |
| `Italorum` 1.5 rejected | lexicon has short I | new vowel rule LICENCE before LEX: Ītalia + vowel p 0.95 (long in 48 of 48 places), other Ital- p 0.18 (long in 9 of 51: Catullus 1.5, Aeneid 3.185, 7.643, 9.698) |
| `Cui dono lepidum donum libellum` passes with dōnum's long o in the short 7th place | not a lexicon gap: the lexicon marks it long, but `lex_long` is 0.9, which leaves the short reading at 0.1, above the violation line of 0.05. Every lexicon long in an open syllable can stand in a short place | NOT FIXED (below) |

Whole set (`scripts/validate_phalaecian_gold.py`, all 552 lines; JSON rewritten):

| | Same count as gold | Accepted | Pattern = gold |
|---|---|---|---|
| Before this round | 549 | 547 | 522 |
| After | 550 | 548 | 522 |

Dev 260 accepted (was 259: 1.5), 243 = gold. Held-out 288 accepted, 279 = gold, 287 aligned (was 286: 10.8).
10.8 is a held-out line: the held-out half was already spent in the entry above. Horace Odes 1: 870 accepted,
860 = gold of 876, unchanged. Rejected now: 38.2, 55.9, 55.10, 55.11. The 26 base misreads are untouched.

**Size of the hole.** Forms attested at least 3 times in the Catullus + Virgil + Horace gold: 7,346; in the quantity
lexicon: 6,989; with at least one non-final syllable that has one weight only in every attestation: 6,632 forms,
11,075 such syllables. The scanner leaves 4,285 of those syllables free (38.7 %; neither weight would be a
violation) in 3,509 forms (52.9 %). By cause: lexicon long at p 0.9 where the gold is always long 2,069 (the
dōnum class); vowel before vowel at p 0.1, gold always short 770; lexicon short by convention at p 0.1, gold always
short 534; lexicon conflict at p 0.5-0.6 678; Greek vowel before vowel 161; other about 70.

Tried: `lex_long` 0.9 -> 0.96 rejects the dōnum line but loses 1 dev line and 4 Horace lines (866 of 876), so it
was not adopted. (0.95 changes nothing: 1 - 0.95 is a hair above 0.05 in floating point.) The gold index
`data/scansion/prosody_la.sqlite` could close the hole for the attested forms as an override layer; that layer was
NOT built in this round. If built it must stay off in `scripts/scansion_eval_la.py` and
`scripts/validate_phalaecian_gold.py`, or the gold grades itself.

## Looks at the held-out half

| Date | Setting | Reason |
|---|---|---|
| 2026-10-10 19:45 PDT | core, as typed and folded | LA1 milestone score (first and only look) |
| 2026-10-10 19:59 PDT | core + lexicon, as typed and folded | LA2 milestone score (second look; the pattern metric now ignores the line-final anceps, so the core rows were re-read too) |
| 2026-10-10 20:21 PDT | core + lexicon, after the lexicon audit's fixes (Lewis & Short "either" marks, Cyrillic y, Wiktionary page titles without marks dropped; Winge rows deduped to 325,380) | LA2 rebuild (third look). Held-out, lexicon: decided 88.9 %, accuracy on decided 99.96 %, Brier 0.030, lines fitting 284/285, best pattern = gold 275/285, perturbed rejected 80 % / 81 %. The LA2 tables above are from the first build; these are the current numbers |
| 2026-10-11 (LA5) | core + lexicon, as typed, after the Horace list fixes and INIT-GREEK | regression check only (fourth look): decided 88.9 %, accuracy on decided 100 %, 284/285 fitting, 275/285 pattern, perturbed accepted 20 % / 19 %: no movement |
| 2026-11-15 22:50 PST | core + lexicon, as typed; every line read one by one | whole-set validation (fifth look, and the last as a held-out set). The `coetus` fix came from held-out 46.9 and every held-out miss was read: **the held-out half is spent**. After the fix: 3 misaligned, decided 88.9 %, accuracy on decided 100 %, 285/286 fitting, 276/286 pattern, perturbed accepted 21.4 % / 20.0 % |
| 2026-11-15 23:06 PST | core + lexicon, as typed, after the iambus / aes / Ītalia fixes; no gold layer | regression check (the set is already spent): 288/289 accepted, 279 pattern = gold, 287 aligned |
