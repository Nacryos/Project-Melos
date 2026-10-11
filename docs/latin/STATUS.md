# Latin composer: live status

Last updated: 2026-10-10 19:46 PDT

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
- Survey passes A (scansion tools, quantity resources), B (texts, translations), C (lemmatisers, dictionaries, lemma
  gold): 124 rows with verbatim licences in `data/open/latin/survey-2026-10-10/`; the report
  `docs/research/latin-scansion-prior-art.md` is being assembled.
- Hypotactic Latin ingested as gold (CC BY 4.0 stated on its Latin about page): Catullus 2,287 lines, Horace Odes 1
  876 lines (`data/open/latin/hypotactic/`).
- **Scanner POC (LA1), core rules, no lexicon**, scored on Catullus's 552 hendecasyllables (`docs/latin/eval-log.md`):
  held-out half (frozen, scored once) 99.6 % right on the 52 % of syllables it decides, elision right 99.3 %, 281 of
  285 genuine lines accepted, exact pattern on 65 %, and the negative control rejects 77 % of perturbed lines. The
  other half of the syllables are open vowels inside words that only a lexicon can settle (LA2).
- Elision is a parse branch in the metre layer (drop the unit; prodelision keeps the unit long and drops *est*);
  hiatus where elision is normal is a reported violation. Greek scanner, lock and composer tests unchanged.

## Running

- Survey report assembly (subagent) → `docs/research/latin-scansion-prior-art.md`.
- Raw fetch for the lexicon phase (subagent): Winge's macron table (33 MB), Lewis & Short TEI (77 MB), Collatinus data,
  Wiktionary Latin extraction (about 1.2 GB, streamed), Perseus Catullus TEI with Smithers's prose, LASLA Catullus and
  Horace (CC BY-NC-SA: owner decision needed before use).

## Next

1. LA2: `quantities_la.sqlite` from the admitted sources (per-source rows, upstream recorded), LEX nodes, calibration
   pass (measured shares into `docs/latin/hypotheses.md`), coverage report on the held-out half.
2. LA3: Catullus text from Perseus (Merrill 1893, CC BY-SA) with source records; L1 analyser choice; Latin partition.
3. LA4: `language=la` through lint, routes, store, agent, page; one hendecasyllable end to end.

## Decisions wanted from the owner

- LASLA (human-verified lemmas for all of Catullus and Horace) is CC BY-NC-SA 4.0: use it as lemma gold and recorded
  lemmas under the rights-recorded policy, or ask CIRCSE first?
- Winge's macron table: the richest form-level source, but only the code is licensed (GPL-3); the data derives from
  Perseus Morpheus (CC BY-SA). Use server-side now and ask the author before any redistribution (proposed)?

## Notes for the coordinator

- Disk: 13 GB free (98 % used) before the Wiktionary download (1.2 GB); nothing over 2 GB is pulled without telling the owner.
- Nothing on this branch touches the live `melos-api*` or `melos-composer-agent` containers.
- `tests/test_composer.py::test_every_composer_route_and_the_page_are_404_signed_out` fails on `origin/composer-w` too in
  this light venv (environmental); all scanner, lock and composer-route tests pass.
