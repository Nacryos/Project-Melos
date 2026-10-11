#!/bin/sh
# Release X (literal translation fallback and search rows; docs/decisions.md 2026-10-10).
# Code layer atop the LIVE image (W). canary/promote copy the live container's mounts, environment and command
# (deploy/clone_run.py) and replace three data mounts with X's:
#   $X/data/corpus.sqlite      -> /app/data/corpus.sqlite:ro   (O's corpus + 59 machine_translation rows)
#   $X/data/embeddings         -> /app/data/embeddings:ro      (O's BGE-M3 rows/vectors + 59, manifest rebound)
#   $X/data/embeddings-s       -> /s-embeddings:ro             (S: bge-m3 manifest rebound, shlm rows/vectors + 59)
#
#   sh /home/alvin/melos-x/src/deploy/release_x.sh build        # melos-api:20261011x atop the live image
#   sh /home/alvin/melos-x/src/deploy/release_x.sh canary       # melos-api-canary-x on 127.0.0.1:8793 (8792 is held by an older canary)
#   sh /home/alvin/melos-x/src/deploy/release_x.sh stop-canary
#   sh /home/alvin/melos-x/src/deploy/release_x.sh promote      # stop+keep live as melos-api-before-x, start X on 8791
#   sh /home/alvin/melos-x/src/deploy/release_x.sh rollback     # stop X, restart the kept container
set -eu
X=${MELOS_X_DIR:-/home/alvin/melos-x}
SRC=$X/src
IMAGE=${MELOS_X_IMAGE:-melos-api:20261011x}
LIVE=melos-api
KEPT=${MELOS_X_KEPT:-melos-api-before-x}
CANARY=${MELOS_X_CANARY:-melos-api-canary-x}
CANARY_PORT=${MELOS_X_CANARY_PORT:-8793}
# Point releases (X.1 ...): MELOS_X_IMAGE=melos-api:20261011x1 MELOS_X_KEPT=melos-api-before-x1 MELOS_X_CANARY=melos-api-canary-x1.
# MELOS_X_CANARY_RUNTIME=<dir>: the canary gets that directory as /app/runtime (a copy of the live one), so a schema
# migration or a stray write cannot touch the live composer store.
CANARY_RUNTIME=${MELOS_X_CANARY_RUNTIME:-}
NETWORK=${MELOS_X_NETWORK:-melos-net}
step=${1:-}

x_mounts() {
  for f in "$X/data/corpus.sqlite" "$X/data/embeddings/manifest.json" "$X/data/embeddings-s/bge-m3/manifest.json" "$X/data/embeddings-s/shlm/manifest.json"; do
    test -s "$f" || { echo "missing $f" >&2; exit 1; }
  done
  echo --mount "$X/data/corpus.sqlite:/app/data/corpus.sqlite:ro" \
       --mount "$X/data/embeddings:/app/data/embeddings:ro" \
       --mount "$X/data/embeddings-s:/s-embeddings:ro"
}

join_network() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 && docker network connect "$NETWORK" "$1" 2>/dev/null || true
}

case "$step" in
  build)
    base=${MELOS_X_BASE:-$(docker inspect "$LIVE" --format '{{.Config.Image}}')}
    docker image inspect "$base" >/dev/null
    echo "$base" > "$X/base-image.txt"
    docker build -q -f "$SRC/deploy/Dockerfile.x" --build-arg BASE_IMAGE="$base" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format "built {{.Id}} {{.Size}} bytes atop $base"
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$CANARY" --port "$CANARY_PORT" --image "$IMAGE" $(x_mounts) \
      ${CANARY_RUNTIME:+--mount "$CANARY_RUNTIME:/app/runtime"}
    join_network "$CANARY"
    sleep 25; curl -fsS "http://127.0.0.1:$CANARY_PORT/api/status" | head -c 300; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker container inspect "$KEPT" >/dev/null 2>&1 && { echo "$KEPT exists; resolve it first" >&2; exit 1; }
    mounts=$(x_mounts)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    # shellcheck disable=SC2086
    python3 "$SRC/deploy/clone_run.py" --from "$KEPT" --name "$LIVE" --port 8791 --image "$IMAGE" \
      $mounts || { docker rename "$KEPT" "$LIVE"; docker start "$LIVE"; exit 1; }
    join_network "$LIVE"
    sleep 25; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-x"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 25; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_x.sh build|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
