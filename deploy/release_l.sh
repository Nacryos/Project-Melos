#!/bin/sh
# Release L (2026-10-08): K3 + open lexica supplement + every Campbell GLP poem + word-panel headline.
#
# Combines deploy/release_k.sh (image from Dockerfile.patch atop the QA29 base) and
# deploy/release_glp.sh (staged corpus copy with the 232 new poems and the five corrected
# Alcaeus rows). Run on Basecamp after the L source tarball is unpacked into $L/src:
#
#   sh /home/alvin/melos-l/src/deploy/release_l.sh lexica    # check the open-lexica supplement files in the data mount
#   sh /home/alvin/melos-l/src/deploy/release_l.sh stage     # corpus copy + correct five + import 232 + rebind manifest + verify
#   sh /home/alvin/melos-l/src/deploy/release_l.sh receipts  # import Morpheus receipts (absent keys only)
#   sh /home/alvin/melos-l/src/deploy/release_l.sh build     # melos-api:20261008l
#   sh /home/alvin/melos-l/src/deploy/release_l.sh canary    # melos-api-canary on 127.0.0.1:8792
#   sh /home/alvin/melos-l/src/deploy/release_l.sh promote   # stop+keep K3 as melos-api-before-l, start L on 8791
#   sh /home/alvin/melos-l/src/deploy/release_l.sh rollback  # stop L, restart the kept K3
#
# The supplement (docs/lexica-open-supplement.md, "Deploy") is copied into the live data
# directory (/home/alvin/services/melos/data, alvin-owned, mounted read-only); K3 code ignores it.
set -eu
cd /home/alvin/services/melos
L=/home/alvin/melos-l
SRC=$L/src
DATA=$L/data
LIVE_DATA=/home/alvin/services/melos/releases/campbell-20261007b/candidate-data
DATAMOUNT=/home/alvin/services/melos/data
BASE=melos-api:20261005-qa29
IMAGE=melos-api:20261008l
LIVE=melos-api
KEPT=melos-api-before-l
CANARY=melos-api-canary
SUPPLEMENT_SHA=aacdddbec624daae4acce18ca1f16c9c323fee89ff49be8aea5631f7f60db511
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
    -v $DATA/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $DATA/manifest.json:/app/data/embeddings/manifest.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    "$IMAGE" \
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
    --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
}

case "$step" in
  lexica)
    echo "$SUPPLEMENT_SHA  $DATAMOUNT/lexica/supplement-entries.jsonl" | sha256sum -c -
    python3 -c "import json,sys; a=json.load(open(sys.argv[1])); assert a['verdict']=='PASS' and a['sha256']==sys.argv[2], a.get('verdict'); print('audit PASS')" \
      "$DATAMOUNT/reports/audit-lexica-supplement.json" "$SUPPLEMENT_SHA"
    for f in lexica/supplement.manifest.json raw/lexica/lsj-logeion-6aa48692192d/download-manifest.json \
             raw/lexica/dodson-74f70358d4ac/dodson.xml \
             raw/perseus-lexica/hopper-2011-05-27/Classics/LSJ/opensource/ml.xml \
             raw/perseus-lexica/homerica-d71ed43cc912d3e053cbb0dd6341f798ea058378/cunliffe.lexentries.unicode.xml; do
      test -s "$DATAMOUNT/$f" || { echo "missing $f" >&2; exit 1; }
    done
    echo "lexica files present"
    ;;
  stage)
    test ! -e "$DATA/corpus.sqlite" || { echo "$DATA/corpus.sqlite exists; move it aside first" >&2; exit 1; }
    mkdir -p "$DATA"
    cp "$LIVE_DATA/corpus.sqlite" "$DATA/corpus.sqlite"
    cd "$SRC"
    python3 scripts/correct_campbell_five.py corpus --corpus "$DATA/corpus.sqlite" | tee "$DATA/correct-five-receipt.json"
    python3 scripts/import_campbell_glp.py --corpus "$DATA/corpus.sqlite" \
      --semantic-manifest "$LIVE_DATA/manifest.json" --semantic-output "$DATA/manifest.json" \
      --base-corpus "$LIVE_DATA/corpus.sqlite" | tee "$DATA/import-receipt.json"
    python3 scripts/verify_campbell_glp.py --corpus "$DATA/corpus.sqlite" --expected-passages 288821 \
      | tee "$DATA/verify-corpus.json"
    sha256sum "$DATA/corpus.sqlite" "$DATA/manifest.json"
    ;;
  receipts)
    test -f "$L/receipts-bundle.json"
    cd "$SRC" && python3 deploy/sync_morphology_receipts.py import /home/alvin/services/melos/runtime/machine_morphology.sqlite "$L/receipts-bundle.json" --apply
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
  promote)
    docker container inspect "$LIVE" >/dev/null
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "$KEPT"
    run_container "$LIVE" 8791
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  rollback)
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-l"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_l.sh lexica|stage|receipts|build|canary|promote|rollback" >&2; exit 1;;
esac
