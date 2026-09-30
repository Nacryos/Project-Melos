"""Accept collector outputs into the index manifests on the owner's authority.

The corpus build admits only files whose exact SHA-256 and record count appear
with a PASS verdict in ``data/reports/audit-acceptance.json``. The second-pass
workflow filled that manifest through independent auditor agents. Under the
owner decision of 2026-09-30 (docs/decisions.md) the owner accepts outputs
directly; this script writes that acceptance with the same hash binding, so
the build's fail-closed checks keep working.

  python scripts/accept_owner_outputs.py p2_eulogikon.jsonl p2_cgl_anthology.jsonl
  python scripts/accept_owner_outputs.py --ogc          # after ingest_ogc.py + label_ogc.py

``p2_*.jsonl`` files go through ``data/reports/p2-text-acceptance.json`` and
``scripts/merge_p2_acceptance.py`` (the single authority for phase-two text).
Other files are written into ``audit-acceptance.json`` directly. ``--ogc``
re-binds ``data/reports/ogc-manual.json`` to the current ``ogc.jsonl`` and the
quality annotation that ``label_ogc.py`` produced, and accepts ``ogc.jsonl``
and ``ogc_derived.jsonl``; without that re-binding the build would demote the
whole Open Greek Corpus to reference material.

The script changes manifests only; it never edits collector outputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASIS = "owner acceptance per docs/decisions.md (2026-09-30); no independent auditor"


def digest_and_count(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with path.open(encoding="utf-8-sig") as stream:
        count = sum(bool(line.strip()) for line in stream)
    return digest, count


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".json") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def load_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def entry_for(path: Path) -> dict:
    digest, count = digest_and_count(path)
    return {"verdict": "PASS", "sha256": digest, "records": count, "output_sha256": digest,
            "manual_verdict": "PASS", "acceptance_basis": BASIS,
            "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def accept(names: list[str], *, root: Path = ROOT, ogc: bool = False) -> dict:
    processed = root / "data/processed"
    reports = root / "data/reports"
    staged_path = reports / "p2-text-acceptance.json"
    manifest_path = reports / "audit-acceptance.json"
    staged = load_json(staged_path, {"files": {}})
    manifest = load_json(manifest_path, {"files": {}})
    staged.setdefault("files", {})
    manifest.setdefault("files", {})
    accepted: dict[str, int] = {}
    for name in names:
        if Path(name).name != name or not name.endswith(".jsonl"):
            raise ValueError(f"Expected a bare processed file name ending in .jsonl: {name}")
        path = processed / name
        if not path.is_file():
            raise FileNotFoundError(path)
        entry = entry_for(path)
        if name.startswith("p2_"):
            staged["files"][name] = entry
        else:
            manifest["files"][name] = {**manifest["files"].get(name, {}), **entry}
        accepted[name] = entry["records"]
    if ogc:
        quality_report = load_json(reports / "ogc-quality.json", {})
        if not quality_report:
            raise FileNotFoundError("data/reports/ogc-quality.json is missing; run scripts/label_ogc.py first")
        ogc_file = processed / "ogc.jsonl"
        ogc_digest, ogc_count = digest_and_count(ogc_file)
        if quality_report.get("input_sha256") != ogc_digest:
            raise ValueError("ogc-quality.json was produced from a different ogc.jsonl; re-run scripts/label_ogc.py")
        annotation_rel = quality_report.get("annotation_output", "data/annotations/ogc-quality.jsonl")
        annotation_path = root / annotation_rel
        annotation_digest, _ = digest_and_count(annotation_path)
        manual = load_json(reports / "ogc-manual.json", {})
        manual.update({
            "verdict": "PASS_FOR_LABELED_STAGING",
            "input": "data/processed/ogc.jsonl",
            "input_sha256": ogc_digest,
            "records": ogc_count,
            "quality_annotation": {"path": annotation_rel, "sha256": annotation_digest,
                                   "report": "data/reports/ogc-quality.json",
                                   "report_sha256": hashlib.sha256((reports / "ogc-quality.json").read_bytes()).hexdigest()},
            "rebound_by_owner_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rebinding_basis": BASIS,
        })
        write_json(reports / "ogc-manual.json", manual)
        for name in ("ogc.jsonl", "ogc_derived.jsonl"):
            path = processed / name
            if path.is_file():
                entry = entry_for(path)
                manifest["files"][name] = {**manifest["files"].get(name, {}), **entry}
                accepted[name] = entry["records"]
    if any(name.startswith("p2_") for name in accepted):
        write_json(staged_path, staged)
    write_json(manifest_path, manifest)
    if any(name.startswith("p2_") for name in accepted):
        from scripts.merge_p2_acceptance import merge
        merge(root)
    return accepted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="processed file names, e.g. p2_eulogikon.jsonl")
    parser.add_argument("--ogc", action="store_true", help="re-bind ogc-manual.json and accept ogc.jsonl / ogc_derived.jsonl")
    args = parser.parse_args()
    if not args.names and not args.ogc:
        parser.error("name at least one processed file or pass --ogc")
    accepted = accept(args.names, ogc=args.ogc)
    for name, count in accepted.items():
        print(f"accepted {name}: {count:,} records")
    print("Now run: python scripts/build_corpus.py && python scripts/report_coverage.py")


if __name__ == "__main__":
    main()
