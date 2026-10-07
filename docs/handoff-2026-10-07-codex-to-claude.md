# Handoff: Codex thread "Critique Archaic Greek dictionary" → Claude Code (2026-10-07)

Written by Claude Code from the Codex transcript, the working tree, and `docs/deployment.md`.
The Codex thread ended at 06:58 PDT 2026-10-07 on a usage-limit error (resets Oct 13), one
turn after the owner asked it to document progress. It never wrote that document; this is it.

## Where the thread lives

- Codex transcript (789 MB JSONL, 46 compactions, Sep 28 → Oct 7):
  `~/.codex/sessions/2026/09/27/rollout-2026-09-27T23-59-00-01a0e6cf-4ea2-7d23-9d92-697c51211bb7.jsonl`
- Thread id `01a0e6cf-4ea2-7d23-9d92-697c51211bb7`; cwd was `C:\Users\alvin` but all work is in `C:\Users\alvin\melos`.
- Readable extract (scratch, may be gone): `%TEMP%\claude\C--Users-alvin\16f4cc31-…\scratchpad\thread2.txt`.

## How the thread evolved

1. **Sep 28:** critique of a chat trace proposing a Jev-classified Sappho/Aeolic dictionary.
   Verdict: build deterministically from citations first (corpus exact match → LSJ/Wiktionary
   extraction), reserve Jev for grey-zone classification; tiers A/B/C/X; provenance on every entry.
2. **Sep 28–Oct 1:** built the reader + lexicon + backend (Morpheus parses, LSJ/Wiktionary senses,
   Jev contextual ranking, source-bound translations). Deployed: backend on Basecamp (Hetzner),
   frontend on Vercel → https://greeklyric.com.
3. **Sep 30 goal (thread goal 1):** act as CI/QA — test the live site as a real user via computer
   use, judge accuracy, deploy fixes.
4. **Oct 6, 22:25 — owner assignment:** *"Weds 10.7 – Alcaeus, political songs. Greek: Fragments
   34a, 129, 130b, 326, 350"* from `C:\Users\alvin\Downloads\Campbell Greek Lyric Poetry.pdf.pdf`.
   Ensure all five are on the live site exactly as in Campbell's edition, then use them to test
   dictionary + multiword search.
5. **Oct 7, 01:34 — thread goal 2 (still active):** *"fix all the words and spans in these poems
   listed, ensure their meanings are actually accurate to the poem, with a translation and
   commentary available for each (sourced and cited correctly), fix the parsing engine and the
   morphology tool / multi-weight ranking system, so the user experience is great."*
   Trigger complaint: ἦλθες showed only "sg. ind. act." instead of "2nd sg. aor. ind. act."

## The five poems (reader URLs)

`https://greeklyric.com/?id=campbell-glp%3Aalcaeus%3A<n>` for n = `34a`, `129`, `130b`, `326`, `350`.
Owner-approved Campbell texts, 88 Campbell commentary paragraphs, and 5 English comparison
translations (Edmonds etc., labelled as comparisons because readings differ from Campbell) are live.

## Live state (authoritative source: top of `docs/deployment.md`)

- **Backend:** release **I** (`lexical-20261007i`), container
  `f888ab86…`, at `/home/alvin/services/melos/releases/lexical-20261007i` on Basecamp.
  Public endpoint `https://basecamp.taila44c41.ts.net:8443` (Tailscale Funnel → `127.0.0.1:8791`),
  proxied by Vercel at `greeklyric.com/api/*`. Rollback container `melos-api-before-lexical-20261007i`.
- **Frontend:** Reader-I, Vercel `dpl_4t9JqwmbUUAtJsKqXAoghEKVrRY1`, aliased to greeklyric.com.
- Release ladder on Oct 7 (all documented in `docs/deployment.md`): E (translations/commentary),
  F, G (παχέων "cubit" link, grouped alternatives), H (LSJ present-only senses excluded for aorist →
  ἦλθες "come or go"), I (gzip for large JSON; 718 KB → 119 KB).
- Release recipe per letter: `deploy/lexical_baseline_<x>.py`, `deploy/lexical_release_<x>.py`,
  `deploy/lexical_transport_<x>.py`, `deploy/approve_lexical_<x>.py`; receipts under
  `runtime/lexical-release-<x>/` (`canary-promotion-pass.json`, `live-verify.json`).
  Private canary runs on port 8792 before promotion. Smoke: `python deploy/smoke_backend.py --origin https://greeklyric.com`;
  regressions: `python deploy/qa_regressions.py --origin https://greeklyric.com`.
- Jev (paid classifier) key: `secrets/jev.env` on the box, never in git/Vercel.

## What was in flight when the thread died (release J — NOT deployed)

`runtime/lexical-release-j/staging.json` → `verdict: STAGED_NOT_APPROVED` (06:32).
J bundles the verified local fixes from 06:07–06:33:

- Dropped person / infinitive / participle / middle-passive labels across saved parser results
  (one display path only recognised numeric person; parser supplies "1st/2nd/3rd").
- Missing LSJ subentry meanings now reach **both** ordinary word-click and phrase views
  (`backend/lexicon_subentries.py`, `backend/machine_subentries.py`, `interlinear.py`).
- Repeated dictionary rendering memoised within a lookup (70 → 36 renders, identical output).
- Patches to `server.py`, `passage_routes.py`, `morphology.py`, `passage_analysis.py`.
- Owner audit input: `runtime/alcaeus-morpheus-maintenance/machine-subentry-wiring-audit.json`.

Codex's last words (06:33): combined backend review passed; "deployment candidate is now being
checked against the current live version." Next step was the J canary → approve → promote cycle.

