# Release V: code-only patch atop the live image (U). Adds backend/scansion (the scanner, its rules file and
# data) and backend/compose_routes.py; pyyaml is already in the base image (6.0.3).
# The lexical vowel-length database (data/scansion/quantities.sqlite, 125 MB) stays a read-only mount.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY backend /app/backend
