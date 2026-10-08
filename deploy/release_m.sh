#!/bin/sh
# Release M (2026-10-08): general lemma/gloss fixes found by random sampling across every
# Campbell GLP poem (scripts/sample_glp_quality.py), plus Morpheus receipts for the most
# frequent GLP forms. Code-only image atop the live L image; same mounts as L (the L staged
# corpus, the live data mount with the open-lexica supplement, the live runtime).
#
# Run on Basecamp after the M source tarball is unpacked into $M/src and the receipts
# bundle copied to $M/receipts-bundle.json:
#
#   sh /home/alvin/melos-m/src/deploy/release_m.sh receipts   # import Morpheus receipts (absent keys only)
#   sh /home/alvin/melos-m/src/deploy/release_m.sh build      # melos-api:20261008m from Dockerfile.patch atop L
#   sh /home/alvin/melos-m/src/deploy/release_m.sh canary     # melos-api-canary-m on 127.0.0.1:8792
#   sh /home/alvin/melos-m/src/deploy/release_m.sh promote    # stop+keep L as melos-api-before-m, start M on 8791
#   sh /home/alvin/melos-m/src/deploy/release_m.sh rollback   # stop M, restart the kept L
set -eu
cd /home/alvin/services/melos 2>/dev/null || true
M=${MELOS_M_DIR:-/home/alvin/melos-m}
SRC=$M/src
CORPUS=/home/alvin/melos-l/data          # release L staged corpus (288,821 passages), unchanged
DATAMOUNT=/home/alvin/services/melos/data
BASE=melos-api:20261008l
IMAGE=melos-api:20261008m
LIVE=melos-api
KEPT=melos-api-before-m
CANARY=melos-api-canary-m
step=${1:-}

run_container() {
  name=$1; port=$2
  docker run -d --name "$name" --restart unless-stopped \
    --cpus=2 --cpu-shares=256 --memory=8g --memory-swap=8g --pids-limit=128 \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=128m \
    --cap-drop=ALL --security-opt=no-new-privileges --user=1000:1000 \
    --log-driver=local --log-opt max-size=10m --log-opt max-file=3 \
    -p "127.0.0.1:$port:8791" \
    -e MELOS_PUBLIC_DEPLOYMENT=1 -e MELOS_PUBLICATION_POLICY=source-labels \
    -e MELOS_PUBLIC_CLASSIFIER=1 -e MELOS_CLASSIFIER_STATE=/app/runtime/classifier.sqlite \
    -e MELOS_JEV_MODEL=jev-1.13.0 -e MELOS_CLASSIFIER_DAILY_LIMIT=500 \
    -e MELOS_CORS_ORIGINS=https://greeklyric.com,https://project-melos.vercel.app \
    -e MELOS_SYNTAX_MODEL_PATH=/syntax-model \
    -e MELOS_MACHINE_GLOBAL_DAILY=1000 -e MELOS_MACHINE_GLOBAL_MINUTE=30 \
    -e MELOS_MACHINE_VISITOR_DAILY=100 -e MELOS_MACHINE_VISITOR_MINUTE=10 \
    -v /home/alvin/services/melos/models:/models:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v $DATAMOUNT:/app/data:ro \
    -v /home/alvin/services/melos/runtime:/app/runtime:rw \
    -v $CORPUS/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $CORPUS/manifest.json:/app/data/embeddings/manifest.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    "$IMAGE" \
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
    --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
}

case "$step" in
  receipts)
    test -f "$M/receipts-bundle.json"
    cd "$SRC" && python3 deploy/sync_morphology_receipts.py import /home/alvin/services/melos/runtime/machine_morphology.sqlite "$M/receipts-bundle.json" --apply
    ;;
  build)
    test -f "$SRC/deploy/Dockerfile.patch"
    docker image inspect "$BASE" >/dev/null
    docker build -q -f "$SRC/deploy/Dockerfile.patch" --build-arg BASE_IMAGE="$BASE" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format 'built {{.Id}} {{.Size}} bytes'
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    run_container "$CANARY" 8792
    sleep 8; curl -fsS http://127.0.0.1:8792/api/status | head -c 300; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-m"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_m.sh receipts|build|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
