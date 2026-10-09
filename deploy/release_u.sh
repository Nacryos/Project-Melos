#!/bin/sh
# Release U (composer-ready backend): POST /api/analyze-text for typed Greek, unmetered local parser with a
# per-client rate limit, POST /api/dialectize (Attic -> Lesbian/Doric/Ionic spellings), each fragment
# counted once across editions (edition groups), fast-lookup fixes, concept search scoped by author/genre
# and read through head meanings, line-level parallels, /api/word latency.
# Code-only image atop the LIVE image (T once T is live); canary/promote copy the live container's mounts,
# environment and command (deploy/clone_run.py, release T), adding:
#   $U/data/edition_groups.sqlite -> /lemma/edition_groups.sqlite (scripts/build_edition_groups.py)
#   $U/data/ngrams.sqlite         -> /lemma/ngrams.sqlite (scripts/build_ngrams.py with the edition groups)
#   $U/data/render_cache.sqlite   -> /lemma/render_cache.sqlite (scripts/build_render_cache.py: dictionary renderings)
# The canary reads release T's synthetic private store, never the owner's.
#
#   sh /home/alvin/melos-u/src/deploy/release_u.sh build        # melos-api:20261009u atop the live image
#   sh /home/alvin/melos-u/src/deploy/release_u.sh dev          # live image + U dev tree on 127.0.0.1:8798 (not a release step)
#   sh /home/alvin/melos-u/src/deploy/release_u.sh canary       # melos-api-canary-u on 127.0.0.1:8792
#   sh /home/alvin/melos-u/src/deploy/release_u.sh stop-canary
#   sh /home/alvin/melos-u/src/deploy/release_u.sh promote      # stop+keep live as melos-api-before-u, start U on 8791
#   sh /home/alvin/melos-u/src/deploy/release_u.sh rollback     # stop U, restart the kept container
set -eu
U=${MELOS_U_DIR:-/home/alvin/melos-u}
SRC=$U/src
DATA=$U/data
IMAGE=${MELOS_U_IMAGE:-melos-api:20261009u}
LIVE=melos-api
KEPT=melos-api-before-u
CANARY=melos-api-canary-u
DEV=${MELOS_U_DEV:-melos-api-dev-u}
DEV_PORT=${MELOS_U_DEV_PORT:-8798}
T_CANARY_STORE=/home/alvin/melos-t/canary-private/store
step=${1:-}

u_args() {
  test -f "$DATA/edition_groups.sqlite" && test -f "$DATA/ngrams.sqlite" && test -f "$DATA/render_cache.sqlite"
  echo --mount "$DATA/edition_groups.sqlite:/lemma/edition_groups.sqlite:ro" \
       --mount "$DATA/ngrams.sqlite:/lemma/ngrams.sqlite:ro" \
       --mount "$DATA/render_cache.sqlite:/lemma/render_cache.sqlite:ro" \
       --env MELOS_EDITION_GROUPS=/lemma/edition_groups.sqlite --env MELOS_RENDER_CACHE=/lemma/render_cache.sqlite
}

canary_store() {
  # Release T's canary store, when the live container mounts a private store.
  if docker inspect "$LIVE" --format '{{range .HostConfig.Binds}}{{println .}}{{end}}' | grep -q ':/private:'; then
    echo --mount "$T_CANARY_STORE:/private:ro"
  fi
}

case "$step" in
  build)
    base=${MELOS_U_BASE:-$(docker inspect "$LIVE" --format '{{.Config.Image}}')}
    docker image inspect "$base" >/dev/null
    echo "$base" > "$U/base-image.txt"
    docker build -q -f "$SRC/deploy/Dockerfile.u" --build-arg BASE_IMAGE="$base" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format "built {{.Id}} {{.Size}} bytes atop $base"
    ;;
  dev)
    docker rm -f "$DEV" >/dev/null 2>&1 || true
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$DEV" --port "$DEV_PORT" \
      --image "$(docker inspect "$LIVE" --format '{{.Config.Image}}')" \
      --mount "$SRC/backend:/app/backend:ro" $(u_args) $(canary_store)
    sleep 15; curl -fsS "http://127.0.0.1:$DEV_PORT/api/status" | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$CANARY" --port 8792 --image "$IMAGE" \
      $(u_args) $(canary_store)
    sleep 15; curl -fsS http://127.0.0.1:8792/api/status | head -c 200; echo
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
      $(u_args) || { docker rename "$KEPT" "$LIVE"; docker start "$LIVE"; exit 1; }
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-u"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  *)
    echo "usage: release_u.sh build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
