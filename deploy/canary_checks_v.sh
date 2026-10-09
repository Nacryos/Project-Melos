#!/bin/sh
# Release V checks on Basecamp; usage: sh deploy/canary_checks_v.sh ORIGIN OUTDIR [samples]
# All of release U's checks (deploy/canary_checks_u.sh run from the V tree: smoke, Campbell identity, spans, both
# search sets, citations, word-click latency, release U items, endpoints, and with "samples" the sampler seeds and
# lyric gold), then: the same sampler runs compared with U's canary, the scanner and composer checks
# (scripts/check_release_v.py), and container memory before and after.
set -u
B=$1; OUT=$2; SAMPLES=${3:-}
SRC=${MELOS_V_SRC:-/home/alvin/melos-v/src}
U_CHECKS=${MELOS_V_BASELINE:-/home/alvin/melos-u/canary-checks}
mkdir -p "$OUT"
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" > "$OUT/memory-before.txt" 2>&1
MELOS_U_SRC=$SRC sh "$SRC/deploy/canary_checks_u.sh" "$B" "$OUT" $SAMPLES
cd "$SRC"
if [ -n "$SAMPLES" ]; then
  python3 scripts/compare_sample_runs.py "$U_CHECKS/sampleU-101.jsonl" "$OUT/sampleU-101.jsonl" --json "$OUT/compare-u-101.json" > "$OUT/compare-u-101.txt" 2>&1
  python3 scripts/compare_sample_runs.py "$U_CHECKS/sampleU-heldout.jsonl" "$OUT/sampleU-heldout.jsonl" --json "$OUT/compare-u-heldout.json" > "$OUT/compare-u-heldout.txt" 2>&1
  echo "compare with U done" >> "$OUT/progress"
fi
python3 scripts/check_release_v.py --base "$B" --out "$OUT/release-v.json" > "$OUT/release-v.txt" 2>&1; echo "release-v exit $?" >> "$OUT/progress"
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" > "$OUT/memory-after.txt" 2>&1
echo "v done $(date -u)" >> "$OUT/progress"
