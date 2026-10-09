#!/bin/sh
# Release U development helper (Basecamp): run a Python script inside the live R image with the U dev
# tree's backend/scripts mounted and the R data mounts, without a server. Not a release step.
#   sh u_py.sh script.py [args...]      (script path relative to the dev tree, or absolute under $U)
set -eu
U=${MELOS_U_DIR:-/home/alvin/melos-u}
R=/home/alvin/melos-r
Q=/home/alvin/melos-q
O=/home/alvin/melos-o
IMAGE=${MELOS_U_BASE:-melos-api:20261009r2}
exec docker run --rm -i --network melos-morpheus --cpus=${U_CPUS:-4} --memory=12g --user=1000:1000 \
  -e MELOS_MORPHEUS_LOCAL=http://melos-morpheus:8080/api/v1/analysis/word -e MELOS_GENERATED_NORMALISATION=1 \
  -e MELOS_LEMMA_INDEX=/lemma/lemma_index.sqlite -e MELOS_CITATION_INDEX=/lemma/citation_index.sqlite \
  -e MELOS_NGRAM_INDEX=${U_NGRAMS:-/lemma/ngrams.sqlite} -e MELOS_LEMMA_CALIBRATION=/lemma/lemma_calibration.json \
  -e MELOS_ATTRIBUTIONS=/p-metadata/attributions.json -e MELOS_GENRE_SOURCES=/p-metadata/genre_sources.json \
  -e MELOS_SYNTAX_MODEL_PATH=/syntax-model -e MELOS_EDITION_GROUPS=${U_GROUPS:-/u-data/edition_groups.sqlite} \
  -v /home/alvin/services/melos/models:/models:ro \
  -v /home/alvin/services/melos/releases/qa29/model/pipeline:/syntax-model:ro \
  -v /home/alvin/services/melos/data:/app/data:ro \
  -v $O/data/corpus.sqlite:/app/data/corpus.sqlite:ro -v $O/data/embeddings:/app/data/embeddings:ro \
  -v $R/data/lemma_index.sqlite:/lemma/lemma_index.sqlite:ro \
  -v $Q/data/citation_index.sqlite:/lemma/citation_index.sqlite:ro \
  -v $R/data/ngrams.sqlite:/lemma/ngrams.sqlite:ro \
  -v $R/data/lemma_calibration.json:/lemma/lemma_calibration.json:ro \
  -v $Q/data/metadata/chronology.json:/app/data/metadata/chronology.json:ro -v $Q/data/metadata:/p-metadata:ro \
  -v $U/src/backend:/app/backend:ro -v $U/src/scripts:/app/scripts:ro -v $U/src/data/evaluation:/u-eval:ro \
  -v $U/data:/u-data:rw -v $U/work:/u-work:rw \
  -w /app "$IMAGE" python "$@"
