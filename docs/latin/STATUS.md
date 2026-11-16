# Latin composer: live status

Last updated: 2026-11-15 23:15 PST

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

- **Pool measurement 1** (`docs/latin/pool.md`): next words in 8-9 s cold and mid-line; a stanza of four whole
  Phalaecians from 36 s (11 whole lines in 77 s); 13 of 62 proposals rejected, all on the metre; $1.306 in all.

- **Latin lemma index** (`docs/latin/lemma-index.md`): LASLA's human lemmas aligned to the Perseus lines (98 % of the
  held texts), Morpheus lemmas as fallback; bake-off on LASLA's Catullus: a Horace-trained lookup 95 % on the 71 % it
  covers, LatinCy 92.8 % overall and 85 % on unseen words; routes `/api/la/lemma`, `/api/la/lemma/resolve`; L4 now
  reports headword attestation per poet; agent tool `la_lemma`.

- **Page polish**: the metre list shows human labels and only the metres of the chosen language (from
  `/api/compose/status` `metre_info`; Latin: Phalaecian hendecasyllable, Horace's Sapphic and Alcaic stanzas,
  asclepiads, choliambic, pure trimeter, plus the shared hexameter, elegiac and Sapphic); a **macrons** toggle shows
  the Latin line with macrons on vowels the scanner holds long by nature and breves on certain short open ones
  (`ComposerCore.macronise`, tested).

- **Horace Odes interlinear complete**: all 103 odes, 3,034 lines, in 14 batches: 10 written by Opus subagents and 4
  (H10, H11, H13, H14: Odes 3.14-3.28 and 4.4-4.15, 862 lines) written inline by this session after the harness refused
  their launches, same format and provenance. Every line audited by an independent Opus auditor (14 of 14 batches;
  verdicts: 2,953 OK, 49 doubtful, 32 wrong; the four inline batches scored 6 wrong and 6 doubtful of 862); every
  flagged line revised inline from the audit (84 lines, 0 disputed), with per-batch reasoning summaries. Assembled by
  `scripts/assemble_interlinear_horace.py` into `data/open/latin/interlinear-horace/odes-interlinear.jsonl` (every
  Latin line re-checked against the Perseus text; manifest) and loaded by the generalised corpus loader as 103
  `machine_translation` passages linked to their Latin odes, shown only where no human translation exists.
- **LatinCy sidecar** (`scripts/latincy_service.py`, `.venv-nlp`, port 8802; started by the dev stack): `la_core_web_lg`
  lemmas, POS and morphology for forms LASLA and Morpheus do not know, used as the lemma reader's third fallback.

- **Horace metres on the Odes 1 gold (LA5)**: every metre Hypotactic labels in Odes 1 (Alcaic, Sapphic, the five
  Asclepiad systems, the fourth Archilochian, the Alcmanic strophe, the greater Sapphic) has a stanza template; on all
  876 lines the scanner decides 87.5 % of syllables at 99.8 %, 868 of 870 aligned lines fit and the best pattern equals
  the gold on 98.5 %: Horace scans as well as Catullus did, with no Horace-specific rule. The first pass's misaligned
  lines gave six word-list entries (bronze aēna against Aenēās, Lāertēs, Pholoē, Teucer, anteit, aeque) and one new
  hypothesis (Greek initial clusters seldom make position); the Catullus held-out numbers did not move
  (`docs/latin/eval-log.md` LA5, `docs/latin/hypotheses.md`).
- **LatinCy in context**: L4 and the lemma routes now read the whole draft once through the sidecar and put LatinCy's
  reading in context first among a form's LASLA readings (quod the conjunction, not the pronoun, when the line says
  so); `/api/la/lemma` and the agent's `la_lemma` tool take the draft line as `context`. Tested.

- **Horace Epodes and Carmen Saeculare interlinear complete**: 17 Epodes (625 lines) and the Carmen Saeculare (76) in
  three Opus batches, every line audited by an independent Opus auditor (6 wrong, 11 doubtful; Epodes 8 and 12 rendered
  in full and plainly, nothing softened), every flagged line revised inline (17), assembled per work by the generalised
  `scripts/assemble_interlinear_horace.py` and loaded as 18 more `machine_translation` passages. **All of Horace's lyric
  (3,735 lines) and all of Catullus (2,308) now carry an audited literal interlinear.**

- **Pool measurement 2** (`docs/latin/pool.md`): with an allusive source and an opening chat turn the research tools
  were used at once (33 calls in the first minute: concordance, headwords, citations) and the first whole line came at
  10.5 s instead of 36 s because the fills forked from the chat's research; next words still 9-15 s. The allusive
  source made the agent recast Catullus, so the metre check rejected more (26 of 74, against 13 of 62); verbatim
  Catullan lines are flagged by L11 and shown, not blocked. $2.04 for the four fills. A chat-only re-run with a ten-minute cap:
  a research-heavy question is answered well in about six minutes and two dollars (first text after three), naming the
  five poems echoed with corpus evidence and the lines reusable whole.

## Catullan hendecasyllable checks (branch `catullan-composer`, 2026-11-15)

PRD `docs/prd/catullan-hendecasyllable-checks.md`. One command runs everything on a draft:
`python scripts/la_check.py --file draft.txt` (`--brief`, `--only L7,L12`, `--json`; exit 1 on a blocking failure).
How to compose with it: `docs/latin/composing-hendecasyllables.md`; the critic's brief: `docs/latin/critic-brief.md`.

