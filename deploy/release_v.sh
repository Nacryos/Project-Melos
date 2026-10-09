#!/bin/sh
# Release V (composer canvas backend): POST /api/scan (the metre-free scanner with metre fit; GET /api/scan/rules)
# and POST /api/compose/suggest (next-line suggestions: corpus proposer, scanner/parser/dialect lint, repair rounds).
# Code-only image atop the LIVE image (U); canary/promote copy the live container's mounts, environment and
# command (deploy/clone_run.py), adding:
#   $V/data/scansion/quantities.sqlite -> /lemma/quantities.sqlite (scripts/scansion_build_lexicon.py; read with
#   SQLite immutable=1, so pages are shared from the OS page cache rather than held in the process)
#
#   sh /home/alvin/melos-v/src/deploy/release_v.sh build        # melos-api:20261009v atop the live image
#   sh /home/alvin/melos-v/src/deploy/release_v.sh dev          # live image + V dev tree on 127.0.0.1:8799 (not a release step)
#   sh /home/alvin/melos-v/src/deploy/release_v.sh canary       # melos-api-canary-v on 127.0.0.1:8792
#   sh /home/alvin/melos-v/src/deploy/release_v.sh stop-canary
#   sh /home/alvin/melos-v/src/deploy/release_v.sh promote      # stop+keep live as melos-api-before-v, start V on 8791
#   sh /home/alvin/melos-v/src/deploy/release_v.sh rollback     # stop V, restart the kept container
set -eu
V=${MELOS_V_DIR:-/home/alvin/melos-v}
SRC=$V/src
DATA=$V/data
IMAGE=${MELOS_V_IMAGE:-melos-api:20261009v}
LIVE=melos-api
KEPT=melos-api-before-v
CANARY=melos-api-canary-v
DEV=${MELOS_V_DEV:-melos-api-dev-v}
DEV_PORT=${MELOS_V_DEV_PORT:-8799}
step=${1:-}

v_args() {
  test -f "$DATA/scansion/quantities.sqlite"
  echo --mount "$DATA/scansion/quantities.sqlite:/lemma/quantities.sqlite:ro" \
       --env MELOS_SCANSION_LEXICON=/lemma/quantities.sqlite
}

case "$step" in
  build)
    base=${MELOS_V_BASE:-$(docker inspect "$LIVE" --format '{{.Config.Image}}')}
    docker image inspect "$base" >/dev/null
    echo "$base" > "$V/base-image.txt"
    docker build -q -f "$SRC/deploy/Dockerfile.v" --build-arg BASE_IMAGE="$base" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format "built {{.Id}} {{.Size}} bytes atop $base"
    ;;
  dev)
    docker rm -f "$DEV" >/dev/null 2>&1 || true
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$DEV" --port "$DEV_PORT" \
      --image "$(docker inspect "$LIVE" --format '{{.Config.Image}}')" \
      --mount "$SRC/backend:/app/backend:ro" $(v_args)
    sleep 20; curl -fsS "http://127.0.0.1:$DEV_PORT/api/status" | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$CANARY" --port 8792 --image "$IMAGE" $(v_args)
    sleep 20; curl -fsS http://127.0.0.1:8792/api/status | head -c 200; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker container inspect "$KEPT" >/dev/null 2>&1 && { echo "$KEPT exists; resolve it first" >&2; exit 1; }
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$KEPT" --name "$LIVE" --port 8791 --image "$IMAGE" \
      $(v_args) || { docker rename "$KEPT" "$LIVE"; docker start "$LIVE"; exit 1; }
    sleep 20; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-v"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 20; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  *)
    echo "usage: release_v.sh build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
