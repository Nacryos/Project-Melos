"""Release U: precompute dictionary entry renderings (backend.lexicon_render.render_source_record).

A word lookup renders every dictionary entry of each candidate headword (TEI to display text plus the parsed
sense tree); a big entry (LSJ ὁ, σύ) takes 10-40 ms and a first click on a common word rendered dozens. This
script renders each dictionary record the reader's lookup can show with the same function and stores the
result, keyed by raw path, entry id, raw SHA-256 and record id (a changed source has another hash, so a stale
rendering never matches). The server reads it through MELOS_RENDER_CACHE; without it, renderings are made on
demand as before. A round trip through JSON must reproduce each rendering exactly or the record is skipped.

    python scripts/build_render_cache.py --out /u-data/render_cache.sqlite [--workers 6] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROWS = []


def _work(bounds):
    from backend.lexicon_render import _render_key, _render_source_record
    out, skipped = [], 0
    for row in _ROWS[bounds[0]:bounds[1]]:
        key = _render_key(row)
        if key is None:
            continue
        try:
            value = _render_source_record(row)
        except Exception:  # noqa: BLE001 - the server renders such a record on demand, as before
            skipped += 1
            continue
        text = json.dumps(value, ensure_ascii=False)
        if json.loads(text) != value:
            skipped += 1
            continue
        out.append((key, zlib.compress(text.encode("utf-8"), 6)))
    return out, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    t0 = time.time()
    from backend.server import morph_service
    service = morph_service()
    service._load()
    seen = set()
    for bucket in service._entries.values():
        for row in service._visible(bucket):
            ident = (row.get("raw_path"), row.get("entry_id"), row.get("raw_sha256"), row.get("id"))
            if ident not in seen:
                seen.add(ident)
                _ROWS.append(row)
    if args.limit:
        _ROWS[:] = _ROWS[: args.limit]
    print(time.strftime("%H:%M:%S"), "records", len(_ROWS), "loaded in", round(time.time() - t0, 1), "s", flush=True)
    out = Path(args.out)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript("CREATE TABLE rendered(key TEXT PRIMARY KEY, value BLOB NOT NULL) WITHOUT ROWID;"
                     "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
    step = 500
    chunks = [(i, min(i + step, len(_ROWS))) for i in range(0, len(_ROWS), step)]
    stored = skipped = 0
    with mp.get_context("fork").Pool(args.workers) as pool:
        for n, (rows, bad) in enumerate(pool.imap_unordered(_work, chunks), 1):
            db.executemany("INSERT OR REPLACE INTO rendered VALUES (?,?)", rows)
            stored += len(rows)
            skipped += bad
            if n % 20 == 0:
                db.commit()
                print(time.strftime("%H:%M:%S"), n, "/", len(chunks), "chunks", stored, "stored", flush=True)
    manifest = {"version": "u1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "records": len(_ROWS),
                "stored": stored, "skipped": skipped, "seconds": round(time.time() - t0)}
    db.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest),))
    db.commit()
    db.close()
    tmp.replace(out)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
