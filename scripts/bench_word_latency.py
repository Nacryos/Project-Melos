"""Release U: time single-word clicks (GET /api/word as the reader asks it) against an origin.

The reader asks /api/word?form=<printed>&passage_id=<id>&lemma=<headline headword> on a click (js/reader.js
wordLookup), after the batch headlines (POST /api/words/headlines) named the headword. This script samples
words of the given passages with a fixed seed, takes each word's headword from the batch headlines, and times
one request per word, one at a time. Standard library only.

    python3 scripts/bench_word_latency.py --base http://127.0.0.1:8792 --n 80 --seed 7 [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
import urllib.parse
import urllib.request

PASSAGES = ["campbell-glp:sappho:1", "campbell-glp:sappho:2", "campbell-glp:sappho:16", "campbell-glp:sappho:31",
            "campbell-glp:sappho:94", "campbell-glp:sappho:96", "campbell-glp:alcaeus:129", "campbell-glp:alcaeus:346",
            "campbell-glp:alcaeus:42", "campbell-glp:anacreon:348", "campbell-glp:alcman:1", "campbell-glp:ibycus:286"]


def request(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data, {"content-type": "application/json"} if data else {})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    return payload, (time.perf_counter() - t) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-lemma", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()
    words = []
    for pid in PASSAGES:
        try:
            batch, _ = request(args.base, "/api/words/headlines", {"passage_id": pid})
        except Exception:  # noqa: BLE001 - a passage missing from this origin is skipped
            continue
        for tok in batch.get("tokens", []):
            if tok.get("form"):
                words.append((pid, tok.get("printed") or tok["form"], tok.get("lemma") or ""))
    rng = random.Random(args.seed)
    sample = rng.sample(words, min(args.n, len(words)))
    # One untimed request first: a server that just started loads its dictionaries on the first lookup.
    request(args.base, "/api/word?" + urllib.parse.urlencode({"form": "καί", "passage_id": PASSAGES[0]}))
    times = []
    for pid, form, lemma in sample:
        q = {"form": form, "passage_id": pid}
        if lemma and not args.no_lemma:
            q["lemma"] = lemma
        try:
            _, ms = request(args.base, "/api/word?" + urllib.parse.urlencode(q))
        except Exception as exc:  # noqa: BLE001
            print("error", form, exc)
            continue
        times.append({"form": form, "passage_id": pid, "lemma": lemma, "ms": round(ms, 1)})
    ms = sorted(t["ms"] for t in times)
    q = statistics.quantiles(ms, n=10) if len(ms) >= 10 else ms
    summary = {"base": args.base, "n": len(ms), "median_ms": round(statistics.median(ms), 1),
               "p90_ms": round(q[8], 1) if len(ms) >= 10 else None, "max_ms": ms[-1] if ms else None,
               "slowest": sorted(times, key=lambda t: -t["ms"])[:8]}
    print(json.dumps(summary, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "times": times}, fh, ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
