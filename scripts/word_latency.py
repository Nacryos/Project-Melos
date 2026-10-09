"""Time single-word lookups and passage headlines (release S check that search changes add no word latency).

  python3 scripts/word_latency.py --base http://127.0.0.1:8792 --out word-latency.json

For a fixed list of Campbell poems: GET /api/words/headlines?passage_id=… for each poem, then
GET /api/word?form=<word>&compact=true for the first words of each poem. Reports median and 90th percentile.
"""
import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request

POEMS = ["campbell-glp:sappho:1", "campbell-glp:sappho:16", "campbell-glp:sappho:31", "campbell-glp:alcaeus:346",
         "campbell-glp:anacreon:348", "campbell-glp:alcman:1", "campbell-glp:ibycus:286", "campbell-glp:archilochus:5"]


def get(base, path):
    started = time.time()
    with urllib.request.urlopen(urllib.request.Request(base + path, headers={"User-Agent": "melos-latency-check"}),
                                timeout=60) as r:
        body = r.read()
    return time.time() - started, body


def stats(xs):
    xs = sorted(xs)
    return {"n": len(xs), "median": round(statistics.median(xs), 3), "p90": round(xs[int(0.9 * (len(xs) - 1))], 3),
            "max": round(xs[-1], 3)} if xs else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--words", type=int, default=6)
    args = ap.parse_args()
    head, word, words = [], [], []
    for pid in POEMS:
        try:
            t, body = get(args.base, "/api/words/headlines?" + urllib.parse.urlencode({"passage_id": pid}))
        except Exception:  # noqa: BLE001 - a poem missing from the build is skipped
            continue
        head.append(t)
        rows = json.loads(body).get("tokens") or []
        words += [r.get("form") or r.get("text") for r in rows[: args.words] if (r.get("form") or r.get("text"))]
    for w in words:
        t, _ = get(args.base, "/api/word?" + urllib.parse.urlencode({"form": w, "compact": "true"}))
        word.append(t)
    out = {"base": args.base, "headlines": stats(head), "word": stats(word), "words": words}
    open(args.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("base", "headlines", "word")}))


if __name__ == "__main__":
    main()
