# Composer agent service (release W, W1/W2 server side)

Code: `agent/`. PRD: `docs/prd/composer-agent.md`. Written 2026-10-09 (Pacific).

## Contract with melos-api

- Container `melos-composer-agent`, network `melos-net`, port 8800, no published ports. Every request carries
  `X-Composer-Token` (secret file `COMPOSER_AGENT_TOKEN_FILE`; constant-time compare); otherwise 401.
- The agent calls melos-api (`MELOS_API_URL`) with the same header, which lifts rate limits.
- `POST /chat {poem, thread, message}` → SSE: `text` (deltas), `tool` (name, summary), `candidate`, `error`, `done`.
- `POST /pool {poem, slot{line_position, caret, prefix, remaining_template?}, n}` → SSE: `candidate`s that passed
  the lint, `tool`, then `{"type":"rejected","count","reasons":{check_id: count}}`, `done`.
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

## Pool loop (generate, then discard)

The model calls `propose_candidates` with a batch (≤ 16). The handler drops duplicates, lints every candidate in
parallel through `POST /api/composer/check` (8 at a time), streams those that pass at once as `candidate` events,
and returns the failures with their blocking check ids and details to the model. A candidate passes only when
`pass` is true and no blocking check failed; a lint transport or HTTP failure counts as a blocking failure
(`lint_unavailable`), so no unlinted candidate is ever emitted. Once `n` have passed, or after
`COMPOSER_POOL_ROUNDS` calls (4), or `COMPOSER_POOL_SECONDS` (120 s), the session is interrupted.

The lint request is `{greek: <continuation>, metre, dialect, author, remaining_template}` from the poem settings
and the slot; the continuation is sent without the prefix.

## Cost and logs

Cost = usage × Fable 5.1 prices ($10 in, $50 out, $0.25 cache read, $12.50 cache write per MTok; cache-write
price assumed at 1.25× input, matching the CLI's own figure in the smoke test). One JSON line per request in
`$COMPOSER_AGENT_STATE/usage.jsonl` (endpoint, poem, usage, our cost, the SDK's cost, ms, stop/terminal reason,
pool counts). The key is never logged; it is read from its file per request and passed only in the CLI
subprocess environment.

## Smoke test (2026-10-09, laptop, fake melos-api)

`agent/smoke.py`: `/backtranslate` of Sappho 31.1 → "Seems to me that man equal to the gods" (7.8 s, $0.026).
`/pool` n=2, 1 round: 7 research tool calls (lemma_search, themes search, dialectize, scan), one batch of 8, two
passed and streamed (e.g. ἀ σελάννα φαίνετ' ὐπὲρ θαλάσσας, evidence Sappho 34, 96, 154), stopped at n; 74 s,
$0.343 (our cost = SDK cost). Total live spend of the session including debugging the recording proxy: about
$0.6.

## Open points

- Time to first pool candidate was ~70 s at `xhigh` (target < 15 s in PRD §4): the model researches first. Options
  for the owner: the pool prompt now asks for a first batch after a few quick lookups (not yet re-measured live);
  a lower effort for pools only would be faster but is contrary to the current ruling.
- The Docker image has not been built here (no Docker on the laptop); build and run on the box.
- Cache writes are priced by assumption ($12.50/MTok).
