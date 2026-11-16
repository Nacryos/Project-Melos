#!/usr/bin/env python3
"""Where a Latin form scans in the hand-scanned poets: scripts/la_prosody.py <form> [<form> ...] [--author Catullus] [--json]

Prints backend.latin_prosody.attested() compactly: each quantity pattern of the form (L long, S short, E elided), the
count per poet, the contexts of the final syllable and up to three loci with the line.
"""
from __future__ import annotations

import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from backend import latin_prosody as lp  # noqa: E402


def show(form: str, author: str = "") -> str:
    a = lp.attested(form, author)
    if not a["available"]:
        return f"{form}: unavailable: prosody index not built ({lp.index_path()}; scripts/build_prosody_index_la.py)"
    if not a["patterns"]:
        return f"{form}: not in the gold" + (f" ({author})" if author else " (Catullus, Virgil, Horace's lyrics)")
    out = [f"{form} ({a['key']}): {a['tokens']} token(s), {len(a['patterns'])} pattern(s)"]
    for p in a["patterns"]:
        poets = ", ".join(f"{k} {v}" for k, v in sorted(p["per_poet"].items(), key=lambda kv: lp._poet_order("Catullus")(kv[0])))
        ctx = " ".join(f"{k}:{v}" for k, v in sorted(p["final_contexts"].items()))
        out.append(f"  {p['pattern']:<8} {p['count']:>4}  {poets}  [final before {ctx}]")
        out += [f"      {x['locus']}: {x['text']}" for x in p["loci"]]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("forms", nargs="+")
    ap.add_argument("--author", default="", help="only this poet's tokens (Catullus, Vergil, Horace)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    for f in args.forms:
        print(json.dumps(lp.attested(f, args.author), ensure_ascii=False) if args.json else show(f, args.author))
    return 0


if __name__ == "__main__":
    sys.exit(main())
