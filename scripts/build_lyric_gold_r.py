"""Assemble the release R lyric gold set from hand annotations (data/evaluation/lyric-gold-r.json).

    python scripts/build_lyric_gold_r.py --annotations gold_A.json gold_B.json ... --texts dump.json \
        --out data/evaluation/lyric-gold-r.json

Each annotation file holds one row per printed word of a Campbell GLP poem (passage id, start offset, printed
word, lemma, parse, uncertain flag and reason, evidence: Campbell's note with page, the LSJ entry of the
lemma with a verbatim quote, or an Aeolic rule from Campbell pp. 262-264 / the project docs). This script
checks every row against the stored text (the printed word must stand at its offset), checks the parse
vocabulary, and assigns the split: the stored lines of each poem are taken in blocks of four (about a
stanza) and the blocks alternate between the development half and the held-out half, starting on a
different half for consecutive poems. Rules were developed on the development half only; results are
reported for both.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from eval_lyric_gold import POEMS, gold_features  # noqa: E402


def split_of(pid, text, start):
    block = text.count("\n", 0, start) // 4
    return "dev" if (block + POEMS.index(pid)) % 2 == 0 else "held"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--annotations", nargs="+", required=True)
    p.add_argument("--texts", required=True, help="a dump (scripts/eval_lyric_gold.py dump) with the poems' stored texts")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    texts = {pid: v["text"] for pid, v in json.load(open(args.texts, encoding="utf-8"))["passages"].items()}
    tokens, problems = [], []
    for path in args.annotations:
        for row in json.load(open(path, encoding="utf-8"))["tokens"]:
            pid, start, printed = row["passage_id"], int(row["start"]), unicodedata.normalize("NFC", row["printed"])
            text = texts[pid]
            if text[start:start + len(printed)] != printed:
                problems.append(f"{pid} {start} {printed!r} not at its offset")
                continue
            try:
                gold_features(row["parse"])
            except ValueError as exc:
                problems.append(f"{pid} {start} {printed}: {exc}")
                continue
            if not row.get("evidence"):
                problems.append(f"{pid} {start} {printed}: no evidence")
            out = {"passage_id": pid, "start": start, "line": text.count("\n", 0, start) + 1, "printed": printed,
                   "lemma": unicodedata.normalize("NFC", row["lemma"]),
                   "lemma_also": [unicodedata.normalize("NFC", x) for x in row.get("lemma_also") or []],
                   "parse": row["parse"], "uncertain": bool(row.get("uncertain")),
                   "uncertain_reason": row.get("uncertain_reason") or "", "split": split_of(pid, text, start),
                   "evidence": row.get("evidence") or [], "note": row.get("note") or ""}
            if row.get("crasis"):
                out["crasis"] = row["crasis"]
            tokens.append(out)
    if problems:
        print("\n".join(problems[:40]), file=sys.stderr)
        sys.exit(f"{len(problems)} problems")
    tokens.sort(key=lambda t: (POEMS.index(t["passage_id"]), t["start"]))
    stats = Counter((t["split"], "uncertain" if t["uncertain"] else "certain") for t in tokens)
    doc = {"version": "melos-lyric-gold-r-v1",
           "method": __doc__.split("\n\n")[1].replace("\n", " "),
           "poems": POEMS, "tokens_total": len(tokens),
           "counts": {f"{a}_{b}": n for (a, b), n in sorted(stats.items())},
           "evidence_kinds": dict(Counter(e.get("kind") for t in tokens for e in t["evidence"])),
           "tokens": tokens}
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("tokens_total", "counts", "evidence_kinds")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
