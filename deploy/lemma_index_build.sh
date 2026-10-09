#!/bin/sh
# Release O: build the corpus headword index on Basecamp (batch job, not a service).
#
#   sh deploy/lemma_index_build.sh engine     # start melos-morpheus-batch (own container, 10 CPUs) on melos-morpheus
#   sh deploy/lemma_index_build.sh forms|morph|generate|assemble
#   sh deploy/lemma_index_build.sh context <shards>   # OdyCy over edited Greek text, <shards> parallel containers
#   sh deploy/lemma_index_build.sh context-all <shards>   # release P: also scholia, commentary and OCR pages
#   sh deploy/lemma_index_build.sh engine-stop
#
# Uses the deployed N image with the source tree mounted read-only; writes only to $O/build and $O/data.
# Release P: MELOS_O_DIR=/home/alvin/melos-p MELOS_O_CORPUS=/home/alvin/melos-o/data/corpus.sqlite NAME=melos-p
# (the O staging file copied to $O/build first, so O's build state is not touched).
set -eu
O=${MELOS_O_DIR:-/home/alvin/melos-o}
TREE=${MELOS_O_TREE:-$O/dev-tree}
CORPUS=${MELOS_O_CORPUS:-$O/data/corpus.sqlite}
IMAGE=${MELOS_O_BUILD_IMAGE:-melos-api:20261008n}
NET=melos-morpheus
NAME=${NAME:-melos-o}
BATCH=melos-morpheus-batch
ENDPOINT=http://$BATCH:8080/api/v1/analysis/word
step=${1:-}

run() {
  name=$1; shift
  docker run --rm --name "$name" --network "$NET" --user 1000:1000 --read-only --tmpfs /tmp:rw,size=512m \
    --memory=12g --memory-swap=12g --cpus=${CPUS:-6} \
    -e OMP_NUM_THREADS=${THREADS_PER:-2} -e MKL_NUM_THREADS=${THREADS_PER:-2} \
    -v "$TREE/backend:/app/backend:ro" -v "$TREE/scripts:/app/scripts:ro" \
    -v /home/alvin/services/melos/data/lexica:/lexica:ro \
    -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
    -v "$CORPUS:/corpus.sqlite:ro" -v "$O/build:/build:rw" -v "$O/data:/out:rw" \
    "$IMAGE" python scripts/build_lemma_index.py "$@" --corpus /corpus.sqlite --build /build/lemma-build.sqlite \
    --lexica /lexica --out /out/lemma_index.sqlite --endpoint "$ENDPOINT"
}

case "$step" in
  engine)
    docker container inspect "$BATCH" >/dev/null 2>&1 || docker run -d --name "$BATCH" --network "$NET" \
      --read-only --tmpfs /tmp:rw,size=64m --cap-drop=ALL --security-opt=no-new-privileges \
      --memory=2g --cpus=10 --pids-limit=512 --log-driver=local --log-opt max-size=5m melos-morpheus:2f1a30d >/dev/null
    sleep 2; docker ps --filter name="$BATCH" --format '{{.Names}} {{.Status}}'
    ;;
  engine-stop) docker rm -f "$BATCH" >/dev/null && echo "removed $BATCH" ;;
  forms) CPUS=2 run $NAME-forms forms ;;
  morph) CPUS=4 run $NAME-morph morph --threads 24 ;;
  generate) CPUS=8 run $NAME-generate generate --threads 40 ;;
  context|context-all)
    shards=${2:-4}; i=0; extra=""
    [ "$step" = context-all ] && extra="--all-records"
    while [ $i -lt "$shards" ]; do
      CPUS=3 THREADS_PER=3 run $NAME-context-$i context --model /syntax-model --shards "$shards" --shard $i $extra \
        > "$O/build/context-$i.log" 2>&1 &
      i=$((i+1))
    done
    wait; tail -n 2 "$O"/build/context-*.log
    ;;
  assemble) CPUS=4 run $NAME-assemble assemble ${ASSEMBLE_ARGS:-} ;;
  *) echo "usage: lemma_index_build.sh engine|engine-stop|forms|morph|generate|context N|context-all N|assemble" >&2; exit 1 ;;
esac
