# Composer page (release W, phases W2 + W3)

Code: `composer.html`, `js/composer.js` (page), `js/composer-core.js` (logic without the DOM, tested in
`tests/composer-core.test.mjs`), `css/composer.css`. API: `backend/composer_routes.py`. PRD: `docs/prd/composer-agent.md`
§3-4. Written 2026-10-09 (Pacific).

## Using it

The composer is for the owner only. Sign in from the menu (Log in). The menu lists **Composer** only while the owner
sign-in marker cookie (`melos_owner_ui=1`) is present. Signed out, `/composer` is a 404.

- **Poem bar.** Pick a poem, start a **New poem**, or edit the title. The title, the English and the poet, metre and
  dialect settings save on their own (PATCH, 0.7 s after you stop typing). The status next to the title shows
  "Saving…", "Saved" or "Not saved". On re-login the last poem opens again (`?poem=<id>` also works).
- **English** (collapsible). This is free text, not split into lines. The agent reads all of it and works out which
  part the next words should carry.
- **Board.** There is one TypeGreek editor per line, with the release V scansion backdrop: colour by longness,
  bars, %, and metre violations underlined. Lines never wrap; long lines scroll sideways. Hover over a word to see
  its analysis; click a syllable to see why it scans the way it does. Under each line you see the live pattern, how
  it fits the metre, the saved version's checks (L7, L1, L2, L4, L11 badges; hover for detail) and the save state.
- **Enter** saves the line as a new version on the server (`source: owner`, or `agent`/`corpus` when the whole line
  is an accepted suggestion left unchanged) and moves to the next line. The saved line is back-translated at once:
  you see "translating…", then the English, which is stored on the version (`PATCH back_translation`).
- **Versions row.** This appears under a line once it has two or more versions. The cards run oldest to newest and
  scroll sideways. Each card shows the Greek, the pattern, the check badges, the back-translation, the source and the
  time (Pacific). Click a card to make it current; the editor takes its text. **archive** hides a version (it is never
  deleted). **archived (n)** shows the archived ones, each with **restore**.
- **Autocomplete pop-up.** Press **Tab**, or pause for 600 ms, to open it under the caret. It has two tiers:
  **next words** (up to 6 short continuations of one to three words, the fast tier) and **whole lines** (up to 8:
  model continuations and corpus lines). Each shows the Greek (the part you have typed is greyed), its metrical
  pattern, the English it carries, and its source (agent, or corpus with citation). Evidence and checks for the
  highlighted option appear beside it. ↑/↓ run through both tiers. Candidates stream in as they pass the lint bank;
  next words arrive first, whole lines as they come. The footer shows "thinking · words + lines" with the last tool
  calls, how many candidates the checks rejected, and any error.
- **Chat** (right, collapsible). Ask anything; the answer streams. Tool calls show as compact chips (`lemma_search ×2`).
  Candidates show as chips: click the Greek to insert it at the caret, or **+ version** to add it as a version of the
  current line (not made current). Each answer shows its cost. The header shows **today's** spend.
- **ask the model when I pause** (toolbar). When this is off, the model is asked only on Tab. Prefetching after a
  commit or an accepted suggestion is off too. Corpus fillers still appear.

## Keys

