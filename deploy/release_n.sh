#!/bin/sh
# Release N (2026-10-08): local Morpheus. A sidecar container (melos-morpheus) runs our own build
# of alpheios-project/morpheus 2f1a30d behind morphsvc 264ad78's envelope code; the API reaches
# it on the user-defined network melos-morpheus (MELOS_MORPHEUS_LOCAL), so every word can be
# parsed with no courtesy quota. Also: generate-and-test dialect/elision normalisation, bracket
# lookup fixes, the αὔως cross-reference follow-up. Code-only image atop the live M image; same
# mounts as M (L staged corpus, live data mount, live runtime).
#
# Run on Basecamp after the N source tarball is unpacked into $N/src:
#
#   sh /home/alvin/melos-n/src/deploy/release_n.sh morpheus   # build melos-morpheus:2f1a30d, network, start sidecar
#   sh /home/alvin/melos-n/src/deploy/release_n.sh build      # melos-api:20261008n from Dockerfile.patch atop M
#   sh /home/alvin/melos-n/src/deploy/release_n.sh warm       # local receipts for every GLP form (absent keys only)
#   sh /home/alvin/melos-n/src/deploy/release_n.sh canary     # melos-api-canary-n on 127.0.0.1:8792
#   sh /home/alvin/melos-n/src/deploy/release_n.sh promote    # stop+keep M as melos-api-before-n, start N on 8791
#   sh /home/alvin/melos-n/src/deploy/release_n.sh rollback   # stop N, restart the kept M (sidecar left running, unused by M)
set -eu
cd /home/alvin/services/melos 2>/dev/null || true
N=${MELOS_N_DIR:-/home/alvin/melos-n}
SRC=$N/src
CORPUS=/home/alvin/melos-l/data          # release L staged corpus (288,821 passages), unchanged
DATAMOUNT=/home/alvin/services/melos/data
RUNTIME=/home/alvin/services/melos/runtime
BASE=melos-api:20261008m
IMAGE=melos-api:20261008n
LIVE=melos-api
KEPT=melos-api-before-n
CANARY=melos-api-canary-n
NET=melos-morpheus
MORPHEUS=melos-morpheus
MORPHEUS_IMAGE=melos-morpheus:2f1a30d
LOCAL=http://$MORPHEUS:8080/api/v1/analysis/word
step=${1:-}

run_container() {
  name=$1; port=$2
  docker run -d --name "$name" --restart unless-stopped --network "$NET" \
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
    -e MELOS_MORPHEUS_LOCAL=$LOCAL \
    -v /home/alvin/services/melos/models:/models:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v $DATAMOUNT:/app/data:ro \
    -v $RUNTIME:/app/runtime:rw \
    -v $CORPUS/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $CORPUS/manifest.json:/app/data/embeddings/manifest.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    "$IMAGE" \
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
    --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
}

case "$step" in
  morpheus)
    docker build -q -t "$MORPHEUS_IMAGE" "$SRC/deploy/morpheus-local"
    docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
    if ! docker container inspect "$MORPHEUS" >/dev/null 2>&1; then
      docker run -d --name "$MORPHEUS" --network "$NET" --restart unless-stopped \
        --read-only --tmpfs /tmp:rw,size=32m --cap-drop=ALL --security-opt=no-new-privileges \
        --memory=1g --cpus=4 --pids-limit=128 --log-driver=local --log-opt max-size=5m \
        -p 127.0.0.1:8793:8080 "$MORPHEUS_IMAGE" >/dev/null
      sleep 2
    fi
    curl -fsS http://127.0.0.1:8793/health; echo
    ;;
  build)
    test -f "$SRC/deploy/Dockerfile.patch"
    docker image inspect "$BASE" >/dev/null
    docker build -q -f "$SRC/deploy/Dockerfile.patch" --build-arg BASE_IMAGE="$BASE" -t "$IMAGE" "$SRC"
    docker image inspect "$IMAGE" --format 'built {{.Id}} {{.Size}} bytes'
    ;;
  warm)
    # Local receipts (morpheus-local-v1) for every GLP form plus generated spellings, written
    # into the live cache under their own keys; M reads only alpheios-literal-v1 keys.
    docker run --rm --name melos-n-warm --network "$NET" --user 1000:1000 --read-only --tmpfs /tmp \
      -v "$SRC/backend:/app/backend:ro" -v "$SRC/scripts:/app/scripts:ro" \
      -v "$CORPUS/corpus.sqlite:/corpus.sqlite:ro" -v "$RUNTIME:/app/runtime:rw" -v "$N:/out:rw" \
      -e MELOS_MORPHEUS_LOCAL=$LOCAL "$IMAGE" \
      python scripts/warm_morphology_forms.py --corpus /corpus.sqlite --id-prefix campbell-glp: \
      --database /app/runtime/machine_morphology.sqlite --delay 0 --report /out/warm-glp.json > "$N/warm-glp.log" 2>&1
    tail -1 "$N/warm-glp.log"
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
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-n"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_n.sh morpheus|build|warm|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
