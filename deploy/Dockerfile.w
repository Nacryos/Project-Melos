# Release W (owner-only composer, W0 + the melos-api half of W1/W2): code layer atop the V image.
# Build with --build-arg BASE_IMAGE=<the V image>; deploy/release_w.sh reads it from the live container.
# Adds httpx (streaming proxy to the composer agent service) and the composer page, which the API now serves
# to the signed-in owner only (/composer). composer.sqlite lives in the runtime mount; the agent token is a
# read-only secrets mount. Corpus, indexes, models, secrets and the private store stay mounts.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN pip install --no-cache-dir "httpx==0.28.1" && python -c "import httpx"
COPY backend /app/backend
COPY js /app/js
COPY css /app/css
COPY composer.html /app/composer.html
USER 1000:1000
