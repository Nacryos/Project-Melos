"""Agreement check: cached Alpheios receipts vs. a local Morpheus build.

For every successful Alpheios receipt in a machine-morphology cache, the same request
(same transport spelling and noAposRetry flag) is sent to the local engine and both raw
responses are projected with backend.machine_morphology.project. Analyses are compared
as sets of (lemma, features); the report counts exact agreement and classifies every
difference. Read-only on the cache; writes only the JSON report.

  python scripts/compare_local_morpheus.py CACHE.sqlite http://127.0.0.1:8793/api/v1/analysis/word --out report.json
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.machine_morphology import project, _sha  # noqa: E402

CORE = ("pofs", "case", "num", "gend", "tense", "mood", "voice", "pers", "comp")


def analyses(raw, form):
    receipt = {"id": "0" * 64, "raw_sha256": _sha(raw)}
    result = project(raw, form, receipt)
    full = collections.Counter()
    for c in result["machine_candidates"]:
        feats = {k: v for k, v in c["features"].items()}
        full[(c["lemma"], tuple(sorted(feats.items())))] += 1
    return full


def core(full):
    return {(lemma, tuple((k, v) for k, v in feats if k in CORE)) for (lemma, feats) in full}


def classify(a, b):
    if a == b:
        return "identical"
    if not a:
        return "alpheios_none_local_some"
    if not b:
        return "local_none_alpheios_some"
    la, lb = {x[0] for x in a}, {x[0] for x in b}
    if core(a) == core(b):
        drop = {k for _, f in a ^ b for k, _ in f}
        return "same_core_parse_other_fields:" + ",".join(sorted(drop - set(CORE)) or ["order/duplicates"])
    if la == lb:
        return "same_lemmas_core_features_differ"
    if {l.rstrip("0123456789") for l in la} == {l.rstrip("0123456789") for l in lb}:
        return "lemma_homograph_number_differs"
    if la & lb:
        return "lemmas_overlap_partly"
    return "lemmas_disjoint"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cache", type=Path)
    ap.add_argument("endpoint")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.cache}?mode=ro", uri=True)
    rows = con.execute("SELECT r.metadata, r.raw FROM cache c JOIN receipts r ON r.id=c.receipt_id "
                       "WHERE c.expires IS NULL").fetchall()
    counts, examples, per_form = collections.Counter(), collections.defaultdict(list), []
    for metadata, raw in rows:
        meta = json.loads(metadata)
        if meta.get("http_status") not in (200, 201):
            counts["alpheios_http_error"] += 1
            continue
        form = meta.get("source_form", meta["request_form"])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(meta["url"]).query))
        with urllib.request.urlopen(args.endpoint + "?" + urllib.parse.urlencode(query), timeout=30) as response:
            local_raw = response.read()
        a, b = analyses(raw, form), analyses(local_raw, form)
        a_set, b_set = set(a), set(b)
        kind = classify(a_set, b_set)
        lemma_same = {x[0] for x in a_set} == {x[0] for x in b_set}
        core_same = core(a_set) == core(b_set)
        counts[kind.split(":")[0]] += 1
        counts["lemma_sets_equal"] += lemma_same
        counts["core_parse_sets_equal"] += core_same
        counts["forms"] += 1
        row = {"form": form, "class": kind, "alpheios": sorted(map(list, a_set)), "local": sorted(map(list, b_set))}
        per_form.append(row)
        if kind != "identical" and len(examples[kind]) < 8:
            examples[kind].append(row)
    n = counts["forms"] or 1
    summary = {"forms": counts["forms"], "identical": counts["identical"],
               "identical_rate": round(counts["identical"] / n, 4),
               "lemma_sets_equal_rate": round(counts["lemma_sets_equal"] / n, 4),
               "core_parse_sets_equal_rate": round(counts["core_parse_sets_equal"] / n, 4),
               "classes": {k: v for k, v in counts.most_common() if k not in ("forms", "lemma_sets_equal", "core_parse_sets_equal")}}
    args.out.write_text(json.dumps({"summary": summary, "examples": examples, "rows": per_form},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
