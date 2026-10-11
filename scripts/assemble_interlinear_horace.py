#!/usr/bin/env python3
"""Assemble the Horace Odes interlinear from the batch files (data/open/latin/interlinear-horace/batch-HNN.jsonl, their
audits batch-HNN.audit.jsonl and revisions batch-HNN.rev.jsonl) into odes-interlinear.jsonl + manifest.json.

Per line: {work, book, poem, n, latin, english, note, quality: "machine_translation", batch, revised, disputed,
audit: {verdict, problem} when the auditor flagged the original line (verdict OK otherwise)}. The revised line is used
where a revision exists; the Latin is re-checked against the source records so every line still traces to the Perseus
text (Shorey & Laing 1919, CC BY-SA 4.0). Usage: python scripts/assemble_interlinear_horace.py
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
WORK = "odes"


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    source = {}
    for r in rows(SRC):
        if r["id"].startswith(f"perseus:{WORK}:lat2:"):
            for l in r["lines"]:
                source[(str(r["book"]), str(r["poem"]), str(l["n"]))] = l["text"]
    out, counts, meta_batches = [], Counter(), {}
    for bpath in sorted(D.glob("batch-H??.jsonl")):
        nn = bpath.stem.split("-")[1]
        base = rows(bpath)
        rev_path = D / f"batch-{nn}.rev.jsonl"
        use = rows(rev_path) if rev_path.exists() else base
        audit, asum = {}, None
        apath = D / f"batch-{nn}.audit.jsonl"
        if apath.exists():
            for a in rows(apath):
                if a.get("summary"):
                    asum = a
                else:
                    audit[(a["poem"], str(a["n"]))] = a
        meta = json.loads((D / f"batch-{nn}.meta.json").read_text(encoding="utf-8"))
        book0 = str(meta["poems"][0]).split(".")[0]
        # the first two audits wrote the poem without the book ("1" for Odes 1.1); later ones wrote "1.1"
        audit = {((pk if "." in pk else f"{book0}.{pk}"), n): a for (pk, n), a in audit.items()}
        rmeta = json.loads((D / f"batch-{nn}.rev.meta.json").read_text(encoding="utf-8")) if rev_path.exists() else None
        meta_batches[nn] = {"poems": meta.get("poems"), "lines": len(use), "model": meta.get("model"), "date": meta.get("date"),
                            "written_by": meta.get("written_by", "Opus writer subagent"),
                            "audit": {k: asum.get(k) for k in ("lines", "ok", "wrong", "doubtful", "auditor_model")} if asum else None,
                            "revision": {k: rmeta.get(k) for k in ("changed", "disputed", "model")} if rmeta else None,
                            "revised": rev_path.exists()}
        for r in use:
            key = (str(r["book"]), str(r["poem"]), str(r["n"]))
            if source.get(key) != r["latin"]:
                counts["latin_mismatch"] += 1
                print("LATIN MISMATCH", key, file=sys.stderr)
            a = audit.get((f"{r['book']}.{r['poem']}", str(r["n"])))
            out.append({"work": WORK, "book": str(r["book"]), "poem": str(r["poem"]), "n": str(r["n"]), "latin": r["latin"],
                        "english": r["english"], "note": r.get("note", ""), "quality": "machine_translation", "batch": nn,
                        "revised": bool(r.get("revised")), "disputed": bool(r.get("disputed")),
                        "audit": {"verdict": a["verdict"], "problem": a.get("problem", "")} if a else {"verdict": "OK"}})
            counts["lines"] += 1
            counts["revised"] += bool(r.get("revised"))
            counts["disputed"] += bool(r.get("disputed"))
            counts[f"audit_{(a or {}).get('verdict', 'OK')}"] += 1
    out.sort(key=lambda r: (int(r["book"]), int(r["poem"]), int(r["n"])))
    path = D / f"{WORK}-interlinear.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    have = {(r["book"], r["poem"], r["n"]) for r in out}
    missing = sorted((k for k in source if k not in have), key=lambda k: tuple(int(x) for x in k))
    dup = counts["lines"] - len(have)
    manifest = {"name": "Horace Odes interlinear (literal line-by-line English), written by Claude Opus subagents and, where the "
                        "harness refused the launch, by the coordinator session inline; audited by independent Opus auditors; revised",
                "work": WORK, "date": time.strftime("%Y-%m-%d"), "quality": "machine_translation",
                "convention": "one English line per Latin line in Latin order, every word rendered, nothing moved across lines (fragments "
                              "with the agreeing word in the note), negatives where they stand, tense and mood kept, only forced function "
                              "words supplied (possessives noted), metaphors literal with the meaning in the note, coarse vocabulary rendered "
                              "plainly, names as in the Latin, the source's quotation marks kept",
                "source": "data/open/latin/perseus-horace/poems.jsonl (Shorey & Laing 1919 via PerseusDL, CC BY-SA 4.0); every Latin line "
                          "re-checked against it at assembly",
                "display_rule": "shown only where no human translation exists (Melos release X convention)",
                "counts": dict(counts), "source_lines_missing": [".".join(k) for k in missing], "duplicate_lines": dup,
                "batches": meta_batches, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (D / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"counts": dict(counts), "missing": len(missing), "duplicates": dup,
                      "batches_audited": sum(1 for b in meta_batches.values() if b["audit"]),
                      "batches_revised": sum(b["revised"] for b in meta_batches.values())}, indent=1))


if __name__ == "__main__":
    main()
