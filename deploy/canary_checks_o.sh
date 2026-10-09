#!/bin/sh
# Release O checks on Basecamp; usage: sh deploy/canary_checks_o.sh ORIGIN OUTDIR
# (canary: http://127.0.0.1:8792; production: https://greeklyric.com)
set -u
B=$1; OUT=$2
SRC=${MELOS_O_SRC:-/home/alvin/melos-o/src}
mkdir -p "$OUT"; cd "$SRC"
echo "start $(date -u)" > "$OUT/progress"
python3 deploy/smoke_backend.py --origin "$B" --expected-passages 288821 > "$OUT/smoke.txt" 2>&1; echo "smoke exit $?" >> "$OUT/progress"
python3 scripts/verify_campbell_glp.py --origin "$B" --expected-passages 288821 --analyze sample > "$OUT/verify.json" 2> "$OUT/verify.err"; echo "verify exit $?" >> "$OUT/progress"
python3 scripts/check_span_parses.py --base "$B" --random 30 > "$OUT/span.txt" 2>&1; echo "span exit $?" >> "$OUT/progress"
python3 scripts/search_eval.py run --base "$B" --out "$OUT/search-eval.json" --counts data/evaluation/search-eval-o-counts.json > "$OUT/search-eval.txt" 2>&1; echo "search-eval exit $?" >> "$OUT/progress"
for u in "/api/lemma/status" "/api/lemma/frequency?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7" \
         "/api/lemma/concordance?q=%E1%BC%94%CF%81%CF%89%CF%82&limit=20" "/api/lemma/collocations?q=%E1%BC%94%CF%81%CF%89%CF%82" \
         "/api/lemma/proximity?q=%E1%BF%A5%CE%BF%CE%B4%CE%BF%CE%B4%CE%AC%CE%BA%CF%84%CF%85%CE%BB%CE%BF%CF%82%20%E1%BC%A8%CF%8E%CF%82" \
         "/api/concept/diachrony?q=moon" "/api/concept/diachrony?q=eros" "/api/words/headlines?passage_id=campbell-glp:anacreon:348"; do
  curl -s -o /dev/null -w "%{http_code} %{time_total}s $u\n" "$B$u" >> "$OUT/endpoints.txt"
done
echo "endpoints done" >> "$OUT/progress"
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" >> "$OUT/progress" 2>&1
echo "done $(date -u)" >> "$OUT/progress"