| Where | Key | Action |
|---|---|---|
| Line | Enter | save as a new version, go to the next line |
| Line | Tab | open the pop-up (asks the model for this slot) |
| Line | ↑ / ↓ | previous / next line (pop-up closed) |
| Line | Ctrl+` | Greek / English typing (all lines) |
| Pop-up | ↑ / ↓ | choose |
| Pop-up | Enter or Tab, or click | accept |
| Pop-up | Esc | close (no auto-reopen until the slot changes) |
| Chat | Enter / Shift+Enter | send / new line |

## How the pool works (PRD §4)

- **Slot** = (poem, line, the line up to the word being typed, settings). The client keeps one pool per slot and
  mode (`ComposerCore.poolKey`, `|words` for the next-words pool). Tab or a pause asks for both at once: `mode:
  "words"` (`n=8`, `ahead_lines: 0`, short continuations) and `mode: "line"` (`n=12`, the rest of the stanza). The
  background prefetch after a commit or an accepted suggestion asks for whole lines only. Each request posts
  `POST /api/composer/poems/{id}/pool` with the caret, the prefix, `n`, `mode` and `remaining_template`. That is the metre's template for the line (stanza position = line index) minus the
  syllables already typed. If the line already fits the whole template, no request is made ("the line is complete");
  if the text so far does not fit, no request is made and the pop-up says so. The pool route requires a template
  (422 `template_required`), so without a named metre (none / detect) the model is not asked; the pop-up says so,
  and corpus fillers still come.
- **Filtering is local** (`ComposerCore.optionsFor`, `tiered`). A pool applies while the line still begins with its
  base. Its candidates are matched against what you typed since (accents, breathings, iota subscript, case and final
  sigma ignored), and a candidate with a pattern must fit the slots open at its base. `tiered` puts next words
  (candidates with `mode: "words"`) first, then whole lines, in one list for the keyboard. Pools from earlier slots on
  the same line keep matching as you type into a candidate, so a pause starts a new model request for a tier only when
  fewer than 3 model continuations of that tier still match (`reusable(entries, before, mode)`).
- **Corpus fillers**: `POST /api/compose/suggest` (the release V proposer) for the line, from the lines above. These
  are whole lines labelled "corpus", shown at once, and filtered the same way. Lines that failed the lint are dropped.
- **Abort**: the page keeps one request per (slot, mode) (`S.fills`). Requests for a slot the caret left (typing a
  space, another line) are aborted, as are all of them when settings change or another poem opens. Streamed
  candidates are kept. Aborting only stops the page listening: melos-api reads the agent's stream to its end and
  stores the rest; the agent's fills for other slots run on (bounded) unless an urgent request needs their place.
- **Prefetch**: right after a commit, a pool request for the next line's first slot starts. After an accepted
  candidate, the request is for the slot after it, or for the next line when the candidate's fit says the line is full.
- **Warm-up** (`POST /api/composer/poems/{id}/warm {line_position, n}`, owner-only): sent when a poem opens (for the
  line the caret lands on) and after each commit (for the next line, when it is empty), if "ask the model when I
  pause" is on and a metre is named. melos-api answers at once (202; 200 `started: false` when every slot already
  has 4 stored candidates) and reads the agent's stream in the background, storing each candidate under its slot.
  The agent does the poem's research once (its session stays open), then fills the stanza in parallel forked
  sessions: whole lines for the line and the rest of the stanza (at least two lines, at most
  `MELOS_COMPOSER_AHEAD_LINES` = 3) and next words for the line. While a warm-up runs (up to 6 min), the page
  re-reads the active slot's stored candidates every 3 s. A Tab during the research gets a *cold* next-words fill at
  once (docs/composer/agent.md, "Cold fills").
- **Stanza batches**: every pool request also carries the empty lines after it (`ahead`, computed by melos-api from
  the metre's templates; written lines are skipped). Candidates for those lines stream back with their `slot_key`;
  the page files them under that line (when the line exists on the board) and melos-api stores them.
- **Stored candidates**: before asking the model, the page reads `GET /api/composer/poems/{id}/pool?slot_key=…` for
  the slot (at most every 3 s). When this pool, earlier pools on the line and the stored candidates together offer 3
  or more model continuations matching what is typed, no model request is made (on Tab too).
- **Slot key** (both sides; `backend/composer_routes.py` `slot_key`, `js/composer-core.js` `slotKey`, same test
  vectors in both test suites): the first 32 hex digits of sha256 over the UTF-8 of
  `v1|<line position>|<prefix>|<author>|<metre>|<dialect>`. Line position = the line's index on the board (0-based);
  prefix = the line's text before the slot, NFC, whitespace runs collapsed to one space, trimmed (a line start is
  ""); a missing setting is "". `GET /api/composer/poems/{id}/slot-key?line_position=&prefix=` returns the server's
  key for checking.
- **Spill-over** (`ComposerCore.spillInsert`): a continuation containing a newline or ` / ` continues on the next
  line(s). An empty next line is filled; a written one is kept and the spill-over is inserted before it. Lines the
  continuation completes are saved.

## Errors

Every failure is visible. A banner appears at the top of the page, or a note in the line, the pop-up, the status
line or the chat:

- Agent unavailable (503): a warning banner. Model pool requests pause for 60 s; typing, scansion, saving and corpus
  fillers keep working.
- 404: "sign in as the owner".
- 502: the agent's error. 422: the server's reason.
- Network failures name the cause.

## Local preview

`python3 tools/serve_composer_mock.py` (standard library), then open http://127.0.0.1:8796/composer.html. It fakes
the composer API in memory, with streamed pool and chat replies, a rough scanner and back-translation.
`--agent-down` makes the agent routes answer 503.

## Speed (measured 2026-10-10, docs/composer/agent.md "Live measurement 2")

Next words reach the pop-up 9-11 s after Tab (medium effort, 16-19 passing per minute, about $0.25 per slot), whole
lines 9-143 s; a warm-up fills a Sapphic stanza (≥ 3 per line) in about 2.5 minutes. Defaults: pool effort
`medium`, four fills in parallel, cold next-words fills while the research runs.

## Known gaps

- The daily cost is counted in this browser (from `done` events and back-translation replies), not read from the
  agent's `usage.jsonl`. A small `GET /api/composer/usage` would make it exact.
- Stored candidates are keyed by line index and prefix: after lines are inserted above (positions shift), stored
  candidates for later lines no longer match their keys and are simply not shown.
- Unsaved drafts (typed, Enter not pressed) are kept in this browser's localStorage only.
- The English span of an option is shown as text; it is not highlighted inside the English panel.
