"""Check that every word in arbitrary multi-word selections gets a full parse.

For each Campbell assignment poem: every printed line, plus N random spans of
2–5 consecutive words, are sent to /api/analyze-passage. Each word row of the
interlinear breakdown must either carry complete parse fields (same policy as
scripts/audit_alcaeus_occurrences.py feature_coverage) or be labelled a damaged
piece / editorial fragment. Reports failures with the span they occurred in.

  python scripts/check_span_parses.py --base https://greeklyric.com --random 40
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.passage_analysis import tokenize_span  # noqa: E402
from scripts.audit_alcaeus_occurrences import feature_coverage  # noqa: E402

IDS = [f"campbell-glp:alcaeus:{n}" for n in ("34a", "129", "130b", "326", "350")]


def analyze(base, pid, text, start, end):
    body = {"passage_id": pid, "start": start, "end": end, "offset_unit": "codepoint",
            "selected_text": text[start:end], "rerank": False, "fetch_machine": False}
    req = urllib.request.Request(base + "/api/analyze-passage", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="https://greeklyric.com")
    parser.add_argument("--random", type=int, default=40, help="random spans per poem")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    checked = failures = spans = 0
    for pid in IDS:
        text = json.load(urllib.request.urlopen(args.base + "/api/passage?id=" + urllib.parse.quote(pid)))["text"]
        words = [t for t in tokenize_span(text, 0, len(text)) if t["kind"] == "word"]
        selections, offset = [], 0
        for line in text.split("\n"):
            if line.strip():
                selections.append((offset, offset + len(line)))
            offset += len(line) + 1
        for _ in range(args.random):
            size = rng.randint(2, 5)
            first = rng.randrange(0, max(1, len(words) - size))
            selections.append((words[first]["start"], words[min(len(words), first + size) - 1]["end"]))
        for start, end in selections:
            spans += 1
            try:
                result = analyze(args.base, pid, text, start, end)
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:200].decode("utf-8", "replace")
                has_words = any(t["kind"] == "word" for t in tokenize_span(text, start, end))
                if exc.code == 422 and not has_words:
                    continue  # a line of lacuna dots only: nothing to parse
                failures += 1
                print(f"FAIL {pid.split(':')[-1]} [{start}:{end}] {text[start:end]!r} HTTP {exc.code} {detail}")
                continue
            for row in result["interlinear"]["readings"][0]["tokens"]:
                if row.get("kind") != "word":
                    continue
                if row.get("damaged_piece") or row.get("status") == "partial_word" or row.get("selection_basis") == "partial_word":
                    continue
                checked += 1
                coverage = feature_coverage(row.get("features") or {})
                if coverage["status"] != "complete_fields":
                    failures += 1
                    print(f"FAIL {pid.split(':')[-1]} [{start}:{end}] {text[start:end]!r} -> {row['text']!r} "
                          f"{row.get('parse_short')!r} {row.get('selection_basis')} {coverage['status']} {coverage.get('missing')}")
    print(json.dumps({"spans": spans, "word_rows_checked": checked, "failures": failures}))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
