# Release X (literal translation fallback + search rows): code layer atop the live W image.
# Build with --build-arg BASE_IMAGE=<the W image>; deploy/release_x.sh reads it from the live container.
# The corpus copy with the 59 appended translation rows and the rebuilt embedding directories are host mounts
# that canary/promote swap in place of W's (corpus.sqlite, /app/data/embeddings, /s-embeddings).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY backend /app/backend
COPY js /app/js
COPY css /app/css
COPY composer.html /app/composer.html
USER 1000:1000
