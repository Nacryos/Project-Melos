#!/bin/sh
# Release U checks on Basecamp; usage: sh deploy/canary_checks_u.sh ORIGIN OUTDIR [samples]
# (canary: http://127.0.0.1:8792; production: https://greeklyric.com). Release R's checks (smoke, the 237-poem
# Campbell identity check, the span check, the search evaluation, citations, endpoints) plus: single-word click
# latency (scripts/bench_word_latency.py, seeds 7/11/13 after one warm-up request), draft analysis
# (/api/analyze-text on the exercise stanza, cold then warm), dialect spellings, fragment counts (Sappho's
# σελήνη / πόθος / μόνος), forms-mode headline rules, and with "samples" the sampler seeds compared with R's and
# the lyric gold dump and score. The search evaluation uses release S's 120-query set when it is in the tree.
set -u
B=$1; OUT=$2; SAMPLES=${3:-}
SRC=${MELOS_U_SRC:-/home/alvin/melos-u/src}
BASE_CHECKS=${MELOS_U_BASELINE:-/home/alvin/melos-s/canary-checks}
mkdir -p "$OUT"; cd "$SRC"
echo "start $(date -u)" > "$OUT/progress"
python3 deploy/smoke_backend.py --origin "$B" --expected-passages 288821 > "$OUT/smoke.txt" 2>&1; echo "smoke exit $?" >> "$OUT/progress"
python3 scripts/verify_campbell_glp.py --origin "$B" --expected-passages 288821 --analyze sample > "$OUT/verify.json" 2> "$OUT/verify.err"; echo "verify exit $?" >> "$OUT/progress"
python3 scripts/check_span_parses.py --base "$B" --random 30 > "$OUT/span.txt" 2>&1; echo "span exit $?" >> "$OUT/progress"
if [ -f data/evaluation/search-eval-s.json ]; then
  python3 scripts/search_eval.py run --base "$B" --out "$OUT/search-eval.json" --counts data/evaluation/search-eval-s-counts.json > "$OUT/search-eval.txt" 2>&1
else
  python3 scripts/search_eval.py run --base "$B" --out "$OUT/search-eval.json" --counts data/evaluation/search-eval-o-counts.json > "$OUT/search-eval.txt" 2>&1
fi
echo "search-eval exit $?" >> "$OUT/progress"
python3 scripts/eval_citations.py --base "$B" --out "$OUT/cite-eval.json" > "$OUT/cite-eval.txt" 2>&1; echo "cite-eval exit $?" >> "$OUT/progress"
for s in 7 11 13; do
  python3 scripts/bench_word_latency.py --base "$B" --n 80 --seed $s --json "$OUT/word-latency-$s.json" >> "$OUT/word-latency.txt" 2>&1
done
[ -f scripts/word_latency.py ] && python3 scripts/word_latency.py --base "$B" --out "$OUT/word-latency-s-method.json" > "$OUT/word-latency-s-method.txt" 2>&1
echo "word latency done" >> "$OUT/progress"
python3 scripts/check_release_u.py --base "$B" --out "$OUT/release-u.json" > "$OUT/release-u.txt" 2>&1; echo "release-u exit $?" >> "$OUT/progress"
for u in "/api/lemma/status" "/api/cite?q=Il.%201.5" "/api/cite?q=Sappho%20fr.%2031" \
         "/api/search?q=moon%20over%20the%20sea&mode=hybrid&author=Sappho" \
         "/api/lemma/frequency?q=%CF%83%CE%B5%CE%BB%CE%AE%CE%BD%CE%B7" \
         "/api/lemma/concordance?q=%CF%80%CF%8C%CE%B8%CE%BF%CF%82&author=Sappho" \
         "/api/lemma/collocations?q=%E1%BC%94%CF%81%CF%89%CF%82" "/api/lemma/ngrams?kind=author&name=Sappho&n=2" \
         "/api/lemma/proximity?q=%E1%BC%94%CF%81%CF%89%CF%82%20%CE%B4%CE%BF%CE%BD%CE%AD%CF%89&window=6&author=Sappho" \
         "/api/concept/diachrony?q=longing" "/api/concept/diachrony?q=longing&author=Sappho" \
         "/api/lemma/variants?q=%E1%BC%94%CF%81%CF%89%CF%82" "/api/words/headlines?passage_id=campbell-glp:sappho:1" \
         "/api/word?form=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&lemma=%CF%86%CE%B1%CE%AF%CE%BD%CF%89&compact=true"; do
  curl -s -o /dev/null -w "%{http_code} %{time_total}s %{size_download}B $u\n" "$B$u" >> "$OUT/endpoints.txt"
done
echo "endpoints done" >> "$OUT/progress"
if [ -n "$SAMPLES" ]; then
  python3 scripts/sample_glp_quality.py --base "$B" --seed 101 --spans 120 --out "$OUT/sampleU-101.jsonl" > "$OUT/sampleU-101.out" 2>&1
  python3 scripts/sample_glp_quality.py --base "$B" --seed 20261008 --spans 150 --no-print --out "$OUT/sampleU-heldout.jsonl" > "$OUT/sampleU-heldout.out" 2>&1
  python3 scripts/compare_sample_runs.py "$BASE_CHECKS/sampleS-101.jsonl" "$OUT/sampleU-101.jsonl" --json "$OUT/compare-101.json" > "$OUT/compare-101.txt" 2>&1
  python3 scripts/compare_sample_runs.py "$BASE_CHECKS/sampleS-heldout.jsonl" "$OUT/sampleU-heldout.jsonl" --json "$OUT/compare-heldout.json" > "$OUT/compare-heldout.txt" 2>&1
  python3 scripts/eval_lyric_gold.py dump --base "$B" --out "$OUT/lyric-dump.json" > "$OUT/lyric-dump.out" 2>&1
  python3 scripts/eval_lyric_gold.py score --gold data/evaluation/lyric-gold-r.json --dump "$OUT/lyric-dump.json" --json "$OUT/lyric-score.json" > "$OUT/lyric-score.txt" 2>&1
  echo "samples done" >> "$OUT/progress"
fi
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" >> "$OUT/progress" 2>&1
echo "done $(date -u)" >> "$OUT/progress"
