#!/usr/bin/env python3
"""One command for every check on a Latin draft (docs/prd/catullan-hendecasyllable-checks.md).

    .venv/bin/python scripts/la_check.py "Cui dono lepidum novum libellum\\narida modo pumice expolitum?"
    .venv/bin/python scripts/la_check.py --file draft.txt --metre phalaecian --author Catullus
    .venv/bin/python scripts/la_check.py "..." --only L7,L12        # some checks only
    .venv/bin/python scripts/la_check.py "..." --brief              # the scansion, then one line per check
    .venv/bin/python scripts/la_check.py "..." --json               # the whole result, every evidence row

Runs backend.composer_lint.check(language="la"): L7 metre, L1 forms, L4 attestation, L11 verbatim, then the
Latin-only checks (L12 prosody attestation, L8 elision and hiatus, L13 Phalaecian manner, L3 agreement, L10 word
order, L14 period and register, L5 collocation, L6 manner evidence). Prints each line with its syllables, scansion
marks and bars, then each check as PASS / WARN / FAIL / unavailable with its evidence, blocking failures first.
Exit status 1 when a blocking check fails, 2 on a bad request. Lines are separated by a newline, "\\n" or " / ".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MELOS_COMPOSER_CHECK_BUDGET_MS", "20000")     # a command line can wait; the editor cannot

BARS = {"phalaecian": (2, 6)}        # base | choriamb | iambic close: x x | – ⏑ ⏑ – | ⏑ – ⏑ – x
ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2, "unavailable": 3}
BRIEF_DETAIL = 160                   # characters of each check's detail printed by --brief
SHORT = {"long poems": "long", "polymetrics": "polymetrics", "epigrams": "epigrams"}


def status_of(check: dict) -> str:
    from backend import composer_lint
    return composer_lint.status_of(check)


def draft_lines(text: str) -> list[str]:
    return [l.strip() for l in text.replace("\\n", "\n").replace(" / ", "\n").split("\n") if l.strip()]


_VOWELS = set("aeiouy")
_MUTES, _LIQUIDS = set("bcdgptfk"), set("lr")


def _plain(ch: str) -> str:
    return unicodedata.normalize("NFD", ch.lower())[:1]


def _tail(text: str) -> int:
    """How many final letters of a scanner unit open the next syllable: one consonant, a mute with a liquid, qu, or
    an aspirate (ch, ph, th); x and a doubled consonant divide."""
    k = len(text)
    while k and _plain(text[k - 1]) not in _VOWELS:
        k -= 1
    if text[-2:].lower() == "qu":
        return 2                                 # "aqu|a": qu goes over
    cons = text[k:].lower()
    if not cons:
        return 0
    if cons[-1] == "x":
        return 0
    if len(cons) >= 3 and cons[-1] in _LIQUIDS and cons[-3:-1] in ("ch", "ph", "th"):
        return 3                                 # pul-chra
    if len(cons) >= 2 and ((cons[-2] in _MUTES and cons[-1] in _LIQUIDS and cons[-2] != cons[-1]) or cons[-2:] in ("ch", "ph", "th")):
        return 2
    return 1


def true_syllables(units: list[dict]) -> list[tuple[str, str]]:
    """(syllable, label) from the scanner's units. A unit is a vowel with every consonant up to the next vowel
    ("Cui d", "on", "o l"): the consonants that open the next syllable are moved to it, so the row reads
    Cui do | no le pi dum. An elided vowel stands in brackets."""
    out, carry = [], ""
    for i, u in enumerate(units):
        text = "".join(ch for ch in u["text"] if ch.isalpha() or ch == " ").strip()
        last = i == len(units) - 1
        if " " in text:
            head, moved = text.rsplit(" ", 1)
            head = head.replace(" ", "")
        elif last:
            head, moved = text, ""
        else:
            n = _tail(text)
            head, moved = (text[:-n], text[-n:]) if n else (text, "")
        if u["label"] == "E":
            k = 0
            while k < len(head) and _plain(head[k]) not in _VOWELS:
                k += 1
            cell = carry + head[:k] + "(" + head[k:] + ")"
        else:
            cell = carry + head
        out.append((cell, u["label"]))
        carry = moved
    return out


def scansion_rows(line: dict, fit: dict | None, metre: str) -> tuple[str, str]:
    """(syllables, marks) of one scanned line: true syllables, each mark centred under its syllable; the fitted
    quantities when the line fits (else the scanner's own, ? = either), elided vowels in brackets with no mark,
    bars after the base and after the choriamb."""
    resolved = list(fit["pattern"]) if fit and fit.get("ok") and fit.get("pattern") else None
    bars = BARS.get(metre, ())
    top, bottom, place = [], [], 0
    for cell, label in true_syllables(line["syllables"]):
        if label == "E":
            mark = ""
        else:
            mark = resolved[place] if resolved and place < len(resolved) else {"L": "–", "S": "⏑"}.get(label, "?")
            place += 1
        width = max(len(cell), 1)
        top.append(cell.ljust(width + 1))
        bottom.append((" " * ((width - 1) // 2) + mark).ljust(width + 1))
        if label != "E" and place in bars:
            top.append("| ")
            bottom.append("| ")
    return "".join(top).rstrip(), "".join(bottom).rstrip()


def evidence_line(row) -> str:
    if not isinstance(row, dict):
        return str(row)[:220]
    kind = row.get("kind")
    if kind == "pair":
        if not row.get("author"):
            return f"{row['pair']} (line {row['line']}, {row['window']}): no parallel"
        locus = row["loci"][0]
        other = f" [{row['reading']}]" if row.get("reading") else ""      # a pair under a word's other lemma
        return (f"{row['pair']}{other}: {row['author']} x{row['count']} ({row['same_line']} in one line), e.g. "
                f"{locus['citation']} {locus['text']}")[:240]
    if kind == "adjacent":
        return f"\"{row['words']}\": " + (f"{row['author']} {row['citation']} ({row['passages']} passage(s))" if row.get("passages") else "not printed side by side")
    if kind == "baseline":
        return (f"held-out baseline: {row['with_parallel']}/{row['pairs']} pairs of {row['poems']} poems recur "
                f"(median {row['median']}, 10th percentile {row['p10']})")
    if kind == "word":
        t = row.get("tokens") or {}
        counts = ", ".join(f"{SHORT.get(k, k)} {v}" for k, v in t.items() if k not in ("total", "in_metre"))
        place = (row.get("position") or {}).get("lemma")
        where = (f"; in the metre {place['n']}x, usual start syllable {place['usual_start']} ({place['at_usual_start']}/{place['n']}), "
                 f"line-final {place['line_final']}/{place['n']}" if place else "; not in the poet's lines of the metre")
        here = f" at syllable {row['start']}" if row.get("start") else ""
        lemma = f"read as {row['lemma']}, not {row['alternative_to']}," if row.get("alternative_to") else row["lemma"]
        return (f"{row['form']}{here} ({lemma} {row['upos']}): {counts or 'total ' + str(t.get('total', 0))}{where}"
                + (f"; reading: {row['reading']}" if row.get("reading") else "")
                + (f", diminutive{' of ' + row['diminutive_of'] if row.get('diminutive_of') else ''} ({row['diminutive']})" if row.get("diminutive") else "")
                + (f"  << {row['warning']}" if row.get("warning") else ""))
    if kind == "marker":
        if row.get("draft") is None:
            return f"{row['marker']}: not counted in the draft; poet {row.get('poet_per_100')} per 100 lines"
        return (f"{row['marker']}: draft {row['draft']} in {row['draft_lines']} lines; poet {row.get('poet_per_100')} per 100 lines "
                f"({row.get('poet_count')}/{row.get('poet_lines')}), per poem p10/median/p90 {row.get('poet_poem_p10_median_p90')}"
                + (f"; counted: {', '.join(map(str, row['draft_words']))}" if row.get("draft_words") else "")
                + (f" ({row['note']})" if row.get("note") else ""))
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}"
                     for k, v in row.items() if v not in (None, "", [], {}))[:240]


def evidence_rows(check: dict, limit: int) -> list[str]:
    rows = list(check.get("evidence") or [])
    if check.get("id") == "L6":                    # warnings first; the markers are already in the detail
        rows = sorted(rows, key=lambda r: (r.get("kind") == "marker", not r.get("warning"),
                                           not (r.get("reading") or r.get("alternative_to")), r.get("line") or 0, r.get("form") or ""))
    shown = rows if limit <= 0 else rows[:limit]
    out = [evidence_line(r) for r in shown]
    if len(rows) > len(shown):
        out.append(f"... {len(rows) - len(shown)} more evidence rows (--evidence 0 or --json for all)")
    return out


def report(result: dict, lines: list[str], metre: str, author: str, limit: int, brief: bool = False) -> str:
    checks = sorted(result["checks"], key=lambda c: ORDER[status_of(c)])     # stable: report order within a status
    failed = [c["id"] for c in checks if status_of(c) == "FAIL"]
    out = [f"la_check: {len(lines)} line(s), metre {metre}, author {author}: "
           + (f"FAIL (blocking: {', '.join(failed)})" if failed else "PASS (no blocking failure)"), ""]
    scanned, fits = result["scansion"]["lines"], result["scansion"].get("fit") or []
    for i, text in enumerate(lines):
        out.append(f"{i + 1:>2}  {text}")
        if i < len(scanned):
            fit = fits[i] if i < len(fits) else None
            top, bottom = scansion_rows(scanned[i], fit, metre)
            verdict = "" if fit is None else ("   fits" if fit.get("ok") else f"   DOES NOT FIT: {fit.get('message') or ''}")
            out += [f"    {top}", f"    {bottom}{verdict}"]
    out.append("")
    for c in checks:
        if brief:                                 # one line per check: what a composing session reads on every draft
            out.append(f"{status_of(c):<11} {c['id']:<4} {c.get('name', ''):<20} {str(c.get('detail', ''))[:BRIEF_DETAIL]}")
            continue
        out.append(f"{status_of(c):<11} {c['id']:<4} {c.get('name', ''):<20} {'blocking' if c.get('blocking') else '        '}  {c.get('detail', '')}")
        out += [f"{'':17}- {e}" for e in evidence_rows(c, limit)]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("text", nargs="?", help='the draft; lines separated by a newline, "\\n" or " / "')
    ap.add_argument("--file", help="read the draft from a file (- for standard input)")
    ap.add_argument("--metre", default="phalaecian")
    ap.add_argument("--author", default="Catullus")
    ap.add_argument("--only", default="", help="comma-separated check ids, e.g. L7,L12")
    ap.add_argument("--json", action="store_true", help="print the whole result as JSON")
    ap.add_argument("--brief", action="store_true", help="the scansion, then one line per check (status, id, name, detail)")
    ap.add_argument("--evidence", type=int, default=6, help="evidence rows shown per check (0 = all)")
    ap.add_argument("--budget", type=float, default=120.0, help="seconds allowed to the Latin-only checks")
    args = ap.parse_args(argv)
    if args.file:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    else:
        text = args.text or ""
    lines = draft_lines(text)
    if not lines:
        ap.error("no draft: give the text or --file")
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()} or None
    from fastapi import HTTPException
    from backend import composer_lint
    try:
        result = composer_lint.check("\n".join(lines), metre_name=args.metre or None, author=args.author, language="la",
                                     latin_budget=args.budget, latin_only=only)
    except HTTPException as exc:
        print(f"la_check: {exc.detail}", file=sys.stderr)
        return 2
    if only:
        result["checks"] = [c for c in result["checks"] if c["id"].upper() in only]
    for c in result["checks"]:
        c["status"] = status_of(c)
    failed = [c["id"] for c in result["checks"] if c["status"] == "FAIL"]
    result["pass"] = not failed
    if args.json:
        print(json.dumps({"metre": args.metre, "author": args.author, "lines": lines, "blocking_failures": failed, **result},
                         ensure_ascii=False, indent=1))
    else:
        print(report(result, lines, args.metre, args.author, args.evidence, args.brief))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
