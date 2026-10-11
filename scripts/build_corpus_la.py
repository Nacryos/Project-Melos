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
INTERLINEARS = [
    {"folder": "interlinear-catullus", "file": "catullus-interlinear.jsonl", "author": "Catullus", "work": "Carmina",
     "work_id": "la:perseus-catullus:Carmina", "translator": "Claude Opus (machine_translation; audited and revised)",
     "key": lambda r: r["poem"], "latin_id": lambda k: f"la:perseus-catullus:lat2:{k}", "citation": lambda k: f"Carmina {k}"},
    {"folder": "interlinear-horace", "file": "odes-interlinear.jsonl", "manifest_work": "odes", "author": "Horace", "work": "Odes",
     "work_id": "la:perseus-horace:Odes", "translator": "Claude (machine_translation; Opus writers and the session inline, audited and revised)",
     "key": lambda r: f"{r['book']}.{r['poem']}", "latin_id": lambda k: f"la:perseus-horace:odes:lat2:{k}", "citation": lambda k: f"Odes {k}"},
    {"folder": "interlinear-horace", "file": "epodes-interlinear.jsonl", "manifest_work": "epodes", "author": "Horace", "work": "Epodes",
     "work_id": "la:perseus-horace:Epodes", "translator": "Claude Opus (machine_translation; audited and revised)",
     "key": lambda r: f"epodes:{r['poem']}", "latin_id": lambda k: f"la:perseus-horace:epodes:lat2:{k.split(':')[1]}",
     "citation": lambda k: f"Epodes {k.split(':')[1]}"},
    {"folder": "interlinear-horace", "file": "carmen-saeculare-interlinear.jsonl", "manifest_work": "carmen-saeculare", "author": "Horace",
     "work": "Carmen Saeculare", "work_id": "la:perseus-horace:Carmen Saeculare", "translator": "Claude Opus (machine_translation; audited and revised)",
     "key": lambda r: "carmen-saeculare:1", "latin_id": lambda k: "la:perseus-horace:carmen-saeculare:lat2:1", "citation": lambda k: "Carmen Saeculare"},
]
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
            pid = f"la:{name}:{r['id'].split('perseus:', 1)[1]}"          # the record's own id (unique per source)
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
    # The Claude-written interlinears (Catullus: data/open/latin/interlinear-catullus/catullus-interlinear.jsonl; Horace Odes:
    # data/open/latin/interlinear-horace/odes-interlinear.jsonl): one translation passage per poem, quality machine_translation,
    # shown only where no human translation exists (release X rule).
    for spec in INTERLINEARS:
        inter = ROOT / "data" / "open" / "latin" / spec["folder"] / spec["file"]
        if not inter.exists():
            continue
        imeta = json.loads((inter.parent / "manifest.json").read_text(encoding="utf-8"))
        if spec.get("manifest_work"):
            imeta = imeta.get("works", {}).get(spec["manifest_work"], {})
        by_poem: dict[str, list[dict]] = {}
        for raw in inter.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                r = json.loads(raw)
                by_poem.setdefault(spec["key"](r), []).append(r)
        for poem, lines in by_poem.items():
            latin_id = spec["latin_id"](poem)
            if not con.execute("SELECT 1 FROM passages WHERE id=?", (latin_id,)).fetchone():
                counts["interlinear_unmatched_poem"] += 1
                continue
            text = "\n".join(l["english"] for l in lines)
            pid = f"la:{spec['folder']}:{poem}"
            cit = spec["citation"](poem)
            data = {"translation_of": latin_id, "translator": spec["translator"],
                    "line_numbers": [l["n"] for l in lines], "notes": [l["note"] for l in lines],
                    "audit": [l["audit"]["verdict"] for l in lines], "revised": [l["revised"] for l in lines],
                    "source_record": {"file": inter.name, "sha256": imeta.get("sha256", ""), "manifest": str(inter.parent.relative_to(ROOT) / "manifest.json")}}
            seq += 1
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, spec["work_id"], spec["folder"], spec["author"], spec["work"], "Claude interlinear",
                         cit, "en", "translation", "machine_translation", text, text.lower(),
                         json.dumps(data, ensure_ascii=False), seq, spec["author"], None))
            con.execute("INSERT INTO passage_authors VALUES (?,?)", (pid, spec["author"].lower()))
            con.execute("INSERT INTO passage_fts VALUES (?,?,?,?,?)", (pid, text.lower(), cit, spec["author"], spec["work"]))
            counts["interlinear"] += 1
        sources_seen[f"{spec['folder']}:{spec['file']}"] = {"manifest": str(inter.parent.relative_to(ROOT) / "manifest.json"),
                                                            "licence": "Claude-written, quality machine_translation", "lines": imeta.get("counts", {}).get("lines")}
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
