# Local Morpheus for Project Melos (release N).
#
# Engine:   alpheios-project/morpheus @ MORPHEUS_COMMIT, built with the repository's own
#           CI recipe (.github/workflows/main.yml: CFLAGS='-std=gnu89 -fcommon' make && make
#           install, no `make clean`), and its CI-built Greek stem library dist/stemlib.
#           Licence: Perseus/Tufts, CC BY-SA 3.0 US (repository LICENSE).
# Envelope: alpheios-project/morphsvc @ MORPHSVC_COMMIT (GPL-3.0): its MorpheusLocalEngine,
#           Betacode XSLT transformers, OA wrapper and xmljson "legacy" serialiser are used
#           unmodified, so the JSON has the same shape as morph.alpheios.net.
# Server:   deploy/morpheus-local/server.py (stdlib HTTP, GET /api/v1/analysis/word).
#
#   docker build -t melos-morpheus:2f1a30d deploy/morpheus-local
ARG UBUNTU=ubuntu@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401
ARG PYTHON=python@sha256:a02e9c5406c416c504d6c9a1a306ff4080c3173f1008d192f953bd20382a2d5c

FROM ${UBUNTU} AS build
ARG MORPHEUS_COMMIT=2f1a30d65ed7ae9c6120dbf64d730b863be412e4
ARG MORPHSVC_COMMIT=264ad78feae7efcb23255736f7ed624f673db1e4
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends build-essential flex-old git ca-certificates >/dev/null
WORKDIR /src
RUN git clone -q https://github.com/alpheios-project/morpheus morpheus \
 && git -C morpheus checkout -q "$MORPHEUS_COMMIT" \
 && git clone -q https://github.com/alpheios-project/morphsvc morphsvc \
 && git -C morphsvc checkout -q "$MORPHSVC_COMMIT"
# Upstream CI recipe verbatim. A clean rebuild of this commit does not compile (GROUP_NAME,
# MEDIEV, APO_TO_APU, LACONIAN are not defined in its headers); the CI links the object files
# committed with the source, so this binary is what the repository's own workflow produces.
RUN cd morpheus/src && CFLAGS='-std=gnu89 -fcommon' make >/dev/null 2>&1 && make install >/dev/null \
 && test -x /src/morpheus/bin/morpheus

FROM ${PYTHON}
ARG MORPHEUS_COMMIT=2f1a30d65ed7ae9c6120dbf64d730b863be412e4
ARG MORPHSVC_COMMIT=264ad78feae7efcb23255736f7ed624f673db1e4
RUN pip install --no-cache-dir -q lxml==5.3.0 requests==2.32.3
COPY --from=build /src/morpheus/bin/morpheus /opt/morpheus/bin/morpheus
COPY --from=build /src/morpheus/dist/stemlib /opt/morpheus/stemlib
COPY --from=build /src/morpheus/LICENSE /opt/morpheus/LICENSE
COPY --from=build /src/morphsvc/morphsvc /opt/morphsvc/morphsvc
COPY --from=build /src/morphsvc/LICENSE /opt/morphsvc/LICENSE
COPY server.py /opt/server.py
ENV MORPHEUS_COMMIT=${MORPHEUS_COMMIT} MORPHSVC_COMMIT=${MORPHSVC_COMMIT} PYTHONPATH=/opt/morphsvc \
    MORPHEUS_BIN=/opt/morpheus/bin/morpheus MORPHEUS_STEMLIB=/opt/morpheus/stemlib
USER 1000:1000
EXPOSE 8080
CMD ["python", "/opt/server.py"]
