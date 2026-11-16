#!/usr/bin/env python3
"""Lewis & Short from the command line (backend/latin_dictionary.py; docs/latin/dictionary.md).

    .venv/bin/python scripts/la_dict.py basia            # the entry of a headword or an inflected form
    .venv/bin/python scripts/la_dict.py --en "kiss"      # English -> Latin headwords, Catullus's words first
    .venv/bin/python scripts/la_dict.py --check "da mi basia mille"   # L14 period and register on a draft
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import latin_dictionary as ld  # noqa: E402


def show_entry(e: dict, full: bool) -> None:
    grammar = ", ".join(x for x in (e["inflection"], e["gender"], e["pos"]) if x)
    print(f"{e['headword']}  {grammar}  [{e['how']}]")
    p = e["period"]
    print(f"  labels: {', '.join(e['labels']) or '-'}   citations: {e['citations']}   earliest: {p['earliest'] or '-'}"
          f"   authors before A.D. 14: {len(p['authors_before_ad14'])}")
    print("  authors: " + ", ".join(f"{a} {n}" for a, n in list(e["authors"].items())[:14]))
    for s in e["senses"]:
        if s["glosses"] or full:
            label = f" ({', '.join(s['labels'])})" if s["labels"] else ""
            body = s["text"] if full else s["glosses"]
            print(textwrap.fill(f"{s['n']}{label} {body}", 110, initial_indent="  " + "  " * max(0, s["level"] - 1),
                                subsequent_indent="      "))
    for c in e["catullus"]:
        print(f"  Cat. {(c['work'] + ' ' + c['locus']).strip()}  [{c['sense']}: {c['gloss'].split('; ')[0]}]  {c['quote']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("word", nargs="?", help="a Latin headword or inflected form")
    ap.add_argument("--en", help="English word or phrase: reverse lookup")
    ap.add_argument("--check", help="a draft: run L14 period and register")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--full", action="store_true", help="print each sense's whole text")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not ld.available():
        print(f"unavailable: {ld.db_path()} not built (scripts/build_dictionary_la.py)")
        return 1
    if args.en:
        rows = ld.reverse(args.en, args.limit)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        for r in rows:
            use = f"Cat. {r['catullus']}, Hor. {r['horace']}"
            flag = " LATE" if r["late"] or not r["before_ad14"] else ""
            src = "+".join("LS" if x == "lewis-short" else "Cat" for x in r["sources"])
            print(f"{r['headword']:<18} {src:<7} {use:<20} {r['match']:<14} {', '.join(r['labels']) or '-':<22}{flag}  {r['sense']['glosses'][:70]}")
            if r["interlinear"]:
                h = r["interlinear"]
                print(f"{'':<18} Catullus {h['loci']}: {h['latin']} | {h['english']}")
        return 0
    if args.check:
        out = ld.check(args.check)
        print(json.dumps(out, ensure_ascii=False, indent=1) if args.json else out["detail"])
        return 0
    if not args.word:
        ap.print_help()
        return 1
    entries = ld.lookup(args.word)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=1))
        return 0
    if not entries:
        print(f"{args.word}: no entry")
    for e in entries:
        show_entry(e, args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