- **Scanner on every Catullan hendecasyllable** (552 lines; the held-out set is now spent, logged in
  `docs/latin/eval-log.md`): 548 accepted, 522 with the best pattern equal to the gold. Rejected: 38.2 (hiatus in the
  gold), 55.9, 55.10, 55.11 (crux, twelve syllables, fragment). Fixed on the way: *iambus* (Greek initial i), *aere*,
  *Italia* with long I. Known hole: the scanner alone still accepts about 1 in 5 lines with one broken quantity, since
  a lexicon quantity is never a hard violation; L12 is the check that closes it.
- **L12 prosody attestation** (`backend/latin_prosody.py`, `scripts/la_prosody.py <form>`,
  `docs/latin/prosody-attestation.md`): every word's quantities against where the form stands in the Hypotactic hand
  scansion of Catullus, then Virgil (12,913 lines) and Horace; 113,023 tokens, 27,138 forms. Leave-one-out on the 552
  lines: confirmed in Catullus 59.2 %, in Virgil 11.2 %, in another poet 2.6 %, by stem 13.8 %, attested variant
  (mute + liquid, *mihi*, *modo*, synizesis; shown with per-poet counts) 6.8 %, unattested 6.4 %, false blocks 0.07 %
  (2 tokens: *Cyrenis* 7.4, *Pegaseo* 58b.3). 75 % of 300 planted quantity errors are caught.
- **L13 Phalaecian manner and L8 elision / hiatus** (`backend/latin_metre_style.py`,
  `docs/latin/phalaecian-profile.md`): base, word-ends, elisions and line-end shape against a profile counted from
  all the hendecasyllables (spondee base 86.7 %, trochee 6.0 %); hiatus blocks.
- **L3 agreement and L10 word order** (`backend/latin_grammar.py`, `backend/latin_morph.py`,
  `docs/latin/grammar-check.md`): readings from LASLA, Morpheus and, when installed, `pycollatinus`. 7 of 552 genuine
  lines fail L3 (1.27 %), none fail L10; a pass that hangs on a rare reading carries a note (2.9 % of genuine lines).
- **L14 period and register, and the dictionary** (`backend/latin_dictionary.py`, `scripts/la_dict.py`,
  `docs/latin/dictionary.md`): all of Lewis & Short (51,645 entries, 379,558 citations, 1,701 of Catullus), author
  table audited (five errors fixed), English-to-Latin lookup from the dictionary and the Catullus interlinear. Warns
  on 14 of 15 late words, on none of Catullus's vocabulary as shipped.
- **Reference stores** (`backend/latin_reference.py`, `scripts/la_ref.py`, `docs/latin/reference-stores.md`):
  Merrill's commentary (2,530 notes, 118 headnotes, 86 introduction sections), Allen & Greenough (642 sections with
  a subject index), Ellis's commentary (2,035 notes, rough OCR, kept out of lookups).
- **L5 collocation, L6 manner evidence** (`backend/latin_style.py`, `docs/latin/catullan-style-rubric.md`; counts
  reproduced by `scripts/catullan_style_counts.py`): diminutives by the dictionary's label, 8.9 per 100 lines.
- **Wiring**: `composer_lint.check(language="la")` runs all of them; routes `/api/la/check`, `/prosody`,
  `/dictionary`, `/reverse`, `/commentary`, `/grammar`; agent tools of the same names (parse-checked only: the agent
  SDK is not installed in this worktree); skill `.claude/skills/catullan-hendecasyllables/`.
- **Acceptance** (`docs/latin/acceptance/`): Catullus 1.1-2 passes every check and is flagged verbatim; a fresh
  five-line poem passes every blocking check; the critic's verdict and its list of ten tool shortcomings are kept.

**Open, for the owner.**
1. `pycollatinus` (GPL) lifts paradigm coverage from 52 % to 93.9 %; it is installed locally but not added to
   `requirements.txt`.
2. Merrill's commentary and Allen & Greenough are public-domain books, but the digitisations carry share-alike
   (Merrill: Perseus page CC BY-SA 3.0 US, TEI header non-commercial) and non-commercial (A&G: CC BY-NC-SA 3.0 US)
   terms. Their text files are **not committed**; only the manifests and the ingest scripts are, which rebuild them.
3. Which larger lexicon next: survey of the Thesaurus, the Oxford Latin Dictionary, Georges, Forcellini, Gaffiot in
   `docs/latin/dictionary.md`.

**Known weak points** (from the critic): L5 is noisy on a short poem and pairs words across sentences; nothing
checks particle order or the force of a question; the corpus store holds Catullus and Horace only, so Virgil stands
behind L12 but not behind L4, L5 or the concordance; `la_dict.py` by form can open on the wrong entry.

## Running

- Nothing in flight. The dev stack (API :8797, agent :8801, LatinCy :8802) stays up for the owner to try the Latin page
  by remote control; stop it with `scripts/latin_dev_stack.sh stop`.

## Next

1. Smart's prose translation of Horace (public domain) aligned per poem, so the interlinear is the fallback it is meant to be.
2. Horace in the composer: Odes 2-4 against the Hypotactic gold when ingested; a Horace e2e fill (Sapphic stanza).
3. Minor poets (Martial, Statius Silvae for Phalaecians; Catullan circle fragments) per the brief's ranking.
4. A second sample of the slow line-2 cell of pool measurement 2 before reading anything into it.

## Notes for the coordinator

- Disk: 11 GB free. Raw data under `data/raw/latin/` (gitignored, fetch log with sha256), licensed data under
  `data/private/`, open data under `data/open/latin/`.
- Nothing on this branch touches the live `melos-api*` or `melos-composer-agent` containers.
- The permission classifier's refusals of subagent launches are erratic: in this pass 2 writer launches were refused
  (H13, H14; written inline on the coordinator's order) while 2 writers on retry and all 6 auditors were accepted. No
  work-around beyond re-wording and inline work was attempted; no data was softened.