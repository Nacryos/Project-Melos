#!/bin/sh
# Release GLP (prepared 2026-10-08, NOT yet deployed): every poem in Campbell's
# Greek Lyric Poetry on the live reader, plus public-domain comparison translations.
#
# Adds 232 passages (campbell-glp:*) to the live K3 corpus (288,589 -> 288,821) and
# corrects 11 lines of the five approved Alcaeus passages to the page images, and ships the
# re-anchored backend sidecars (commentary, comparisons, source-line English, editorial readings)
# plus backend/translation_comparisons_glp_data.json.
# Verification covers all 237 poems.
#
# Run on Basecamp after this branch's source tarball is unpacked into $G/src:
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh stage     # corpus copy + idempotent import + semantic rebind + verify
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh receipts  # import Morpheus receipts for corrected forms (absent keys only)
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh build     # image (Dockerfile.patch atop the QA29 base, like K)
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh canary    # melos-api-canary on 127.0.0.1:8792
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh promote   # keep live container stopped, start GLP on 8791
#   sh /home/alvin/melos-glp/src/deploy/release_glp.sh rollback
#
# Needs ~1.7 GB free on / for the corpus copy (Basecamp was at 98 % on 2026-10-07).
set -eu
cd /home/alvin/services/melos
G=/home/alvin/melos-glp
SRC=$G/src
DATA=$G/data
LIVE_DATA=/home/alvin/services/melos/releases/campbell-20261007b/candidate-data
BASE=melos-api:20261005-qa29
IMAGE=melos-api:20261008glp
LIVE=melos-api
KEPT=melos-api-before-glp
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
    -v $DATA/corpus.sqlite:/app/data/corpus.sqlite:ro \
    -v $DATA/manifest.json:/app/data/embeddings/manifest.json:ro \
    -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
    "$IMAGE" \
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
    --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
}

case "$step" in
  stage)
    test ! -e "$DATA/corpus.sqlite" || { echo "$DATA/corpus.sqlite exists; move it aside first" >&2; exit 1; }
    mkdir -p "$DATA"
    cp "$LIVE_DATA/corpus.sqlite" "$DATA/corpus.sqlite"
    cd "$SRC"
    # Correct the five approved Alcaeus rows to the page images (idempotent; refuses rows that are
    # neither the approved original nor the corrected text). Must run before the semantic rebind.
    python3 scripts/correct_campbell_five.py corpus --corpus "$DATA/corpus.sqlite" | tee "$DATA/correct-five-receipt.json"
    # Idempotent: rows already present must be identical; a re-run adds nothing.
    python3 scripts/import_campbell_glp.py --corpus "$DATA/corpus.sqlite" \
      --semantic-manifest "$LIVE_DATA/manifest.json" --semantic-output "$DATA/manifest.json" \
      --base-corpus "$LIVE_DATA/corpus.sqlite" | tee "$DATA/import-receipt.json"
    # Read-only diff of every stored passage against the verified transcription
    # (opening read-only keeps the mtime the semantic manifest is bound to).
    python3 scripts/verify_campbell_glp.py --corpus "$DATA/corpus.sqlite" --expected-passages 288821 \
      | tee "$DATA/verify-corpus.json"
    sha256sum "$DATA/corpus.sqlite" "$DATA/manifest.json"
    ;;
  receipts)
    # Morpheus receipts for the corrected Alcaeus forms (e.g. ὤς, τωνδέων, ἔγωγ’), exported from the
    # laptop cache with deploy/sync_morphology_receipts.py export; inserts absent keys only.
    test -f "$G/receipts-bundle.json"
    cd "$SRC" && python3 deploy/sync_morphology_receipts.py import /home/alvin/services/melos/runtime/machine_morphology.sqlite "$G/receipts-bundle.json" --apply
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
    docker stop "$LIVE" >/dev/null && docker rename "$LIVE" "melos-api-failed-glp"
    docker rename "$KEPT" "$LIVE" && docker start "$LIVE"
    sleep 8; curl -fsS http://127.0.0.1:8791/api/status | head -c 300; echo
    ;;
  *)
    echo "usage: release_glp.sh stage|receipts|build|canary|promote|rollback" >&2; exit 1;;
esac
