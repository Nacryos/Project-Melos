# Latin pool: measurement 1 (2026-10-10 21:24 PDT)

Setting: the dev stack (`scripts/latin_dev_stack.sh`), Fable 5.1, research turn at xhigh and pool fills at medium
(release W defaults), `COMPOSER_POOL_PARALLEL` 4. Poem: Catullus / phalaecian / language la; English source of three
sentences (a Catullan drinking invitation, `docs/latin/pool/` record). Script: `scripts/latin_pool_measure.py`. One run per
cell (single samples, as in the Greek measurement 2). Costs are the agent's own per-turn figures.

| Run | First passing candidate | Passed (whole lines) | Rejected by the lint (by check) | Lint pass rate | Time to the fill's end | Cost |
|---|---|---|---|---|---|---|
| A words L1 (cold, research starting) | 9.3 s | 12 (0) | 4 {'L7': 4} | 0.75 | 33.0 s | $0.25 |
| B lines L1 + 3 ahead | 36.0 s | 19 (11) | 7 {'L7': 7} | 0.73 | 76.5 s | $0.67 |
| C words mid-L1 after 'Nunc nigrum,' (3 syllables used) | 8.4 s | 12 (0) | 1 {'L7': 1} | 0.92 | 17.7 s | $0.12 |
| D lines L2 after an accepted L1 | 20.4 s | 6 (5) | 1 {'L7': 1} | 0.86 | 48.9 s | $0.26 |

Total $1.306 for the four requests (the research turn is inside run A/B's cost).

Reading: next words reach the pop-up in 8-9 s (cold, before the research ends, and mid-line after a prefix), the same
as the Greek figure (9-11 s); whole lines for a stanza of four Phalaecians arrive from 36 s with 11 whole lines in
77 s (Greek Sapphic stanza: 143 s to three per line); a line-2 fill after an accepted line 1 gives five whole lines in
49 s. The lint rejected 13 of 62 proposals, all on the metre (L7); none on forms (every proposed word was printed in
Catullus or Horace or known to the paradigm lexicon). Whole lines offered, each passing metre, forms and the
verbatim check: hac nocte, o socii, bibamus atrum; venite, hac bibimus nigrum Falernum; cras imber sibi totam habeto Romam; ardescant, pereant licet lucernae; Nunc nigrum, pueri, date huc Falernum; Nox haec, o pueri, Falerno nigro. The elision-across-the-caret path was exercised in run C (prefix "Nunc nigrum,",
three syllables used, eight slots open). The agent made no research lookups (`la_concordance`, `la_forms`) for this
short source; a longer or more allusive source, and the chat, are the next measurement.

# Latin pool: measurement 2, allusive source and chat (2026-10-10 23:25 PDT)

Setting as in measurement 1 (same dev stack, now with the LatinCy sidecar and the contextual lemma reading), plus
`--source allusive --chat`: an English source of seven sentences that echoes Catullus 31 (Sirmio), 5 (vivamus, the
kisses, the short light), 8 (obdura), 46 (spring, the itching mind) and 101 (ave atque vale), and an opening chat turn
asking which poems it echoes and which Latin phrases could be reused whole in a hendecasyllable. Record
`docs/latin/pool/20261010-232540.json`. Single samples, as before.

**Chat turn.** The research tools were used at once and heavily: 33 tool calls in the first 52 s (12 `la_concordance`
lookups: Sirmio, ocelle, vivamus, dormienda, obdura, egelidos, aequora, vale ...; 13 `la_lemma` headword checks:
basium, conturbo, fulgeo, sector, inferiae, cachinnus, perpetuus ...; 5 `cite`; 1 `scan`; 1 `la_forms`), then one
`propose_candidates` with 8 whole lines, every one passing metre and forms: five verbatim Catullan hendecasyllables
(5.1, 5.5, 5.6, 46.1, 46.7, 46.8, each labelled verbatim with its locus) and three adaptations of 31 reset from the
choliambic into the hendecasyllable (`Sirmio, insularumque ocelle, salve`, `ridete, o Lydiae lacus et undae`). The
driver's six-minute cap then closed the stream before the agent wrote its answer (374 s elapsed, 57 characters of
preamble stored), so the time to a written answer is not measured here; a chat-only re-run with a ten-minute cap
follows below.

