#!/usr/bin/env python3
"""Independent Phase 2 corpus audit; never grants a manual PASS automatically.

Run with explicit staged JSONL paths. The existing mechanical gate checks every
row against saved raw bytes. This wrapper adds repeatable per-file samples and
overlap evidence, then preserves only hash-bound manual decisions already in
the separate Phase 2 acceptance file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import tempfile
import os
import unicodedata
import re
import importlib

from audit_corpus import audit, normalized
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_BASE = ROOT / "data/reports/audit-acceptance.json"
REPORT = ROOT / "data/reports/p2-text-audit.json"
ACCEPTANCE = ROOT / "data/reports/p2-text-acceptance.json"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                 delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                yield number, json.loads(line)


def signature(value: str) -> str | None:
    text = normalized(unicodedata.normalize("NFC", value))
    if len(text) < 32:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def baseline_index() -> tuple[dict[str, list[dict]], set[str]]:
    """Index exact text overlaps in already accepted files only."""
    manifest = json.loads(ACCEPTED_BASE.read_text(encoding="utf-8"))["files"]
    seen: dict[str, list[dict]] = {}
    ids: set[str] = set()
    for name, decision in manifest.items():
        # Integration may already have copied Phase 2 decisions into the main
        # manifest. They are the subjects of this audit, not baseline conflicts.
        if name.startswith("p2_"):
            continue
        if decision.get("verdict") != "PASS":
            continue
        path = ROOT / "data/processed" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != decision["sha256"]:
            raise ValueError(f"baseline acceptance hash changed: {name}")
        for _, row in rows(path):
            ids.add(row["id"])
            if row.get("kind") != "text" or row.get("language") != "grc":
                continue
            sig = signature(row["text"])
            if sig:
                refs = seen.setdefault(sig, [])
                if len(refs) < 3:
                    refs.append({key: row.get(key) for key in
                                 ("id", "source", "author", "work", "edition", "citation")})
    return seen, ids


def samples(path: Path, n: int, seed: int) -> list[dict]:
    """Reservoir sample, with a source-text and other-quality stratum."""
    rng = random.Random(seed)
    pools: dict[str, list[dict]] = {"source_text": [], "other": []}
    counts = {key: 0 for key in pools}
    for number, row in rows(path):
        group = "source_text" if row.get("quality") == "source_text" else "other"
        counts[group] += 1
        entry = {
            "line": number, "id": row.get("id"), "source_url": row.get("source_url"),
            "raw_path": row.get("raw_path"), "raw_sha256": row.get("raw_sha256"),
            "author": row.get("author"), "work": row.get("work"),
            "edition": row.get("edition"), "citation": row.get("citation"),
            "kind": row.get("kind"), "quality": row.get("quality"),
            "text_excerpt": str(row.get("text", ""))[:180],
            "manual_source_span": "PENDING", "manual_labels": "PENDING",
        }
        pool = pools[group]
        limit = n if group == "source_text" else min(5, n)
        if len(pool) < limit:
            pool.append(entry)
        else:
            index = rng.randrange(counts[group])
            if index < limit:
                pool[index] = entry
    other_take = min(5, n, len(pools["other"]))
    source_take = min(len(pools["source_text"]), n - other_take)
    chosen = pools["other"][:other_take] + pools["source_text"][:source_take]
    if len(chosen) < n:
        chosen += pools["other"][other_take:other_take + n - len(chosen)]
    return sorted(chosen[:n], key=lambda item: item["line"])


def verify_dcc_table_row(row: dict) -> bool:
    """Independently verify each serialized DCC comparison against one DOM row."""
    meta = row.get("metadata")
    if not isinstance(meta, dict) or meta.get("section") != "Features of Aeloic Dialect":
        return False
    if row.get("kind") != "reference" or not isinstance(meta.get("row_index"), int):
        return False
    raw = ROOT / row["raw_path"]
    soup = BeautifulSoup(raw.read_bytes(), "html.parser")
    heading = next((h for h in soup.find_all(re.compile(r"^(?:h[1-6]|p)$"))
                    if normalized(h.get_text()) == meta["section"]), None)
    if heading is None:
        return False
    table = heading.find_next("table")
    if table is None:
        return False
    table_rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) >= 3:
            values = [normalized(cell.get_text()) for cell in cells[:3]]
            if any(values):
                table_rows.append(values)
    index = meta["row_index"]
    return (0 < index < len(table_rows)
            and table_rows[0] == meta.get("column_labels")
            and " | ".join(table_rows[index]) == row["text"]
            and row["citation"] == f"Features of Aeloic Dialect, row {index}")


def resolve_structured_html(base: dict, files: list[Path]) -> list[dict]:
    """Replace generic flattened-text failures only after exact DOM proof."""
    by_path = {str(path): path for path in files if path.name == "p2_grammar.jsonl"}
    row_cache = {str(path): dict(rows(path)) for path in by_path.values()}
    retained = []
    resolved = []
    for finding in base["findings"]:
        if (finding["code"] == "text_not_in_raw" and
                finding["file"] in by_path and
                verify_dcc_table_row(row_cache[finding["file"]][finding["line"]])):
            resolved.append({"file": finding["file"], "line": finding["line"],
                             "method": "exact DCC HTML table row/cell and heading match"})
        else:
            retained.append(finding)
    base["findings"] = retained
    base["severity_counts"] = {
        level: sum(f["severity"] == level for f in retained) for level in ("FAIL", "WARN")
    }
    for path in by_path.values():
        decision = base["files"][path.name]
        related = [f for f in retained if f["file"] == str(path)]
        decision["failures"] = sum(f["severity"] == "FAIL" for f in related)
        decision["warnings"] = sum(f["severity"] == "WARN" for f in related)
        decision["mechanical_verdict"] = (
            "FAIL" if decision["failures"] else "WARN" if decision["warnings"] else "PASS"
        )
        decision["verdict"] = "PENDING" if decision["mechanical_verdict"] == "PASS" else decision["mechanical_verdict"]
    return resolved


def verify_ibycus_scan_line(row: dict, lyra_pages: dict[str, dict]) -> bool:
    meta = row.get("metadata", {})
    if row.get("source") != "p2_ibycus" or row.get("kind") != "text" or row.get("language") != "grc":
        return False
    printed = str(meta.get("printed_page"))
    parent = lyra_pages.get(printed)
    if not parent or row["source_url"] != parent["metadata"]["page_image_url"]:
        return False
    if meta.get("scan_leaf") != parent["metadata"]["scan_leaf"]:
        return False
    if not re.search(rf"p{printed}:fr\d+:l\d+$", row["id"]):
        return False
    ocr_path = (ROOT / meta["ocr_path"]).resolve()
    crop_path = (ROOT / meta["line_image_path"]).resolve()
    if not (ocr_path.is_relative_to(ROOT / "data/raw/p2_ibycus") and
            crop_path.is_relative_to(ROOT / "data/raw/p2_ibycus")):
        return False
    if (hashlib.sha256(ocr_path.read_bytes()).hexdigest() != meta["ocr_sha256"] or
            hashlib.sha256(crop_path.read_bytes()).hexdigest() != meta["line_image_sha256"]):
        return False
    return (ocr_path.read_text(encoding="utf-8").strip() == row["text"] and
            row.get("lines") == [{"label": row["id"].rsplit("l", 1)[-1], "text": row["text"]}])


def verify_editions_ocr_page(row: dict, lyra_by_id: dict[str, dict]) -> bool:
    """Bind uncorrected OCR to its saved bytes and the pre-existing IA leaf."""
    meta = row.get("metadata", {})
    parent = lyra_by_id.get(meta.get("legacy_ocr_parent_id"))
    if not parent or row.get("source") != "p2_editions":
        return False
    if row.get("kind") != "reference" or row.get("quality") != "machine_ocr" or meta.get("needs_review") is not True:
        return False
    previous = parent.get("metadata", {})
    for key in ("archive_item", "scan_leaf", "printed_page", "page_url", "iiif_manifest_url"):
        if meta.get(key) != previous.get(key):
            return False
    if row.get("source_url") != meta.get("full_resolution_image_url") or row["source_url"] != previous.get("page_image_url"):
        return False
    ocr_path = (ROOT / meta["ocr_path"]).resolve()
    if not ocr_path.is_relative_to(ROOT / "data/raw/p2_editions"):
        return False
    ocr_bytes = ocr_path.read_bytes()
    return (hashlib.sha256(ocr_bytes).hexdigest() == meta.get("ocr_sha256") and
            ocr_bytes.decode("utf-8").strip() == row.get("text"))


def resolve_source_derivatives(base: dict, files: list[Path]) -> list[dict]:
    """Trace binary-source derivatives; manual scan review still required."""
    file_names = {path.name: path for path in files}
    valid_pdf_rows: set[int] = set()
    if "p2_stesichorus.jsonl" in file_names:
        import fitz
        collector = importlib.import_module("ingest_p2_stesichorus")
        path = file_names["p2_stesichorus.jsonl"]
        staged = list(rows(path))
        if staged:
            pdf = ROOT / staged[0][1]["raw_path"]
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            with fitz.open(pdf) as doc:
                regenerated = collector.records(doc, digest)
            if len(regenerated) == len(staged):
                valid_pdf_rows = {number for (number, actual), expected in zip(staged, regenerated)
                                  if actual == expected and actual["raw_sha256"] == digest}
    lyra_pages: dict[str, dict] = {}
    if "p2_ibycus.jsonl" in file_names:
        for _, parent in rows(ROOT / "data/processed/lyra.jsonl"):
            meta = parent.get("metadata", {})
            if meta.get("archive_item") == "lyragraecavol20002jmed" and str(meta.get("printed_page")) in {"84", "86"}:
                lyra_pages[str(meta["printed_page"])] = parent
    lyra_by_id: dict[str, dict] = {}
    if "p2_editions.jsonl" in file_names:
        lyra_by_id = {parent["id"]: parent for _, parent in rows(ROOT / "data/processed/lyra.jsonl")}
    row_cache = {str(path): dict(rows(path)) for path in files if path.name in {"p2_stesichorus.jsonl", "p2_ibycus.jsonl", "p2_editions.jsonl"}}
    retained = []
    resolved = []
    for finding in base["findings"]:
        path = finding["file"]
        row = row_cache.get(path, {}).get(finding["line"])
        if finding["code"] == "raw_text_unavailable" and row is not None:
            method = None
            if Path(path).name == "p2_stesichorus.jsonl" and finding["line"] in valid_pdf_rows:
                method = "saved publisher PDF hash and exact full-file MuPDF regeneration; manual page review required"
            elif Path(path).name == "p2_ibycus.jsonl" and verify_ibycus_scan_line(row, lyra_pages):
                method = "saved IA image/leaf and cropped line/OCR hash; manual scan review required"
            elif Path(path).name == "p2_editions.jsonl" and verify_editions_ocr_page(row, lyra_by_id):
                method = "saved IA image/leaf and exact OCR bytes/hash; uncorrected page OCR remains reference-only"
            if method:
                resolved.append({"file": path, "line": finding["line"], "method": method})
                continue
        retained.append(finding)
    base["findings"] = retained
    base["severity_counts"] = {level: sum(f["severity"] == level for f in retained) for level in ("FAIL", "WARN")}
    for path in files:
        if path.name not in {"p2_stesichorus.jsonl", "p2_ibycus.jsonl", "p2_editions.jsonl"}:
            continue
        decision = base["files"][path.name]
        related = [f for f in retained if f["file"] == str(path)]
        decision["failures"] = sum(f["severity"] == "FAIL" for f in related)
        decision["warnings"] = sum(f["severity"] == "WARN" for f in related)
        decision["mechanical_verdict"] = "FAIL" if decision["failures"] else "WARN" if decision["warnings"] else "PASS"
        decision["verdict"] = "PENDING" if decision["mechanical_verdict"] == "PASS" else decision["mechanical_verdict"]
    return resolved


def resolve_mediawiki_html(base: dict, files: list[Path]) -> list[dict]:
    """Trace text across inline HTML tags in a pinned MediaWiki parse JSON."""
    path = next((path for path in files if path.name == "p2_alcaeus.jsonl"), None)
    if path is None:
        return []
    records = dict(rows(path))
    visible_cache: dict[str, str] = {}
    resolved = []
    retained = []
    for finding in base["findings"]:
        if finding["file"] != str(path) or finding["code"] != "text_not_in_raw":
            retained.append(finding)
            continue
        row = records[finding["line"]]
        raw_path = row["raw_path"]
        if raw_path not in visible_cache:
            payload = json.loads((ROOT / raw_path).read_text(encoding="utf-8"))
            visible_cache[raw_path] = normalized(BeautifulSoup(payload["parse"]["text"]["*"], "html.parser").get_text())
        visible = visible_cache[raw_path]
        lines = row.get("lines", [])
        if (lines and row["text"] == "\n".join(line["text"] for line in lines)
                and all(normalized(line["text"]) in visible for line in lines)):
            resolved.append({"file": str(path), "line": finding["line"],
                             "method": "all passage lines exact in saved revision-pinned MediaWiki DOM visible text"})
        else:
            retained.append(finding)
    base["findings"] = retained
    base["severity_counts"] = {level: sum(f["severity"] == level for f in retained) for level in ("FAIL", "WARN")}
    decision = base["files"][path.name]
    related = [f for f in retained if f["file"] == str(path)]
    decision["failures"] = sum(f["severity"] == "FAIL" for f in related)
    decision["warnings"] = sum(f["severity"] == "WARN" for f in related)
    decision["mechanical_verdict"] = "FAIL" if decision["failures"] else "WARN" if decision["warnings"] else "PASS"
    decision["verdict"] = "PENDING" if decision["mechanical_verdict"] == "PASS" else decision["mechanical_verdict"]
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    files = [path.resolve() for path in args.paths]
    for path in files:
        if not path.is_relative_to(ROOT / "data/processed") or not path.name.startswith("p2_"):
            parser.error(f"expected Phase 2 processed JSONL under data/processed: {path}")
    existing = json.loads(ACCEPTANCE.read_text(encoding="utf-8")) if ACCEPTANCE.exists() else {"files": {}}
    existing_files = existing.get("files", {})
    base = audit(files, ROOT, 0, args.seed, manual={})
    structured_html_resolutions = resolve_structured_html(base, files)
    source_derivative_resolutions = resolve_source_derivatives(base, files)
    mediawiki_html_resolutions = resolve_mediawiki_html(base, files)
    baseline, old_ids = baseline_index()
    report = {
        "scope": "Phase 2 text staging; no manual approval inferred from mechanical checks",
        "seed": args.seed, "sample_requested_per_file": args.sample,
        "files": {}, "mechanical": base,
        "structured_html_resolutions": structured_html_resolutions,
        "source_derivative_resolutions": source_derivative_resolutions,
        "mediawiki_html_resolutions": mediawiki_html_resolutions,
    }
    acceptance = {"files": {}}
    for key, value in existing_files.items():
        if key in {path.name for path in files}:
            continue
        old_path = ROOT / "data/processed" / key
        if old_path.is_file() and hashlib.sha256(old_path.read_bytes()).hexdigest() == value.get("sha256"):
            acceptance["files"][key] = value
    all_new_ids: set[str] = set()
    for path in files:
        name = path.name
        evidence = base["files"][name]
        issues = []
        duplicates = []
        for number, row in rows(path):
            if row.get("id") in old_ids or row.get("id") in all_new_ids:
                issues.append({"line": number, "code": "existing_or_cross_file_id", "id": row.get("id")})
            all_new_ids.add(row.get("id"))
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if row.get("quality") == "source_text" and (
                metadata.get("ocr") or
                re.search(r"(?:ocr|djvu|abbyy)", str(row.get("raw_path", "")), re.I)
            ):
                issues.append({"line": number, "code": "unverified_ocr_promoted", "id": row.get("id")})
            if row.get("kind") == "text" and row.get("language") == "grc":
                sig = signature(row["text"])
                if sig and sig in baseline and len(duplicates) < 100:
                    duplicates.append({"line": number, "id": row["id"],
                                       "existing": baseline[sig]})
        if issues:
            evidence["failures"] += len(issues)
            evidence["mechanical_verdict"] = "FAIL"
            evidence["verdict"] = "FAIL"
        previous = existing_files.get(name, {})
        if (previous.get("sha256") == evidence.get("sha256") and
                previous.get("manual_verdict") in {"PASS", "WARN", "FAIL"}):
            evidence["manual_verdict"] = previous["manual_verdict"]
            evidence["manual_reason"] = previous.get("manual_reason", "")
            if "scope" in previous:
                evidence["scope"] = previous["scope"]
            if previous["manual_verdict"] == "FAIL":
                evidence["verdict"] = "FAIL"
            elif previous["manual_verdict"] == "WARN" and evidence["mechanical_verdict"] == "PASS":
                evidence["verdict"] = "WARN"
            elif previous["manual_verdict"] == "PASS" and evidence["mechanical_verdict"] == "PASS":
                evidence["verdict"] = "PASS"
        report["files"][name] = {
            "decision": evidence, "additional_issues": issues,
            "exact_text_overlaps_with_accepted_corpus": duplicates,
            "overlap_note": "Exact text overlap flags edition lineage for review; it is not an independent witness or automatic failure.",
            "manual_sample": samples(path, max(0, args.sample), args.seed),
        }
        acceptance["files"][name] = evidence
    write_json(REPORT, report)
    write_json(ACCEPTANCE, acceptance)
    print(json.dumps({name: value["verdict"] for name, value in acceptance["files"].items()}, indent=2))
    return 1 if any(acceptance["files"][path.name]["verdict"] == "FAIL" for path in files) else 0


if __name__ == "__main__":
    raise SystemExit(main())
