#!/usr/bin/env bash
# Start melos-composer-agent on the box (internal network only; no published ports).
# Usage: agent/run.sh [image-tag]     (build first: docker build -t melos-composer-agent:<tag> agent/)
set -euo pipefail
TAG="${1:-latest}"
NET="${NET:-melos-net}"
SECRETS="${SECRETS:-/home/alvin/services/melos/secrets}"
KEY="${KEY:-/home/alvin/.config/basecamp/keys/anthropic-api.key}"
STATE="${STATE:-/home/alvin/services/melos/composer-agent-state}"
TOKEN_FILE="$SECRETS/composer_agent_token"     # shared with melos-api (it sends X-Composer-Token)

mkdir -p "$STATE"
[ -s "$TOKEN_FILE" ] || { umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TOKEN_FILE"; }
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
docker rm -f melos-composer-agent >/dev/null 2>&1 || true
docker run -d --name melos-composer-agent --restart unless-stopped --network "$NET" \
  --read-only --tmpfs /tmp:rw,nosuid,size=256m \
  --cap-drop=ALL --security-opt=no-new-privileges --user=1000:1000 \
  --cpus=2 --memory=3g --memory-swap=3g --pids-limit=256 --log-driver=local --log-opt max-size=5m \
  -v "$STATE:/state:rw" \
  -v "$KEY:/run/secrets/anthropic-api.key:ro" \
  -v "$TOKEN_FILE:/run/secrets/composer_agent_token:ro" \
  -e ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic-api.key \
  -e COMPOSER_AGENT_TOKEN_FILE=/run/secrets/composer_agent_token \
  -e MELOS_API_URL="${MELOS_API_URL:-http://melos-api:8791}" \
  "melos-composer-agent:$TAG"
echo "melos-composer-agent:$TAG on $NET:8800 (state $STATE)"