| Run | First passing candidate | Passed (whole lines) | Rejected by the lint (by check) | Lint pass rate | Time to the fill's end | Cost |
|---|---|---|---|---|---|---|
| A words L1 (cold, research starting) | 8.8 s | 10 (0) | 5 {'L7': 5} | 0.67 | 42.2 s | $0.21 |
| B lines L1 + 3 ahead | 10.5 s | 21 (19) | 18 {'L7': 18} | 0.54 | 215.6 s | $1.25 |
| C words mid-L1 after 'Sirmio, o' (4 syllables used) | 14.5 s | 9 (0) | 3 {'L7': 3} | 0.75 | 22.0 s | $0.15 |
| D lines L2 after an accepted L1 | 74.4 s | 8 (8) | 0 | 1.00 | 89.4 s | $0.42 |

Total $2.036 for the four fills (the chat turn's own cost is not relayed through the chat stream; the agent's record
has it). Accepted line 1: `Sirmio, o clarum ocelle, te revisi` (first whole line, at 10.5 s).

Reading against measurement 1: next words are as fast (8.8 s cold, 14.5 s mid-line against 9.3 and 8.4), and the
first whole line came far sooner (10.5 s against 36 s) because the chat turn had already done the research and the
first fill was forked from it. The allusive source changed what the agent proposed: 19 whole lines for the stanza
(11 before), among them three verbatim Catullan lines (`nobis cum semel occidit brevis lux`, `da mi basia mille,
deinde centum`, `vivamus, vetus o sodalis, atque` re-cut from 5.1) that L11 flags as verbatim without blocking (the
owner's rule: homage is shown, not hidden), and many recastings of 31 into the hendecasyllable (`Sirmio, nitide
insularum ocelle`, `ridet nunc lacus, ut puer videbam`, `Bithynumque onus ad fores repono`). The price of the
recasting is the metre: 26 of 74 proposals were rejected on L7 (13 of 62 before), nearly all in the stanza batch
where the agent bent choliambic phrases to the Phalaecian. Still none rejected on forms or attestation. The line-2
fill after the accepted line was the slow cell (74 s to the first line against 20 s), its proposals all variants of
`decus omnium insularum`; worth a second sample before reading anything into it. The contextual lemma reading
(LatinCy on the whole draft) ran inside every L4 check without a visible cost in time.

**Chat-only re-run** (fresh poem, same source and question, ten-minute cap; record `docs/latin/pool/20261010-233338-chat.json`):
35 tool calls (14 `la_concordance`, 8 `la_lemma`, 9 `check_candidate`, 2 `scan`, 1 `la_forms`, 1 `propose_candidates`),
first text at 181 s, the answer complete at 358 s, $2.17 (the agent's own figure for the turn). The answer (4,663
characters) names the five poems in the order the English runs (31, 5, 8, 46, 101), gives for each the Latin phrases
with their corpus evidence (token counts, a concordance line, the headword's use), says which lines can be reused
whole in the hendecasyllable (5.1, 5.5-7, 46.1, 46.7, 46.8 pass as complete lines; 31's choliambics and 101's
pentameter cannot) and which fragments sit where (`ocelle` at positions 5-7 or 7-9, `venusta Sirmio` at 5-10,
`obdura` at 2-4), and warns where the evidence runs out (an unelided `Sirmiō` has no Catullan warrant). Four
re-settings were proposed and checked through the lint on the way. Reading: a research-heavy chat question takes
about six minutes and two dollars to answer well; the owner should expect the first text after three minutes and
the candidates before the prose. The chat's research is then shared by the fills (measurement 2 above: first whole
line at 10.5 s).
