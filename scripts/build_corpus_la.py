#!/usr/bin/env python3
"""Build the Latin corpus partition data/corpus_la.sqlite from the open Latin sources under data/open/latin/
(perseus-catullus, perseus-horace, ...), with the same tables as the Greek corpus (scripts/build_corpus.py SCHEMA):
passages, works, passage_authors, tokens, vocabulary, metadata, passage_fts. One passage per poem (lines joined by
newlines; `data` holds the line numbers, metre milestone, source record and translation links); translations are
passages of kind `translation` with `data.translation_of` = the Latin passage id. `normalized` for Latin: lower case,
marks stripped, v -> u, j -> i (backend/latin_text.py), so u/v and i/j spellings meet in search and attestation.

Nothing is written from memory: every text comes from the ingested records, which carry their source file, URL and
sha256 in their folder's manifest. Usage: python scripts/build_corpus_la.py [--out data/corpus_la.sqlite]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_text import normalize_la, tokenize_la  # noqa: E402

SCHEMA = '''
CREATE TABLE passages (
 id TEXT PRIMARY KEY, work_id TEXT NOT NULL, source TEXT, author TEXT, work TEXT,
 edition TEXT, citation TEXT, language TEXT, kind TEXT, quality TEXT,
 text TEXT NOT NULL, normalized TEXT NOT NULL, data TEXT NOT NULL, sequence INTEGER,
 author_canonical TEXT, text_key TEXT);
CREATE TABLE works (id TEXT PRIMARY KEY, author TEXT, work TEXT, edition TEXT,
 source TEXT, language TEXT, count INTEGER, author_canonical TEXT);
CREATE TABLE passage_authors (passage_id TEXT, author_key TEXT);
CREATE TABLE tokens (passage_id TEXT, form TEXT, normalized TEXT, count INTEGER);
CREATE TABLE vocabulary (normalized TEXT PRIMARY KEY, form TEXT, count INTEGER);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized, citation, author, work,
 tokenize='unicode61 remove_diacritics 0');
CREATE INDEX tokens_norm ON tokens(normalized);
CREATE INDEX passages_author ON passages(author, kind, language);
'''

SOURCES = {
    "perseus-catullus": {"author": "Catullus", "work": "Carmina", "folder": "perseus-catullus"},
    "perseus-horace": {"author": "Horace", "work": None, "folder": "perseus-horace"},
}
WORK_OF_URN = {"phi0893.phi001": "Odes", "phi0893.phi002": "Carmen Saeculare", "phi0893.phi003": "Epodes",
               "phi0472.phi001": "Carmina"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "corpus_la.sqlite"))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    counts = Counter()
    vocab: dict[str, tuple[str, int]] = {}
    works: dict[str, dict] = {}
    seq = 0
    sources_seen = {}
    for name, spec in SOURCES.items():
        folder = ROOT / "data" / "open" / "latin" / spec["folder"]
        path = folder / "poems.jsonl"
        if not path.exists():
            print(f"skip {name}: {path} missing", file=sys.stderr)
            continue
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        sources_seen[name] = {"manifest": str((folder / "manifest.json").relative_to(ROOT)),
                              "licence": manifest.get("licence", {}).get("name", ""), "files": list(manifest.get("files", {}))}
        latin_ids: dict[tuple, str] = {}
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        rows.sort(key=lambda r: (r["language"] != "la", r.get("book", ""), _num(r["poem"])))
        for r in rows:
            urn_work = ".".join(r["urn"].split(":")[3].split(".")[:2]) if r.get("urn") else ""
            work = spec["work"] or WORK_OF_URN.get(urn_work, r.get("source_file", ""))
            book = r.get("book", "") or ""
            cit = f"{work} {book + '.' if book else ''}{r['poem']}"
            text = "\n".join(l["text"] for l in r["lines"])
            if not text.strip():
                counts["empty"] += 1
                continue
            pid = f"la:{name}:{r['source_file'].split('.perseus-')[1].split('.xml')[0]}:{book + ':' if book else ''}{r['poem']}"
            fm = manifest.get("files", {}).get(r["source_file"], {})
            data = {"line_numbers": [l["n"] for l in r["lines"]], "metre_milestone": r.get("metre_milestone", []),
                    "head": r.get("head", []), "notes": r.get("notes", []), "edition": r.get("edition", ""),
                    "source_record": {"file": r["source_file"], "url": fm.get("url", ""), "sha256": fm.get("sha256", ""),
                                      "fetched_at": fm.get("fetched_at", ""), "urn": r.get("urn", "")}}
            kind = "text" if r["language"] == "la" else "translation"
            if kind == "text":
                latin_ids[(book, r["poem"])] = pid
            else:
                data["translation_of"] = latin_ids.get((book, r["poem"]))
                data["translator"] = r.get("edition", "")
            work_id = f"la:{name}:{work}"
            if work_id not in works:
                works[work_id] = {"author": spec["author"], "work": work, "edition": fm.get("header", {}).get("source_editor", "") or r.get("edition", ""),
                                  "source": name, "language": "la", "count": 0}
            works[work_id]["count"] += kind == "text"
            seq += 1
            norm = normalize_la(text) if r["language"] == "la" else text.lower()
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, work_id, name, spec["author"], work, r.get("edition", ""), cit, r["language"], kind,
                         "source_text", text, norm, json.dumps(data, ensure_ascii=False), seq, spec["author"], None))
            con.execute("INSERT INTO passage_authors VALUES (?,?)", (pid, spec["author"].lower()))
            con.execute("INSERT INTO passage_fts VALUES (?,?,?,?,?)", (pid, norm, cit, spec["author"], work))
            counts[kind] += 1
            if kind == "text":
                tok = Counter()
                forms: dict[str, str] = {}
                for form in tokenize_la(text):
                    n = normalize_la(form)
                    if not n:
                        continue
                    tok[n] += 1
                    forms.setdefault(n, form)
                for n, c in tok.items():
                    con.execute("INSERT INTO tokens VALUES (?,?,?,?)", (pid, forms[n], n, c))
                    f0, c0 = vocab.get(n, (forms[n], 0))
                    vocab[n] = (f0, c0 + c)
                counts["tokens"] += sum(tok.values())
    for n, (f, c) in vocab.items():
        con.execute("INSERT INTO vocabulary VALUES (?,?,?)", (n, f, c))
    for wid, w in works.items():
        con.execute("INSERT INTO works VALUES (?,?,?,?,?,?,?,?)", (wid, w["author"], w["work"], w["edition"], w["source"], w["language"], w["count"], w["author"]))
    meta = {"built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "language": "la", "sources": sources_seen,
            "counts": dict(counts), "vocabulary": len(vocab), "normalization": "lower, marks stripped, v->u, j->i (backend/latin_text.py)"}
    con.execute("INSERT INTO metadata VALUES ('build', ?)", (json.dumps(meta),))
    con.commit()
    con.close()
    print(json.dumps(meta, indent=1), file=sys.stderr)


def _num(p: str) -> tuple:
    m = re.match(r"(\d+)(.*)", str(p))
    return (int(m.group(1)), m.group(2)) if m else (0, str(p))


if __name__ == "__main__":
    main()
