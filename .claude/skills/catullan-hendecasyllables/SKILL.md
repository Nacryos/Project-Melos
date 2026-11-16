---
name: catullan-hendecasyllables
description: Use when composing, repairing or judging Latin verse in Catullan (Phalaecian) hendecasyllables in this repository. Gives the working loop (intent, harvest, drafts, la_check, repair, style critic, hand checks) and the commands for the checks, the dictionary, the commentary and the grammar.
---

# Catullan hendecasyllables

Full method: `docs/latin/composing-hendecasyllables.md`. What counts as Catullan, with counts:
`docs/latin/catullan-style-rubric.md`. The critic's rules: `docs/latin/critic-brief.md`. The checks:
`docs/prd/catullan-hendecasyllable-checks.md`. Run commands from the repository root with `.venv/bin/python`.

The line: `x x | – ⏑ ⏑ – | ⏑ – ⏑ – x`, eleven syllables.

## The rule

No Latin is approved on a feeling for Latin. Every word, phrase and construction that stays in the poem is
supported by a check result or a citation: a corpus locus, a Lewis & Short sense, a Merrill note, an Allen &
Greenough section. Where there is none, say "no evidence found".

## The loop

1. **Intent.** Write the English in plain prose, one sentence per thought: addressee, occasion, turn, close. Keep
   it; the critic judges against it. Catullus: 3 to 34 lines, median 11; a vocative in line 1 in 25 of 41 poems.
2. **Harvest** before drafting; do not translate from memory.
   ```
   scripts/la_dict.py --en "kiss"          # English -> Latin headwords
   scripts/la_dict.py basium --full        # senses, constructions, authors cited
   scripts/la_lex.py --en "darling"        # Smith & Hall, Riddle-Arnold English-Latin articles
   scripts/la_lex.py basium                # Georges, Gaffiot, Forcellini, Döderlein's synonyms
   scripts/la_ref.py word basium           # Merrill's notes on the word
   scripts/la_ref.py commentary 5 7        # Merrill on a poem and line
   scripts/la_ref.py search "hiatus"       # grammar, commentary, introduction
   ```
   Keep for each idea: candidate lemmas, the forms that fit, one locus each, the construction the verb takes.
   `la_dict.py --en` marks each headword's sources (`LS` Lewis & Short, `Cat` a line of Catullus, `SH` Smith & Hall);
   prefer a word two sources give. The further dictionaries (`docs/latin/lexica.md`: Georges, Gaffiot, Forcellini,
   Lewis's Elementary, Döderlein, Smith & Hall, Riddle-Arnold) are read with `scripts/la_lex.py <word>`,
   `--en "<english>"`, `--search "<words>"`, `--dict georges,gaffiot`; the critic may cite them as second witnesses
   on sense and on the difference between near-synonyms, never against the corpus or L14.
3. **Drafts.** At least three per line, in whole lines. Vary the last word, the opening word, the stops.
4. **Check.**
   ```
   scripts/la_check.py "line 1\nline 2"
   scripts/la_check.py --file draft.txt [--only L7,L12] [--evidence 0] [--json]
   ```
   Each check prints PASS / WARN / FAIL / unavailable with evidence; exit status 1 on a blocking failure.
   The checks: L7 metre, L1 forms, L12 prosody attestation, L8 elision and hiatus, L4 attestation, L11 verbatim,
   L13 Phalaecian manner, L3 agreement, L10 word order, L14 period and register, L5 collocation, L6 manner
   evidence. Which are blocking is printed beside each.
5. **Repair.** FAIL: repair and re-run. WARN: answer with evidence or change the line. L5 "no parallel": back to
   the harvest. L6 "not in the polymetrics": find the polymetric word (basium, not osculum). Re-run after every
   change.
6. **Critic.** When no blocking check fails, hand the draft, the English intent and the `la_check` report to a
   style critic on the best model, briefed with `docs/latin/critic-brief.md`: grammar in context (Allen &
   Greenough sections), idiom (a locus or dictionary citation for each phrase; no translationese), a Catullan
   parallel for each image or "no parallel in Catullus", register, the poem's shape; verdict per line, keep or
   repair; every repair back through step 4.
7. **By hand, last.** Elision at every join, both sides (final vowel or vowel + m; initial vowel or h); eleven
   syllables per line; the poem against the rubric; the Latin against the English; `la_check` on the final text.

## Reading the report

- `unavailable` means the check did not run: that part is unchecked, not passed. Report it.
- L11 WARN on a deliberate quotation is expected; say that it is deliberate.
- L6's marker row gives the draft's diminutives, vocatives, second-person forms and run-on lines beside
  Catullus's rate per 100 lines and per poem p10 / median / p90. Outside p10-p90 is a question to answer, not a
  fault.
- L5 warns only below 22.2% of pairs with a parallel (the 10th percentile of his own 41 poems held out).

## With the composer agent

The same bank and stores are the tools `la_check`, `la_prosody`, `la_dictionary`, `la_reverse`, `la_lexica`, `la_commentary`,
`la_grammar`, beside `la_concordance`, `la_lemma`, `la_forms` and `scan`.

## Do not

- Do not offer a line that has not been through `la_check` since its last change.
- Do not cite the rubric's "uncounted" statements as evidence.
- Do not mark a poem finished while a blocking check fails or a critic verdict is "repair".
