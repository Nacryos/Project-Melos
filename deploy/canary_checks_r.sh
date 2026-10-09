#!/bin/sh
# Release R checks on Basecamp; usage: sh deploy/canary_checks_r.sh ORIGIN OUTDIR [samples]
# (canary: http://127.0.0.1:8792; production: https://greeklyric.com). "samples" also runs the
# sample_glp_quality seeds (101 development, 20261008 held out), compares them with release Q's, and
# dumps and scores the lyric gold poems (scripts/eval_lyric_gold.py).
set -u
B=$1; OUT=$2; SAMPLES=${3:-}
SRC=${MELOS_R_SRC:-/home/alvin/melos-r/src}
Q=/home/alvin/melos-q
mkdir -p "$OUT"; cd "$SRC"
echo "start $(date -u)" > "$OUT/progress"
python3 deploy/smoke_backend.py --origin "$B" --expected-passages 288821 > "$OUT/smoke.txt" 2>&1; echo "smoke exit $?" >> "$OUT/progress"
python3 scripts/verify_campbell_glp.py --origin "$B" --expected-passages 288821 --analyze sample > "$OUT/verify.json" 2> "$OUT/verify.err"; echo "verify exit $?" >> "$OUT/progress"
python3 scripts/check_span_parses.py --base "$B" --random 30 > "$OUT/span.txt" 2>&1; echo "span exit $?" >> "$OUT/progress"
python3 scripts/search_eval.py run --base "$B" --out "$OUT/search-eval.json" --counts data/evaluation/search-eval-o-counts.json > "$OUT/search-eval.txt" 2>&1; echo "search-eval exit $?" >> "$OUT/progress"
python3 scripts/eval_citations.py --base "$B" --out "$OUT/cite-eval.json" > "$OUT/cite-eval.txt" 2>&1; echo "cite-eval exit $?" >> "$OUT/progress"
for u in "/api/lemma/status" "/api/cite/status" "/api/cite?q=Il.%201.1" "/api/cite?q=Sappho%20fr.%2031" "/api/cite?q=Alc.%20346%20L-P" \
         "/api/search?q=Pind.%20O.%201.1&mode=hybrid" "/api/lemma/frequency?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7" \
         "/api/lemma/concordance?q=%E1%BC%94%CF%81%CF%89%CF%82&limit=20" "/api/lemma/collocations?q=%E1%BC%94%CF%81%CF%89%CF%82" \
         "/api/lemma/proximity?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7%20%E1%BC%80%CF%83%CF%84%CE%AE%CF%81&window=8&cross_passages=true" \
         "/api/lemma/ngrams?kind=author&name=Homer&n=3" "/api/lemma/variants?q=%CE%B3%CE%B1%E1%BF%96%CE%B1" \
         "/api/lemma/resolve?q=%CF%84%CE%B1%CF%87%CE%AD%CF%89%CF%82" \
         "/api/concept/diachrony?q=moon" "/api/words/headlines?passage_id=campbell-glp:sappho:1" \
         "/api/words/headlines?passage_id=campbell-glp:anacreon:348&dictionary=true" \
         "/api/word?form=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&lemma=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&compact=true"; do
  curl -s -o /dev/null -w "%{http_code} %{time_total}s %{size_download}B $u\n" "$B$u" >> "$OUT/endpoints.txt"
done
echo "endpoints done" >> "$OUT/progress"
if [ -n "$SAMPLES" ]; then
  python3 scripts/sample_glp_quality.py --base "$B" --seed 101 --spans 120 --out "$OUT/sampleR-101.jsonl" > "$OUT/sampleR-101.out" 2>&1
  python3 scripts/sample_glp_quality.py --base "$B" --seed 20261008 --spans 150 --no-print --out "$OUT/sampleR-heldout.jsonl" > "$OUT/sampleR-heldout.out" 2>&1
  python3 scripts/compare_sample_runs.py "$Q/canary-checks/sampleQ-101.jsonl" "$OUT/sampleR-101.jsonl" --json "$OUT/compare-101.json" > "$OUT/compare-101.txt" 2>&1
  python3 scripts/compare_sample_runs.py "$Q/canary-checks/sampleQ-heldout.jsonl" "$OUT/sampleR-heldout.jsonl" --json "$OUT/compare-heldout.json" > "$OUT/compare-heldout.txt" 2>&1
  python3 scripts/eval_lyric_gold.py dump --base "$B" --out "$OUT/lyric-dump.json" > "$OUT/lyric-dump.out" 2>&1
  python3 scripts/eval_lyric_gold.py score --gold data/evaluation/lyric-gold-r.json --dump "$OUT/lyric-dump.json" --json "$OUT/lyric-score.json" > "$OUT/lyric-score.txt" 2>&1
  echo "samples done" >> "$OUT/progress"
fi
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" >> "$OUT/progress" 2>&1
echo "done $(date -u)" >> "$OUT/progress"
