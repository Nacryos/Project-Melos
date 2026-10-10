#!/bin/sh
# Release W (owner-only composer: W0 + the melos-api half of W1/W2; docs/prd/composer-agent.md).
# Code layer atop the LIVE image (V): composer.html, /api/compose/* and /api/composer/* owner-only (404 signed
# out), composer.sqlite (poems, lines, versions, pool, chat), POST /api/composer/check (lint bank), and the proxy
# to the composer agent service (agent/, container melos-composer-agent on network melos-net, port 8800).
# canary/promote copy the live container's mounts, environment and command (deploy/clone_run.py), adding:
#   MELOS_COMPOSER_DB=/app/runtime/composer.sqlite        (the live runtime mount; canary/dev use their own file)
#   $SECRETS/composer-agent -> /run/secrets/melos-composer:ro, MELOS_COMPOSER_AGENT_TOKEN_FILE=…/token
#                                                         (the shared token; the agent container mounts the same dir)
#   MELOS_COMPOSER_AGENT_URL=http://melos-composer-agent:8800, and the container joins docker network melos-net.
# The dev and canary containers read release T's synthetic private store, never the owner's.
#
#   sh /home/alvin/melos-w/src/deploy/release_w.sh token        # create the shared agent token once (mode 600)
#   sh /home/alvin/melos-w/src/deploy/release_w.sh build        # melos-api:20261010w atop the live image
#   sh /home/alvin/melos-w/src/deploy/release_w.sh dev          # live image + W dev tree on 127.0.0.1:8799 (not a release step)
#   sh /home/alvin/melos-w/src/deploy/release_w.sh canary       # melos-api-canary-w on 127.0.0.1:8792
#   sh /home/alvin/melos-w/src/deploy/release_w.sh stop-canary
#   sh /home/alvin/melos-w/src/deploy/release_w.sh promote      # stop+keep live as melos-api-before-w, start W on 8791
#   sh /home/alvin/melos-w/src/deploy/release_w.sh rollback     # stop W, restart the kept container
set -eu
W=${MELOS_W_DIR:-/home/alvin/melos-w}
SRC=$W/src
IMAGE=${MELOS_W_IMAGE:-melos-api:20261010w}
LIVE=melos-api
KEPT=melos-api-before-w
CANARY=melos-api-canary-w
DEV=${MELOS_W_DEV:-melos-api-dev-w}
DEV_PORT=${MELOS_W_DEV_PORT:-8799}
NETWORK=${MELOS_W_NETWORK:-melos-net}
SECRETS=${MELOS_SECRETS_DIR:-/home/alvin/services/melos/secrets}
TOKEN_DIR=$SECRETS/composer-agent
AGENT_URL=${MELOS_COMPOSER_AGENT_URL:-http://melos-composer-agent:8800}
T_CANARY_STORE=/home/alvin/melos-t/canary-private/store
step=${1:-}

w_args() {
  # $1 = composer.sqlite file name under /app/runtime
  test -s "$TOKEN_DIR/token" || { echo "no agent token: run release_w.sh token first" >&2; exit 1; }
  echo --mount "$TOKEN_DIR:/run/secrets/melos-composer:ro" \
       --env MELOS_COMPOSER_AGENT_TOKEN_FILE=/run/secrets/melos-composer/token \
       --env MELOS_COMPOSER_AGENT_URL="$AGENT_URL" \
       --env MELOS_COMPOSER_DB="/app/runtime/$1"
}

canary_store() {
  if docker inspect "$LIVE" --format '{{range .HostConfig.Binds}}{{println .}}{{end}}' | grep -q ':/private:'; then
    echo --mount "$T_CANARY_STORE:/private:ro"
  fi
}

join_network() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create --internal=false "$NETWORK" >/dev/null
  docker network connect "$NETWORK" "$1" 2>/dev/null || true
}

case "$step" in
  token)
    umask 077
    mkdir -p "$TOKEN_DIR"
    if [ -s "$TOKEN_DIR/token" ]; then echo "token exists: $TOKEN_DIR/token (kept)"; exit 0; fi
    python3 -c 'import secrets; print(secrets.token_hex(32))' > "$TOKEN_DIR/token"
    chmod 700 "$TOKEN_DIR"; chmod 600 "$TOKEN_DIR/token"; chown -R 1000:1000 "$TOKEN_DIR" 2>/dev/null || true
    echo "wrote $TOKEN_DIR/token (mount the same directory read-only into melos-composer-agent)"
    ;;
  build)
    base=${MELOS_W_BASE:-$(docker inspect "$LIVE" --format '{{.Config.Image}}')}
    docker image inspect "$base" >/dev/null
    echo "$base" > "$W/base-image.txt"
    docker build -q -f "$SRC/deploy/Dockerfile.w" --build-arg BASE_IMAGE="$base" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format "built {{.Id}} {{.Size}} bytes atop $base"
    ;;
  dev)
    docker rm -f "$DEV" >/dev/null 2>&1 || true
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$DEV" --port "$DEV_PORT" --image "$IMAGE" \
      --mount "$SRC/backend:/app/backend:ro" --mount "$SRC/composer.html:/app/composer.html:ro" \
      $(w_args composer-dev.sqlite) $(canary_store)
    join_network "$DEV"
    sleep 20; curl -fsS "http://127.0.0.1:$DEV_PORT/api/status" | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$CANARY" --port 8792 --image "$IMAGE" \
      $(w_args composer-canary.sqlite) $(canary_store)
    join_network "$CANARY"
    sleep 20; curl -fsS http://127.0.0.1:8792/api/status | head -c 200; echo
    # Signed out, the composer does not exist.
    test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8792/api/composer/poems)" = 404
    test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8792/composer)" = 404
    echo "composer gate: 404 signed out"
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker container inspect "$KEPT" >/dev/null 2>&1 && { echo "$KEPT exists; resolve it first" >&2; exit 1; }
    args=$(w_args composer.sqlite)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    # shellcheck disable=SC2086
    python3 "$SRC/deploy/clone_run.py" --from "$KEPT" --name "$LIVE" --port 8791 --image "$IMAGE" \
      $args || { docker rename "$KEPT" "$LIVE"; docker start "$LIVE"; exit 1; }
    join_network "$LIVE"
    sleep 20; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-w"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 20; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  *)
    echo "usage: release_w.sh token|build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
