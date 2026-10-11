#!/usr/bin/env python3
"""Build the Latin lemma index data/lemma_index_la.sqlite (docs/latin/lemma-index.md).

Source 1 (recorded lemmas): LASLA v1.0.1 CoNLL-UP for Catullus and Horace (data/private/lasla/, CC BY-NC-SA 4.0; used
server-side under the owner's licensed-data policy: lemma ids and counts only, never the annotation itself in a UI).
Every LASLA token carries its citation (poem / book, carmen / verse); the builder aligns tokens to the lines of the
Perseus passages in data/corpus_la.sqlite (u/v, i/j folded; LASLA writes u only and splits enclitics -que, -ne, -ue,
-cum, which here attach to the host form), so a corpus token gets its human lemma, POS, morphology and LiLa id.
Source 2 (later): a lemmatiser for texts and typed forms outside LASLA (scripts/latin_lemmatiser_bakeoff.py).

Tables: token(passage_id, line_n, idx, form, normalized, lemma, upos, feats, lila, source, aligned);
form_lemma(normalized, lemma, upos, count); author_lemma(author, lemma, upos, count, in_corpus);
author_form(author, lemma, normalized, form, count, example_passage, example_line); lemma(lemma, upos, count); metadata.
Usage: python scripts/build_lemma_index_la.py [--out data/lemma_index_la.sqlite]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_text import normalize_la, tokenize_la  # noqa: E402

LASLA = ROOT / "data" / "private" / "lasla"
# LASLA file -> (author, work, passage id pattern); Horace works without a text in the corpus still count for the author
FILES = {
    "Catullus_Catullus_Catul.conllup": ("Catullus", "Carmina", "la:perseus-catullus:lat2:{poem}"),
    "Horatius_Carmina_HorCarm1.conllup": ("Horace", "Odes", "la:perseus-horace:odes:lat2:{book}.{poem}"),
    "Horatius_Carmina_HorCarm2.conllup": ("Horace", "Odes", "la:perseus-horace:odes:lat2:{book}.{poem}"),
    "Horatius_Carmina_HorCarm3.conllup": ("Horace", "Odes", "la:perseus-horace:odes:lat2:{book}.{poem}"),
    "Horatius_Carmina_HorCarm4.conllup": ("Horace", "Odes", "la:perseus-horace:odes:lat2:{book}.{poem}"),
    "Horatius_CarmenSaeculare_HorSaecu.conllup": ("Horace", "Carmen Saeculare", "la:perseus-horace:carmen-saeculare:lat2:1"),
    "Horatius_Epodi_HorEpodi.conllup": ("Horace", "Epodes", "la:perseus-horace:epodes:lat2:{poem}"),
    "Horatius_HorEpistulae_HorEpis1.conllup": ("Horace", "Epistles", None),
    "Horatius_HorEpistulae_HorEpis2.conllup": ("Horace", "Epistles", None),
    "Horatius_HorSermones_HorSerm1.conllup": ("Horace", "Satires", None),
    "Horatius_HorSermones_HorSerm2.conllup": ("Horace", "Satires", None),
    "Horatius_ArsPoetica_HorArsPo.conllup": ("Horace", "Ars Poetica", None),
}
SCHEMA = """
CREATE TABLE token (passage_id TEXT, line_n TEXT, idx INTEGER, form TEXT, normalized TEXT, lemma TEXT, upos TEXT, feats TEXT,
  lila TEXT, source TEXT, aligned INTEGER, author TEXT, work TEXT, citation TEXT);
