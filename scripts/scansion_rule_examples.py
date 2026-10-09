"""Collect real example units for every rule of backend/scansion/rules.yaml (shown on rules.html).

Sample: the first 300 lines of the Hypotactic Iliad (book 1), and the non-hexameter check texts of
backend/scansion/data/handcheck.json read from data/corpus.sqlite. The lexical layer is on.

    python scripts/scansion_rule_examples.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.scansion.gold import load_iliad  # noqa: E402
from backend.scansion.lexicon import QuantityLexicon  # noqa: E402
from backend.scansion.quantity import Scanner  # noqa: E402
from scansion_handcheck import CONFIG, corpus, passage_text  # noqa: E402

PER_RULE = 4
OUT = ROOT / "backend/scansion/data/rule_examples.json"


def sample_lines():
    for g in load_iliad(books=[1])[:300]:
        yield f"Iliad {g.book}.{g.line} (Hypotactic)", g.text
    db = corpus()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for p in cfg["passages"]:
        if "passage" not in p:
            continue
        text = passage_text(db, p["passage"], p.get("replace", []))
        for k, line in enumerate(l for l in text.split("\n") if l.strip() and l.strip() != "===="):
            yield f"{p['id']} line {k + 1}", line


def main():
    sc = Scanner(lexicon=QuantityLexicon())
    examples: dict[str, list] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    sources_used: dict[str, set] = defaultdict(set)
    for source, line in sample_lines():
        for u in sc.scan(line):
            ids = set(u.vowel["path"]) | set(u.path) | {f["id"] for f in u.flags}
            for rid in ids:
                counts[rid] += 1
                group = source.split(" ")[0]
                if len(examples[rid]) < PER_RULE and (group not in sources_used[rid] or len(examples[rid]) >= 2):
                    sources_used[rid].add(group)
                    examples[rid].append({"source": source, "line": line, "start": u.start, "end": u.end,
                                          "unit": u.text, "p_long": round(u.p_long, 3)})
    OUT.write_text(json.dumps({"sample": "Iliad 1.1-300 (Hypotactic) and the handcheck texts",
                               "counts": dict(sorted(counts.items())), "examples": dict(sorted(examples.items()))},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(examples)} rules with examples -> {OUT}")


if __name__ == "__main__":
    main()
