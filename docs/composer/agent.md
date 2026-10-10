# Composer agent service (release W, W1/W2 server side)

Code: `agent/`. PRD: `docs/prd/composer-agent.md`. Written 2026-10-09 (Pacific).

## Contract with melos-api

- Container `melos-composer-agent`, network `melos-net`, port 8800, no published ports. Every request carries
  `X-Composer-Token` (secret file `COMPOSER_AGENT_TOKEN_FILE`; constant-time compare); otherwise 401.
- The agent calls melos-api (`MELOS_API_URL`) with the same header, which lifts rate limits.
- `POST /chat {poem, thread, message}` → SSE: `text` (deltas), `tool` (name, summary), `candidate`, `error`, `done`.
- `POST /pool {poem, slot{line_position, caret, prefix, remaining_template, slot_key}, ahead[slot...], n, mode}` → SSE:
  `candidate`s that passed the lint (each with `slot_key`, `line_position`, `prefix`, `mode`), `tool`, per fill
  `{"type":"rejected","count","reasons":{check_id: count},"slot_key","mode"}` and
  `{"type":"fill","slot_key","mode","cold","cost_usd","usage"}` when it ends, then one `done` (cost of the fills this
  request started). `mode` = `line` (whole-line continuations, default) or `words` (next words: 1-3 words each).
  `slot` is the current slot (wants `n`, urgent); `ahead` are later slots of the stanza (want `COMPOSER_POOL_AHEAD_N`
  each, line mode), each filled by its own session (see Fills).
- `POST /warm {poem, slot?, ahead?, n?}` → SSE like `/pool`: starts (or joins) the poem's research; with `slot` it
  also fills the stanza in line mode plus next words for `slot`. Without `slot` it is research only (`terminal_reason`
  `already_warm`, cost 0, when the research already ran). Fills whose (slot, mode) already has enough passing
  candidates in this session are skipped (`skipped` in `done`; `already_filled` when nothing was started).
- `POST /backtranslate {greek, dialect}` → `{english, usage, cost_usd}` (502 on failure).
- `done` = `{"type":"done","usage":{input_tokens, output_tokens, cache_read_input_tokens,
  cache_creation_input_tokens},"cost_usd"}`. Candidate = `{greek, english_span, slots, evidence[], checks[], scansion}`.

## Harness

