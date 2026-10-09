"""Score the metre-free scanner on the open gold sets in data/open/ (see their manifest.json files).

* hypotactic/lines.jsonl.gz: David Chamberlain's hand scansion (CC BY 4.0), per-syllable L/S.
  Lines are grouped by metre class: hexameter, pentameter (elegiac), iambic (ia*, tr*, an* ...),
  lyric (everything else, incl. Pindar's dactylo-epitrite and Aeolic). Chunks of 20 lines per file
  are split 50/50 into dev and held-out with a fixed seed (manifest: backend/scansion/data/
  eval_open_chunks.json). Files from Iliad 1-12 are never held out (they calibrated the parameters).
  Hexameter is sampled (it is scored on the owner's data separately).
* norma/norma.jsonl.gz: Norma Syllabarum Graecarum (Macronizer/norma, GPL-3.0; independent of
  Hypotactic): marked vowel lengths (`^` short, `_` long). Scored on the VOWEL tree: every α ι υ the
  source marks, against the scanner's p_vowel.

Lexicon modes: none (core rules only), wiktionary (Wiktionary marks only), full (all sources).

    python scripts/scansion_eval_open.py --split dev [--out report.json]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scansion.greek import DICHRONA, letters  # noqa: E402
from backend.scansion.lexicon import QuantityLexicon  # noqa: E402
from backend.scansion.quantity import Scanner  # noqa: E402

DATA = Path(os.environ.get("MELOS_DATA_DIR", ROOT / "data"))
OPEN = DATA / "open"
MANIFEST = ROOT / "backend/scansion/data/eval_open_chunks.json"
SEED, CHUNK, HEX_CHUNKS = 20261010, 20, 40
CALIBRATION_FILES = {f"iliad{i}" for i in range(1, 13)}


def metre_class(m: str) -> str:
    m = (m or "").strip()
    if m == "hexameter":
        return "hexameter"
    if m == "pentameter":
        return "pentameter"
    if re.match(r"^(ia|tr|an|cho)\d", m) or m in ("ia6g",):
        return "iambic_trochaic_anapaestic"
    return "lyric_and_other"


def hypotactic_lines():
    with gzip.open(OPEN / "hypotactic/lines.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_file_class = defaultdict(list)
    for r in hypotactic_lines():
        by_file_class[(r["file"], metre_class(r["metre"]))].append(r["id"])
    rng = random.Random(SEED)
    chunks = []
    for (f, c), ids in sorted(by_file_class.items()):
        for s in range(0, len(ids), CHUNK):
            chunks.append({"file": f, "class": c, "ids": ids[s:s + CHUNK]})
    rng.shuffle(chunks)
    dev, held = [], []
    hex_count = {"dev": 0, "heldout": 0}
    for ch in chunks:
        split = "dev" if (len(dev) <= len(held) or ch["file"] in CALIBRATION_FILES) else "heldout"
        if ch["class"] == "hexameter":
            if hex_count[split] >= HEX_CHUNKS:
                continue
            hex_count[split] += 1
        (dev if split == "dev" else held).append(ch)
    doc = {"seed": SEED, "chunk_lines": CHUNK, "hexameter_chunks_per_split": HEX_CHUNKS,
           "dev": dev, "heldout": held}
    MANIFEST.write_text(json.dumps(doc), encoding="utf-8")
    return doc


def align(text: str, words: list[dict], units):
    """Gold L/S per unit (None if the unit shares a gold syllable or the letters disagree)."""
    gold_letters, bounds, n = [], [], 0
    sylls = [s for w in words for s in w["syl"]]
    for s in sylls:
        ls = letters(s["t"])
        gold_letters += [b for b, _ in ls]
        n += len(ls)
        bounds.append(n)
    text_letters = [b for b, _ in letters(text)]
    if text_letters != gold_letters:
        return None
    idx = []
    for u in units:
        o = len(letters(text[: u.nstart]))
        idx.append(next((i for i, b in enumerate(bounds) if o < b), None))
    out = []
    for k, u in enumerate(units):
        g = idx[k]
        shared = (k + 1 < len(units) and idx[k + 1] == g) or (k > 0 and idx[k - 1] == g)
        final = g == len(sylls) - 1
        q = sylls[g]["q"] if g is not None else None
        out.append((u, None if shared or final or q not in ("L", "S") else q, shared))
    return out


class Score:
    def __init__(self):
        self.t = defaultdict(int)
        self.bins = defaultdict(lambda: [0, 0])
        self.amb = defaultdict(int)
        self.wrong = defaultdict(int)
        self.examples = defaultdict(list)
        self.brier = 0.0
        self.ms = []

    def add(self, u, gold, where):
        y = int(gold == "L")
        self.t["n"] += 1
        self.brier += (u.p_long - y) ** 2
        self.bins[min(int(u.p_long * 10), 9)][0] += 1
        self.bins[min(int(u.p_long * 10), 9)][1] += y
        key = u.rule if u.rule not in ("NATURE", "CONS-VOW") else f"{u.rule}/{u.vowel['rule']}"
        if u.label == "A":
            self.t["A"] += 1
            self.amb[key] += 1
        else:
            self.t["decided"] += 1
            if (u.label == "L") == bool(y):
                self.t["ok"] += 1
            else:
                self.wrong[key] += 1
                if len(self.examples[key]) < 3:
                    self.examples[key].append(f"{where}: '{u.text}' gold {gold}, p={u.p_long:.2f}")

    def report(self):
        n = max(self.t["n"], 1)
        self.ms.sort()
        return {"lines": self.t["lines"], "lines_skipped_letters_differ": self.t["skipped"],
                "units_scored": self.t["n"], "decided_share": round(self.t["decided"] / n, 4),
                "decided_accuracy": round(self.t["ok"] / max(self.t["decided"], 1), 4),
                "ambiguous_share": round(self.t["A"] / n, 4), "brier": round(self.brier / n, 4),
                "reliability": {f"{b / 10:.1f}-{(b + 1) / 10:.1f}": {"n": c, "observed_long": round(l / c, 3)}
                                for b, (c, l) in sorted(self.bins.items()) if c},
                "ambiguous_by_rule": dict(sorted(self.amb.items(), key=lambda kv: -kv[1])[:12]),
                "errors_by_rule": {k: {"wrong": v, "examples": self.examples[k]}
                                   for k, v in sorted(self.wrong.items(), key=lambda kv: -kv[1])[:12]},
                "ms_per_line_median": round(self.ms[len(self.ms) // 2], 3) if self.ms else None}


def eval_hypotactic(scanner, split_chunks, dialect_by_file=None):
    want = {}
    for ch in split_chunks:
        for i in ch["ids"]:
            want[i] = ch["class"]
    scores = defaultdict(Score)
    for r in hypotactic_lines():
        c = want.get(r["id"])
        if c is None:
            continue
        sc = scores[c]
        sc.t["lines"] += 1
        t0 = time.perf_counter()
        units = scanner.scan(r["text"])
        sc.ms.append((time.perf_counter() - t0) * 1000)
        al = align(r["text"], r["words"], units)
        if al is None:
            sc.t["skipped"] += 1
            continue
        for u, gold, _ in al:
            if gold:
                sc.add(u, gold, f"{r['file']} {r['line_no']}")
    return {c: s.report() for c, s in sorted(scores.items())}


def norma_rows():
    with gzip.open(OPEN / "norma/norma.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["task"] == "macronize":
                yield r


def norma_marks(marked: str, text: str):
    """{char index in text: 'L'|'S'} from the `^`/`_` marks, or None if the plain text does not match."""
    out, plain = {}, []
    for ch in marked:
        if ch in "^_":
            if plain:
                out[len(plain) - 1] = "S" if ch == "^" else "L"
            continue
        plain.append(ch)
    return out if "".join(plain) == text else None


def eval_norma(scanner):
    per = defaultdict(lambda: defaultdict(int))
    for r in norma_rows():
        marks = norma_marks(r["marked"], r["text"])
        src = r["source"]
        if marks is None:
            per[src]["rows_mismatch"] += 1
            continue
        per[src]["rows"] += 1
        for u in scanner.scan(r["text"]):
            if u.vowel["rule"] in ("NAT-DIPH", "NAT-ETA", "NAT-EO", "NAT-ISUB", "CRA-1"):
                continue
            # nucleus is a single α ι υ; its character index is the nucleus start (combining marks follow it)
            gold = marks.get(u.nstart)
            if gold is None:
                continue
            p = u.vowel["p_long"]
            lab = "L" if p >= 0.9 else "S" if p <= 0.1 else "A"
            per[src]["n"] += 1
            if lab == "A":
                per[src]["A"] += 1
            else:
                per[src]["decided"] += 1
                per[src]["ok"] += int(lab == gold)
    out = {}
    tot = defaultdict(int)
    for src, d in sorted(per.items()):
        for k, v in d.items():
            tot[k] += v
        out[src] = dict(d, decided_accuracy=round(d["ok"] / max(d["decided"], 1), 4),
                        ambiguous_share=round(d["A"] / max(d["n"], 1), 4))
    out["ALL"] = dict(tot, decided_accuracy=round(tot["ok"] / max(tot["decided"], 1), 4),
                      ambiguous_share=round(tot["A"] / max(tot["n"], 1), 4))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "heldout"], required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    man = manifest()
    modes = {"none": None, "wiktionary": QuantityLexicon(sources=("wiktionary",)), "full": QuantityLexicon()}
    report = {"split": args.split, "hypotactic": {}, "norma": {}}
    for name, lex in modes.items():
        sc = Scanner(lexicon=lex)
        report["hypotactic"][name] = eval_hypotactic(sc, man[args.split])
        if args.split == "heldout":
            report["norma"][name] = eval_norma(sc)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:2000])


if __name__ == "__main__":
    main()
