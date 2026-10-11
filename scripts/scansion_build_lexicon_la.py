#!/usr/bin/env python3
"""Build the Latin vowel-quantity lexicon data/scansion/quantities_la.sqlite (same table as the Greek one).

Sources (raw files under data/raw/latin/, fetched 2026-10-10 with sha256 in data/raw/latin/fetch-log.jsonl):
  winge        Johan Winge's latin-macronizer macrons.txt: form \\t tag \\t lemma \\t macronised (_ long, ^ short,
               _^ either; an unmarked vowel is short by the file's convention, coded 's'). Data derives from Perseus Morpheus Latin (CC BY-SA 3.0 US) plus Winge's overrides; the
               repo licenses only the code (GPL-3): server-side use, redistribution of this table only after asking
               the author (survey A). Upstream: Morpheus / Lewis & Short.
  wiktionary   Kaikki extraction of English Wiktionary's Latin entries (CC BY-SA 4.0 + GFDL): the canonical headword
               and every inflection-table form, with macrons; an unmarked vowel is short by Wiktionary's convention
               (coded 's', weaker than an explicit 'S'). Upstream: editors citing Lewis & Short, Gaffiot, OLD.
  lewis_short  Perseus Lewis & Short TEI <orth> headwords with breves / macrons (CC BY-SA 4.0). Headwords only.

Codes per base letter of the key (u for v, i for j): L long, S short, s short by convention, u unmarked / either,
'.' consonant. Rows are per (key, source, marks, lemma); the lookup merges them (lexicon_la.py).
Usage: python scripts/scansion_build_lexicon_la.py [--out data/scansion/quantities_la.sqlite] [--skip wiktionary]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.scansion.latin import BREVE, MACRON, VOWELS, key as la_key  # noqa: E402

RAW = ROOT / "data" / "raw" / "latin"
OUT = ROOT / "data" / "scansion" / "quantities_la.sqlite"
SKIP_TAGS = {"table-tags", "inflection-template", "romanization", "class"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def marks_of(form: str, unmarked: str = "u") -> tuple[str, str]:
    """(key, codes) from a form written with macrons / breves (combining or precomposed)."""
    codes = []
    letters = []
    for ch in unicodedata.normalize("NFD", form):
        if unicodedata.combining(ch):
            if ch == MACRON and codes and codes[-1] in ("u", "s", "S"):
                codes[-1] = "L" if codes[-1] != "S" else "A"      # macron + breve: either (A)
            elif ch == BREVE and codes and codes[-1] in ("u", "s", "L"):
                codes[-1] = "S" if codes[-1] != "L" else "A"
            continue
        if ch in ("æ", "Æ"):
            letters += ["a", "e"]; codes += [unmarked, unmarked]; continue
        if ch in ("œ", "Œ"):
            letters += ["o", "e"]; codes += [unmarked, unmarked]; continue
        if not ch.isalpha():
            continue
        b = ch.lower()
        letters.append(b)
        codes.append(unmarked if b in VOWELS or b == "y" else ".")
    k = la_key("".join(letters))
    return k, "".join(codes)


def winge_marks(macronised: str) -> tuple[str, str]:
    """'vi_num' -> ('uinum', '.L.s.'): _ long, ^ short, _^ either (A); an unmarked vowel is short by convention (s)."""
    codes, letters = [], []
    for ch in macronised:
        if ch == "_":
            if codes:
                codes[-1] = "A" if codes[-1] == "S" else "L"
        elif ch == "^":
            if codes:
                codes[-1] = "A" if codes[-1] == "L" else "S"
        elif ch.isalpha():
            b = ch.lower()
            letters.append(b)
            codes.append("s" if b in VOWELS or b == "y" else ".")
    return la_key("".join(letters)), "".join(codes)


def build_winge(con, counts):
    path = RAW / "winge" / "macrons.txt"
    n = 0
    batch = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            key, codes = winge_marks(parts[3])
            if not key or len(key) != len(codes):
                counts["winge_skipped_mismatch"] += 1
                continue
            batch.append((key, key, "winge", codes, parts[2]))
            n += 1
            if len(batch) >= 50000:
                con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", batch); batch.clear()
    con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", batch)
    counts["winge_rows"] = n
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "rows": n}


def build_wiktionary(con, counts):
    path = RAW / "wiktionary" / "kaikki.org-dictionary-Latin.jsonl"
    n = entries = 0
    batch = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                counts["wiktionary_bad_json"] += 1
                continue
            if d.get("lang_code") != "la":
                continue
            entries += 1
            lemma = d.get("word") or ""
            seen = set()
            forms = d.get("forms") or []
            for fm in forms:
                form = fm.get("form") or ""
                tags = set(fm.get("tags") or [])
                if not form or tags & SKIP_TAGS or " " in form.strip() or form.startswith("-"):
                    continue
                key, codes = marks_of(form, unmarked="s")
                if not key or len(key) != len(codes) or (key, codes) in seen:
                    continue
                seen.add((key, codes))
                batch.append((key, key, "wiktionary", codes, lemma))
                n += 1
            if not forms:
                key, codes = marks_of(lemma, unmarked="s")
                if key and len(key) == len(codes) and any(c != "." for c in codes):
                    batch.append((key, key, "wiktionary", codes, lemma)); n += 1
            if len(batch) >= 50000:
                con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", batch); batch.clear()
    con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", batch)
    counts["wiktionary_rows"], counts["wiktionary_entries"] = n, entries
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "rows": n, "entries": entries}


def build_lewis_short(con, counts):
    path = RAW / "lewis-short" / "lat.ls.perseus-eng2.xml"
    n = 0
    batch = []
    orth = re.compile(r'<orth[^>]*>([^<]+)</orth>')
    entry = re.compile(r'<entryFree[^>]*key="([^"]+)"')
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = entry.search(line)
            lemma = re.sub(r"\d+$", "", m.group(1)) if m else ""
            for o in orth.findall(line):
                key, codes = marks_of(o, unmarked="u")
                if not key or len(key) != len(codes) or not any(c in "LS" for c in codes):
                    continue
                batch.append((key, key, "lewis_short", codes, lemma))
                n += 1
    con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", batch)
    counts["lewis_short_rows"] = n
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "rows": n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--skip", nargs="*", default=[])
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    con.execute("CREATE TABLE q (key TEXT, akey TEXT, source TEXT, marks TEXT, lemmas TEXT)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    counts = Counter()
    sources = {}
    t0 = time.time()
    for name, fn in (("winge", build_winge), ("wiktionary", build_wiktionary), ("lewis_short", build_lewis_short)):
        if name in args.skip:
            continue
        sources[name] = fn(con, counts)
        con.commit()
        print(name, sources[name], f"{time.time() - t0:.0f}s", file=sys.stderr)
    con.execute("CREATE INDEX q_key ON q(key)")
    distinct = con.execute("SELECT COUNT(DISTINCT key) FROM q").fetchone()[0]
    meta = {"built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "sources": sources, "counts": dict(counts),
            "distinct_keys": distinct,
            "codes": "L long, S short, A either (Winge _^, Wiktionary macron+breve), s short by the source's convention (unmarked in Winge and Wiktionary), u unmarked (Lewis & Short), . consonant",
            "licences": {"winge": "code GPL-3.0; data from Perseus Morpheus Latin (CC BY-SA 3.0 US): server-side use; ask the author before redistribution",
                         "wiktionary": "CC BY-SA 4.0 + GFDL", "lewis_short": "CC BY-SA 4.0 (Perseus)"}}
    con.execute("INSERT INTO meta VALUES ('rows', ?)", (json.dumps(meta),))
    con.commit()
    con.execute("VACUUM")
    con.close()
    manifest = out.with_suffix(".manifest.json")
    meta["sqlite_sha256"] = sha(out)
    meta["sqlite_bytes"] = out.stat().st_size
    manifest.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "sources"}, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
