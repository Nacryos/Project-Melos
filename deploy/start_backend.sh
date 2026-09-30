#!/bin/sh
set -eu
cd /home/alvin/services/melos
test -f data/corpus.sqlite
test -f data/embeddings/manifest.json
if docker container inspect melos-api >/dev/null 2>&1; then
  echo 'melos-api already exists; explicitly review before replacing it.' >&2
  exit 1
fi
docker run -d --name melos-api --restart unless-stopped \
  --cpus=2 --cpu-shares=256 --memory=8g --memory-swap=8g --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  --cap-drop=ALL --security-opt=no-new-privileges --user=1000:1000 \
  --log-driver=local --log-opt max-size=10m --log-opt max-file=3 \
  -p 127.0.0.1:8791:8791 \
  -e MELOS_PUBLIC_DEPLOYMENT=1 -e MELOS_PUBLICATION_POLICY=source-labels \
  -e MELOS_CORS_ORIGINS=https://greeklyric.com,https://project-melos.vercel.app \
  -v /home/alvin/services/melos/data:/app/data:ro \
  -v /home/alvin/services/melos/models:/models:ro \
  melos-api:20260930
