# Latin composer: live status

Last updated: 2026-10-10 19:59 PDT

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
- **LA2, quantity lexicon** (`docs/latin/lexicon.md`, 1.07 M distinct forms from Winge, Wiktionary, Lewis & Short):
  held-out half, one look: 87.9 % of syllables decided at 99.96 %, 284 of 285 genuine lines accepted, best pattern
  equal to the gold on 96.5 %, perturbed lines rejected 4 in 5. **The owner's doubt is answered**: Latin quantity is
  lexical plus positional in practice, the open resources cover Catullus, and what stays open is real ambiguity
  (nom./abl. -a, homographs) that the metre settles (`docs/latin/eval-log.md`).
- Survey report written: `docs/research/latin-scansion-prior-art.md` (354 lines; 11 owner decisions in §8).
- Catullus text ingested from Perseus (Merrill 1893, CC BY-SA 4.0) with Smithers's prose and Burton's verse aligned
  per poem (`data/open/latin/perseus-catullus/`, 115 Latin poems, 2,308 lines); an independent auditor is checking it.
  Horace Odes, Epodes, Carmen Saeculare TEI and Conington's Odes fetched; Smart's prose Horace from Gutenberg.

## Running

- Adversarial audit of the Perseus Catullus ingest (subagent, data-extraction discipline).

## Next

1. LA3: Horace ingest (Odes, Epodes, Carmen Saeculare + Conington, Smart) with audit; Latin partition for L1/L4/L11
   (form attested in the corpus or in the Morpheus-derived form list; FTS over Latin lines); Opus interlinear for
   Catullus with an auditor, stored `machine_translation`.
2. LA4: `language=la` through lint (joint prefix + candidate fit), routes, store, agent prompt, page; one
   hendecasyllable end to end.
3. Lexicon audit (100 rows per source) and the Collatinus paradigm expansion if coverage needs it.

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
