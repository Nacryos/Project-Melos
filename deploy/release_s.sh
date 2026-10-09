#!/bin/sh
# Release S (2026-10-09): stacked semantic search. Fused lists with weights fitted on the development
# queries of data/evaluation/search-eval-s.json: release R's word, form, BGE-M3, English-bridge and
# headword lists plus a keyword list with spelling variants, headwords widened to their variant groups,
# per-kind vectors (Greek text, English translation, commentary) and commentary notes
# (public-domain commentaries linked to passages). Code-only image atop the live R image (melos-api:20261009r2).
# Data (read-only):
#   O's corpus.sqlite and embeddings/ (unchanged)          $O/data
#   R's lemma_index.sqlite, ngrams.sqlite, calibration      $R/data
#   Q's citation_index.sqlite and metadata/                 $Q/data
#   $S/data/embeddings-s/<model>/  manifest, rows, float16 vectors (bge-m3 points at O's files)
#   $S/data/commentary_context.sqlite                      scripts/build_commentary_context.py
#   $S/models                                              pinned Hugging Face snapshots of the S encoders
#
#   sh /home/alvin/melos-s/src/deploy/release_s.sh build      # melos-api:20261009s from Dockerfile.patch atop R
#   sh /home/alvin/melos-s/src/deploy/release_s.sh dev        # R image + S dev-tree backend on 8796 (not a release step)
#   sh /home/alvin/melos-s/src/deploy/release_s.sh canary     # melos-api-canary-s on 127.0.0.1:8792
#   sh /home/alvin/melos-s/src/deploy/release_s.sh stop-canary
#   sh /home/alvin/melos-s/src/deploy/release_s.sh promote    # stop+keep R as melos-api-before-s, start S on 8791
#   sh /home/alvin/melos-s/src/deploy/release_s.sh rollback   # stop S, restart the kept R
set -eu
S=${MELOS_S_DIR:-/home/alvin/melos-s}
R=/home/alvin/melos-r
Q=/home/alvin/melos-q
O=/home/alvin/melos-o
SRC=$S/src
DATA=$S/data
DATAMOUNT=/home/alvin/services/melos/data
RUNTIME=/home/alvin/services/melos/runtime
BASE=${MELOS_S_BASE:-melos-api:20261009r2}
IMAGE=${MELOS_S_IMAGE:-melos-api:20261009s}
LIVE=melos-api
KEPT=melos-api-before-s
CANARY=melos-api-canary-s
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
    -e MELOS_S_EMBEDDINGS=/s-embeddings -e MELOS_S_MODEL_CACHE=/s-models \
    -e MELOS_COMMENTARY_CONTEXT=/s-data/commentary_context.sqlite \
    -e HF_MODULES_CACHE=/tmp/hf_modules -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 \
    -v /home/alvin/services/melos/models:/models:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v $DATAMOUNT:/app/data:ro \
    -v $RUNTIME:/app/runtime:rw \
    -v $O/data/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $O/data/embeddings:/app/data/embeddings:ro \
    -v $R/data/lemma_index.sqlite:/lemma/lemma_index.sqlite:ro \
    -v $Q/data/citation_index.sqlite:/lemma/citation_index.sqlite:ro \
    -v $R/data/ngrams.sqlite:/lemma/ngrams.sqlite:ro \
    -v $R/data/lemma_calibration.json:/lemma/lemma_calibration.json:ro \
    -v $Q/data/metadata/chronology.json:/app/data/metadata/chronology.json:ro \
    -v $Q/data/metadata:/p-metadata:ro \
    -v $DATA/embeddings-s:/s-embeddings:ro \
    -v $S/models:/s-models:ro \
    -v $DATA/commentary_context.sqlite:/s-data/commentary_context.sqlite:ro \
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
    # Development only: R image with the S backend tree mounted, port 8796 (not a release step).
    docker rm -f melos-api-dev-s >/dev/null 2>&1 || true
    IMAGE=$BASE run_container melos-api-dev-s 8796 "$S/dev-tree/backend" >/dev/null
    sleep 15; curl -fsS http://127.0.0.1:8796/api/status | head -c 120; echo
    ;;
  canary)
    docker container inspect "$CANARY" >/dev/null 2>&1 && { echo "$CANARY exists; remove it first" >&2; exit 1; }
    run_container "$CANARY" 8792 >/dev/null
    sleep 15; curl -fsS http://127.0.0.1:8792/api/status | head -c 300; echo
    ;;
  stop-canary)
    docker stop "$CANARY" >/dev/null && echo "stopped $CANARY (kept)"
    ;;
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791 >/dev/null
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-s"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 15; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_s.sh build|dev|canary|stop-canary|promote|rollback" >&2; exit 1;;
esac
