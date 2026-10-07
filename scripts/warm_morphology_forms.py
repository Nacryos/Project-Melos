"""Fetch and cache Morpheus analyses for every word of the given passages.

Each printed word of each passage is tokenised exactly as the reader does
(backend.passage_analysis.tokenize_span), its editor's reading is sent to the
hosted Alpheios Morpheus service through the ordinary MachineMorphologyService,
and the signed receipt lands in the cache database. Receipts are the same
immutable records the server uses, so the cache can later be exported with
deploy/sync_morphology_receipts.py and imported into production.

Usage:
  python scripts/warm_morphology_forms.py --records runtime/campbell-assignment/campbell_assignment.jsonl \
      --database runtime/dev/machine_morphology.sqlite [--corpus data/corpus.sqlite --ids id1 id2]
      [--delay 2.0] [--limit 0] [--dry-run]

Rate: one request every --delay seconds (default 2 s, i.e. 30 per minute, the
service module's own per-minute ceiling). Failures are recorded by the service
and skipped; rerun to retry after its backoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VISITOR = hashlib.sha256(b"melos-warm-morphology-forms").hexdigest()


def passages_from_records(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            yield row["id"], row["text"]


def passages_from_corpus(path: Path, ids):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        for pid in ids:
            row = con.execute("SELECT id, text FROM passages WHERE id=?", (pid,)).fetchone()
            if row:
                yield row


EDGE_VARIANTS = {}


def collect_forms(passages):
    from backend.lacuna_boundaries import annotate_lacuna_boundaries
    from backend.passage_analysis import tokenize_span, uncertain_edge_variants
    forms, occurrences = [], {}
    for pid, text in passages:
        tokens = annotate_lacuna_boundaries(text, tokenize_span(text, 0, len(text)), source_critical=True)
        for token in tokens:
            if token["kind"] != "word" or token.get("editorial_fragment") or token.get("partial_word"):
                continue
            form = token["form"]
            if form not in occurrences:
                occurrences[form] = []
                forms.append(form)
            occurrences[form].append(f"{pid}@{token['start']}:{token['end']}")
            for variant in uncertain_edge_variants(token):
                EDGE_VARIANTS.setdefault(form, []).append(variant)
    return forms, occurrences


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    passages = []
    if args.records:
        passages += list(passages_from_records(args.records))
    if args.corpus and args.ids:
        passages += list(passages_from_corpus(args.corpus, args.ids))
    forms, occurrences = collect_forms(passages)
    print(f"passages={len(passages)} unique_forms={len(forms)}", flush=True)
    if args.dry_run:
        for form in forms:
            print(form, len(occurrences[form]))
        return
    # Lift the per-visitor ceilings to the module maxima; the delay keeps the
    # global per-minute rate at or below the service's own ceiling.
    os.environ.setdefault("MELOS_MACHINE_GLOBAL_DAILY", "1000")
    os.environ.setdefault("MELOS_MACHINE_GLOBAL_MINUTE", "30")
    os.environ.setdefault("MELOS_MACHINE_VISITOR_DAILY", "100")
    os.environ.setdefault("MELOS_MACHINE_VISITOR_MINUTE", "10")
    from backend.machine_morphology import MachineMorphologyService
    service = MachineMorphologyService(args.database)
    counts, results = {}, {}
    done = 0
    for index, form in enumerate(forms):
        if args.limit and done >= args.limit:
            break
        cached = service.analyze(form, VISITOR, fetch=False)
        if cached["status"] != "cache_miss":
            status = cached["status"]
        else:
            # Nine requests per visitor keeps each visitor under its per-minute cap.
            visitor = hashlib.sha256(f"{VISITOR}:{done // 9}".encode()).hexdigest()
            result = service.analyze(form, visitor, fetch=True)
            status = result["status"]
            if status == "rate_limited":
                print("rate limited; sleeping 65 s", flush=True)
                time.sleep(65)
                result = service.analyze(form, visitor, fetch=True)
                status = result["status"]
            done += 1
            time.sleep(args.delay)
        counts[status] = counts.get(status, 0) + 1
        results[form] = {"status": status, "occurrences": occurrences[form],
                         "candidates": len((cached if cached["status"] != "cache_miss" else result)["machine_candidates"])}
        print(f"{index + 1}/{len(forms)} {form} {status} candidates={results[form]['candidates']}", flush=True)
    # Forms the parser does not know: warm their labelled Aeolic spelling
    # normalisations too, so the reader can serve those parses cache-only.
    from backend.aeolic_variants import LEXICAL, variants
    variant_counts = {}
    for form, record in list(results.items()):
        # Lexical-table forms (τὼ → τῶ) are queried even when the printed form
        # has analyses of its own, as the reader does.
        if record["status"] != "no_analyses" and form not in LEXICAL:
            continue
        record["normalised"] = []
        for variant in [*variants(form), *EDGE_VARIANTS.get(form, [])]:
            if args.limit and done >= args.limit:
                break
            cached = service.analyze(variant["form"], VISITOR, fetch=False)
            if cached["status"] == "cache_miss":
                visitor = hashlib.sha256(f"{VISITOR}:{done // 9}".encode()).hexdigest()
                cached = service.analyze(variant["form"], visitor, fetch=True)
                if cached["status"] == "rate_limited":
                    time.sleep(65)
                    cached = service.analyze(variant["form"], visitor, fetch=True)
                done += 1
                time.sleep(args.delay)
            variant_counts[cached["status"]] = variant_counts.get(cached["status"], 0) + 1
            record["normalised"].append({**variant, "status": cached["status"],
                                         "candidates": len(cached["machine_candidates"])})
            print(f"  {form} ~ {variant['form']} [{variant['rule']}] {cached['status']} candidates={len(cached['machine_candidates'])}", flush=True)
    print(json.dumps({"exact": counts, "normalised": variant_counts}, ensure_ascii=False), flush=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"database": str(args.database), "counts": counts, "forms": results},
                                          ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
