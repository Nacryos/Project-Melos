#!/bin/sh
set -eu
cd /home/alvin/services/melos
test -f data/corpus.sqlite
test -f data/embeddings/manifest.json
test -f secrets/jev.env
test -d runtime
container=${MELOS_CONTAINER_NAME:-melos-api}
port=${MELOS_HOST_PORT:-8791}
image=${MELOS_IMAGE:-melos-api:20260930-qa1}
case "$container" in melos-api|melos-api-canary) ;; *) echo 'Unexpected container name' >&2; exit 1;; esac
case "$port" in 8791|8792) ;; *) echo 'Unexpected host port' >&2; exit 1;; esac
if docker container inspect "$container" >/dev/null 2>&1; then
  echo "$container already exists; explicitly review before replacing it." >&2
  exit 1
fi
docker run -d --name "$container" --restart unless-stopped \
  --cpus=2 --cpu-shares=256 --memory=8g --memory-swap=8g --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  --cap-drop=ALL --security-opt=no-new-privileges --user=1000:1000 \
  --log-driver=local --log-opt max-size=10m --log-opt max-file=3 \
  -p "127.0.0.1:$port:8791" \
  -e MELOS_PUBLIC_DEPLOYMENT=1 -e MELOS_PUBLICATION_POLICY=source-labels \
  -e MELOS_PUBLIC_CLASSIFIER=1 -e MELOS_CLASSIFIER_STATE=/app/runtime/classifier.sqlite \
  -e MELOS_JEV_MODEL=jev-1.13.0 -e MELOS_CLASSIFIER_DAILY_LIMIT=500 \
  -e MELOS_CORS_ORIGINS=https://greeklyric.com,https://project-melos.vercel.app \
  -v /home/alvin/services/melos/data:/app/data:ro \
  -v /home/alvin/services/melos/models:/models:ro \
  -v /home/alvin/services/melos/runtime:/app/runtime:rw \
  -v /home/alvin/services/melos/secrets/jev.env:/run/secrets/jev.env:ro \
  "$image" \
  python -m uvicorn backend.server:app --host 0.0.0.0 --port 8791 --workers 1 \
  --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log --env-file /run/secrets/jev.env
