# Composer agent service (release W, W1/W2 server side)

Code: `agent/`. PRD: `docs/prd/composer-agent.md`. Written 2026-10-09 (Pacific).

## Contract with melos-api

- Container `melos-composer-agent`, network `melos-net`, port 8800, no published ports. Every request carries
  `X-Composer-Token` (secret file `COMPOSER_AGENT_TOKEN_FILE`; constant-time compare); otherwise 401.
- The agent calls melos-api (`MELOS_API_URL`) with the same header, which lifts rate limits.
- `POST /chat {poem, thread, message}` → SSE: `text` (deltas), `tool` (name, summary), `candidate`, `error`, `done`.
- `POST /pool {poem, slot{line_position, caret, prefix, remaining_template, slot_key}, ahead[slot...], n}` → SSE:
  `candidate`s that passed the lint (each with `slot_key`, `line_position`, `prefix` when slots are keyed), `tool`,
  then `{"type":"rejected","count","reasons":{check_id: count}}`, `done`. `slot` is the current slot (wants `n`);
  `ahead` are later slots of the stanza (want `COMPOSER_POOL_AHEAD_N` each), filled in the same turn.
- `POST /warm {poem, slot?, ahead?, n?}` → SSE like `/pool`: starts (or joins) the poem's research and first
  stanza batch. Without `slot` it is a research-only turn (skipped when the session already ran a turn); a warm-up
  whose slots already have enough passing candidates in this session is skipped (`terminal_reason`
  `already_filled`, cost 0).
- `POST /backtranslate {greek, dialect}` → `{english, usage, cost_usd}` (502 on failure).
- `done` = `{"type":"done","usage":{input_tokens, output_tokens, cache_read_input_tokens,
  cache_creation_input_tokens},"cost_usd"}`. Candidate = `{greek, english_span, slots, evidence[], checks[], scansion}`.

## Harness

- Claude Agent SDK for Python 0.2.165 (bundles Claude Code CLI 2.1.294 as a native binary: no Node needed).
- Model `claude-fable-5-1`, effort `xhigh` via `ClaudeAgentOptions(effort="xhigh")`, which the SDK passes as the
  CLI flag `--effort xhigh` (docs: https://code.claude.com/docs/en/agent-sdk/python, field `effort`, values
  low/medium/high/xhigh/max). Verified in the live smoke test by recording the requests the CLI sent: every one
  had `"model":"claude-fable-5-1"`, `"output_config":{"effort":"xhigh"}`, `"thinking":{"type":"adaptive"}`. No
  thinking budget is set anywhere (Fable 5.1 thinks always); no forced tool choice; `stop_reason: refusal` becomes
  an `error` event.
- Tools: `tools=[]` removes every built-in tool (no Bash, files, web, Task); built-ins are also listed in
  `disallowed_tools`. Only `mcp__melos__*` tools are allowed; `permission_mode="dontAsk"` (never prompts, denies
  anything not allowed); `setting_sources=[]` (no settings files, CLAUDE.md, hooks or plugins);
  `strict_mcp_config`. The CLI's config dir and cwd live under `COMPOSER_AGENT_STATE`.
- Melos tools (in-process SDK MCP server `melos`): search, word, morpheus, headlines, analyze_text, dialectize,
  scan, lemma_resolve, lemma_search, lemma_frequency, concordance, collocations, proximity, ngrams,
  concept_diachrony, cite, commentary, check_candidate (`/api/composer/check`), propose_candidates.

## Sessions (release W, speed pass 2026-10-10)

Code: `agent/composer_agent/sessions.py`. One long-lived `ClaudeSDKClient` per (poem, kind, poem settings), kind
`pool` (serves `/pool` and `/warm`) or `chat` (serves `/chat`): chat and pool never interleave in one conversation.
API used (https://code.claude.com/docs/en/agent-sdk/python, ClaudeSDKClient): `connect()` once, then one
`query()` + `receive_response()` per turn on the same client; the conversation keeps every earlier turn, so later
turns read the research from the prompt cache. Nothing is edited or re-sent (append-only history, as Fable 5.1's
preserved thinking needs): a later pool turn sends only an update (Greek so far, caret; the English only when it
changed) and the new slots with the continuations already offered for them. The first pool turn asks the model to
research once (the English, the poet's use of the key lemmas, dialect forms) and to start proposing after two or
three lookups. A change of poet, metre or dialect opens a new session.

- **Turns run in the background**; the HTTP response subscribes to the turn's events. If melos-api stops reading,
  the turn still runs to its end (bounded below) and its candidates still reach melos-api's store.
- **Join / preempt.** A `/pool` or `/warm` whose current slot the running pool turn already covers joins it: the
  candidates sent so far are replayed (`"replay": true`, melos-api does not store them twice), then live events;
  its `done` has `cost_usd: 0, shared: true`. A request for another slot preempts the running turn (`stop`
  `preempted`: interrupted at once); the research stays in the conversation. Turns of one session are serialised
  by a lock.
- **Ending a turn.** When every slot has its count, or after `COMPOSER_POOL_ROUNDS` propose calls, the model is told
  to reply "done"; after `COMPOSER_STOP_GRACE_SECONDS` it is interrupted. Deadline: `COMPOSER_WARM_SECONDS` for a
  session's first turn, `COMPOSER_POOL_SECONDS` after. A turn that does not end after an interrupt, or a CLI
  failure, drops the session (the next request starts a new one).
- **Bounds.** Idle sessions close after `COMPOSER_SESSION_IDLE_MINUTES` (30; the reaper runs every ≤ 60 s). At most
  `COMPOSER_MAX_SESSIONS` (4) exist: the least recently used idle one is closed to make room; if all are busy the
  request gets 503 `agent busy`. The prompt cache itself lives 5 minutes after the last turn; a session idle longer
  still keeps its context, but the next turn re-reads it at the cache-write price.
- `max_turns` is not set on session clients (it is unclear whether the CLI counts it per query or per session);
  rounds and deadlines bound each turn instead.

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

## Open points

- Target (15-30 s per new slot) not reached at `xhigh`: 40-120 s per new slot after the warm-up, ~4 min to the
  first candidate of a poem. The warm-up on poem open hides most of it: the whole first stanza (17 candidates) was
  ready after ~8 min, and whole-line candidates keep matching as the owner types into them, so most mid-line slots
  need no new turn. Further options (owner's choice): parallel per-line sessions forked from the warm session
  (`resume` + `fork_session`) to fill later lines at once; or a lower effort for pool turns only (contrary to the
  current ruling).
- The prompt cache's default lifetime is 5 minutes; a turn after a longer pause pays cache writes again (still no research).
- Cache writes are priced by assumption ($12.50/MTok); it matched the CLI's own cost figure to the cent.
