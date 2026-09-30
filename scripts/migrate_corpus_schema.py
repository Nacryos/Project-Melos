"""Upgrade an existing corpus.sqlite to the author-merging / mirror-grouping schema.

`scripts/build_corpus.py` writes `author_canonical` and `text_key` columns and a
`passage_authors` table. A deployment that only holds the built SQLite (no
collector JSONL) cannot rebuild, so this script derives those columns from the
rows already in the index and replaces the file atomically. Every value comes
from the row itself: the merged author name from `backend/author_aliases.json`
applied to the stored label, and the text key from the stored language, kind
and words. No passage text, label or provenance changes.

With --promote-corrected-ocr, Open Greek Corpus rows typed `text` with quality
`machine_ocr`, whose stored quality screening marks the block an unflagged OCR
candidate and whose edition the pinned OGC README marks auto-corrected, are
relabelled `machine_corrected_ocr` and tokenised so word and form search reach
them (owner decision 2026-09-30, docs/decisions.md). The README is fetched from
the commit recorded in the rows' source URLs unless --readme points to a copy.

Usage:
  python scripts/migrate_corpus_schema.py --db /path/to/corpus.sqlite [--promote-corrected-ocr] [--readme README.md]

The upgraded file replaces --db in place; the previous file is kept beside it
as <name>.before-migrate-<timestamp>.sqlite unless --no-backup is given.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.author_aliases import canonical as canonical_author, canonical_key, component_keys  # noqa: E402
from backend.textutils import normalize, tokenize, text_key  # noqa: E402

try:  # newer indexes join Greek line-end word divisions in a search copy
    from backend.textutils import search_text  # noqa: E402
except ImportError:  # pragma: no cover - older checkout
    def search_text(text):
        return text

OCR_STATUSES = {"raw ocr", "auto-corrected", "manual"}
COMMIT_IN_URL = re.compile(r"open-greek-corpus/([0-9a-f]{40})/")


def ocr_status_table(readme: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for line in readme.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[-1].lower() in OCR_STATUSES:
            table[cells[0].strip("`")] = cells[-1].lower()
    return table


def has_column(con: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def load_readme(con: sqlite3.Connection, readme_path: Path | None) -> dict[str, str]:
    if readme_path is not None:
        return ocr_status_table(readme_path.read_text(encoding="utf-8-sig", errors="replace"))
    row = con.execute("SELECT json_extract(data,'$.source_url') FROM passages WHERE source='ogc' LIMIT 1").fetchone()
    match = COMMIT_IN_URL.search(row[0] or "") if row else None
    if not match:
        raise ValueError("Cannot find the pinned OGC commit in the index; pass --readme")
    url = f"https://raw.githubusercontent.com/open-greek/open-greek-corpus/{match.group(1)}/README.md"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "melos-migrate/1.0"}), timeout=60) as response:
        return ocr_status_table(response.read().decode("utf-8-sig", errors="replace"))


def migrate(db: Path, *, promote: bool, readme_path: Path | None, backup: bool) -> dict:
    if not db.is_file():
        raise FileNotFoundError(db)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    working = db.with_name(f"{db.stem}.migrating-{stamp}.sqlite")
    shutil.copyfile(db, working)
    report: dict = {"input": str(db), "started_at": stamp}
    con = sqlite3.connect(working)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        added_columns = []
        for table, column in (("passages", "author_canonical"), ("passages", "text_key"), ("works", "author_canonical")):
            if not has_column(con, table, column):
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                added_columns.append(f"{table}.{column}")
        if has_table(con, "passage_authors"):
            con.execute("DELETE FROM passage_authors")
        else:
            con.execute("CREATE TABLE passage_authors (passage_id TEXT, author_key TEXT)")
        rows = con.execute("SELECT id, author, language, kind, text FROM passages").fetchall()
        canonical_keys = set()
        author_rows = []
        updates = []
        for identifier, author, language, kind, text in rows:
            canonical_keys.add(canonical_key(author or ""))
            updates.append((canonical_author(author or ""), text_key(language, kind, text), identifier))
            author_rows.extend((identifier, key) for key in component_keys(author or ""))
        con.executemany("UPDATE passages SET author_canonical=?, text_key=? WHERE id=?", updates)
        con.executemany("INSERT INTO passage_authors VALUES (?,?)", author_rows)
        con.executemany("UPDATE works SET author_canonical=? WHERE id=?",
                        [(canonical_author(author or ""), work_id) for work_id, author in con.execute("SELECT id, author FROM works")])
        report["passages"] = len(rows)
        report["author_keys"] = len(author_rows)
        report["merged_authors"] = len(canonical_keys)
        promoted = 0
        if promote:
            statuses = load_readme(con, readme_path)
            if not statuses:
                raise ValueError("No OCR-status rows found in the OGC README")
            candidates = con.execute(
                "SELECT id, data, language, text FROM passages WHERE source='ogc' AND kind='text' AND quality='machine_ocr'").fetchall()
            for identifier, data, language, text in candidates:
                record = json.loads(data)
                metadata = record.get("metadata") or {}
                screening = metadata.get("quality_screening") or {}
                urn = metadata.get("ogc_urn") or ""
                if statuses.get(urn) != "auto-corrected":
                    continue
                if screening.get("block_label") not in ("ocr_text_candidate", "clean_source_text"):
                    continue
                if screening.get("bibliographic_scope", "poetry") != "poetry":
                    continue
                metadata["original_index_classification"] = {"kind": record.get("kind"), "quality": record.get("quality")}
                metadata["ocr_status"] = "auto-corrected"
                metadata["promotion_basis"] = "scripts/migrate_corpus_schema.py; docs/decisions.md 2026-09-30"
                record["quality"] = "machine_corrected_ocr"
                record["metadata"] = metadata
                con.execute("UPDATE passages SET quality='machine_corrected_ocr', data=? WHERE id=?",
                            (json.dumps(record, ensure_ascii=False), identifier))
                indexed = search_text(text) if language == "grc" else text
                tokens = collections.Counter(tokenize(indexed))
                con.execute("DELETE FROM tokens WHERE passage_id=?", (identifier,))
                con.executemany("INSERT INTO tokens VALUES (?,?,?,?)",
                                [(identifier, word, normalize(word), count) for word, count in tokens.items()])
                promoted += 1
            if promoted:
                # The candidate may already have token rows in an older index.
                # Rebuild this disposable aggregate from all current tokens so
                # removed forms cannot linger and repeated migration is stable.
                con.execute("DELETE FROM vocabulary")
                con.execute("INSERT INTO vocabulary (normalized,form,count) "
                            "SELECT normalized,MIN(form),SUM(count) FROM tokens GROUP BY normalized")
        report["promoted_corrected_ocr"] = promoted
        con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_passage_canonical ON passages(author_canonical);
            CREATE INDEX IF NOT EXISTS idx_passage_mirror ON passages(author_canonical,text_key);
            CREATE INDEX IF NOT EXISTS idx_passage_authors_key ON passage_authors(author_key,passage_id);
            CREATE INDEX IF NOT EXISTS idx_passage_authors_id ON passage_authors(passage_id);
        """)
        manifest_row = con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        manifest = json.loads(manifest_row[0]) if manifest_row else {}
        manifest["schema"] = 2
        manifest["searchable_qualities"] = ["source_text", "machine_corrected_ocr"]
        manifest["vocabulary"] = con.execute("SELECT count(*) FROM vocabulary").fetchone()[0]
        manifest.setdefault("migrations", []).append({"script": "scripts/migrate_corpus_schema.py", "at": stamp,
                                                      "added_columns": added_columns, "promoted_corrected_ocr": promoted})
        statistics = manifest.setdefault("statistics", {})
        statistics["authors"] = len(canonical_keys)
        statistics["author_labels"] = con.execute("SELECT count(DISTINCT author) FROM passages").fetchone()[0]
        statistics["quality"] = [{"quality": quality, "count": count} for quality, count in
                                 con.execute("SELECT quality, count(*) FROM passages GROUP BY quality ORDER BY quality")]
        con.execute("INSERT OR REPLACE INTO metadata VALUES ('manifest', ?)", (json.dumps(manifest),))
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity check failed: {integrity}")
    finally:
        con.close()
    if backup:
        kept = db.with_name(f"{db.stem}.before-migrate-{stamp}.sqlite")
        shutil.copyfile(db, kept)
        report["backup"] = str(kept)
    os.replace(working, db)
    report["output"] = str(db)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=ROOT / "data/corpus.sqlite")
    parser.add_argument("--promote-corrected-ocr", action="store_true")
    parser.add_argument("--readme", type=Path, help="local copy of the pinned OGC README (optional)")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    report = migrate(args.db, promote=args.promote_corrected_ocr, readme_path=args.readme, backup=not args.no_backup)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
