# melos-composer-agent

The composer's agent service (PRD `docs/prd/composer-agent.md`, phases W1/W2, server side). Design and
contract: [`docs/composer/agent.md`](../docs/composer/agent.md).

- `composer_agent/app.py`: FastAPI on :8800; `POST /chat` and `POST /pool` (SSE), `POST /backtranslate` (JSON).
  Every request needs `X-Composer-Token` (the secret in `COMPOSER_AGENT_TOKEN_FILE`), else 401.
- `composer_agent/runner.py`: one Claude Agent SDK session per request; model `claude-fable-5-1`, effort `xhigh`.
- `composer_agent/melos.py`: the Melos tools (in-process SDK MCP server) and the `propose_candidates` lint gate.
- `composer_agent/prompts.py`: instructions (PRD §7) and per-request messages.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSER_AGENT_TOKEN_FILE` | (required) | Shared secret with melos-api |
| `ANTHROPIC_API_KEY_FILE` | (required) | Anthropic key file; read per request, passed only to the CLI subprocess |
| `MELOS_API_URL` | `http://melos-api:8791` | melos-api base URL |
| `COMPOSER_AGENT_STATE` | `/state` | Writable dir: `usage.jsonl`, CLI config, scratch cwd |
| `COMPOSER_POOL_ROUNDS` / `COMPOSER_POOL_SECONDS` | 4 / 120 | Pool bounds |
| `COMPOSER_CHAT_SECONDS` | 600 | Chat bound |
| `COMPOSER_TOOL_RESULT_CHARS` | 20000 | Tool results are truncated to this |

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
