#!/usr/bin/env python3
"""Assemble the Horace interlinear from the batch files in data/open/latin/interlinear-horace/ (batch-HNN = Odes,
batch-ENN = Epodes and Carmen Saeculare; audits batch-XNN.audit.jsonl; revisions batch-XNN.rev.jsonl) into one file
per work, <work>-interlinear.jsonl (odes, epodes, carmen-saeculare), plus manifest.json with a section per work.

Per line: {work, book, poem, n, latin, english, note, quality: "machine_translation", batch, revised, disputed,
audit: {verdict, problem} when the auditor flagged the original line (verdict OK otherwise)}. The revised line is used
where a revision exists; the Latin is re-checked against the source records so every line still traces to the Perseus
text (Odes and Carmen Saeculare: Shorey & Laing 1919; Epodes: Vollmer 1912; CC BY-SA 4.0).
Usage: python scripts/assemble_interlinear_horace.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "open" / "latin" / "interlinear-horace"
SRC = ROOT / "data" / "open" / "latin" / "perseus-horace" / "poems.jsonl"
WORKS = ("odes", "epodes", "carmen-saeculare")


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def source_lines() -> dict[tuple, str]:
    out = {}
    for r in rows(SRC):
        head, _, rest = r["id"].partition(":lat2:")
        if not rest:
            continue
        work = head.split(":")[1]
        book = str(r.get("book") or "") if work == "odes" else ""
        for l in r["lines"]:
            out[(work, book, str(r["poem"]), str(l["n"]))] = l["text"]
    return out


def audit_key(a: dict, book0: str) -> tuple[str, str]:
    pk = str(a["poem"])
    if book0 and "." not in pk:
        pk = f"{book0}.{pk}"          # the first two Odes audits wrote the poem without its book
    return pk, str(a["n"])


def main():
    source = source_lines()
    out: dict[str, list] = {w: [] for w in WORKS}
    counts: dict[str, Counter] = {w: Counter() for w in WORKS}
    meta_batches: dict[str, dict] = {w: {} for w in WORKS}
    for bpath in sorted(D.glob("batch-[HE]??.jsonl")):
        nn = bpath.stem.split("-")[1]
        base = rows(bpath)
        rev_path = D / f"batch-{nn}.rev.jsonl"
        use = rows(rev_path) if rev_path.exists() else base
        meta = json.loads((D / f"batch-{nn}.meta.json").read_text(encoding="utf-8"))
        book0 = str(meta["poems"][0]).split(".")[0] if nn.startswith("H") else ""
        audit, asum = {}, None
        apath = D / f"batch-{nn}.audit.jsonl"
        if apath.exists():
            for a in rows(apath):
                if a.get("summary"):
                    asum = a
                else:
                    audit[audit_key(a, book0)] = a
        rmeta = json.loads((D / f"batch-{nn}.rev.meta.json").read_text(encoding="utf-8")) if rev_path.exists() else None
        binfo = {"poems": meta.get("poems"), "lines": len(use), "model": meta.get("model"), "date": meta.get("date"),
                 "written_by": meta.get("written_by", "Opus writer subagent"),
                 "audit": {k: asum.get(k) for k in ("lines", "ok", "wrong", "doubtful", "auditor_model")} if asum else None,
                 "revision": {k: rmeta.get(k) for k in ("changed", "disputed", "model")} if rmeta else None,
                 "revised": rev_path.exists()}
        for r in use:
            work = r.get("work") or "odes"
            book = str(r.get("book") or "")
            key = (work, book, str(r["poem"]), str(r["n"]))
            if source.get(key) != r["latin"]:
                counts[work]["latin_mismatch"] += 1
                print("LATIN MISMATCH", key, file=sys.stderr)
            pk = f"{book}.{r['poem']}" if book else str(r["poem"])
            a = audit.get((pk, str(r["n"])))
            out[work].append({"work": work, "book": book, "poem": str(r["poem"]), "n": str(r["n"]), "latin": r["latin"],
                              "english": r["english"], "note": r.get("note", ""), "quality": "machine_translation", "batch": nn,
                              "revised": bool(r.get("revised")), "disputed": bool(r.get("disputed")),
                              "audit": {"verdict": a["verdict"], "problem": a.get("problem", "")} if a else {"verdict": "OK"}})
            c = counts[work]
            c["lines"] += 1
            c["revised"] += bool(r.get("revised"))
            c["disputed"] += bool(r.get("disputed"))
            c[f"audit_{(a or {}).get('verdict', 'OK')}"] += 1
            meta_batches[work][nn] = binfo
    manifest = {"name": "Horace interlinear (literal line-by-line English): Odes, Epodes, Carmen Saeculare; written by Claude Opus "
                        "subagents and, where the harness refused the launch, by the coordinator session inline; audited by "
                        "independent Opus auditors; revised",
                "date": time.strftime("%Y-%m-%d"), "quality": "machine_translation",
                "convention": "one English line per Latin line in Latin order, every word rendered, nothing moved across lines (fragments "
                              "with the agreeing word in the note), negatives where they stand, tense and mood kept, only forced function "
                              "words supplied (possessives noted), metaphors literal with the meaning in the note, coarse vocabulary rendered "
                              "plainly, names as in the Latin, the source's quotation marks kept",
                "source": "data/open/latin/perseus-horace/poems.jsonl (Odes, Carmen Saeculare: Shorey & Laing 1919; Epodes: Vollmer 1912; "
                          "via PerseusDL, CC BY-SA 4.0); every Latin line re-checked against it at assembly",
                "display_rule": "shown only where no human translation exists (Melos release X convention)", "works": {}}
    summary = {}
    for work in WORKS:
        lines = out[work]
        if not lines:
            continue
        lines.sort(key=lambda r: (int(r["book"] or 0), int(r["poem"]), int(r["n"])))
        path = D / f"{work}-interlinear.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")
        have = {(r["book"], r["poem"], r["n"]) for r in lines}
        missing = sorted((k[1:] for k in source if k[0] == work and k[1:] not in have), key=lambda k: tuple(int(x or 0) for x in k))
        dup = counts[work]["lines"] - len(have)
        manifest["works"][work] = {"file": path.name, "counts": dict(counts[work]), "source_lines_missing": [".".join(x for x in k if x) for k in missing],
                                   "duplicate_lines": dup, "batches": meta_batches[work], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        summary[work] = {"lines": counts[work]["lines"], "revised": counts[work]["revised"], "wrong": counts[work]["audit_WRONG"],
                         "doubtful": counts[work]["audit_DOUBTFUL"], "missing": len(missing), "duplicates": dup,
                         "batches_audited": sum(1 for b in meta_batches[work].values() if b["audit"]), "batches": len(meta_batches[work])}
    (D / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
