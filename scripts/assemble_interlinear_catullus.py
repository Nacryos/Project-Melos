#!/usr/bin/env python3
"""Assemble the Catullus interlinear from the batch files (data/open/latin/interlinear-catullus/batch-NN.jsonl, their
audits batch-NN.audit.jsonl and revisions batch-NN.rev.jsonl) into catullus-interlinear.jsonl + manifest.json.

Per line: {poem, n, latin, english, note, quality: "machine_translation", batch, revised, disputed, audit: {verdict,
problem} when the auditor flagged the original line (verdict OK otherwise)}. The revised line is used where a revision
exists; the Latin is re-checked against the source records so every line still traces to the Perseus text.
Usage: python scripts/assemble_interlinear_catullus.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "open" / "latin" / "interlinear-catullus"
SRC = ROOT / "data" / "open" / "latin" / "perseus-catullus" / "poems.jsonl"


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    source = {}
    for r in rows(SRC):
        if r["language"] == "la":
            for l in r["lines"]:
                source[(r["poem"], l["n"])] = l["text"]
    out, counts, meta_batches = [], Counter(), {}
    for bpath in sorted(D.glob("batch-??.jsonl")):
        nn = bpath.stem.split("-")[1]
        base = rows(bpath)
        rev_path = D / f"batch-{nn}.rev.jsonl"
        use = rows(rev_path) if rev_path.exists() else base
        audit = {}
        apath = D / f"batch-{nn}.audit.jsonl"
        asum = None
        if apath.exists():
            for a in rows(apath):
                if a.get("summary"):
                    asum = a
                else:
                    audit[(a["poem"], a["n"])] = a
        meta = json.loads((D / f"batch-{nn}.meta.json").read_text(encoding="utf-8"))
        rmeta = json.loads((D / f"batch-{nn}.rev.meta.json").read_text(encoding="utf-8")) if rev_path.exists() else None
        meta_batches[nn] = {"poems": meta.get("poems"), "lines": len(use), "model": meta.get("model"), "date": meta.get("date"),
                            "audit": {k: asum.get(k) for k in ("lines", "ok", "wrong", "doubtful", "auditor_model")} if asum else None,
                            "revision": {k: rmeta.get(k) for k in ("changed", "disputed", "model")} if rmeta else None,
                            "revised": rev_path.exists()}
        for r in use:
            key = (r["poem"], r["n"])
            if source.get(key) != r["latin"]:
                counts["latin_mismatch"] += 1
                print("LATIN MISMATCH", key, file=sys.stderr)
            a = audit.get(key)
            out.append({"poem": r["poem"], "n": r["n"], "latin": r["latin"], "english": r["english"], "note": r.get("note", ""),
                        "quality": "machine_translation", "batch": nn, "revised": bool(r.get("revised")), "disputed": bool(r.get("disputed")),
                        "audit": {"verdict": a["verdict"], "problem": a.get("problem", "")} if a else {"verdict": "OK"}})
            counts["lines"] += 1
            counts["revised"] += bool(r.get("revised"))
            counts["disputed"] += bool(r.get("disputed"))
            counts[f"audit_{(a or {}).get('verdict', 'OK')}"] += 1
    def key(r):
        m = re.match(r"(\d+)(.*)", r["poem"]); n = re.match(r"(\d+)(.*)", str(r["n"]))
        return (int(m.group(1)), m.group(2), int(n.group(1)) if n else 0, n.group(2) if n else "")
    out.sort(key=key)
    path = D / "catullus-interlinear.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    missing = sorted(set(source) - {(r["poem"], r["n"]) for r in out}, key=lambda k: key({"poem": k[0], "n": k[1]}))
    manifest = {"name": "Catullus interlinear (literal line-by-line English), written by Claude Opus subagents, audited by independent Opus auditors, revised",
                "date": time.strftime("%Y-%m-%d"), "quality": "machine_translation",
                "convention": "one English line per Latin line in Latin order, every word rendered, nothing added beyond forced function words (supplied possessives noted), negatives where they stand, metaphors literal with the meaning in the note, coarse vocabulary rendered plainly, names as in the Latin, gap markers kept",
                "source": "data/open/latin/perseus-catullus/poems.jsonl (Merrill 1893 via PerseusDL, CC BY-SA 4.0); every Latin line re-checked against it at assembly",
                "display_rule": "shown only where no human translation exists (Melos release X convention)",
                "counts": dict(counts), "source_lines_missing": missing, "batches": meta_batches,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (D / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"counts": dict(counts), "missing": len(missing), "batches_revised": sum(b["revised"] for b in meta_batches.values())}, indent=1))


if __name__ == "__main__":
    main()
