#!/usr/bin/env python3
"""Command line over the Latin reference stores (backend/latin_reference.py; docs/latin/reference-stores.md).

  la_ref.py commentary 5 [7]        Merrill's notes on poem 5 (on line 7)
  la_ref.py word bellus [basia ..]  Merrill's notes that discuss a word (inflected forms resolve to the lemma)
  la_ref.py intro [86 | Metres]     Merrill's Introduction: all headings, one section, or a heading's sections
  la_ref.py grammar 603 [603f]      Allen and Greenough by section
  la_ref.py search "mute and liquid"   full-text search of the grammar, the commentary and the introduction
  la_ref.py status
Add --json for the raw rows, --limit N for searches.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import latin_reference as ref  # noqa: E402


def wrap(text: str, indent: str = "    ") -> str:
    return "\n".join(textwrap.fill(line, 110, initial_indent=indent, subsequent_indent=indent) for line in text.split("\n"))


def show_note(r: dict, full: bool = True) -> str:
    where = f"{r['poem']}.{r['line']}" if r["line"] else f"{r['poem']} (headnote)"
    head = f"Merrill on {where}" + (f"  [{r['lemma']}]" if r["lemma"] else "") + (f"  ({r['matched_in']}: {r['matched_form']})" if r.get("matched_in") else "")
    return head + "\n" + wrap(r["text"] if full else r.get("excerpt") or r["text"][:240])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["commentary", "word", "intro", "grammar", "search", "status"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    out: object
    lines: list[str] = []
    if a.command == "status":
        out = ref.status()
        lines = [json.dumps(out, ensure_ascii=False, indent=1)]
    elif a.command == "commentary":
        if not a.args:
            ap.error("commentary POEM [LINE]")
        line = int(a.args[1]) if len(a.args) > 1 and a.args[1].isdigit() else None
        out = ref.commentary(a.args[0], line)
        lines = [show_note(r) for r in out]
    elif a.command == "word":
        out = ref.notes_for_words(a.args, limit=a.limit)
        for w in out:
            lines.append(f"== {w['word']}  (keys: {', '.join(w['keys'])}; {len(w['notes'])} notes)")
            lines += [show_note(r, full=False) for r in w["notes"]]
    elif a.command == "intro":
        out = ref.intro(a.args[0] if a.args else None)
        if a.args:
            lines = [f"Merrill, Introduction § {r['section']}  [{r['heading']}]\n" + wrap(r["text"]) for r in out]
        else:
            seen: dict[str, list[str]] = {}
            for r in out:
                seen.setdefault(f"{r['heading_n']}. {r['heading']}", []).append(r["section"])
            lines = [f"{h}  §§ {v[0]}-{v[-1]}" for h, v in seen.items()]
    elif a.command == "grammar":
        out = [ref.grammar(x) for x in a.args]
        for x, r in zip(a.args, out):
            if not r:
                lines.append(f"A&G § {x}: not found")
                continue
            lines.append(f"A&G § {r['section']}{r['sub']}  [{' > '.join(r['heading_path'])}]\n" + wrap(r.get("full_text") or r["text"]))
    else:
        q = " ".join(a.args)
        out = {"grammar": ref.grammar_search(q, a.limit), "commentary": ref.commentary_search(q, a.limit), "intro": ref.intro_search(q, a.limit)}
        for r in out["grammar"]:
            lines.append(f"A&G § {r['section']}{r['sub']}  [{' > '.join(r['heading_path'])}]  ({r['match']})\n" + wrap(r["excerpt"]))
        for r in out["commentary"]:
            lines.append(show_note(r, full=False))
        for r in out["intro"]:
            lines.append(f"Merrill, Introduction § {r['section']}  [{r['heading']}]  ({r['match']})\n" + wrap(r["excerpt"]))
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lines) if lines else "nothing found" + ("" if ref.available() else f" ({ref.status().get('reason')})"))


if __name__ == "__main__":
    main()
