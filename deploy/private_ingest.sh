#!/bin/sh
# Owner private corpus ingestion on the box (release T). The container has no network.
#   sh private_ingest.sh build    # image melos-private-ingest:20261009t (poppler, tesseract grc+eng, pypdf, betacode)
#   sh private_ingest.sh ingest   # everything in $PRIV/inbox with a <file>.json provenance manifest
#   sh private_ingest.sh link     # passage links against the public corpus (re-run after each ingest)
#   sh private_ingest.sh status
# The API reads $PRIV/store/private.sqlite read-only; new material appears without a restart.
set -eu
SRC=${MELOS_T_SRC:-/home/alvin/melos-t/src}
PRIV=${MELOS_PRIVATE_ROOT:-/home/alvin/melos-private}
ORIG=${MELOS_PRIVATE_ORIGINALS:-/home/alvin/storagebox/melos-private/originals}
CORPUS=${MELOS_PUBLIC_CORPUS:-/home/alvin/melos-o/data/corpus.sqlite}
IMG=melos-private-ingest:20261009t
mkdir -p "$PRIV/inbox" "$PRIV/store" "$ORIG"
chmod 700 "$PRIV"

run() {
  docker run --rm --network none --read-only --tmpfs /tmp:rw,size=2g --cap-drop=ALL \
    --security-opt=no-new-privileges --user="$(id -u):$(id -g)" \
    -v "$SRC:/src:ro" -v "$PRIV:/private:rw" -v "$ORIG:/originals:rw" "$@"
}

case "${1:-}" in
  build)  docker build -q -t "$IMG" -f "$SRC/deploy/Dockerfile.private-ingest" "$SRC/deploy" ;;
  ingest) run "$IMG" python /src/scripts/private_ingest.py ingest --root /private --originals /originals ;;
  link)   run -v "$CORPUS:/corpus.sqlite:ro" "$IMG" python /src/scripts/private_ingest.py link --root /private --corpus /corpus.sqlite ;;
  status) run "$IMG" python /src/scripts/private_ingest.py status --root /private ;;
  *) echo "usage: private_ingest.sh build|ingest|link|status" >&2; exit 1 ;;
esac
