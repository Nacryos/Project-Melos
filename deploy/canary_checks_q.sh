#!/bin/sh
# Release Q checks on Basecamp; usage: sh deploy/canary_checks_q.sh ORIGIN OUTDIR [samples]
# (canary: http://127.0.0.1:8792; production: https://greeklyric.com). "samples" also runs the
# sample_glp_quality seeds (101 development, 20261008 held out) and compares them with release P's.
set -u
B=$1; OUT=$2; SAMPLES=${3:-}
SRC=${MELOS_Q_SRC:-/home/alvin/melos-q/src}
P=/home/alvin/melos-p
mkdir -p "$OUT"; cd "$SRC"
echo "start $(date -u)" > "$OUT/progress"
python3 deploy/smoke_backend.py --origin "$B" --expected-passages 288821 > "$OUT/smoke.txt" 2>&1; echo "smoke exit $?" >> "$OUT/progress"
python3 scripts/verify_campbell_glp.py --origin "$B" --expected-passages 288821 --analyze sample > "$OUT/verify.json" 2> "$OUT/verify.err"; echo "verify exit $?" >> "$OUT/progress"
python3 scripts/check_span_parses.py --base "$B" --random 30 > "$OUT/span.txt" 2>&1; echo "span exit $?" >> "$OUT/progress"
python3 scripts/search_eval.py run --base "$B" --out "$OUT/search-eval.json" --counts data/evaluation/search-eval-o-counts.json > "$OUT/search-eval.txt" 2>&1; echo "search-eval exit $?" >> "$OUT/progress"
python3 scripts/eval_citations.py --base "$B" --out "$OUT/cite-eval.json" > "$OUT/cite-eval.txt" 2>&1; echo "cite-eval exit $?" >> "$OUT/progress"
for u in "/api/lemma/status" "/api/cite/status" "/api/cite?q=Il.%201.1" "/api/cite?q=Sappho%20fr.%2031" "/api/cite?q=Sappho%20fr.%2031%20V" "/api/cite?q=Alc.%20346%20L-P" "/api/cite?q=Sappho%20Campbell%2016" \
         "/api/search?q=Pind.%20O.%201.1&mode=hybrid" "/api/lemma/frequency?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7" \
         "/api/lemma/concordance?q=%E1%BC%94%CF%81%CF%89%CF%82&limit=20" "/api/lemma/collocations?q=%E1%BC%94%CF%81%CF%89%CF%82" \
         "/api/lemma/proximity?q=%E1%BF%A5%CE%BF%CE%B4%CE%BF%CE%B4%CE%AC%CE%BA%CF%84%CF%85%CE%BB%CE%BF%CF%82%20%E1%BC%A8%CF%8E%CF%82" \
         "/api/lemma/proximity?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7%20%E1%BC%80%CF%83%CF%84%CE%AE%CF%81&window=8&cross_passages=true" \
         "/api/lemma/ngrams?kind=author&name=Homer&n=3" "/api/lemma/variants?q=%E1%BC%94%CF%81%CF%89%CF%82" \
         "/api/concept/diachrony?q=moon" "/api/concept/diachrony?q=eros" "/api/words/headlines?passage_id=campbell-glp:anacreon:348" \
         "/api/words/headlines?passage_id=campbell-glp:anacreon:348&dictionary=true" \
         "/api/word?form=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&lemma=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&compact=true"; do
  curl -s -o /dev/null -w "%{http_code} %{time_total}s %{size_download}B $u\n" "$B$u" >> "$OUT/endpoints.txt"
done
echo "endpoints done" >> "$OUT/progress"
if [ -n "$SAMPLES" ]; then
  python3 scripts/sample_glp_quality.py --base "$B" --seed 101 --spans 120 --out "$OUT/sampleQ-101.jsonl" > "$OUT/sampleQ-101.out" 2>&1
  python3 scripts/sample_glp_quality.py --base "$B" --seed 20261008 --spans 150 --no-print --out "$OUT/sampleQ-heldout.jsonl" > "$OUT/sampleQ-heldout.out" 2>&1
  python3 scripts/compare_sample_runs.py "$P/canary-checks/sampleP-101.jsonl" "$OUT/sampleQ-101.jsonl" --json "$OUT/compare-101.json" > "$OUT/compare-101.txt" 2>&1
  python3 scripts/compare_sample_runs.py "$P/canary-checks/sampleP-heldout.jsonl" "$OUT/sampleQ-heldout.jsonl" --json "$OUT/compare-heldout.json" > "$OUT/compare-heldout.txt" 2>&1
  echo "samples done" >> "$OUT/progress"
fi
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" >> "$OUT/progress" 2>&1
echo "done $(date -u)" >> "$OUT/progress"
