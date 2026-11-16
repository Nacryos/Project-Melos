#!/usr/bin/env python
"""Build data/morph_la.sqlite: every morphological reading of a Latin form, for backend/latin_morph.py and the
grammar checks L3 / L10 (backend/latin_grammar.py; docs/latin/grammar-check.md).

Sources, united under the normalised spelling (backend.latin_text.normalize_la):
- Winge's Morpheus table data/raw/latin/winge/macrons.txt (GPL): form, nine-place Perseus tag, lemma for whole
  generated paradigms (about 0.8 M rows), so forms the corpus never prints are read too.
- LASLA's hand tags from data/lemma_index_la.sqlite (licensed; the output is gitignored): the readings Catullus and
  Horace actually use, with the split enclitics (-que, -ne, -ve, -cum) recorded against their host.
It also counts, from the punctuated corpus text (data/corpus_la.sqlite), what the word-order check needs: where the
postpositive candidates and the prepositions stand in their sentences, and which letters an enclitic's host ends in.

Usage: .venv/bin/python scripts/build_morph_la.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_text import normalize_la, tokenize_la  # noqa: E402

DATA = ROOT / "data"
WINGE = DATA / "raw/latin/winge/macrons.txt"
LEMMA_INDEX = DATA / "lemma_index_la.sqlite"
CORPUS = DATA / "corpus_la.sqlite"
OUT = DATA / "morph_la.sqlite"

POS = {"n": "NOUN", "v": "VERB", "a": "ADJ", "d": "ADV", "c": "CONJ", "r": "ADP", "p": "PRON", "m": "NUM", "e": "INTJ",
       "i": "INTJ", "t": "VERB"}
NUMBER = {"s": "sg", "p": "pl"}
TENSE = {"p": "pres", "i": "impf", "r": "perf", "l": "plup", "t": "futp", "f": "fut"}
MOOD = {"i": "ind", "s": "subj", "n": "inf", "m": "imp", "p": "part", "d": "gerund", "g": "gerundive", "u": "supine"}
VOICE = {"a": "act", "p": "pass", "d": "act"}
CASE = {"n": "nom", "g": "gen", "d": "dat", "a": "acc", "b": "abl", "v": "voc", "l": "loc"}
DEGREE = {"c": "comp", "s": "sup"}
ENCLITICS = ("que", "ne", "ue", "cum")
UPOS = {"AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}
U_CASE = {"Nom": "nom", "Gen": "gen", "Dat": "dat", "Acc": "acc", "Abl": "abl", "Voc": "voc", "Loc": "loc"}
U_GENDER = {"Masc": "m", "Fem": "f", "Neut": "n"}
U_MOOD = {"Ind": "ind", "Sub": "subj", "Imp": "imp"}
U_VERBFORM = {"Part": "part", "Inf": "inf", "Ger": "gerund", "Gdv": "gerundive", "Sup": "supine"}
POSTPOSITIVE_CANDIDATES = ("enim", "autem", "uero", "quoque", "quidem", "igitur", "tamen", "ergo", "itaque", "namque",
                           "nam", "etiam", "tandem", "denique", "etenim", "sed", "at")
SENTENCE_END = re.compile(r"[.;?!:]")


def fold_lemma(lemma: str) -> str:
    return normalize_la(lemma).rstrip("0123456789")


def winge_rows():
    seen = set()
    with WINGE.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or len(parts[1]) != 9:
                continue
            form, tag, lemma = parts[0], parts[1], parts[2]
            if tag[0] not in POS:
                continue
            row = (normalize_la(form), fold_lemma(lemma), POS[tag[0]], CASE.get(tag[7], ""), NUMBER.get(tag[2], ""),
                   tag[6] if tag[6] in "mfn" else "", tag[1] if tag[1] in "123" else "", TENSE.get(tag[3], ""),
                   MOOD.get(tag[4], ""), VOICE.get(tag[5], ""), DEGREE.get(tag[8], ""), "", "morpheus")
            if row[0] and row not in seen:
                seen.add(row)
                yield row


def lasla_tense(f: dict) -> str:
    t, a = f.get("Tense", ""), f.get("Aspect", "")
    if t == "Pqp":
        return "plup"
    if t == "Fut":
        return "futp" if a == "Perf" else "fut"
    if t == "Past":
        return "perf" if a == "Perf" else "impf"
    if t == "Pres":
        return "perf" if a == "Perf" else "pres"
    return "perf" if a == "Perf" and f.get("VerbForm") == "Part" else ""


def lasla_rows():
    if not LEMMA_INDEX.exists():
        return
    db = sqlite3.connect(f"file:{LEMMA_INDEX.as_posix()}?mode=ro", uri=True)
    rows = db.execute("SELECT rowid, normalized, lemma, upos, feats FROM token ORDER BY rowid").fetchall()
    host_enclitic = {}
    for i, (rid, norm, lemma, _upos, _f) in enumerate(rows):
        if lemma in ENCLITICS and norm != lemma and norm.endswith(lemma) and i and rows[i - 1][1] == norm:
            host_enclitic[rows[i - 1][0]] = lemma
    seen = set()
    for rid, norm, lemma, upos, feats in rows:
        if lemma in ENCLITICS and norm != lemma and norm.endswith(lemma):
            continue
        f = dict(p.split("=", 1) for p in (feats or "").split("|") if "=" in p)
        mood = U_VERBFORM.get(f.get("VerbForm", ""), "") or U_MOOD.get(f.get("Mood", ""), "")
        genders = [U_GENDER[g] for g in f.get("Gender", "").split(",") if g in U_GENDER] or [""]
        degree = {"Cmp": "comp", "Abs": "sup", "Sup": "sup"}.get(f.get("Degree", ""), "")
        for g in genders:
            row = (norm, fold_lemma(lemma), UPOS.get(upos, upos), U_CASE.get(f.get("Case", ""), ""),
                   {"Sing": "sg", "Plur": "pl"}.get(f.get("Number", ""), ""), g, f.get("Person", ""),
                   lasla_tense(f) if upos in ("VERB", "AUX") else "", mood,
                   {"Act": "act", "Pass": "pass"}.get(f.get("Voice", ""), ""), degree,
                   host_enclitic.get(rid, ""), "lasla")
            if row not in seen:
                seen.add(row)
                yield row


def corpus_sentences(author: str | None = None):
    """Sentences of the Latin corpus text as lists of normalised words (split at . ; ? ! :)."""
    if not CORPUS.exists():
        return
    db = sqlite3.connect(f"file:{CORPUS.as_posix()}?mode=ro", uri=True)
    sql = "SELECT text FROM passages WHERE language='la' AND kind='text'" + (" AND author=?" if author else "")
    for (text,) in db.execute(sql, (author,) if author else ()):
        for s in SENTENCE_END.split(text):
            words = [normalize_la(w) for w in tokenize_la(s)]
            if words:
                yield words


def word_order_stats(prepositions: set[str], enclitic_forms: dict[str, str]) -> dict:
    post = {w: {"total": 0, "first": 0} for w in POSTPOSITIVE_CANDIDATES}
    for words in corpus_sentences():
        for i, w in enumerate(words):
            if w in post:
                post[w]["total"] += 1
                post[w]["first"] += i == 0
    prep = defaultdict(lambda: {"total": 0, "last": 0})
    encl_first, encl_total, host_final = Counter(), Counter(), Counter()
    for words in corpus_sentences("Catullus"):
        for i, w in enumerate(words):
            if w in prepositions:
                prep[w]["total"] += 1
                prep[w]["last"] += i == len(words) - 1
    for words in corpus_sentences():
        for i, w in enumerate(words):
            e = enclitic_forms.get(w)
            if e and e != "cum":
                encl_total[e] += 1
                encl_first[e] += i == 0
                host_final[e + ":" + w[: -len(e)][-1:]] += 1
    return {"postpositive": post, "preposition_catullus": dict(prep), "enclitic_total": dict(encl_total),
            "enclitic_first": dict(encl_first), "enclitic_host_final": dict(host_final)}


def main() -> None:
    tmp = OUT.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("CREATE TABLE m (key TEXT, lemma TEXT, pos TEXT, cas TEXT, number TEXT, gender TEXT, person TEXT, "
               "tense TEXT, mood TEXT, voice TEXT, degree TEXT, enclitic TEXT, source TEXT)")
    db.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    counts = Counter()
    enclitic_forms: dict[str, str] = {}
    lasla = list(lasla_rows())
    for r in lasla:
        if r[11]:
            enclitic_forms[r[0]] = r[11]
    db.executemany("INSERT INTO m VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lasla)
    counts["lasla"] = len(lasla)
    batch = []
    for r in winge_rows():
        batch.append(r)
        counts["morpheus"] += 1
        if len(batch) >= 50000:
            db.executemany("INSERT INTO m VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            batch = []
    db.executemany("INSERT INTO m VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    db.execute("CREATE INDEX m_key ON m(key)")
    preps = {r[0] for r in db.execute("SELECT DISTINCT key FROM m WHERE pos='ADP' AND enclitic=''")}
    stats = word_order_stats(preps, enclitic_forms)
    db.execute("INSERT INTO meta VALUES ('word_order', ?)", (json.dumps(stats, ensure_ascii=False),))
    db.execute("INSERT INTO meta VALUES ('rows', ?)", (json.dumps(dict(counts)),))
    db.commit()
    db.close()
    tmp.replace(OUT)
    print(f"{OUT}: {dict(counts)}")


if __name__ == "__main__":
    main()
