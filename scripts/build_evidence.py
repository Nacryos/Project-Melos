"""Build a disposable SQLite graph from independently accepted claim JSONL.

Only exact PASS hashes in data/reports/p2-claim-acceptance.json are ingested.
No claim text or value is supplied by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.morphology import normalize  # noqa: E402


PREDICATES = {
    "lemma", "morphology", "dialect_label", "sense_gloss",
    "equivalent_form", "variant_reading", "editorial_state", "grammar_rule", "author_alias",
    "literary_dialect", "parallel_proposal",
}
ASSERTION_TYPES = {"quoted_source", "extracted_annotation", "model_inference"}
STATUSES = {"source_claim", "machine_proposed", "needs_review"}
SCHEMA = """
CREATE TABLE input_files (
    name TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    records INTEGER NOT NULL
);
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT,
    passage_id TEXT,
    form TEXT,
    normalized_form TEXT,
    start_offset INTEGER,
    end_offset INTEGER,
    predicate TEXT NOT NULL,
    subject_json TEXT NOT NULL,
    object_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    assertion_type TEXT NOT NULL,
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    source_family TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    source_file TEXT NOT NULL REFERENCES input_files(name)
);
CREATE TABLE form_edges (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    ordinal INTEGER NOT NULL,
    form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    object_form_json TEXT NOT NULL,
    PRIMARY KEY (claim_id, ordinal)
);
"""
INDEXES = """
CREATE INDEX claims_form_idx ON claims(normalized_form);
CREATE INDEX claims_passage_idx ON claims(passage_id);
CREATE INDEX claims_subject_idx ON claims(subject_type,subject_id);
CREATE INDEX edges_form_idx ON form_edges(normalized_form);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _validate(row: Any, source: str, line: int) -> dict[str, Any]:
    location = f"{source}:{line}"
    if not isinstance(row, dict):
        raise ValueError(f"{location}: expected a JSON object")
    for key in ("id", "method", "source_family"):
        _nonempty(row.get(key), f"{location} {key}")
    subject = row.get("subject")
    if not isinstance(subject, dict):
        raise ValueError(f"{location}: subject must be an object")
    _nonempty(subject.get("type"), f"{location} subject.type")
    for key in ("id", "passage_id", "form"):
        if key in subject:
            _nonempty(subject[key], f"{location} subject.{key}")
    start, end = subject.get("start"), subject.get("end")
    if (start is None) != (end is None):
        raise ValueError(f"{location}: subject offsets must be paired")
    if start is not None:
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(end, int) or isinstance(end, bool) or
                start < 0 or end <= start or not subject.get("passage_id")):
            raise ValueError(f"{location}: invalid subject passage offsets")
    if row.get("predicate") not in PREDICATES:
        raise ValueError(f"{location}: invalid predicate {row.get('predicate')!r}")
    if "object" not in row:
        raise ValueError(f"{location}: missing object")
    if row.get("assertion_type") not in ASSERTION_TYPES:
        raise ValueError(f"{location}: invalid assertion_type")
    if row.get("status") not in STATUSES:
        raise ValueError(f"{location}: invalid status")
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{location}: evidence must be a nonempty list")
    for i, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise ValueError(f"{location}: evidence[{i}] must be an object")
        for key in ("source_url", "raw_path", "raw_sha256", "quote"):
            _nonempty(item.get(key), f"{location} evidence[{i}].{key}")
        digest = item["raw_sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"{location}: invalid evidence[{i}].raw_sha256")
    if "metadata" in row and not isinstance(row["metadata"], dict):
        raise ValueError(f"{location}: metadata must be an object")
    return row


def _read_claims(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            yield line_number, _validate(value, path.name, line_number)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _accepted_files(root: Path, manifest_path: Path) -> list[tuple[Path, str, int]]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Independent claim acceptance manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Claim acceptance manifest needs a files object")
    accepted: list[tuple[Path, str, int]] = []
    for name, entry in sorted(files.items()):
        if not isinstance(entry, dict) or entry.get("verdict") != "PASS":
            continue
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"Unsafe or invalid accepted claim filename: {name!r}")
        kind = entry.get("kind", "claims")
        if kind == "metadata" and name == "p2-author-profiles.json":
            path = root / "data" / "metadata" / name
        elif kind == "claims" and name.endswith(".jsonl"):
            path = root / "data" / "claims" / name
        else:
            raise ValueError(f"Unknown accepted evidence input: {name!r} ({kind!r})")
        expected = entry.get("sha256")
        if (not isinstance(expected, str) or len(expected) != 64 or
                any(c not in "0123456789abcdef" for c in expected)):
            raise ValueError(f"Invalid accepted SHA256 for {name}")
        if not path.is_file():
            raise FileNotFoundError(f"Accepted evidence input missing: {path}")
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"Accepted evidence input hash mismatch: {name}: {actual} != {expected}")
        if kind == "metadata":
            continue
        records = entry.get("records")
        if not isinstance(records, int) or isinstance(records, bool) or records < 0:
            raise ValueError(f"Invalid accepted record count for {name}")
        accepted.append((path, expected, records))
    if not accepted:
        raise ValueError("No independently accepted claim files; evidence index not replaced")
    return accepted


