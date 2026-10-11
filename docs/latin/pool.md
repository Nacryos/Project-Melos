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
