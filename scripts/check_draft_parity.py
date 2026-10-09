"""Release U: does POST /api/analyze-text read typed Greek as the reader reads the stored passage?

For lines of the lyric gold poems this runs, in-process, (a) the stored-passage analysis of the line
(/api/analyze-passage on its span), (b) the draft analysis of the same text with the poem's author as the
hint, with full word lookups, and (c) the same with the lean lookups the endpoint uses. It compares, word by
word, the displayed headword, parse and short gloss (backend.draft_analysis.headline, the reader's rule) and
times (c). Run inside the API image (it imports backend.server):

    python scripts/check_draft_parity.py --lines 60 --seed 3 [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POEMS = ["campbell-glp:sappho:1", "campbell-glp:sappho:16", "campbell-glp:sappho:31", "campbell-glp:sappho:34",
         "campbell-glp:sappho:44", "campbell-glp:sappho:94", "campbell-glp:sappho:96", "campbell-glp:alcaeus:34a",
         "campbell-glp:alcaeus:129", "campbell-glp:alcaeus:130b", "campbell-glp:alcaeus:326", "campbell-glp:alcaeus:350",
         "campbell-glp:alcaeus:346", "campbell-glp:alcaeus:347"]


def service_of(server):
    for route in server.app.routes:
        if getattr(route, "path", "") == "/api/analyze-text":
            for cell in route.endpoint.__closure__ or ():
                if cell.cell_contents.__class__.__name__ == "PassageAnalysisService":
                    return cell.cell_contents
    raise SystemExit("analysis service not found")


def shown(result):
    from backend.draft_analysis import headline
    rows = [r for r in (result.get("interlinear") or {}).get("readings", [{}])[0].get("tokens", []) if r.get("kind") == "word"]
    out = []
    for row in rows:
        lemma, _, parse = headline(row)
        gloss = row.get("gloss") or {}
        out.append((row.get("text"), lemma or "", parse or "", gloss.get("short_text") or gloss.get("text") or ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=60)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--json")
    args = ap.parse_args()
    from backend import server
    from backend.draft_analysis import draft_passage, attach_headlines
    service = service_of(server)
    lines = []
    for pid in POEMS:
        passage = server.passage(pid)
        text, pos = passage["text"], 0
        for line in text.split("\n"):
            s, e = pos, pos + len(line)
            pos = e + 1
            if len(line.split()) >= 3 and not any(c in line for c in "[]⟦⟧…"):
                lines.append((pid, passage.get("author"), s, e, line))
    rng = random.Random(args.seed)
    sample = rng.sample(lines, min(args.lines, len(lines)))
    words = {"stored_vs_full": [0, 0], "full_vs_lean": [0, 0], "stored_vs_lean": [0, 0]}
    fields = {"lemma": [0, 0], "parse": [0, 0], "gloss": [0, 0]}
    diffs, times = [], []
    for pid, author, s, e, line in sample:
        stored = service.analyze({"version": 1, "passage_id": pid, "start": s, "end": e, "offset_unit": "codepoint",
                                  "selected_text": line, "rerank": False, "fetch_machine": False})
        results = {}
        for lean in (False, True):
            passage, internal = draft_passage({"text": line, "author": author})
            passage["lean"] = lean
            t = time.perf_counter()
            result = service._analyze(internal, visitor_id=None, ranker_visitor_id=None, draft=passage)
            attach_headlines(result, {**passage, "detail": "full"})
            if lean:
                times.append((time.perf_counter() - t) * 1000)
            results[lean] = shown(result)
        a, b, c = shown(stored), results[False], results[True]
        for name, x, y in (("stored_vs_full", a, b), ("full_vs_lean", b, c), ("stored_vs_lean", a, c)):
            for u, v in zip(x, y):
                words[name][1] += 1
                words[name][0] += int(u[1:] == v[1:])
                if name == "stored_vs_lean" and u[1:] != v[1:]:
                    diffs.append({"passage": pid, "word": u[0], "stored": u[1:], "draft": v[1:]})
        for u, v in zip(a, c):
            for i, f in enumerate(("lemma", "parse", "gloss"), 1):
                fields[f][1] += 1
                fields[f][0] += int(u[i] == v[i])
    report = {"lines": len(sample), "seed": args.seed,
              "word_agreement": {k: {"same": v[0], "words": v[1], "rate": round(v[0] / v[1], 4) if v[1] else None}
                                 for k, v in words.items()},
              "stored_vs_lean_by_field": {k: round(v[0] / v[1], 4) if v[1] else None for k, v in fields.items()},
              "lean_draft_ms": {"median": round(statistics.median(times)), "max": round(max(times))},
              "differences": diffs[:40]}
    print(json.dumps({k: v for k, v in report.items() if k != "differences"}, ensure_ascii=False))
    for d in diffs[:25]:
        print(json.dumps(d, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
