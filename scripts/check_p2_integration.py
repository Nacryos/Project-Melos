"""Read-only acceptance and SQLite integration check for Melos phase 2.

Reports facts about independently PASS files and the two derived indexes.
It does not accept, edit, rebuild, or publish any corpus records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def digest_and_rows(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            rows += bool(line.strip())
    return digest.hexdigest(), rows


def accepted(root: Path, manifests: tuple[str, ...], subdir: str) -> tuple[dict, list[str]]:
    entries: dict[str, dict] = {}
    errors: list[str] = []
    for name in manifests:
        path = root / "data/reports" / name
        if not path.is_file():
            errors.append(f"missing acceptance manifest: {name}")
            continue
        files = json.loads(path.read_text(encoding="utf-8")).get("files", {})
        for filename, row in files.items():
            if row.get("verdict") != "PASS":
                continue
            if row.get("kind") == "metadata":
                # Metadata is accepted evidence input, but never a claim row.
                continue
            prior = entries.get(filename)
            if prior and (prior.get("sha256"), prior.get("records")) != (
                    row.get("sha256"), row.get("records")):
                errors.append(f"conflicting PASS manifests: {filename}")
                continue
            entries[filename] = row
    for filename, row in entries.items():
        if Path(filename).name != filename or not filename.endswith(".jsonl"):
            errors.append(f"unsafe accepted filename: {filename}")
            continue
        path = root / "data" / subdir / filename
        if not path.is_file():
            errors.append(f"missing accepted file: {subdir}/{filename}")
        else:
            actual_digest, actual_rows = digest_and_rows(path)
            if actual_digest != row.get("sha256"):
                errors.append(f"accepted hash mismatch: {subdir}/{filename}")
            if actual_rows != row.get("records"):
                errors.append(f"accepted row count mismatch: {subdir}/{filename}: "
                              f"{actual_rows} != {row.get('records')}")
    return entries, errors


def check(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    text_files, errors = accepted(root, (
        "audit-acceptance.json", "p2-text-acceptance.json"), "processed")
    claim_files, claim_errors = accepted(root, (
        "p2-claim-acceptance.json",), "claims")
    errors.extend(claim_errors)
    result = {
        "accepted_text_files": len(text_files),
        "accepted_claim_files": len(claim_files),
        "corpus": {"ready": False},
        "evidence": {"ready": False},
        "errors": errors,
    }

    claim_manifest_path = root / "data/reports/p2-claim-acceptance.json"
    claim_manifest = (json.loads(claim_manifest_path.read_text(encoding="utf-8"))
                      if claim_manifest_path.is_file() else {})
    metadata = {name: row for name, row in claim_manifest.get("files", {}).items()
                if row.get("verdict") == "PASS" and row.get("kind") == "metadata"}
    result["accepted_metadata_files"] = len(metadata)
    for name, row in metadata.items():
        if name != "p2-author-profiles.json":
            errors.append(f"unknown accepted metadata file: {name}")
            continue
        path = root / "data/metadata" / name
        if not path.is_file():
            errors.append(f"missing accepted metadata file: {name}")
            continue
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != row.get("sha256"):
            errors.append(f"accepted metadata hash mismatch: {name}")
        profiles = json.loads(path.read_text(encoding="utf-8")).get("profiles", [])
        if len(profiles) != row.get("records"):
            errors.append(f"accepted metadata profile count mismatch: {name}")

    corpus_path = root / "data/corpus.sqlite"
    if corpus_path.is_file():
        with sqlite3.connect(f"file:{corpus_path.as_posix()}?mode=ro", uri=True) as con:
            raw = con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0]
            manifest = json.loads(raw)
            actual_count = con.execute("SELECT count(*) FROM passages").fetchone()[0]
            actual_sources = dict(con.execute(
                "SELECT source,count(*) FROM passages GROUP BY source"))
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        indexed_files = {Path(name).name for name in manifest.get("files", [])}
        expected_files = set(text_files)
        expected_count = sum(row.get("records", 0) for row in text_files.values())
        result["corpus"] = {
            "ready": True, "passages": actual_count,
            "expected_passages_from_pass_manifests": expected_count,
            "indexed_files": sorted(indexed_files),
            "missing_pass_files": sorted(expected_files - indexed_files),
            "unaccepted_indexed_files": sorted(indexed_files - expected_files),
            "integrity": integrity,
        }
        if manifest.get("passages") != actual_count or expected_count != actual_count:
            errors.append("corpus passage count disagrees with index or accepted file counts")
        if manifest.get("sources") != actual_sources:
            errors.append("corpus source counts disagree with SQLite")
        if indexed_files != expected_files:
            errors.append("corpus indexed files differ from accepted text files")
        if integrity != "ok":
            errors.append(f"corpus SQLite integrity: {integrity}")
    else:
        errors.append("corpus SQLite missing")

    evidence_path = root / "data/evidence.sqlite"
    if evidence_path.is_file():
        with sqlite3.connect(f"file:{evidence_path.as_posix()}?mode=ro", uri=True) as con:
            embedded = {name: {"sha256": sha256, "records": records}
                        for name, sha256, records in con.execute(
                            "SELECT name,sha256,records FROM input_files")}
            actual_claims = con.execute("SELECT count(*) FROM claims").fetchone()[0]
            status_counts = dict(con.execute(
                "SELECT status,count(*) FROM claims GROUP BY status"))
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        expected_claims = sum(row.get("records", 0) for row in claim_files.values())
        result["evidence"] = {
            "ready": True, "claims": actual_claims,
            "expected_claims_from_pass_manifests": expected_claims,
            "input_files": embedded, "status_counts": status_counts,
            "integrity": integrity,
        }
        if actual_claims != expected_claims:
            errors.append("evidence claim count disagrees with accepted file counts")
        if set(embedded) != set(claim_files):
            errors.append("evidence input files differ from accepted claim files")
        for filename, row in embedded.items():
            approval = claim_files.get(filename)
            if approval and (row["sha256"] != approval.get("sha256") or
                             row["records"] != approval.get("records")):
                errors.append(f"evidence input hash/count mismatch: {filename}")
        if integrity != "ok":
            errors.append(f"evidence SQLite integrity: {integrity}")
    elif claim_files:
        errors.append("evidence SQLite missing despite accepted claims")
    return result


if __name__ == "__main__":
    import sys

    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if report["errors"] else 0)
