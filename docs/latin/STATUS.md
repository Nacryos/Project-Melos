# Latin composer: live status

Last updated: 2026-10-10 19:21 PDT

**Plan (one paragraph).** Build the Latin twin of the Greek composer on this branch (`latin-composer`, from release W)
as a `language=la` switch, not a fork. First the PRD (`docs/prd/latin-composer.md`, pushed) and an adversarial
critique of it; then a prior-art and open-sources survey with licences (scansion tools, macronised lexica, gold
scansions, corpora, translations, lemmatisers); then a Latin sibling of the decision-tree scanner (same engine, a
Latin rules file, Phalaecian templates) scored honestly against Hypotactic and Pedecerto gold for Catullus's
hendecasyllables, with a coverage report that answers the owner's doubt about Latin vowel quantities; then Catullus
ingested with source records, public-domain literal translations and an Opus-written interlinear stored as
`machine_translation`; then the composer loop end to end for one Catullan hendecasyllable; then Horace and the minor
poets. Every scanner rule and lint threshold is a versioned hypothesis with a measured share; metre-locking is never
applied in the composer.

## Done

- Worktree reset to `origin/composer-w` (9888c7e); Greek PRD, composer docs, scanner, lint bank and agent code read.
- PRD written and pushed; adversarial critique (Opus critic, 32 items) folded into PRD v2: 29 accepted, 3 rejected,
  logged in §11. Main corrections: elision is a drop branch in the metre layer with hiatus as a violation; Pedecerto
  is dactylic-only so Hypotactic plus a hand-scanned adjudicated set is the gold; three template strings fixed;
  negative control (false-accept rate) added to the evaluation; honest "language backend" naming with the call-site list.

## Running

- Prior-art survey in three parallel passes (scansion tools and quantity resources; corpora and translations;
  lemmatisers), licences quoted from the fetched pages.

## Next

1. Survey table to `docs/research/latin-scansion-prior-art.md` (under 8 pages).
2. Scanner POC (in progress: `backend/scansion/latin.py` written; syllabifier, features, `rules_la.yaml`,
   `metres_la.yaml`, elision branch in `metre.py`, Hypotactic Latin gold loader, eval on Catullus next).

## Notes for the coordinator

- Disk: 13 GB free (97 % used). Nothing over 2 GB will be pulled without telling the owner.
- Nothing on this branch touches the live `melos-api*` or `melos-composer-agent` containers.