CREATE TABLE form_lemma (normalized TEXT, lemma TEXT, upos TEXT, count INTEGER);
CREATE TABLE author_lemma (author TEXT, lemma TEXT, upos TEXT, count INTEGER, in_corpus INTEGER);
CREATE TABLE author_form (author TEXT, lemma TEXT, normalized TEXT, form TEXT, count INTEGER, example_passage TEXT, example_line TEXT);
CREATE TABLE lemma (lemma TEXT, upos TEXT, count INTEGER);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX token_norm ON token(normalized); CREATE INDEX token_lemma ON token(lemma); CREATE INDEX token_passage ON token(passage_id);
CREATE INDEX form_lemma_norm ON form_lemma(normalized); CREATE INDEX author_lemma_k ON author_lemma(author, lemma);
CREATE INDEX author_form_k ON author_form(author, lemma);
"""


def catullus_place(poem: str, verse: str) -> tuple[str, str]:
    """LASLA's Catullus numbering -> Merrill's (Perseus): 68.41-160 = 68a.1-120; 2b = 2.11-13; 14b = 14a; 58b = 55.23-32;
    78b = 78.7-10; 117 (a fragment) has no Perseus text."""
    try:
        v = int(verse)
    except (TypeError, ValueError):
        return poem, verse
    if poem == "68" and v > 40:
        return "68a", str(v - 40)
    if poem == "2b":
        return "2", str(10 + v)
    if poem == "14b":
        return "14a", verse
    if poem == "58b":
        return "55", str(22 + v)
    if poem == "78b":
        return "78", str(6 + v)
    return poem, verse


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def close(a: str, b: str) -> bool:
    """Edition spelling variants: cartis / chartis, quicquid / quidquid, Iupiter / Iuppiter, karum / carum."""
    if a == b:
        return True
    if a.rstrip("que") == b.rstrip("que") and a != b and (a.endswith("que") or b.endswith("que")):
        return True
    n = min(len(a), len(b))
    return n >= 4 and a[0] == b[0] and _lev(a, b) <= (1 if n < 8 else 2)


def cite(misc: str) -> dict:
    m = re.search(r"CitationHierarchy=([^|\t]*)", misc or "")
    out = {}
    for part in (m.group(1) if m else "").split(","):
        if "_" in part:
            k, v = part.split("_", 1)
            out[k.lower()] = v
    return out


def read_conllup(path: Path):
    """Yield per sentence: list of tokens {form, lemma, upos, feats, lila, cite, mw: multiword span or None}."""
    sent, mw = [], {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            if sent:
                yield sent
            sent, mw = [], {}
            continue
        if raw.startswith("#"):
            continue
        cols = raw.split("\t")
        tid = cols[0]
        if "-" in tid:                                  # multiword token line (quicum = qui + cum): remember the surface
            a, b = tid.split("-")
            for i in range(int(a), int(b) + 1):
                mw[str(i)] = (cols[1], tid)
            continue
        lila = next((c.split(":", 1)[1] for c in cols[13:] if c.startswith("lilaLemma:")), "")
        sent.append({"id": tid, "form": cols[1], "lemma": cols[2], "upos": cols[3], "feats": cols[5], "misc": cols[9] if len(cols) > 9 else "",
                     "lila": lila, "cite": cite(cols[9] if len(cols) > 9 else ""), "mw": mw.get(tid)})
    if sent:
        yield sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "lemma_index_la.sqlite"))
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus_la.sqlite"))
    args = ap.parse_args()
    corpus = sqlite3.connect(f"file:{Path(args.corpus).as_posix()}?mode=ro", uri=True)
    corpus.row_factory = sqlite3.Row
    passages = {r["id"]: r for r in corpus.execute("SELECT id, author, work, citation, text, json_extract(data,'$.line_numbers') AS lns FROM passages WHERE kind='text'")}
    out = Path(args.out)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    stats = Counter()
    form_lemma, author_lemma, author_form, lemma_count = Counter(), Counter(), Counter(), Counter()
    examples: dict = {}
    in_corpus_lemmas: dict = defaultdict(set)
    rows = []
    for fname, (author, work, pattern) in FILES.items():
        path = LASLA / fname
        if not path.exists():
            print("missing", fname, file=sys.stderr)
            continue
        # group LASLA tokens by (passage id, verse); then align each verse's tokens to the corpus line's words
        by_line: dict = defaultdict(list)
        for sent in read_conllup(path):
            for t in sent:
                c = t["cite"]
                poem = c.get("carmen") or c.get("poema") or c.get("liber")
                book = c.get("liber") if ("carmen" in c or "poema" in c) else ""
                verse = c.get("versus", "")
                if author == "Catullus":
                    poem, verse = catullus_place(poem, verse)
                pid = pattern.format(poem=poem, book=book) if pattern else None
                by_line[(pid, verse, author, work, f"{work} {book + '.' if book else ''}{poem or ''}")].append(t)
        for (pid, verse, auth, wk, citation), toks in by_line.items():
            passage = passages.get(pid) if pid else None
            line_text, line_words = "", []
            if passage is not None:
                lns = json.loads(passage["lns"]) if passage["lns"] else []
                lines = passage["text"].split("\n")
                try:
                    k = lns.index(str(verse))
                    line_text = lines[k]
                except ValueError:
                    line_text = ""
                line_words = [normalize_la(w) for w in tokenize_la(line_text)]
            # merge LASLA's split enclitics back into one surface token (quicum, Cupidinesque) for the alignment
            merged = []
            i = 0
            while i < len(toks):
                t = toks[i]
                if t["mw"] and i + 1 < len(toks) and toks[i + 1]["mw"] == t["mw"]:
                    merged.append({"form": t["mw"][0], "parts": [t, toks[i + 1]]}); i += 2
                else:
                    merged.append({"form": t["form"], "parts": [t]}); i += 1
            # greedy in-order alignment of LASLA surface forms to the corpus line's words: exact, then a spelling
            # variant (close), then LASLA's joined form against two corpus words (nescioquid = nescio quid)
            j = 0
            for m in merged:
                n = normalize_la(m["form"])
                aligned, idx = 0, -1
                for jj in range(j, min(j + 3, len(line_words))):
                    if line_words[jj] == n or close(line_words[jj], n):
                        idx, aligned, j = jj, 1, jj + 1
                        break
                    if jj + 1 < len(line_words) and line_words[jj] + line_words[jj + 1] == n:
                        idx, aligned, j = jj, 1, jj + 2
                        break
                stats["aligned" if aligned else ("unaligned_in_corpus" if passage is not None else "no_text")] += 1
                for part in m["parts"]:
                    lem, upos = part["lemma"], part["upos"]
                    pn = normalize_la(part["form"])
                    rows.append((pid, str(verse), idx, m["form"], n, lem, upos, part["feats"], part["lila"], "lasla", aligned, auth, wk, citation))
                    form_lemma[(pn, lem, upos)] += 1
                    if n != pn:
                        form_lemma[(n, lem, upos)] += 1          # the host spelling with its enclitic also maps to the lemma
                    author_lemma[(auth, lem, upos)] += 1
                    lemma_count[(lem, upos)] += 1
                    if passage is not None:
                        in_corpus_lemmas[auth].add((lem, upos))
                    author_form[(auth, lem, pn, part["form"])] += 1
                    if (auth, lem, pn) not in examples and line_text:
                        examples[(auth, lem, pn)] = (pid, line_text)
    db.executemany("INSERT INTO token VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO form_lemma VALUES (?,?,?,?)", [(n, l, u, c) for (n, l, u), c in form_lemma.items()])
    db.executemany("INSERT INTO author_lemma VALUES (?,?,?,?,?)", [(a, l, u, c, int((l, u) in in_corpus_lemmas[a])) for (a, l, u), c in author_lemma.items()])
    db.executemany("INSERT INTO author_form VALUES (?,?,?,?,?,?,?)", [(a, l, n, f, c, *(examples.get((a, l, n)) or (None, None))) for (a, l, n, f), c in author_form.items()])
    db.executemany("INSERT INTO lemma VALUES (?,?,?)", [(l, u, c) for (l, u), c in lemma_count.items()])
    meta = {"built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "tokens": len(rows), "alignment": dict(stats),
            "lemmas": len(lemma_count), "forms": len({n for n, _, _ in form_lemma}),
            "source": "LASLA v1.0.1 (CIRCSE/LASLA), CC BY-NC-SA 4.0, data/private/lasla; server-side use only (owner's licensed-data policy)",
            "files": list(FILES)}
    db.execute("INSERT INTO metadata VALUES ('build', ?)", (json.dumps(meta),))
    db.commit()
    print(json.dumps(meta, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