def _listed_forms(row: dict[str, Any]) -> Iterator[tuple[int, str, Any]]:
    """Index explicit entry form lists without rewriting them as attestations."""
    obj = row["object"]
    if not isinstance(obj, dict) or "forms" not in obj:
        return
    forms = obj["forms"]
    if not isinstance(forms, list):
        raise ValueError(f"{row['id']}: object.forms must be a list")
    for index, item in enumerate(forms):
        form = item if isinstance(item, str) else item.get("form") if isinstance(item, dict) else None
        if not isinstance(form, str) or not form.strip():
            raise ValueError(f"{row['id']}: object.forms[{index}] needs a form string")
        yield index, form, item


def _has_greek_letter(form: str) -> bool:
    return any(("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff")
               and char.isalpha() for char in form)


def build(root: Path = ROOT, output: Path | None = None,
          manifest_path: Path | None = None) -> dict[str, Any]:
    """Rebuild atomically; failure never replaces an existing evidence DB."""
    root = Path(root).resolve()
    output = Path(output) if output is not None else root / "data/evidence.sqlite"
    manifest_path = Path(manifest_path) if manifest_path is not None else root / "data/reports/p2-claim-acceptance.json"
    accepted = _accepted_files(root, manifest_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="evidence-", suffix=".sqlite", dir=output.parent, delete=False) as handle:
        temp = Path(handle.name)
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(temp)
        con.executescript(SCHEMA)
        claim_count = 0
        edge_count = 0
        for path, digest, expected_records in accepted:
            con.execute("INSERT INTO input_files VALUES (?,?,?)", (path.name, digest, expected_records))
            file_count = 0
            for line_number, row in _read_claims(path):
                subject = row["subject"]
                form = subject.get("form")
                try:
                    con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        row["id"], subject["type"], subject.get("id"), subject.get("passage_id"),
                        form, normalize(form) if form else None, subject.get("start"), subject.get("end"),
                        row["predicate"], _json(subject), _json(row["object"]), _json(row["evidence"]),
                        row["assertion_type"], row["status"], row["method"], row["source_family"],
                        _json(row.get("metadata", {})), path.name,
                    ))
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"{path.name}:{line_number}: duplicate claim id {row['id']!r}") from exc
                for ordinal, listed_form, original in _listed_forms(row):
                    # The source form arrays may include English table labels.
                    # Preserve them in object_json, but never expand a Greek
                    # corpus search with a non-Greek heading.
                    if not _has_greek_letter(listed_form):
                        continue
                    folded = normalize(listed_form)
                    if not folded:
                        continue
                    con.execute("INSERT INTO form_edges VALUES (?,?,?,?,?)", (
                        row["id"], ordinal, listed_form, folded, _json(original),
                    ))
                    edge_count += 1
                file_count += 1
                claim_count += 1
            if file_count != expected_records:
                raise ValueError(f"Accepted claim count mismatch: {path.name}: {file_count} != {expected_records}")
        con.executescript(INDEXES)
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Evidence SQLite integrity check failed: {integrity}")
        con.close()
        con = None
        os.replace(temp, output)
    finally:
        if con is not None:
            con.close()
        if temp.exists():
            temp.unlink()
    return {
        "output": str(output), "claims": claim_count,
        "listed_form_edges": edge_count,
        "files": [{"name": p.name, "sha256": digest, "records": count}
                  for p, digest, count in accepted],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
