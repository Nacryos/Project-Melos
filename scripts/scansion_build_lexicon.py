"""Build the vowel-quantity lexicon used by backend.scansion (data/scansion/quantities.sqlite).

Every row is read from a source file by code; nothing is typed by hand. Sources (all local):

* morpheus  - local Morpheus (alpheios-project/morpheus @ 2f1a30d, stem library dist/stemlib;
              Perseus/Tufts, CC BY-SA 3.0 US) run over every distinct Greek token spelling of
              data/corpus.sqlite (see --morpheus-xml). Morpheus prints stems and endings in Beta
              Code with '_' (long) and '^' (short). An unmarked dichronon is coded 'u' in a stem
              and 'e' in an ending, because the two conventions differ (measured in
              docs/scansion.md, "Lexical evidence").
* wiktionary - Kaikki extraction of English Wiktionary, Ancient Greek (CC BY-SA 4.0 / GFDL):
              headwords, inflection-table and head-template forms written with macrons/breves.
* lsj        - PerseusDL LSJ TEI (CC BY-SA 4.0): <orth> headwords with '_' / '^'.
* logeion    - helmadik/LSJLogeion (CC BY-SA 4.0): <head orth_orig> headwords with macrons/breves.

Marks are stored per base letter of the spelling ('.' = not a dichronon; L, S, u, e as above).

    python scripts/scansion_build_lexicon.py --data /path/to/melos/data
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.scansion.greek import (  # noqa: E402
    DICHRONA, accentless_key, base_letters, beta_letters, key, quantity_marks,
)

GREEK_WORD = re.compile(r"^[Ͱ-Ͽἀ-῿̀-ͯ]+$")


def marks_from_term(form: str, parts: list[tuple[str, str]]) -> str | None:
    """Align Morpheus stem/suffix letters to the printed form and carry their quantity codes over."""
    target = base_letters(form)
    src_letters, src_codes = [], []
    for kind, beta in parts:
        for base, q in beta_letters(beta):
            src_letters.append(base)
            src_codes.append(q or ("u" if kind == "stem" else "e"))
    if not src_letters:
        return None
    codes = ["u" if ch in DICHRONA else "." for ch in target]
    sm = difflib.SequenceMatcher(None, "".join(src_letters), target, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for i in range(n):
            if target[b + i] in DICHRONA:
                codes[b + i] = src_codes[a + i]
    return "".join(codes)


def morpheus_rows(words_txt: Path, xml_path: Path):
    forms = [line.split("\t", 1)[0] for line in words_txt.read_text(encoding="utf-8").splitlines()]
    idx = -1
    lemma = None
    stem = suff = None
    in_term = False
    with xml_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("<word>") or line.startswith("<unknown"):
                idx += 1
                lemma = None
                continue
            if idx < 0 or idx >= len(forms):
                continue
            m = re.search(r"<hdwd[^>]*>([^<]*)</hdwd>", line)
            if m:
                lemma = m.group(1)
            m = re.search(r"<term[^>]*>(.*)</term>", line)
            if m:
                body = m.group(1)
                parts = [("stem", s) for s in re.findall(r"<stem>([^<]*)</stem>", body)]
                parts += [("suff", s) for s in re.findall(r"<suff>([^<]*)</suff>", body)]
                marks = marks_from_term(forms[idx], parts)
                if marks:
                    yield forms[idx], marks, lemma
    if idx + 1 != len(forms):
        sys.exit(f"Morpheus output has {idx + 1} words for {len(forms)} inputs: refusing to misalign")


def wiktionary_rows(kaikki: Path):
    with kaikki.open(encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            lemma = e.get("word")
            strings = {lemma}
            for f in e.get("forms") or []:
                strings.add(f.get("form"))
            for h in e.get("head_templates") or []:
                strings.update((h.get("args") or {}).values())
            for s in strings:
                if not isinstance(s, str) or not GREEK_WORD.match(s):
                    continue
                marks = quantity_marks(s)
                if "L" in marks or "S" in marks:
                    yield s, marks, lemma


def lsj_rows(lsj_dir: Path):
    for path in sorted(glob.glob(str(lsj_dir / "*.xml"))):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for beta in re.findall(r'<orth[^>]*lang="greek"[^>]*>([^<]*)</orth>', text):
            if "_" not in beta and "^" not in beta:
                continue
            beta = beta.strip().rstrip(",.:;")
            if not re.fullmatch(r"[*a-z()/\\=+|_^']+", beta):
                continue
            letters_q = beta_letters(beta)
            spelling = _beta_to_unicode(beta)
            if base_letters(spelling) != "".join(b for b, _ in letters_q):
                continue
            marks = "".join((q or "u") if b in DICHRONA else "." for b, q in letters_q)
            yield spelling, marks, spelling


def _beta_to_unicode(beta: str) -> str:
    from betacode.conv import beta_to_uni
    return beta_to_uni(beta.replace("_", "").replace("^", ""))


def logeion_rows(logeion_dir: Path):
    for path in sorted(glob.glob(str(logeion_dir / "greatscott*.xml"))):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for orig in re.findall(r'<head[^>]*orth_orig="([^"]*)"', text):
            for word in re.split(r"[\s,]+", orig):
                word = word.replace("-", "").strip("·.:;()[]")
                if not word or not GREEK_WORD.match(word):
                    continue
                marks = quantity_marks(word)
                if "L" in marks or "S" in marks:
                    yield word, marks, word


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("MELOS_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data")))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = Path(args.data)
    out = Path(args.out or data / "scansion" / "quantities.sqlite")
    sources = {
        "morpheus": lambda: morpheus_rows(data / "scansion/morpheus/words.txt", data / "scansion/morpheus/all.xml"),
        "wiktionary": lambda: wiktionary_rows(data / "raw/wiktionary/kaikki.org-dictionary-AncientGreek.jsonl"),
        "lsj": lambda: lsj_rows(data / "raw/lexica/lsj/CTS_XML_TEI/perseus/pdllex/grc/lsj"),
        "logeion": lambda: logeion_rows(data / "raw/lexica/lsj-logeion-6aa48692192d"),
    }
    table: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    counts = {}
    for name, gen in sources.items():
        t0, n = time.time(), 0
        for spelling, marks, lemma in gen():
            k = key(spelling)
            if len(marks) != len(base_letters(k)):
                continue
            table[(k, name, marks)].add(lemma or "")
            n += 1
        counts[name] = n
        print(f"{name}: {n} rows in {time.time() - t0:.0f}s", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.execute("CREATE TABLE q (key TEXT NOT NULL, akey TEXT NOT NULL, source TEXT NOT NULL, marks TEXT NOT NULL, lemmas TEXT NOT NULL)")
    db.executemany("INSERT INTO q VALUES (?,?,?,?,?)",
                   ((k, accentless_key(k), s, m, "|".join(sorted(l for l in lem if l)))
                    for (k, s, m), lem in sorted(table.items())))
    db.execute("CREATE INDEX q_key ON q(key)")
    db.execute("CREATE INDEX q_akey ON q(akey)")
    db.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    db.execute("INSERT INTO meta VALUES ('counts', ?)", (json.dumps(counts),))
    db.execute("INSERT INTO meta VALUES ('built', ?)", (time.strftime("%Y-%m-%dT%H:%M:%S"),))
    db.commit()
    db.close()
    os.replace(tmp, out)
    print(f"{len(table)} distinct (key, source, marks) rows -> {out}")


if __name__ == "__main__":
    main()
