# melos-composer-agent

The composer's agent service (PRD `docs/prd/composer-agent.md`, phases W1/W2, server side). Design and
contract: [`docs/composer/agent.md`](../docs/composer/agent.md).

- `composer_agent/app.py`: FastAPI on :8800; `POST /chat`, `/pool` and `/warm` (SSE), `POST /backtranslate` (JSON).
  Every request needs `X-Composer-Token` (the secret in `COMPOSER_AGENT_TOKEN_FILE`), else 401.
- `composer_agent/sessions.py`: one persistent Claude Agent SDK session per poem (pool) and per poem (chat).
- `composer_agent/runner.py`: SDK options and turn driving; model `claude-fable-5-1`, effort `xhigh`.
- `composer_agent/melos.py`: the Melos tools (in-process SDK MCP server) and the `propose_candidates` lint gate.
- `composer_agent/prompts.py`: instructions (PRD §7) and per-request messages.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSER_AGENT_TOKEN_FILE` | (required) | Shared secret with melos-api |
| `ANTHROPIC_API_KEY_FILE` | (required) | Anthropic key file; read per request, passed only to the CLI subprocess |
| `MELOS_API_URL` | `http://melos-api:8791` | melos-api base URL |
| `COMPOSER_AGENT_STATE` | `/state` | Writable dir: `usage.jsonl`, CLI config, scratch cwd |
| `COMPOSER_POOL_ROUNDS` / `COMPOSER_POOL_SECONDS` | 8 / 240 | Pool bounds per turn (propose calls / seconds) |
| `COMPOSER_WARM_SECONDS` | 600 | Bound of a session's first turn (research + first stanza batch) |
| `COMPOSER_POOL_AHEAD_N` | 6 | Passing candidates wanted per later slot of the stanza |
| `COMPOSER_STOP_GRACE_SECONDS` | 8 | After "stop", time for the model to end the turn before it is interrupted |
| `COMPOSER_SESSION_IDLE_MINUTES` | 30 | Idle sessions are closed after this |
| `COMPOSER_MAX_SESSIONS` | 4 | Open sessions (each a CLI process) at most |
| `COMPOSER_CHAT_SECONDS` | 600 | Chat bound |
| `COMPOSER_TOOL_RESULT_CHARS` | 10000 | Tool results are truncated to this |

## Develop and test

```
uv venv -p 3.12 agent/.venv && uv pip install --python agent/.venv/bin/python -r agent/requirements.txt -r agent/requirements-dev.txt
agent/.venv/bin/python -m pytest -q agent/tests          # fake melos-api, no Anthropic calls
env -i HOME=$HOME PATH=$PATH ANTHROPIC_API_KEY_FILE=/path/key agent/.venv/bin/python agent/smoke.py   # live, ~$0.4
```

## Deploy (box)

```
docker build -t melos-composer-agent:<tag> agent/
agent/run.sh <tag>      # --network melos-net, no published ports, read-only root, secrets ro, /state volume
```
