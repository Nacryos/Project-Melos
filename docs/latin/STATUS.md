# Latin composer: live status

Last updated: 2026-10-10 20:38 PDT

**Plan (one paragraph).** Build the Latin twin of the Greek composer on this branch (`latin-composer`, from release W)
as a second language backend behind the release W code, not a fork. First the PRD (`docs/prd/latin-composer.md`,
pushed, v2 after an adversarial critique); then a prior-art and open-sources survey with licences; then a Latin
sibling of the decision-tree scanner (same engine, a Latin rules file, Phalaecian templates) scored honestly against
Hypotactic gold for Catullus's hendecasyllables, with a coverage report that answers the owner's doubt about Latin
vowel quantities; then Catullus ingested with source records, public-domain literal translations and an Opus-written
interlinear stored as `machine_translation`; then the composer loop end to end for one Catullan hendecasyllable; then
Horace and the minor poets. Every scanner rule and lint threshold is a versioned hypothesis with a measured share;
metre-locking is never applied in the composer.

## Done

- PRD v2 pushed (critique: 29 of 32 items folded in, 3 rejected, logged in §11).
- Survey: 124 rows with verbatim licences (`data/open/latin/survey-2026-10-10/`); report
  `docs/research/latin-scansion-prior-art.md` (11 owner decisions in §8; two now ruled, see below).
- Gold: Hypotactic Latin ingested (CC BY 4.0 on its Latin about page): Catullus 2,287 lines, Odes 1 876 lines.
- **Scanner (LA1 + LA2)**: Latin sibling of the Greek decision-tree scanner (same engine, `rules_la.yaml`,
  `metres_la.yaml`, elision as a parse branch, prodelision, base priors) plus the quantity lexicon (Winge, Wiktionary,
  Lewis & Short; 1.07 M forms; audited and rebuilt). Held-out Catullan hendecasyllables, scored three times and
  logged (`docs/latin/eval-log.md`): 88.9 % of syllables decided at 99.96 %, 284 of 285 genuine lines accepted, best
  pattern equal to Chamberlain's on 96.5 %, 4 in 5 perturbed lines rejected. **The owner's doubt is answered.**
- **Texts (LA3)**: Perseus Catullus (Merrill 1893, CC BY-SA 4.0; 115 poems, 2,308 lines) with Smithers's prose and
  Burton's verse aligned per poem, audited line for line; Perseus Horace (Odes 103 with their metre labels, Carmen
  Saeculare, Epodes 17) with Conington's Odes, audited. Latin corpus partition `data/corpus_la.sqlite` (same tables as
  the Greek corpus; u/v, i/j folded): 236 texts, 335 translations, 12,329 vocabulary forms.
- **Lint bank and routes (LA4, backend)**: `composer_lint.check(language="la")`: L7 via the Latin scanner with the
  prefix's elided syllable rejoining the fit; L1 forms (corpus, then paradigm forms), L4 attestation by author, L11
  verbatim over the Latin partition; L2 not applicable. `/api/la/concordance`, `/api/la/forms`, `/api/la/status`.
  Slot key appends `|la` only for Latin poems (Greek keys byte-identical). Agent: Latin system prompt, `la_concordance`
  and `la_forms` tools, Latin back-translation. Page: Language switch, Catullus and Horace, TypeGreek off for Latin.
  Tests: scanner 14, lint 5, routes and page suites green; agent suite 24 of 26 (the 2 failures are order-dependent and
  fail on `origin/composer-w` too).
- **Interlinear (Opus writers + independent Opus auditors + revisers)**: batches 01-06 written (1248 of 2,308
  Catullus lines); audits so far: 01 (13 wrong, 12 doubtful of 230; revised, 26 lines changed), 02 (1 wrong, 6
  doubtful of 221), 03 (5 wrong, 5 doubtful of 225; revising), 04 (0 wrong, 14 doubtful of 177). Stored under
  `data/open/latin/interlinear-catullus/` as `machine_translation` with per-batch reasoning summaries.
- Licensed data: the owner's addendum and the coordinator's rulings are logged in `docs/decisions.md`; register in
  `docs/latin/licensed-data.md`; LASLA under `data/private/lasla/` with manifest; Winge email drafted, not sent
  (`docs/latin/drafts/winge-email.md`).

- **End to end (deliverable 5)**: on the local dev stack (API + agent service from this worktree, never the live
  containers) a Latin poem with Catullus / phalaecian got "nigrum nocte bibamus hac Falernum" proposed at 24 s, linted
  (metre –––⏑⏑–⏑–⏑–⏑, forms, attestation, no verbatim run) and saved as the line's version; 4 candidates rejected on the
  metre; $0.27 for the fill (`docs/latin/e2e.md`, records in `docs/latin/e2e/`).
- **Catullus interlinear complete**: all 116 poems, 2,308 lines, written by Opus subagents in 10 batches, every
  line audited by an independent Opus auditor (verdicts: 2,047 OK, 228 doubtful, 33 wrong), every
  flagged line revised (265 revised, 0 disputed); assembled by `scripts/assemble_interlinear_catullus.py`
  into `data/open/latin/interlinear-catullus/catullus-interlinear.jsonl` (every Latin line re-checked against the
  Perseus text; manifest with per-batch models, audits and revisions) and loaded into the corpus partition as 115
  `machine_translation` passages linked to their Latin poems, shown only where no human translation exists.

## Running

- Nothing. The dev stack (API :8797, agent :8801) is left running for the coordinator to try the page; stop it with
  `scripts/latin_dev_stack.sh stop`.

## Next

1. Measure the pool with a longer English source and the next-words mode; try the page itself (Language: Latin).
2. Horace interlinear (Odes first) the same way, after Smart's prose is parsed; Horace templates evaluated on Odes 1 gold.
3. Lemma index for Latin: lemmatiser bake-off against LASLA (held-out), recorded lemmas, `forms_found` and
   collocations for the agent's research tools; Horace templates evaluated on Odes 1 gold.
4. Page polish for Latin (macron overlay, metre list labels) and the Horace translations (Smart's prose parser).

## Notes for the coordinator

- Disk: 11 GB free. Raw data under `data/raw/latin/` (gitignored, fetch log with sha256), licensed data under
  `data/private/`, open data under `data/open/latin/`.
- Nothing on this branch touches the live `melos-api*` or `melos-composer-agent` containers.
- Four subagent launches were refused by the permission classifier (translation prompts naming the poet's obscene
  vocabulary); re-worded prompts were accepted. No work-around beyond re-wording was attempted.
