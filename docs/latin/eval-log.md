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

## Looks at the held-out half

| Date | Setting | Reason |
|---|---|---|
| 2026-10-10 19:45 PDT | core, as typed and folded | LA1 milestone score (first and only look) |
