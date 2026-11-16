#!/usr/bin/env python3
"""Build data/reference_la.sqlite: the Latin composer's reference stores, read by backend/latin_reference.py.

Sources (all public-domain books; see docs/latin/reference-stores.md):
  data/open/latin/merrill-commentary/notes.jsonl, intro.jsonl   (scripts/ingest_open_merrill_commentary.py)
  data/open/latin/allen-greenough/sections.jsonl                (scripts/ingest_open_allen_greenough.py)
Tables: merrill_notes, merrill_intro, ag_sections (the rows as ingested, in source order `seq`), each with an FTS5
table over the folded text (lower case, marks stripped, v -> u, j -> i: backend.latin_text.normalize_la), and
note_words(note_id, form, lemma, place): every Latin word of a note's lemma phrase (place 'lemma') and of the Latin
phrases Merrill prints inside the note (place 'latin'), with the lemmas backend.latin_lemma gives the form when the
lemma index is built (else the form alone), so an inflected word finds the note on its headword. metadata(key, value).
Usage: python scripts/build_reference_la.py [--out data/reference_la.sqlite]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import latin_lemma  # noqa: E402
from backend.latin_text import normalize_la, tokenize_la  # noqa: E402

OPEN = ROOT / "data" / "open" / "latin"
SCHEMA = """
CREATE TABLE merrill_notes(id TEXT PRIMARY KEY, seq INTEGER, poem TEXT, line TEXT, line_start INTEGER, line_end INTEGER,
                           kind TEXT, lemma TEXT, text TEXT, source_url TEXT);
CREATE INDEX merrill_notes_poem ON merrill_notes(poem, line_start);
CREATE TABLE merrill_intro(id TEXT PRIMARY KEY, seq INTEGER, section TEXT, heading_n TEXT, heading TEXT, text TEXT, source_url TEXT);
CREATE TABLE ag_sections(id TEXT PRIMARY KEY, seq INTEGER, section TEXT, sub TEXT, heading_path TEXT, text TEXT, source_url TEXT);
CREATE INDEX ag_sections_section ON ag_sections(section, seq);
CREATE TABLE ag_subjects(id TEXT PRIMARY KEY, seq INTEGER, source TEXT, subject TEXT, detail TEXT, head_fold TEXT, fold TEXT,
                         ref TEXT, row_id TEXT, confirmed INTEGER);
CREATE TABLE note_words(note_id TEXT, form TEXT, lemma TEXT, place TEXT);
CREATE INDEX note_words_form ON note_words(form);
CREATE INDEX note_words_lemma ON note_words(lemma);
CREATE VIRTUAL TABLE merrill_notes_fts USING fts5(id UNINDEXED, lemma, text, tokenize='unicode61');
CREATE VIRTUAL TABLE merrill_intro_fts USING fts5(id UNINDEXED, heading, text, tokenize='unicode61');
CREATE VIRTUAL TABLE ag_sections_fts USING fts5(id UNINDEXED, heading, text, tokenize='unicode61');
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
"""


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def lemmas(form: str) -> set[str]:
    out = {form}
    try:
        out |= {normalize_la(r["lemma"]) for r in latin_lemma.readings(form) if r.get("lemma")}
    except Exception:  # noqa: BLE001 - the lemma index is optional
        pass
    return {x for x in out if x}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "reference_la.sqlite"))
    args = ap.parse_args()
    out = Path(args.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    notes = rows(OPEN / "merrill-commentary" / "notes.jsonl")
    intro = rows(OPEN / "merrill-commentary" / "intro.jsonl")
    ag = rows(OPEN / "allen-greenough" / "sections.jsonl")
    n_words = 0
    for seq, r in enumerate(notes):
        db.execute("INSERT INTO merrill_notes VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (r["id"], seq, r["poem"], r["line"], r["line_start"], r["line_end"], r["kind"], r["lemma"], r["text"], r["source_url"]))
        db.execute("INSERT INTO merrill_notes_fts VALUES (?,?,?)", (r["id"], normalize_la(r["lemma"]), normalize_la(r["text"])))
        seen = set()
        for place, phrases in (("lemma", [r["lemma"]]), ("latin", r.get("latin") or [])):
            for phrase in phrases:
                for tok in tokenize_la(phrase):
                    form = normalize_la(tok)
                    for lem in lemmas(form):
                        if (form, lem, place) not in seen:
                            seen.add((form, lem, place))
                            db.execute("INSERT INTO note_words VALUES (?,?,?,?)", (r["id"], form, lem, place))
                            n_words += 1
    for seq, r in enumerate(intro):
        db.execute("INSERT INTO merrill_intro VALUES (?,?,?,?,?,?,?)",
                   (r["id"], seq, r["section"], r["heading_n"], r["heading"], r["text"], r["source_url"]))
        db.execute("INSERT INTO merrill_intro_fts VALUES (?,?,?)", (r["id"], normalize_la(r["heading"]), normalize_la(r["text"])))
    for seq, r in enumerate(ag):
        path = " > ".join(r["heading_path"])
        db.execute("INSERT INTO ag_sections VALUES (?,?,?,?,?,?,?)",
                   (r["id"], seq, r["section"], r["sub"], json.dumps(r["heading_path"], ensure_ascii=False), r["text"], r["source_url"]))
        db.execute("INSERT INTO ag_sections_fts VALUES (?,?,?)", (r["id"], normalize_la(path), normalize_la(r["text"])))
    subjects = rows(OPEN / "allen-greenough" / "subjects.jsonl")     # the book's index (OCR) and the TEI's headings
    for seq, r in enumerate(subjects):
        head = " ".join(normalize_la(t) for t in tokenize_la(r["subject"]))
        both = " ".join(normalize_la(t) for t in tokenize_la(r["subject"] + " " + r["detail"]))
        db.execute("INSERT INTO ag_subjects VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (r["id"], seq, r["source"], r["subject"], r["detail"], head, both, r["ref"], r["row"], int(r["confirmed"])))
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "merrill_notes": len(notes),
            "merrill_intro": len(intro), "ag_rows": len(ag), "note_words": n_words,
            "ag_subjects": len(subjects), "ag_subjects_confirmed": sum(bool(r["confirmed"]) for r in subjects),
            "lemma_index": "used" if latin_lemma.available() else "absent: note words carry their printed form only"}
    for name in ("merrill-commentary", "allen-greenough"):
        m = OPEN / name / "manifest.json"
        if m.exists():
            meta[f"manifest:{name}"] = json.dumps(json.loads(m.read_text(encoding="utf-8")).get("licence", {}), ensure_ascii=False)
    db.executemany("INSERT INTO metadata VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, out)
    print(json.dumps({k: v for k, v in meta.items() if not k.startswith("manifest:")}), file=sys.stderr)


if __name__ == "__main__":
    main()
