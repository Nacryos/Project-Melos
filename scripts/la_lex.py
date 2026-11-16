#!/usr/bin/env python3
"""The further Latin dictionaries from the command line (backend/latin_lexica.py; docs/latin/lexica.md).

    .venv/bin/python scripts/la_lex.py                       # the stores that are built, with counts and licences
    .venv/bin/python scripts/la_lex.py venustus              # a Latin word in Georges, Gaffiot, Forcellini, Doederlein ...
    .venv/bin/python scripts/la_lex.py basia --dict georges,gaffiot --full
    .venv/bin/python scripts/la_lex.py --en "darling"        # Smith & Hall and Riddle-Arnold: English -> Latin
    .venv/bin/python scripts/la_lex.py --search "hendecasyllab*"   # full text; stores that only hold pages answer too
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import latin_lexica as lx  # noqa: E402


def block(head: str, text: str) -> None:
    print(head)
    for para in (text or "").splitlines():
        if para.strip():
            print(textwrap.fill(para.strip(), 110, initial_indent="    ", subsequent_indent="      "))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("word", nargs="?", help="a Latin headword or inflected form")
    ap.add_argument("--en", help="an English word: the English-Latin dictionaries")
    ap.add_argument("--search", help="full text across the stores")
    ap.add_argument("--dict", help="comma-separated stores (default: all that fit)")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--full", action="store_true", help="whole entries, not the first lines")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = lx.query(args.word or "", en=args.en or "", search_text=args.search or "", dicts=args.dict, limit=args.limit, full=args.full)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if out.get("error") or not out["dictionaries"]:
        print(out.get("error") or f"no lex_*.sqlite under {lx.lex_dir()} (scripts/ingest_lexica_la.py)")
        return 1
    if not (args.word or args.en or args.search):
        for m in out["dictionaries"]:
            size = f"{m['entries']} entries" if m["entries"] else f"{m['pages']} pages"
            print(f"{m['name']:<18} {m['direction'] or '-':<6} {size:<16} {m['title']}")
            print(f"{'':<18} licence: {' '.join((m['licence'] or '-').split())[:150]}")
        return 0
    for name, entries in out.get("lookup", {}).items():
        for e in entries:
            block(f"[{name}] {e['headword']}  ({e['how']}, {e['chars']} characters)", e["text"])
    if args.word and not out.get("lookup"):
        print(f"{args.word}: no entry")
    for e in out.get("english", []):
        block(f"[{e['dict']}] {e['headword']}  ({e['how']})", e["text"])
        if e["latin"]:
            print("    Latin: " + ", ".join(w["word"] for w in e["latin"]))
    if args.en and not out.get("english"):
        print(f"{args.en}: no English-Latin entry")
    for name, hits in out.get("search", {}).items():
        for h in hits:
            block(f"[{name}] {h['headword']}", h["excerpt"])
    for name, hits in out.get("pages", {}).items():
        for h in hits:
            block(f"[{name}] vol. {h['volume']}, col. {h['col']}", h["excerpt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