**Tree vs J candidate (checked by Claude 2026-10-07):** `lexicon_subentries.py`, `machine_subentries.py`,
`morphology.py`, `passage_routes.py` are identical. Three differ:

- `backend/server.py` in the tree **lacks the gzip middleware registration** that is live in I
  (`from .large_json_gzip import LargeJSONGZipMiddleware` + `app.add_middleware(LargeJSONGZipMiddleware,
  minimum_size=4096, compresslevel=1)`, placed inner to CORS). Codex patched it only into the frozen
  release artifact. **Re-add it before any future backend release** or the next deploy silently drops compression.
  The tree's `server.py` additionally has `with_visual_themes` (not in J).
- `backend/interlinear.py` and `backend/passage_analysis.py` in the tree carry newer (06:17–06:34)
  **lacuna-boundary** work: `backend/lacuna_boundaries.py` marks words adjacent to printed dot-runs as
  `conditional_on_word_boundary` for `campbell_assignment` passages with approved commentary; parses stay
  visible but are labelled conditional. Audit: `docs/audits/lacuna-boundary-uncertainty.json`. Untested live.

## Open gaps Codex explicitly left unsolved

- **Contextual meaning selection** across all five poems. Full-poem audit (01:43): of 269 undamaged
  word segments only 47 had a selected gloss, 120 had one among alternatives. Jev ranks παχέων
  "cubit" first but only at 0.57 (below display threshold); commentary-aware ranking experiment
  (`docs/audits/commentary-relevance-*.json`) showed **no improvement** and was not shipped.
- A prompt conflict in the Jev commentary instructions (unconditional "abstain" at the end) was
  found; needs a controlled test, not a lowered threshold.
- **Parser coverage:** only 3/269 occurrences had cached Morpheus analyses at 04:37; elision marks
  (ἔρχεσθ') were rejected by a validator (fixed); 11/12 uncached forms now analysed; εὐρύσαο
  returns nothing. Offline libmorpheus (`runtime/libmorpheus-offline-eval/`,
  `docs/morpheus-offline-*.json`) misses forms the hosted parser finds → use only as extra candidates.
- Bracketed editorial readings (β[ό]λλας, χ[θόνα]) now analysable as the editor's printed word with
  brackets preserved; uncertain letters beside gaps separated from intact words (local).
- Mobile (Oct 6 21:37–21:43): background image only appears after the fullscreen button; multiword
  controls sit below the whole poem; owner asked for fullscreen backgrounds on all browsers/devices
  and **touch as a selection modality** (`css/touch-selection.css`, `css/fullscreen.css` exist, untracked).
- Whole-poem analysis responses were 46 MB (compressed to 6.5 MB); still a duplication problem.
- Commentary ranking must keep dictionary senses, Campbell's interpretation and machine parses visibly distinct.

## Working tree state (branch `lyric-corpus-reader`, in sync with origin at commit level)

- 53 tracked files modified (+3391/−306), **355 untracked** (new backend modules, css, deploy
  scripts, tests, `docs/audits/` ×40, `assets/`, `data/author-profiles/`).
- Last commit `74ee93f` (Oct 6). Everything from the Oct 6–7 release ladder E→I plus the J
  candidate is **uncommitted**. Deployments were made from frozen artifacts, not from the dirty
  tree, so git does not reflect what is live. Commit in logical batches before further work.
- Tests, run by Claude on the dirty tree 2026-10-07 ~08:00 PDT:
  - `npm run test:frontend`: **436 pass, 0 fail**.
  - `python -m pytest tests -q`: **1860 pass, 6 fail** (needs the `platform._wmi=None` guard on Windows).
    All six are in the commentary / sense-packet area and match the problems Codex was mid-way through:
    - `test_contextual_lemma_senses.py` ×3: Jev packets for canary 326 / 350 are 32,698–34,345 chars,
      over the 32,000 classifier input limit. Codex's metadata-trimming fix (03:38) evidently lives only
      in the release artifact or is incomplete in the tree.
    - `test_edition_commentary_integration.py` ×2: `sense_ranker.CommentaryContextUnavailable` — the
      approved commentary retrieval source/occurrence is not resolvable locally; and an oversized-packet
      regex no longer matches.
    - `test_run_commentary_relevance.py`: the frozen preflight already has a saved answer, so the
      "offline and exact" check refuses to repeat. Fixture-state issue, not a code bug.
    - `test_classifier_prompt_eval_runner.py::test_hard_fourteen_cap…` is order-dependent (fails under
      `-x`, passes alone).

## Rules Codex followed (keep them)

- Every meaning, parse feature, or form link must trace to a source record (LSJ, Wiktionary,
  Morpheus receipt, Campbell page). No inferred definitions, no accent-stripping guesses.
- Editorial brackets preserved verbatim; reconstructions labelled.
- Never present a model parse that contradicts dictionary evidence as "the reading."
- Translations from other editions labelled as comparisons, not exact translations.
- Canary before promotion; retain the previous container stopped for rollback; record receipts.
- Don't claim universal accuracy from a fixed example.

## Suggested next actions

1. Verify the working tree: run both test suites; diff `runtime/lexical-release-j/candidate-code/`
   against the tree to confirm J == tree.
2. Commit the Oct 6–7 work in batches (backend modules, deploy scripts, docs/audits, frontend).
3. Finish J: canary on 8792 → smoke/qa_regressions → approve → promote; append to `docs/deployment.md`.
4. Then attack the real gap: contextual sense selection + parser coverage on the five Alcaeus poems,
   measured by the full-poem audit script (search `docs/audits/` and `deploy/` for the 269-segment audit).
5. Mobile fullscreen background + touch selection (owner-requested Oct 6, unverified on Safari).
