"""Transfer verified successful cached responses without operational counters.

Export is read-only. Import defaults to a read-only preview; --apply inserts
only absent keys and immutable receipts in one transaction. No network calls.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.machine_morphology import (MachineMorphologyService, PARSER_VERSION,
                                       MAX_RESPONSE, validate_form)

FORMAT = "melos-successful-morphology-receipts-v1"
MAX_BUNDLE = 64 * 1024 * 1024


class _Validator(MachineMorphologyService):
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def _connect(self):
        # Bypass service schema initialization: source and preview stay read-only.
        yield self.connection


@contextmanager
def connect(path, write=False):
    connection = sqlite3.connect(Path(path).resolve().as_uri() +
                                 ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def validate(connection, key, receipt_id, metadata, raw):
    if not isinstance(metadata, str) or len(metadata.encode()) > 4096:
        raise ValueError("Invalid receipt metadata size")
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
        raise ValueError("Invalid receipt body size")
    provenance = json.loads(metadata)
    # Elided queries retain their source spelling separately from the
    # documented Alpheios transport spelling; legacy intact receipts do not.
    form = validate_form(provenance.get("source_form", provenance["request_form"]))
    expected = hashlib.sha256((PARSER_VERSION + "\n" + form).encode()).hexdigest()
    if key != expected:
        raise ValueError("Cache key does not bind the exact source form/parser")
    result = _Validator(connection).load_receipt(receipt_id, form=form)
    # A verified empty-result envelope (no_analyses) is a successful upstream
    # answer too: it lets the reader try labelled spelling normalisations
    # instead of treating the form as never looked up.
    if result["status"] not in ("ok", "no_analyses") or (result["status"] == "ok" and not result["machine_candidates"]):
        raise ValueError("Receipt is not a verified successful analysis")
    return {"form": form, "candidates": len(result["machine_candidates"]), "status": result["status"]}


def export_bundle(database, output):
    entries, skipped = [], 0
    with connect(database) as connection:
        connection.execute("BEGIN")
        for row in connection.execute("SELECT c.key,c.receipt_id,r.metadata,r.raw "
                                      "FROM cache c JOIN receipts r ON r.id=c.receipt_id "
                                      "WHERE c.expires IS NULL ORDER BY c.key"):
            try:
                validate(connection, *row)
            except (ValueError, KeyError, TypeError):
                skipped += 1
                continue
            entries.append({"key": row["key"], "receipt_id": row["receipt_id"],
                            "metadata": row["metadata"],
                            "raw_base64": base64.b64encode(row["raw"]).decode("ascii")})
    bundle = {"format": FORMAT, "parser_version": PARSER_VERSION, "entries": entries}
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_BUNDLE:
        raise ValueError("Bundle exceeds transfer limit")
    with Path(output).open("xb") as stream:
        stream.write(encoded)
    return {"exported": len(entries), "skipped": skipped,
            "sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def read_bundle(path):
    with Path(path).open("rb") as stream:
        encoded = stream.read(MAX_BUNDLE + 1)
    if len(encoded) > MAX_BUNDLE:
        raise ValueError("Bundle exceeds transfer limit")
    bundle = json.loads(encoded)
    if bundle.get("format") != FORMAT or bundle.get("parser_version") != PARSER_VERSION:
        raise ValueError("Unsupported bundle/parser version")
    entries = bundle["entries"]
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError("Invalid entries")
    memory = sqlite3.connect(":memory:")
    memory.row_factory = sqlite3.Row
    memory.execute("CREATE TABLE receipts(id TEXT PRIMARY KEY,metadata TEXT,raw BLOB)")
    result, keys = [], set()
    try:
        for row in entries:
            key, receipt_id, metadata = row["key"], row["receipt_id"], row["metadata"]
            raw = base64.b64decode(row["raw_base64"], validate=True)
            if key in keys:
                raise ValueError("Duplicate cache key")
            keys.add(key)
            memory.execute("INSERT INTO receipts VALUES(?,?,?)", (receipt_id, metadata, raw))
            info = validate(memory, key, receipt_id, metadata, raw)
            result.append((key, receipt_id, metadata, raw, info))
    finally:
        memory.close()
    return result


def import_bundle(database, bundle, apply=False):
    entries = read_bundle(bundle)
    service = MachineMorphologyService(database)
    with connect(database, write=apply) as connection:
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        # Existing production schema is required; no migration or initialization.
        counts = {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("receipts", "cache", "attempts", "inflight", "failures")}
        pending, skipped = [], []
        for key, receipt_id, metadata, raw, info in entries:
            if connection.execute("SELECT 1 FROM cache WHERE key=?", (key,)).fetchone():
                skipped.append({**info, "reason": "existing_key"})
                continue
            if connection.execute("SELECT 1 FROM inflight WHERE key=?", (key,)).fetchone():
                skipped.append({**info, "reason": "inflight_key"})
                continue
            existing = connection.execute("SELECT metadata,raw FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if existing is not None and tuple(existing) != (metadata, raw):
                raise ValueError("Immutable receipt conflict")
            pending.append((key, receipt_id, metadata, raw, info, existing is None))
        stored = connection.execute("SELECT COALESCE(SUM(length(raw)+length(CAST(metadata AS BLOB))),0) FROM receipts").fetchone()[0]
        fresh = [row for row in pending if row[5]]
        if (counts["receipts"] + len(fresh) + counts["inflight"] > 10000 or
                stored + sum(len(row[2].encode()) + len(row[3]) for row in fresh) +
                counts["inflight"] * (MAX_RESPONSE + 4096) > service.max_bytes):
            raise ValueError("Import would exceed service receipt capacity")
        if apply:
            for key, receipt_id, metadata, raw, info, is_new in pending:
                if is_new:
                    connection.execute("INSERT INTO receipts VALUES(?,?,?)", (receipt_id, metadata, raw))
                connection.execute("INSERT INTO cache(key,receipt_id,expires) VALUES(?,?,NULL)", (key, receipt_id))
                validate(connection, key, receipt_id, metadata, raw)
            for table in ("attempts", "inflight", "failures"):
                if connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] != counts[table]:
                    raise ValueError("Operational counters changed during import")
        return {"mode": "applied" if apply else "preview", "eligible": len(entries),
                "missing": len(pending), "new_receipts": len(fresh), "before_counts": counts,
                "entries": [row[4] for row in pending], "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("database", type=Path)
    export.add_argument("output", type=Path)
    ingest = commands.add_parser("import")
    ingest.add_argument("database", type=Path)
    ingest.add_argument("bundle", type=Path)
    ingest.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (export_bundle(args.database, args.output) if args.command == "export"
              else import_bundle(args.database, args.bundle, args.apply))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
