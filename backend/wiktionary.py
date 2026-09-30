"""Audited, independent Wiktionary reference lookup.

Listed forms are dictionary metadata, never corpus attestations or morphology
analyses. The Kaikki wrapper and nested entry object remain source-scoped.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any
from urllib.parse import quote

from .morphology import normalize, query_variants
from .normalization_contract import NORMALIZATION_VERSION


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/lexica/wiktionary-entries.jsonl"
AUDIT = ROOT / "data/reports/wiktionary-audit.json"
INDEX = ROOT / "data/wiktionary.sqlite"
SCHEMA_VERSION = "1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SENSE_FIELDS = ("glosses", "raw_glosses", "tags", "raw_tags", "form_of",
                "alt_of", "topics", "categories")


class AuditGateError(RuntimeError):
    """Source, audit, or derived index is not an approved matching snapshot."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def approved_source_hash(source_path: str | Path = SOURCE,
                         audit_path: str | Path = AUDIT) -> str:
    """Require independent acceptance and compare the complete JSONL bytes."""
    source, audit = Path(source_path), Path(audit_path)
    if not source.is_file():
        raise AuditGateError(f"Wiktionary source file is missing: {source}")
    if not audit.is_file():
        raise AuditGateError(f"Independent Wiktionary audit is missing: {audit}")
    try:
        report = json.loads(audit.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditGateError(f"Invalid independent Wiktionary audit: {audit}") from exc
    expected = report.get("output_sha256") if isinstance(report, dict) else None
    if (not isinstance(report, dict) or report.get("status") != "accepted" or
            not isinstance(expected, str) or not SHA256.fullmatch(expected)):
        raise AuditGateError("Wiktionary source lacks an accepted independent audit hash")
    actual = _file_sha256(source)
    if actual != expected:
        raise AuditGateError(f"Wiktionary source SHA-256 differs from accepted audit: {source}")
    return actual


def _key_rows(record: dict[str, Any], line_number: int) -> list[tuple[str, str, str, int]]:
    entry = record.get("entry")
    if not isinstance(entry, dict) or entry.get("lang_code") != "grc":
        raise ValueError(f"Non-Ancient-Greek or malformed Wiktionary entry at line {line_number}")
    word = entry.get("word")
    entry_id = record.get("id")
    if not isinstance(word, str) or not word or not isinstance(entry_id, str) or not entry_id:
        raise ValueError(f"Missing Wiktionary word/id at line {line_number}")
    rows = [(normalize(word), entry_id, "headword", -1)]
    forms = entry.get("forms", [])
    if not isinstance(forms, list):
        raise ValueError(f"Malformed Wiktionary forms at line {line_number}")
    for index, form in enumerate(forms):
        if not isinstance(form, dict):
            raise ValueError(f"Malformed Wiktionary form at line {line_number}, index {index}")
        spelling = form.get("form")
        if isinstance(spelling, str) and spelling.strip():
            rows.append((normalize(spelling), entry_id, "listed_form", index))
    return [row for row in rows if row[0]]


def build_index(source_path: str | Path = SOURCE, audit_path: str | Path = AUDIT,
                index_path: str | Path = INDEX) -> dict[str, Any]:
    """Build a separate SQLite index only for the audited JSONL snapshot."""
    source, target = Path(source_path), Path(index_path)
    approved_hash = approved_source_hash(source, audit_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".building")
    if temporary.exists():
        temporary.unlink()  # exact derived temporary target; safe to regenerate
    connection = sqlite3.connect(temporary)
    entries = 0
    key_count = 0
    try:
        connection.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE entries (
                id TEXT PRIMARY KEY,
                headword TEXT NOT NULL,
                headword_key TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE lookup_keys (
                key TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('headword','listed_form')),
                form_index INTEGER NOT NULL,
                PRIMARY KEY (key, entry_id, kind, form_index),
                FOREIGN KEY (entry_id) REFERENCES entries(id)
            );
            CREATE INDEX lookup_by_key ON lookup_keys(key,kind,entry_id);
        """)
        connection.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", [
            ("schema_version", SCHEMA_VERSION), ("approved_source_sha256", approved_hash),
            ("normalization_version", NORMALIZATION_VERSION),
        ])
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise ValueError(f"Blank Wiktionary JSONL line {line_number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid Wiktionary JSONL line {line_number}") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"Non-object Wiktionary JSONL line {line_number}")
                rows = _key_rows(record, line_number)
                entry = record["entry"]
                connection.execute("INSERT INTO entries VALUES (?,?,?,?)",
                                   (record["id"], entry["word"], normalize(entry["word"]),
                                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))))
                connection.executemany("INSERT INTO lookup_keys VALUES (?,?,?,?)", rows)
                entries += 1
                key_count += len(rows)
                if entries % 2000 == 0:
                    connection.commit()
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Wiktionary SQLite integrity check failed: {integrity}")
        if _file_sha256(source) != approved_hash:
            raise AuditGateError("Wiktionary source changed during index construction")
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    os.replace(temporary, target)
    return {"entries": entries, "keys": key_count, "source_sha256": approved_hash,
            "index_path": str(target)}


class WiktionaryLookup:
    """Read-only reference service with an independent source/audit gate."""

    def __init__(self, source_path: str | Path = SOURCE, audit_path: str | Path = AUDIT,
                 index_path: str | Path = INDEX) -> None:
        self.source_path = Path(source_path)
        self.audit_path = Path(audit_path)
        self.index_path = Path(index_path)
        self.approved_hash = approved_source_hash(self.source_path, self.audit_path)
        if not self.index_path.is_file():
            raise AuditGateError(f"Wiktionary SQLite index is missing: {self.index_path}")
        self._lock = RLock()
        connection = None
        try:
            connection = sqlite3.connect(f"file:{self.index_path.as_posix()}?mode=ro", uri=True,
                                         check_same_thread=False)
            connection.row_factory = sqlite3.Row
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise AuditGateError(f"Invalid Wiktionary SQLite index: {self.index_path}") from exc
        self._connection = connection
        if (metadata.get("schema_version") != SCHEMA_VERSION or
                metadata.get("approved_source_sha256") != self.approved_hash):
            self._connection.close()
            raise AuditGateError("Wiktionary SQLite index does not match the accepted source hash")
        if metadata.get('normalization_version') != NORMALIZATION_VERSION:
            self._connection.close()
            raise AuditGateError('Wiktionary lookup normalization version differs from runtime; migration/rebuild required')

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def lookup(self, query: str, limit: int = 8, max_senses: int = 8,
               max_form_matches: int = 12) -> dict[str, Any]:
        """Return bounded source entries with tags at their original scope."""
        with self._lock:
            return self._lookup_unlocked(query, limit, max_senses, max_form_matches)

    def _lookup_unlocked(self, query: str, limit: int, max_senses: int,
                         max_form_matches: int) -> dict[str, Any]:
        variants = query_variants(query)
        limit = max(1, min(int(limit), 20))
        max_senses = max(1, min(int(max_senses), 20))
        max_form_matches = max(1, min(int(max_form_matches), 30))
        if not variants:
            return {"query": query, "normalized": [], "results": [], "total": 0,
                    "source_sha256": self.approved_hash,
                    "method": "audited Kaikki/Wiktionary headword and listed-form index",
                    "warnings": []}
        placeholders = ",".join("?" for _ in variants)
        total = self._connection.execute(
            f"SELECT COUNT(DISTINCT entry_id) FROM lookup_keys WHERE key IN ({placeholders})",
            variants).fetchone()[0]
        ids = [row[0] for row in self._connection.execute(
            f"SELECT k.entry_id FROM lookup_keys k JOIN entries e ON e.id=k.entry_id "
            f"WHERE k.key IN ({placeholders}) GROUP BY k.entry_id "
            f"ORDER BY MIN(CASE k.kind WHEN 'headword' THEN 0 ELSE 1 END), "
            f"e.headword COLLATE NOCASE, k.entry_id LIMIT ?", [*variants, limit])]
        results = []
        for entry_id in ids:
            source_record = json.loads(self._connection.execute(
                "SELECT record_json FROM entries WHERE id=?", (entry_id,)).fetchone()[0])
            entry = source_record["entry"]
            matches = []
            for row in self._connection.execute(
                f"SELECT kind,form_index FROM lookup_keys WHERE entry_id=? "
                f"AND key IN ({placeholders}) ORDER BY CASE kind WHEN 'headword' THEN 0 ELSE 1 END, form_index",
                [entry_id, *variants]):
                if len(matches) >= max_form_matches:
                    break
                if row["kind"] == "headword":
                    matches.append({"kind": "headword", "word": entry["word"]})
                else:
                    form = entry["forms"][row["form_index"]]
                    matches.append({"kind": "listed_form", "form_index": row["form_index"],
                                    "form": form, "evidence_type": "dictionary_listed_form"})
            senses = entry.get("senses", [])
            if not isinstance(senses, list):
                senses = []
            results.append({
                "id": source_record["id"], "headword": entry["word"],
                "pos": entry.get("pos"),
                "entry_tags": entry.get("tags", []),
                "entry_raw_tags": entry.get("raw_tags", []),
                "entry_form_of": entry.get("form_of", []),
                "entry_alt_of": entry.get("alt_of", []),
                "senses": [{"sense_index": i, **{field: sense[field] for field in SENSE_FIELDS
                             if field in sense}} for i, sense in enumerate(senses[:max_senses])
                            if isinstance(sense, dict)],
                "total_senses": len(senses), "matches": matches,
                "source": source_record.get("source"),
                "source_url": source_record.get("source_url"),
                "live_entry_url": "https://en.wiktionary.org/wiki/" +
                    quote(entry["word"], safe="") + "#Ancient_Greek",
                "live_entry_note": "Live Wiktionary may differ from the audited Kaikki snapshot.",
                "quality": source_record.get("quality"),
                "license": source_record.get("license"),
                "raw_path": source_record.get("raw_path"),
                "raw_sha256": source_record.get("raw_sha256"),
                "raw_line": source_record.get("raw_line"),
                "raw_line_sha256": source_record.get("raw_line_sha256"),
            })
        return {"query": query, "normalized": variants, "results": results,
                "total": total, "source_sha256": self.approved_hash,
                "method": "audited Kaikki/Wiktionary headword and listed-form index",
                "warnings": ["Listed forms are dictionary metadata, not attestations in the lyric corpus."]
                if results else []}


__all__ = ["WiktionaryLookup", "build_index", "approved_source_hash", "AuditGateError"]
