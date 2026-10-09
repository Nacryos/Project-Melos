#!/bin/sh
# Release T (private mode): owner sign-in, owner-only private library panels, private ranking signals
# for public search through one gate. Rules: docs/private-mode.md.
# Code-only image atop the LIVE image (S once S is live): build reads the live container's image, and
# canary/promote copy the live container's mounts, environment and command (deploy/clone_run.py), adding:
#   /home/alvin/services/melos/secrets/owner_auth.env -> /run/secrets/owner_auth.env (ro, mode 600)
#   $PRIVATE_STORE (the private store directory)        -> /private (ro)
#
#   sh /home/alvin/melos-t/src/deploy/release_t.sh build        # melos-api:<date>t atop the live image
#   sh /home/alvin/melos-t/src/deploy/release_t.sh canary       # melos-api-canary-t on 127.0.0.1:8792
#   sh /home/alvin/melos-t/src/deploy/release_t.sh stop-canary
#   sh /home/alvin/melos-t/src/deploy/release_t.sh promote      # stop+keep live as melos-api-before-t, start T on 8791
#   sh /home/alvin/melos-t/src/deploy/release_t.sh rollback     # stop T, restart the kept container
# The canary reads a separate store with one synthetic test document (MELOS_T_CANARY_STORE) unless
# PRIVATE_STORE is set; promote always mounts the owner's real store.
set -eu
T=${MELOS_T_DIR:-/home/alvin/melos-t}
SRC=$T/src
IMAGE=${MELOS_T_IMAGE:-melos-api:20261009t}
LIVE=melos-api
KEPT=melos-api-before-t
CANARY=melos-api-canary-t
SECRET=/home/alvin/services/melos/secrets/owner_auth.env
REAL_STORE=/home/alvin/melos-private/store
CANARY_STORE=${MELOS_T_CANARY_STORE:-$T/canary-private/store}
step=${1:-}

t_args() {
  store=$1
  test -f "$SECRET" || { echo "missing $SECRET (scripts/owner_auth_setup.py)" >&2; exit 1; }
  [ "$(stat -c %a "$SECRET")" = 600 ] || { echo "$SECRET must be mode 600" >&2; exit 1; }
  mkdir -p "$store"
  echo --mount "$SECRET:/run/secrets/owner_auth.env:ro" --mount "$store:/private:ro" \
       --env MELOS_OWNER_AUTH_FILE=/run/secrets/owner_auth.env --env MELOS_PRIVATE_STORE=/private/private.sqlite \
       --env MELOS_OWNER_ORIGINS=https://greeklyric.com
}

case "$step" in
  build)
    base=${MELOS_T_BASE:-$(docker inspect "$LIVE" --format '{{.Config.Image}}')}
    docker image inspect "$base" >/dev/null
    echo "$base" > "$T/base-image.txt"
    docker build -q -f "$SRC/deploy/Dockerfile.t" --build-arg BASE_IMAGE="$base" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format "built {{.Id}} {{.Size}} bytes atop $base"
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    # shellcheck disable=SC2046
    python3 "$SRC/deploy/clone_run.py" --from "$LIVE" --name "$CANARY" --port 8792 --image "$IMAGE" \
      $(t_args "${PRIVATE_STORE:-$CANARY_STORE}")
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
      $(t_args "$REAL_STORE") || { docker rename "$KEPT" "$LIVE"; docker start "$LIVE"; exit 1; }
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-t"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 200; echo
    ;;
  *)
    echo "usage: release_t.sh build|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
