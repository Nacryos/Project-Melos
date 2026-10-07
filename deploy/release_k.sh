#!/bin/sh
# Release K (2026-10-07): full parses for every printed word.
#
# Run on Basecamp from /home/alvin/services/melos after the K source tarball
# has been unpacked into releases/lexical-20261007k/src. Each step is explicit
# so it can be run and checked one at a time:
#
#   sh releases/lexical-20261007k/src/deploy/release_k.sh build     # image from Dockerfile.patch atop the verified QA29 base
#   sh releases/lexical-20261007k/src/deploy/release_k.sh receipts  # import Morpheus receipts (absent keys only)
#   sh releases/lexical-20261007k/src/deploy/release_k.sh canary    # start melos-api-canary on 127.0.0.1:8792
#   sh releases/lexical-20261007k/src/deploy/release_k.sh promote   # stop+keep the live container, start K on 8791
#   sh releases/lexical-20261007k/src/deploy/release_k.sh rollback  # stop K, restart the kept container
#
# Unlike releases E–I, K ships the whole backend package in the image; no
# per-module bind overlays. Data, models, runtime and secrets mounts are the
# same as the live container's.
set -eu
cd /home/alvin/services/melos
# releases/ is root-owned on Basecamp; K lives in the operator's own directory.
K=/home/alvin/melos-k
SRC=$K/src
BASE=melos-api:20261005-qa29
# Later K-series builds set MELOS_K_TAG (e.g. k2); the kept and failed names follow it.
TAG=${MELOS_K_TAG:-k}
IMAGE=melos-api:20261007$TAG
LIVE=melos-api
KEPT=melos-api-before-lexical-20261007$TAG
CANARY=melos-api-canary
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
    -v /home/alvin/services/melos/data:/app/data:ro \
    -v /home/alvin/services/melos/runtime:/app/runtime:rw \
    -v /home/alvin/services/melos/releases/campbell-20261007b/candidate-data/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v /home/alvin/services/melos/releases/campbell-20261007b/candidate-data/manifest.json:/app/data/embeddings/manifest.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    "$IMAGE" \
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
    --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
}

case "$step" in
  build)
    test -f "$SRC/deploy/Dockerfile.patch"
    docker image inspect "$BASE" >/dev/null
    docker build -q -f "$SRC/deploy/Dockerfile.patch" --build-arg BASE_IMAGE="$BASE" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format 'built {{.Id}} {{.Size}} bytes'
    ;;
  receipts)
    test -f "$K/receipts-bundle.json"
    cd "$SRC" && python3 deploy/sync_morphology_receipts.py import /home/alvin/services/melos/runtime/machine_morphology.sqlite "$K/receipts-bundle.json" --apply
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    run_container "$CANARY" 8792
    sleep 8; curl -fsS http://127.0.0.1:8792/api/status | head -c 300; echo
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-lexical-20261007$TAG"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_k.sh build|receipts|canary|promote|rollback" >&2; exit 1;;
esac