- Claude Agent SDK for Python 0.2.165 (bundles Claude Code CLI 2.1.294 as a native binary: no Node needed).
- Model `claude-fable-5-1` everywhere. Effort per job kind via `ClaudeAgentOptions(effort=...)` (CLI `--effort`;
  docs: https://code.claude.com/docs/en/agent-sdk/python, values low/medium/high/xhigh/max): chat
  `COMPOSER_CHAT_EFFORT` and the research turn `COMPOSER_WARM_EFFORT` stay `xhigh` (owner ruling); pool fills run
  at `COMPOSER_POOL_EFFORT` (owner ruling 2026-10-10: lower effort for the pop-up only). The SDK has no way to change
  the effort of a connected client between turns (no `set_effort`; only `set_model` and `set_permission_mode`), so a
  fill is a *forked* session: `ClaudeAgentOptions(resume=<research session id>, fork_session=True, effort=<pool>)`
  → CLI `--resume <id> --fork-session`. The fork starts with the research conversation (cache read), gets a new
  session id, and the research session is untouched; several forks of one session run at once. The id comes from
  the init system message / `ResultMessage.session_id`; the transcript is under `$CLAUDE_CONFIG_DIR/projects/<cwd>/`
  on the state volume (same config dir and cwd for all clients). Verified in the live smoke test (W1) by recording
  the requests the CLI sent: `"model":"claude-fable-5-1"`, `"output_config":{"effort":...}`,
  `"thinking":{"type":"adaptive"}`. No thinking budget is set anywhere (Fable 5.1 thinks always); no forced tool
  choice; `stop_reason: refusal` becomes an `error` event.
- Tools: `tools=[]` removes every built-in tool (no Bash, files, web, Task); built-ins are also listed in
  `disallowed_tools`. Only `mcp__melos__*` tools are allowed; `permission_mode="dontAsk"` (never prompts, denies
  anything not allowed); `setting_sources=[]` (no settings files, CLAUDE.md, hooks or plugins);
  `strict_mcp_config`. The CLI's config dir and cwd live under `COMPOSER_AGENT_STATE`.
- Melos tools (in-process SDK MCP server `melos`): search, word, morpheus, headlines, analyze_text, dialectize,
  scan, lemma_resolve, lemma_search, lemma_frequency, concordance, collocations, proximity, ngrams,
  concept_diachrony, cite, commentary, check_candidate (`/api/composer/check`), propose_candidates.

## Sessions and fills (release W, speed pass 2 2026-10-10)

Code: `agent/composer_agent/sessions.py` (persistent sessions), `fills.py` (forked fills). One long-lived
`ClaudeSDKClient` per (poem, kind, poem settings): kind `pool` holds the poem's **research** (its first and only
turn, `xhigh`: the English, the poet's use of the key lemmas, dialect forms; research-only prompt, no slots), kind
`chat` serves `/chat`. A change of poet, metre or dialect opens a new session. API used
(https://code.claude.com/docs/en/agent-sdk/python, ClaudeSDKClient): `connect()` once, `query()` +
`receive_response()` per turn; history is append-only.

- **Fills.** Every (slot, mode) a `/pool` or `/warm` names gets its own fill: a session forked from the research
  session at the pool effort, which proposes for that one slot and disconnects. The prompt is an update (Greek so
  far, caret, the English only when it changed since the research) plus the slot and what was already offered for
  it (the `seen` set is shared by all fills of the poem, so no repeats across fills or modes). Fills run in
  parallel: a `Gate` allows `COMPOSER_POOL_PARALLEL` (4) at once over the service, serving the **urgent** fill (the
  `/pool` request's own slot) before queued ones; when no permit is free, an urgent fill preempts the oldest running
  fill for a slot the request does not name (the owner moved on; `stop` `preempted`). Fills for the rest of the
  stanza and warm-up fills are not urgent.
- **Cold fills.** A `/pool` whose slot is urgent while the research turn still runs does not wait: with
  `COMPOSER_COLD_FILLS` (on) it starts a fresh session with the whole poem context and the instruction not to
  research first (`cold: true` in its `fill` event and usage log). Non-urgent fills wait for the research and fork.
  If the research session failed, every fill of that poem runs cold until the next request opens a new session.
- **Join.** A request for a (slot, mode) whose fill is running joins it: the candidates sent so far are replayed
  (`replay: true`; melos-api does not store them twice), then live events; its `fill` event has `shared: true` and
  the request's `done` counts no cost for it.
- **Ending a fill.** When the slot has its count (`n`, or `COMPOSER_POOL_AHEAD_N` / `COMPOSER_WORDS_N`), or after
  `COMPOSER_POOL_ROUNDS` / `COMPOSER_WORDS_ROUNDS` propose calls, the model is told to reply "done"; after
  `COMPOSER_STOP_GRACE_SECONDS` it is interrupted. Deadlines: `COMPOSER_POOL_SECONDS` (line), `COMPOSER_WORDS_SECONDS`
  (words), `COMPOSER_WARM_SECONDS` (research).
- **Bounds.** Idle sessions close after `COMPOSER_SESSION_IDLE_MINUTES` (30); a session with fills running or queued
  counts as busy. At most `COMPOSER_MAX_SESSIONS` (4) persistent sessions exist (least recently used idle one is
  closed to make room; all busy → 503 `agent busy`). Processes at most: sessions + `COMPOSER_POOL_PARALLEL`. The
  prompt cache lives 5 minutes after the last turn; a fork after a longer pause pays cache writes for the research
  context again (still no new research).
- The HTTP response of a `/pool` ends when all the fills it named have ended (melos-api reads it to the end in the
  background and stores every candidate); the page stops listening when the caret leaves the slot.

## Modes

- `line`: whole-line continuations (single words to the rest of the line, spill-over with a newline), 3-5 per
  propose call, the stanza's later slots in their own fills.
- `words`: **next words**, one to three words each that fit the *beginning* of the open metrical slots; the model is
  told to call `propose_candidates` at once with 6-8 before any lookup and to keep going with different first
  words. A candidate longer than three words or with a line break is refused before the lint (`words_length`).
  Each candidate event carries `mode`; melos-api stores it with the candidate, so the page can show the two tiers.

## Pool loop (generate, then discard)

The model calls `propose_candidates` early and repeatedly with small batches (≤ 16), each candidate naming its
`slot` key. The handler drops repeats (per slot, across the whole session) and unknown slot keys, lints every
candidate in parallel through `POST /api/composer/check` (8 at a time) against **its own slot**, and streams each
one that passes the moment its lint returns (not at the end of the batch); the failures go back to the model with
their blocking check ids and details, plus the per-slot counts. A candidate passes only when `pass` is true and no
blocking check failed; a lint transport or HTTP failure counts as a blocking failure (`lint_unavailable`), so no
unlinted candidate is ever emitted.

The lint request is `{greek: <continuation>, metre, dialect, author, remaining_template, prefix, line_index}` from
the poem settings and the candidate's slot (`prefix` = the text already on that line, for word-boundary
quantities; `line_index` = the slot's line, so a continuation that runs over the line end is fitted to the right
next template). `norm()` keeps line breaks (a newline or ` / `), so spill-over candidates reach the lint as lines.

## Cost and logs

Cost = usage × Fable 5.1 prices ($10 in, $50 out, $0.25 cache read, $12.50 cache write per MTok; cache-write
price assumed at 1.25× input, matching the CLI's own figure in the smoke test). One JSON line per turn in
`$COMPOSER_AGENT_STATE/usage.jsonl` (endpoint, poem, usage summed over the turn's assistant messages, our cost, the
SDK result's usage and cost, ms, session turn number, first turn or not, stop/terminal reason, per-slot passed
counts and ms to the first passing candidate per slot). The key is never logged; it is read from its file per request and passed only in the CLI
subprocess environment.

## Smoke test (2026-10-09, laptop, fake melos-api)

`agent/smoke.py`: `/backtranslate` of Sappho 31.1 → "Seems to me that man equal to the gods" (7.8 s, $0.026).
`/pool` n=2, 1 round: 7 research tool calls (lemma_search, themes search, dialectize, scan), one batch of 8, two
passed and streamed (e.g. ἀ σελάννα φαίνετ' ὐπὲρ θαλάσσας, evidence Sappho 34, 96, 154), stopped at n; 74 s,
$0.343 (our cost = SDK cost). Total live spend of the session including debugging the recording proxy: about
$0.6.

## Live measurement (2026-10-10, box, image `melos-composer-agent:w2`, test container on melos-net)

Sappho, sapphic, aeolic; English "The moon has set, and the Pleiades; it is the middle of the night, the hour goes
by, and I sleep alone." One persistent pool session per run; costs are the CLI's own per-turn figures (our formula
matches them exactly). Total spend of the measurement: about $7.2.

| Run / turn | First candidate | Turn time | Passed | Cost | Cache read / write tokens |
|---|---|---|---|---|---|
| A1 warm-up, line 1 + 3 ahead (old prompt, 360 s cap) | 292 s (line 1 only) | 360 s, cut | 5 | $1.57 | 20k / 36k |
| A2 next slot, line 1 mid ("ἀ σελάννα …") | 38 s | 39 s | 4 | $0.36 | 82k / 13k |
| A3 line 2 start | 83 s | 123 s | 6 | $0.71 | 157k / 11k |
| A4 line 3 start | 53 s | 55 s | 5 | $0.33 | 122k / 5k |
| A5 line 4 (adonean) start | 80 s | 83 s | 4 | $0.53 | 202k / 13k |
| B1 warm-up, whole stanza (final prompt, 600 s cap) | line 1 222 s, 2 329 s, 3 376 s, 4 458 s | 470 s | 17 (5/3/4/5) | $2.76 | 198k / 68k |
| B2 next slot, line 2 mid | 121 s (first batch at 49 s all rejected) | 124 s | 4 | $0.80 | 223k / 19k |

What dominates: Fable 5.1 at `xhigh` thinks 20-22k output tokens (about 4-5 minutes at ~76 tokens/s) in the response
that composes its first batch, even when told to propose before any lookup and to keep thinking short. Lookups
themselves take about a second each. Once the session has done that, later slots take 40-120 s (3-10k output
tokens) and read the earlier context from the cache. All passing candidates were linted; none unlinted reached the
stream.

## Live measurement 2 (2026-10-10, box, image `melos-composer-agent:w3`, test container on melos-net)

Same poem as above (Sappho, sapphic, aeolic; "The moon has set, and the Pleiades…"), `COMPOSER_POOL_PARALLEL=4`,
one run per cell (so single samples; the spread between slots in the stanza row shows the variance). Costs are
the CLI's own per-turn figures; total spend of the measurement $6.39 (11 turns, `usage.jsonl`).

| Cell | First linted candidate | Passed / time | Per minute | Lint pass rate | Cost per slot | Output tok / cache read |
|---|---|---|---|---|---|---|
| Research turn, xhigh (research only; ×3 runs) | – | 13-16 lookups | – | – | $0.88 / $0.97 / $1.09 per poem | 6-9k / 55-64k |
| Next words, **medium**, forked | **9.3 s** | 11 in 34 s | 19.2 | 0.55 | $0.25 | 2.7k / 188k |
| Next words, medium, **cold** (research still running) | 10.8 s | 11 in 40 s | 16.4 | 0.50 | $0.25 | 3.3k / 36k |
| Next words, high, forked | 9.5 s | 11 in 64 s | 10.3 | 0.65 | $0.41 | 5.2k / 233k |
| Whole line, medium, forked (line 1, under 4-way parallel) | 143 s | 8 in 158 s | 3.0 | – | $0.81 | 12.0k / 149k |
| Whole line, medium, forked (lines 2 / 3 / 4 of the stanza) | 9 / 69 / 78 s | 8 / 7 / 7 in 31 / 99 / 87 s | 15.5 / 4.2 / 4.8 | 0.77 (stanza) | $0.21 / $0.52 / $0.44 | 2.4k / 7.4k / 5.8k |
| Whole line, high, forked (line 1) | 32 s | 9 in 97 s | 5.5 | 0.90 | $0.56 | 7.6k / 238k |
| **Stanza warm-up, medium, 4 fills in parallel** | line 2 at 9 s | 30 in 158 s | 11.4 | 0.77 | $1.98 (4 slots) | – |

Stanza warm-up: every slot had ≥ 3 passing candidates after **143 s** (lines 2, 4, 3 at 9 s, 78 s, 69 s; line 1,
the slowest, at 143 s), against 458 s for the same in the one-turn design (B1 above), at $1.98 against $2.76, plus
the research $0.97 once per poem. With a cold next-words fill the owner has next words for the first line about 11 s
after opening a poem, before the research ends.

Quality spot-check (medium): next words `Δῦ σελάννα` (– ⏑ – –, "the moon has set"), `Πληΐαδές τε`, `Νὺξ μέσα`;
whole lines `Δῦ σελάννα, Πληΐαδές τε· μέσσαι / νύκτες` (the hendecasyllable, close to fr. 168B), `νύκτες, ὤρα δ'
ἄμμι παρέρχεται νῦν` (Aeolic ἄμμι), adonean `ἔννυχα μούνα`. All passed the lint (metre, forms, dialect). High
offered a few odd glosses (`κατθάνε σελάννα`, "the moon has died") at twice the cost and half the rate; its
whole-line pass rate was higher (0.90 vs 0.77) but no better to read.

**Chosen defaults** (`COMPOSER_POOL_EFFORT=medium`, `COMPOSER_POOL_PARALLEL=4`, `COMPOSER_COLD_FILLS=1`, next words
first in the pop-up): medium gives the same time to the first next word as high (9-11 s) at twice the rate and
0.6× the cost, with candidates that read as well; the parallel stanza fill brings the whole stanza in 2.5 min
instead of 8; the cold words fill removes the research from the critical path of the first keystroke. Chat and the
research turn stay at xhigh (owner ruling).

## Open points

- Whole-line fills vary a lot between slots (9-143 s to the first candidate at medium): the model sometimes thinks
  at length before its first propose call, in spite of the prompt. Next words do not show this (the first batch is
  asked for "at once", 9-11 s in every run). A candidate option: ask line fills to open with a 3-candidate batch
  like the words prompt does, or start a words fill for every stanza slot too (cheap).
- Single samples; the medium vs high quality judgement rests on one slot each. More runs before any ruling change.
- Running fills are preempted only when an urgent fill needs a permit; otherwise fills for slots the owner has
  left run to their bounds (spend was ruled acceptable). `COMPOSER_POOL_PARALLEL` × ~300 MB per CLI process must fit
  the container's 3 GB with the persistent sessions.
- The prompt cache's default lifetime is 5 minutes; a fork after a longer pause pays cache writes for the research
  context again (still no research).
- Cache writes are priced by assumption ($12.50/MTok); it matched the CLI's own cost figure to the cent.
