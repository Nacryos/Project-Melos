"""Small lyric lemma gold set for calibration checks (release Q).

There is no treebank of the lyric poets, so the gold lemma of a lyric word is taken from a dictionary
that cites that very place: an LSJ entry (PerseusDL LSJ TEI, data/lexica/entries.jsonl) whose text
cites "Sapph. 1.20", "Alc. 34.7", "Archil. 5" ... names its own headword for a word at that place.
A Campbell GLP poem (campbell-glp:<poet>:<number>; Campbell prints the standard edition numbers,
for Sappho and Alcaeus Lobel-Page's) gives a gold token when exactly one token on the cited line
(or, for a citation without a line, in the whole poem) has the entry's headword among its index
readings; that check also guards against a numbering mismatch between LSJ and Campbell. Every row
keeps its provenance (entry id, the citation as printed, passage, line, printed word) so the set
can be checked by hand. Caveat: the gold headword is always one of the token's index readings, so
the set measures ranking and calibration, not coverage.

    python scripts/build_lyric_lemma_gold.py --entries /lexica/entries.jsonl --index INDEX.sqlite \
        --corpus /corpus.sqlite --campbell data/campbell_glp/campbell_glp.jsonl --out data/evaluation/lyric-lemma-gold.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lemma_tokens import fold, word_tokens  # noqa: E402

# LSJ abbreviation -> Campbell GLP poet slug (only unambiguous author abbreviations)
POETS = {"Sapph": "sappho", "Alc": "alcaeus", "Anacr": "anacreon", "Alcm": "alcman", "Ibyc": "ibycus",
         "Stesich": "stesichorus", "Simon": "simonides", "Archil": "archilochus", "Semon": "semonides",
         "Mimn": "mimnermus", "Tyrt": "tyrtaeus", "Sol": "solon", "Thgn": "theognis", "Xenoph": "xenophanes",
         "Hippon": "hipponax", "Callin": "callinus", "Corinn": "corinna", "B": "bacchylides", "Phoc": "phocylides",
         "Timocr": "timocreon", "Pratin": "pratinas", "Praxill": "praxilla"}
CITE = re.compile(r"(?<![A-Za-z.])(" + "|".join(sorted(POETS, key=len, reverse=True)) +
                  r")\.\s?(\d+[a-z]?)(?:\.(\d+))?(?![\d])")
NOT_AFTER = re.compile(r"(Supp|Oxy|Com|Trag|Lyr|Fr|Epigr|Eleg)\.?\s*$")
DIGITS = re.compile(r"\d+$")


def line_numbers(record):
    """Printed line number of each text line (labels every few lines; else 1, 2, 3 ...)."""
    lines = record.get("lines") or []
    offset = None
    for i, line in enumerate(lines):
        label = str(line.get("label") or "").strip()
        if label.isdigit():
            offset = int(label) - i
            break
    return [(i + offset if offset is not None else i + 1) for i in range(len(lines))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--entries", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--corpus", required=True)
    p.add_argument("--campbell", nargs="+", required=True, help="campbell_glp.jsonl (+ corrected records)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    records = {}
    for path in args.campbell:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            records[r["id"]] = r
    ix = sqlite3.connect(f"file:{args.index}?mode=ro", uri=True)
    corpus = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    lemma_of = dict(ix.execute("SELECT id, lemma FROM lemma"))
    readings = defaultdict(list)
    for fid, lid in ix.execute("SELECT form_id, lemma_id FROM form_lemma"):
        readings[fid].append(lemma_of.get(lid, ""))
    pid_of = dict(ix.execute("SELECT id, pid FROM passage WHERE id LIKE 'campbell-glp:%'"))

    cache = {}

    def poem(pid):
        if pid not in cache:
            row = corpus.execute("SELECT text FROM passages WHERE id=?", (pid,)).fetchone()
            ipid = pid_of.get(pid)
            tok = ix.execute("SELECT forms FROM tok WHERE pid=?", (ipid,)).fetchone() if ipid else None
            if not row or not tok or pid not in records:
                cache[pid] = None
            else:
                import numpy as np
                text = row[0]
                tokens = word_tokens(text)
                fids = np.frombuffer(tok[0], dtype=np.uint32).tolist()
                starts = [0] + [m.end() for m in re.finditer("\n", text)]
                numbers = line_numbers(records[pid])
                rows = []
                for i, (s, e, printed, form, dmg) in enumerate(tokens):
                    line_index = sum(1 for st in starts if st <= s) - 1
                    number = numbers[line_index] if line_index < len(numbers) else None
                    rows.append({"i": i, "printed": printed, "form": form, "damaged": dmg, "line": number,
                                 "readings": readings.get(fids[i], [])})
                cache[pid] = rows
        return cache[pid]

    gold, seen, stats = [], set(), defaultdict(int)
    for line in open(args.entries, encoding="utf-8"):
        entry = json.loads(line)
        if "LSJ" not in str(entry.get("source")):
            continue
        text = str(entry.get("entry_text") or "")
        head = DIGITS.sub("", unicodedata.normalize("NFC", str(entry.get("lemma") or ""))).lstrip("†").strip()
        if not head:
            continue
        for m in CITE.finditer(text):
            if NOT_AFTER.search(text[max(0, m.start() - 8):m.start()]):
                continue
            stats["citations"] += 1
            pid = f"campbell-glp:{POETS[m[1]]}:{m[2]}"
            rows = poem(pid)
            if rows is None:
                continue
            stats["citations_of_campbell_poems"] += 1
            line_no = int(m[3]) if m[3] else None
            pool = [r for r in rows if line_no is None or r["line"] == line_no]
            hits = [r for r in pool if not r["damaged"] and any(fold(x) == fold(head) for x in r["readings"])]
            if len(hits) != 1:
                stats["no_unique_token" if not hits else "several_tokens"] += 1
                continue
            r = hits[0]
            key = (pid, r["i"])
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            gold.append({"passage_id": pid, "token": r["i"], "line": r["line"], "printed": r["printed"],
                         "form": r["form"], "gold_lemma": head,
                         "source": {"dictionary": "LSJ (PerseusDL LSJ TEI)", "entry_id": entry.get("id"),
                                    "entry_url": entry.get("entry_url"), "citation": m.group(0)}})
    gold.sort(key=lambda g: (g["passage_id"], g["token"]))
    out = {"version": "melos-lyric-lemma-gold-v1",
           "method": __doc__.split("\n\n")[1].replace("\n", " "),
           "stats": dict(stats), "tokens": len(gold),
           "poems": len({g["passage_id"] for g in gold}), "gold": gold}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("stats", "tokens", "poems")}))


if __name__ == "__main__":
    main()
