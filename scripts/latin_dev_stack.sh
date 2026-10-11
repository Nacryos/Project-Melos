#!/usr/bin/env bash
# Local development stack for the Latin composer on the box: melos-api (this worktree) on 127.0.0.1:8797 and the
# composer agent service on 127.0.0.1:8801, with scratch secrets and state under data/private/dev-stack/ (gitignored).
# Never touches the live melos-api* / melos-composer-agent containers. Usage: scripts/latin_dev_stack.sh start|stop|status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV="$ROOT/data/private/dev-stack"
KEY="${KEY:-$HOME/.config/basecamp/keys/anthropic-api.key}"
API_PORT="${API_PORT:-8797}"
AGENT_PORT="${AGENT_PORT:-8801}"
mkdir -p "$DEV/runtime" "$DEV/secrets" "$DEV/agent-state" "$DEV/logs"

prepare() {
  if [ ! -s "$DEV/secrets/owner_auth.env" ]; then
    "$ROOT/.venv/bin/python" - "$DEV/secrets" <<'PY'
import secrets, sys, pathlib
sys.path.insert(0, ".")
from backend import private_auth
d = pathlib.Path(sys.argv[1])
password = secrets.token_urlsafe(18)
(d / "owner_password.txt").write_text(password + "\n")
(d / "owner_auth.env").write_text(f"MELOS_OWNER_USERNAME=Owner\nMELOS_OWNER_PASSWORD_HASH={private_auth.hash_password(password)}\n"
                                   f"MELOS_OWNER_SESSION_KEY={secrets.token_hex(32)}\n")
(d / "composer_agent_token").write_text(secrets.token_hex(24) + "\n")
print("dev secrets written")
PY
    chmod 600 "$DEV/secrets/"*
  fi
}

start() {
  prepare
  [ -r "$KEY" ] || { echo "no Anthropic key at $KEY" >&2; exit 1; }
  (cd "$ROOT" && MELOS_OWNER_AUTH_FILE="$DEV/secrets/owner_auth.env" MELOS_COMPOSER_DB="$DEV/runtime/composer.sqlite" \
    MELOS_COMPOSER_AGENT_TOKEN_FILE="$DEV/secrets/composer_agent_token" MELOS_COMPOSER_AGENT_URL="http://127.0.0.1:$AGENT_PORT" \
    MELOS_OWNER_ORIGINS="http://127.0.0.1:$API_PORT" MELOS_DATA_DIR="$ROOT/data" nohup "$ROOT/.venv/bin/python" -m uvicorn backend.server:app --host 127.0.0.1 --port "$API_PORT" \
    > "$DEV/logs/api.log" 2>&1 & echo $! > "$DEV/api.pid")
  (cd "$ROOT/agent" && ANTHROPIC_API_KEY_FILE="$KEY" COMPOSER_AGENT_TOKEN_FILE="$DEV/secrets/composer_agent_token" \
    MELOS_API_URL="http://127.0.0.1:$API_PORT" COMPOSER_AGENT_STATE="$DEV/agent-state" COMPOSER_AGENT_HOST=127.0.0.1 \
    COMPOSER_AGENT_PORT="$AGENT_PORT" nohup "$ROOT/.venv-agent/bin/python" -m composer_agent.app \
    > "$DEV/logs/agent.log" 2>&1 & echo $! > "$DEV/agent.pid")
  echo "api pid $(cat "$DEV/api.pid") on :$API_PORT; agent pid $(cat "$DEV/agent.pid") on :$AGENT_PORT; logs in $DEV/logs"
}

stop() {
  for n in api agent; do
    if [ -f "$DEV/$n.pid" ]; then kill "$(cat "$DEV/$n.pid")" 2>/dev/null && echo "$n stopped" || true; rm -f "$DEV/$n.pid"; fi
  done
  # the dev ports only (the live containers use other ports): kill whatever still listens there
  for port in "$API_PORT" "$AGENT_PORT"; do
    for pid in $(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {print $NF}' | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$pid" 2>/dev/null || true; done
  done
  sleep 1
}

status() {
  for pair in "api:$API_PORT" "agent:$AGENT_PORT"; do
    n="${pair%%:*}"; port="${pair##*:}"
    if ss -ltn 2>/dev/null | grep -q ":$port "; then echo "$n listening on :$port"; else echo "$n not running"; fi
  done
}

case "${1:-status}" in start) start ;; stop) stop ;; status) status ;; *) echo "usage: $0 start|stop|status" >&2; exit 2 ;; esac
