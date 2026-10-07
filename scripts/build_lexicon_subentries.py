"""Build an isolated candidate LSJ subentry evidence index from archived XML.

No downloads, invented data, or production corpus changes. The resulting
candidate requires independent audit before any production integration.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.lexicon_subentries import VERSION, extract_subentries


def build(source, destination, entry_ids=None):
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing subentry index")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    db = sqlite3.connect(destination)
    db.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                     "CREATE TABLE subentries(id TEXT PRIMARY KEY,lookup_key TEXT NOT NULL,record_json TEXT NOT NULL);"
                     "CREATE INDEX subentry_keys ON subentries(lookup_key);")
    entries = count = 0
    try:
        for line in source.open(encoding="utf8"):
            record = json.loads(line)
            if record.get("source") != "PerseusDL LSJ TEI" or entry_ids and record["id"] not in entry_ids:
                continue
            entries += 1
            for row in extract_subentries(record):
                db.execute("INSERT INTO subentries VALUES(?,?,?)",
                           (row["id"], row["lookup_key"], json.dumps(row, ensure_ascii=False, sort_keys=True)))
                count += 1
            if entries % 5000 == 0:
                print(f"Read {entries} LSJ entries; {count} source-bound subentries", flush=True)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("Lexicon source manifest changed during build")
        metadata = {"version": VERSION, "input_sha256": digest,
                    "entries_examined": str(entries), "subentries": str(count),
                    "audit_status": "candidate_requires_independent_audit"}
        db.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/lexica/entries.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry-id", action="append")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, set(args.entry_id or [])), indent=2))
