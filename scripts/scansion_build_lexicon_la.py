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
  lewis_short  Perseus Lewis & Short TEI <orth> headwords with breves / macrons (CC BY-SA 4.0). Headwords only;
               a common vowel is written macron + '^' (or breve + '_') and coded A; y-breve is written with a Cyrillic
               ў in the TEI and is mapped back to y; suffix fragments (-ius) and multi-word orths are skipped.
  Audit 2026-10-11 (Team B): the first build read the L&S 'either' marks as L/S, kept the Cyrillic letter and coded
  113,339 Wiktionary page titles without marks as short; all three fixed here, with the smaller slips it listed.

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


CYRILLIC_Y = {"\u045e": "y", "\u0443": "y", "\u040e": "y", "\u0423": "y"}   # Lewis & Short writes y-breve as Cyrillic ў
LATIN_ONLY = re.compile(r"^[A-Za-z\u00C0-\u024F\u1E00-\u1EFF\u0300-\u036F\u045e\u0443\u040e\u0423æœÆŒ]+$")


def marks_of(form: str, unmarked: str = "u") -> tuple[str, str]:
    """(key, codes) from a form written with macrons / breves (combining or precomposed). Lewis & Short writes a
    common vowel as macron + '^' (or breve + '_'): both become A (either). Marks after a consonant are ignored."""
    codes = []
    letters = []
    form = "".join(CYRILLIC_Y.get(ch, ch) for ch in form)
    for ch in unicodedata.normalize("NFD", form):
        if ch in ("^", "_"):
            if codes and codes[-1] in ("L", "S", "A", "u", "s"):
                codes[-1] = "A" if (ch == "^" and codes[-1] == "L") or (ch == "_" and codes[-1] == "S") else \
                            ("S" if ch == "^" else "L") if codes[-1] in ("u", "s") else codes[-1]
            continue
        if unicodedata.combining(ch):
            if codes and codes[-1] == ".":
                continue                                         # a mark on a consonant: ignored
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
            if codes and codes[-1] != ".":
                codes[-1] = "A" if codes[-1] == "S" else "L"
        elif ch == "^":
            if codes and codes[-1] != ".":
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
    seen_w: set = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or parts[0].startswith("#") or parts[3].startswith("#"):
                continue                                          # '#': suppressed analyses (undocumented)
            key, codes = winge_marks(parts[3])
            if not key or len(key) != len(codes):
                counts["winge_skipped_mismatch"] += 1
                continue
            row = (key, key, "winge", codes, parts[2])
            if row in seen_w:
                continue                                          # one row per morph tag in the file: keep one
            seen_w.add(row)
            batch.append(row)
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
                if not form or tags & SKIP_TAGS or " " in form.strip() or form.startswith("-") or not LATIN_ONLY.match(form):
                    continue                                      # IPA, sigla, Greek and Old Italic forms are skipped
                key, codes = marks_of(form, unmarked="s")
                if not key or len(key) != len(codes) or (key, codes) in seen:
                    continue
                seen.add((key, codes))
                batch.append((key, key, "wiktionary", codes, lemma))
                n += 1
            # An entry without forms gives no quantity information (the page title carries no marks): no row.
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
                if o.strip().startswith("-") or " " in o.strip():
                    continue                                      # suffix fragments and multi-word headwords
                key, codes = marks_of(o, unmarked="u")
                if not key or len(key) != len(codes) or not any(c in "LSA" for c in codes):
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
            "codes": "L long, S short, A either (Winge _^, Wiktionary macron+breve, Lewis & Short macron+^ or breve+_), s short by the source's convention (unmarked in Winge and Wiktionary), u unmarked (Lewis & Short), . consonant (v and j stand at their folded u/i position)",
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
