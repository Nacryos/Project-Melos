#!/bin/sh
# Release O (2026-10-09): corpus headword index + Logeion/TLG features, search quality,
# concept diachrony groundwork, meaning vectors for the Campbell GLP poems, parser fixes.
# Code-only image atop the live N image. New data, all under $O/data and mounted read-only:
#   corpus.sqlite        L corpus + leading-sign repair + recomputed author columns (scripts/stage_corpus_o.py)
#   embeddings/          L vectors + 237 GLP poems + 77 re-encoded passages (scripts/embed_release_o.py)
#   lemma_index.sqlite   corpus headword index (scripts/build_lemma_index.py, deploy/lemma_index_build.sh)
#   chronology.json      Wikidata author date claims, 55 authors (scripts/collect_chronology.py)
#
#   sh /home/alvin/melos-o/src/deploy/release_o.sh build      # melos-api:20261009o from Dockerfile.patch atop N
#   sh /home/alvin/melos-o/src/deploy/release_o.sh canary     # melos-api-canary-o on 127.0.0.1:8792
#   sh /home/alvin/melos-o/src/deploy/release_o.sh stop-canary
#   sh /home/alvin/melos-o/src/deploy/release_o.sh promote    # stop+keep N as melos-api-before-o, start O on 8791
#   sh /home/alvin/melos-o/src/deploy/release_o.sh rollback   # stop O, restart the kept N
set -eu
O=${MELOS_O_DIR:-/home/alvin/melos-o}
SRC=$O/src
DATA=$O/data
DATAMOUNT=/home/alvin/services/melos/data
RUNTIME=/home/alvin/services/melos/runtime
BASE=melos-api:20261008n
IMAGE=${MELOS_O_IMAGE:-melos-api:20261009o}
LIVE=melos-api
KEPT=melos-api-before-o
CANARY=melos-api-canary-o
NET=melos-morpheus
LOCAL=http://melos-morpheus:8080/api/v1/analysis/word
step=${1:-}

run_container() {
  name=$1; port=$2; backend=${3:-}
  extra=""
  [ -n "$backend" ] && extra="-v $backend:/app/backend:ro"
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
    -e MELOS_MORPHEUS_LOCAL=$LOCAL -e MELOS_GENERATED_NORMALISATION=1 \
    -e MELOS_LEMMA_INDEX=/lemma/lemma_index.sqlite \
    -v /home/alvin/services/melos/models:/models:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v $DATAMOUNT:/app/data:ro \
    -v $RUNTIME:/app/runtime:rw \
    -v $DATA/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $DATA/embeddings:/app/data/embeddings:ro \
    -v $DATA/lemma_index.sqlite:/lemma/lemma_index.sqlite:ro \
    -v $DATA/chronology.json:/app/data/metadata/chronology.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    $extra ${EXTRA_ENV:-} "$IMAGE" \
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
  dev)
    # Development only: N image with the O backend tree mounted, port 8797 (not a release step).
    docker rm -f melos-api-dev-o >/dev/null 2>&1 || true
    IMAGE=$BASE run_container melos-api-dev-o 8797 "$O/dev-tree/backend" >/dev/null
    sleep 10; curl -fsS http://127.0.0.1:8797/api/status | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    run_container "$CANARY" 8792 >/dev/null
    sleep 10; curl -fsS http://127.0.0.1:8792/api/status | head -c 300; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791 >/dev/null
    sleep 10; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-o"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 10; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_o.sh build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
