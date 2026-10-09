# Release T (private mode): code-only patch atop the live image (S once S is live).
# Build with --build-arg BASE_IMAGE=<the live image>; deploy/release_t.sh reads it from the live container.
# Adds argon2-cffi (owner password hash check). Corpus, models, secrets and the private store stay mounts.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN pip install --no-cache-dir "argon2-cffi==23.1.0" && python -c "import argon2; argon2.PasswordHasher()"
COPY backend /app/backend
COPY js/reader.js /app/js/reader.js
COPY js/usage-space.js /app/js/usage-space.js
COPY js/machine-morphology.js /app/js/machine-morphology.js
COPY js/owner-loader.js /app/js/owner-loader.js
COPY js/owner.js /app/js/owner.js
COPY reader.html /app/reader.html
COPY owner.html /app/owner.html
COPY css/reader.css /app/css/reader.css
