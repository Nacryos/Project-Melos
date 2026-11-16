# Composing Catullan hendecasyllables: the working loop

How a poem goes from an English intent to finished Phalaecians, with the commands at each step. The checks are
specified in `docs/prd/catullan-hendecasyllable-checks.md`; what counts as Catullan is in
`docs/latin/catullan-style-rubric.md`; the last judge works from `docs/latin/critic-brief.md`. The condensed form of
this page is the skill `.claude/skills/catullan-hendecasyllables/SKILL.md`.

All commands run from the repository root with `.venv/bin/python`.

## The line

`x x | – ⏑ ⏑ – | ⏑ – ⏑ – x`: eleven syllables; the base (usually two longs), the choriamb, the iambic close. The
metre's details and Catullus's habits in it are in `docs/latin/phalaecian-profile.md`.

## 1. Intent

Write the English first, in plain prose, one sentence per thought: who is addressed, the occasion, the turn, the
close. Decide the length (Catullus: 3 to 34 lines, median 11) and where the address falls (line 1 in 25 of his 41
poems). Keep this text: the critic judges the Latin against it.

## 2. Harvest

Before any line is drafted, collect Latin for each idea of the English. Do not translate from memory.

```
scripts/la_dict.py --en "sparrow"            # English -> Lewis & Short headwords (agent: la_reverse)
scripts/la_dict.py passer --full             # senses, constructions, the authors cited (la_dictionary)
scripts/la_lex.py --en "darling"             # Smith & Hall, Riddle-Arnold: the English-Latin articles (la_lexica en=)
scripts/la_lex.py venustus                   # Georges, Gaffiot, Forcellini, Döderlein on a Latin word (la_lexica q=)
scripts/la_ref.py word passer                # Merrill's notes that discuss the word (la_commentary)
scripts/la_ref.py commentary 2 1             # Merrill on a poem and line you mean to echo
scripts/la_ref.py search "diminutives"       # the grammar, the commentary, the introduction
```

`la_dict.py --en` names the sources of each headword: `LS` (Lewis & Short's glosses read backwards), `Cat` (a line
of Catullus whose literal English has the word) and `SH` (Smith & Hall's English-Latin dictionary, 1871). A word two
or three of them give comes first. The further dictionaries (`docs/latin/lexica.md`) are read with `scripts/la_lex.py`:
`--en` prints the whole Smith & Hall and Riddle-Arnold articles, which sort the senses of the English word and name
the authors, so they are the place to choose between candidates; a Latin word prints its entry in Georges
(Latin-German), Gaffiot (Latin-French), Forcellini (Latin-Latin), Lewis's Elementary and Döderlein's synonyms (how
*osculum*, *suavium* and *basium* differ); `--search` finds words anywhere in them. They widen the harvest; whether
Catullus has the word is still settled by the corpus (`la_lemma`) and its period by L14.

With the agent, `la_concordance` and `la_lemma` give every locus of a word or lemma and `la_forms` its inflected
forms; `la_prosody` shows how the poets scan a form and where in the line they put it.

Keep for each idea: the candidate lemmas, the forms that fit a slot of the line, one locus each, and the
construction the verb takes. Prefer a lemma that occurs in the polymetrics (rubric section 5): `la_check --only L6`
on a list of candidate words prints the count for each.

## 3. Drafts

Write several drafts of each line, not one: three is a working minimum. Vary the word at line end (a trisyllable
closes 44% of his lines, a disyllable 28%), the opening (non, et, nec, nam, quod, sed, ut open one line in five),
and where the sentence stops (one line in three runs on). Draft in whole lines; the new checks run only on whole
lines.

## 4. Check

```
scripts/la_check.py "Cui dono lepidum novum libellum\narida modo pumice expolitum?"
scripts/la_check.py --file draft.txt
scripts/la_check.py --file draft.txt --only L7,L12,L8        # some checks
scripts/la_check.py --file draft.txt --evidence 0            # every evidence row
scripts/la_check.py --file draft.txt --json                  # the whole result
```

It prints each line with its syllables, quantities and bars, then every check as PASS / WARN / FAIL / unavailable
with evidence, blocking failures first; exit status 1 on a blocking failure. The agent calls the same bank as the
tool `la_check` (`POST /api/la/check`).

| Check | What it decides | Blocking |
|---|---|---|
| L7 metre | the line scans as a Phalaecian | yes |
| L1 forms | every form is attested Latin | yes |
| L12 prosody attestation | each quantity is the one the poets used | yes |
| L8 elision and hiatus | joins are ones Catullus allows | yes |
| L4 attestation | the lemma is in the author, the period | no |
| L11 verbatim | a run of words copied from the corpus (homage) | no |
| L13 Phalaecian manner | base, caesura, word shapes against his lines | no |
| L3 agreement, L10 word order | case, number, gender; placement | no |
| L14 period and register | Lewis & Short labels and authors | no |
| L5 collocation | which word pairs have a parallel, with loci | no |
| L6 manner evidence | the lemma's group counts, its place, the markers | no |

`unavailable` means the check did not run (a store not built, a module missing, a timeout): that part is unchecked.

## 5. Repair

- FAIL: repair and re-run. Do not argue with a blocking check; if it is wrong, record the case and tell the owner.
- WARN: answer it with evidence (a locus, a dictionary sense, a rubric count) or change the line. L11 is expected
  when a phrase is quoted on purpose; say that it is on purpose.
- L5 "no parallel": go back to the harvest for that pair before keeping it.
- L6 "not in the polymetrics": look for the polymetric word for the same thing (basium, not osculum).
- Re-run `la_check` after every change; a repair that fixes one check often breaks the metre.

## 6. The critic

When every line passes the blocking checks, give the draft, the English intent and the `la_check` report to the
style critic on the best model, working from `docs/latin/critic-brief.md`: grammar in context with Allen &
Greenough sections, idiom with loci, a Catullan parallel for each image, register, the poem's shape, a verdict per
line. The critic approves nothing without a citation. Its repairs come back through step 4.

## 7. Final checks by hand

1. Elision: every join, both sides (critic brief, section 6); eleven syllables in every line.
2. Read the poem aloud against the bars in the `la_check` output.
3. The whole poem against the rubric: address, repetition, diminutives, line ends, run-on lines.
4. Lay the Latin beside the English intent once more: each thought present, nothing added.
5. `la_check` on the final text, saved with the poem; list any check that was `unavailable`.
