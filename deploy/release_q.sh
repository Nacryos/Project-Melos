#!/bin/sh
# Release Q (2026-10-09): elided words ranked by a treebank-trained model (restored vowels only,
# frequency prior, context), frequency tables count each text once, Voigt / Lobel-Page / Campbell
# fragment-number concordance, sourced dates for the Homeric Hymns, Anacreontea and Semonides.
# Code-only image atop the live P image. Data:
#   O's corpus.sqlite and embeddings/ (unchanged, read-only from $O/data)
#   $Q/data/lemma_index.sqlite     reassembled from P's staging with the elision model (data/elision_model.json)
#   $Q/data/citation_index.sqlite  scripts/build_citation_index.py (+ data/fragment_concordance.json)
#   $Q/data/ngrams.sqlite          scripts/build_ngrams.py (one collection per text inside the scope)
#   $Q/data/lemma_calibration.json scripts/calibrate_lemma_confidence.py (cross-fitted, elision class)
#   $Q/data/metadata/{chronology,attributions,genre_sources}.json   scripts/collect_chronology.py
#
#   sh /home/alvin/melos-q/src/deploy/release_q.sh build      # melos-api:20261009q from Dockerfile.patch atop P
#   sh /home/alvin/melos-q/src/deploy/release_q.sh dev        # P image + Q dev-tree backend on 8797 (not a release step)
#   sh /home/alvin/melos-q/src/deploy/release_q.sh canary     # melos-api-canary-q on 127.0.0.1:8792
#   sh /home/alvin/melos-q/src/deploy/release_q.sh stop-canary
#   sh /home/alvin/melos-q/src/deploy/release_q.sh promote    # stop+keep P as melos-api-before-q, start Q on 8791
#   sh /home/alvin/melos-q/src/deploy/release_q.sh rollback   # stop Q, restart the kept P
set -eu
Q=${MELOS_Q_DIR:-/home/alvin/melos-q}
O=/home/alvin/melos-o
SRC=$Q/src
DATA=$Q/data
DATAMOUNT=/home/alvin/services/melos/data
RUNTIME=/home/alvin/services/melos/runtime
BASE=melos-api:20261009p
IMAGE=${MELOS_Q_IMAGE:-melos-api:20261009q}
LIVE=melos-api
KEPT=melos-api-before-q
CANARY=melos-api-canary-q
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
    -e MELOS_CITATION_INDEX=/lemma/citation_index.sqlite \
    -e MELOS_NGRAM_INDEX=/lemma/ngrams.sqlite \
    -e MELOS_LEMMA_CALIBRATION=/lemma/lemma_calibration.json \
    -e MELOS_ATTRIBUTIONS=/p-metadata/attributions.json -e MELOS_GENRE_SOURCES=/p-metadata/genre_sources.json \
    -v /home/alvin/services/melos/models:/models:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v $DATAMOUNT:/app/data:ro \
    -v $RUNTIME:/app/runtime:rw \
    -v $O/data/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $O/data/embeddings:/app/data/embeddings:ro \
    -v ${LEMMA_INDEX:-$DATA/lemma_index.sqlite}:/lemma/lemma_index.sqlite:ro \
    -v $DATA/citation_index.sqlite:/lemma/citation_index.sqlite:ro \
    -v $DATA/ngrams.sqlite:/lemma/ngrams.sqlite:ro \
    -v $DATA/lemma_calibration.json:/lemma/lemma_calibration.json:ro \
    -v $DATA/metadata/chronology.json:/app/data/metadata/chronology.json:ro \
    -v $DATA/metadata:/p-metadata:ro \
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
    # Development only: P image with the Q backend tree mounted, port 8797 (not a release step).
    docker rm -f melos-api-dev-q >/dev/null 2>&1 || true
    IMAGE=$BASE run_container melos-api-dev-q 8797 "$Q/dev-tree/backend" >/dev/null
    sleep 12; curl -fsS http://127.0.0.1:8797/api/status | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    run_container "$CANARY" 8792 >/dev/null
    sleep 12; curl -fsS http://127.0.0.1:8792/api/status | head -c 300; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791 >/dev/null
    sleep 12; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-q"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 12; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_q.sh build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
