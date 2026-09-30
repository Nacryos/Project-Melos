"""Collect a focused, auditable poetry and poetic-reception subset of OGC.

Run from the repository root: python scripts/ingest_ogc.py
The selection below is a list of *source file families*, not transcribed data.
Every passage comes from a downloaded, commit-pinned OGC JSONL artifact.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ogc"
OUTPUT = ROOT / "data" / "processed" / "ogc.jsonl"
REPORT = ROOT / "data" / "reports" / "ogc.json"
API = "https://api.github.com/repos/open-greek/open-greek-corpus"
RAW_BASE = "https://raw.githubusercontent.com/open-greek/open-greek-corpus"
USER_AGENT = "melos-ogc-collector/1.0 (research corpus; polite cached fetches)"

# Source-file prefixes selected for lyric, elegy, epic, hymn, bucolic poetry,
# epigram, and small fragmentary poets. These are OGC URN/filename prefixes.
POET_PREFIXES = {
    "agathias-scholasticus.epigrammata",
    "alcaeus-lyric.", "alcman.", "alexander-lyric.", "anacreon.",
    "anacreontea.", "antimachus-elegy.", "apollonius-rhodius-epic.",
    "aratus-astronomy.", "archilochus.",
    "anthologia-graeca.", "asius.", "bacchylides.", "bion-bucolic.",
    "callimachus.", "callinus.", "choerilus.", "cleobulina-scriptor-aenigmatum.",
    "corinna.", "diodorus-periegesis.", "dionysius-chalcus.",
    "dionysius-periegesis.", "diphilus-epic.", "euphorion.", "hesiodus.",
    "hipponax.", "homerica.", "homerus-epic.", "hymni-homerici.",
    "ibycus.", "lyrica-adespota-ca.", "melanthius-elegy.",
    "lycophron-tragedy.", "lycophronides.", "mimnermus-elegy.",
    "moschus.", "musaeus-grammaticus.", "nicander-epic.",
    "nonnus.dionysiaca", "oppianus-epic.", "orphica.hymni",
    "panyassis.", "phanocles.", "phocylides.", "pindarus.",
    "pisander-epic.", "posidippus.fragmenta", "pratinas.", "quintus.posthomerica",
    "rhianus.", "sappho.", "simias.fragmenta", "simonides-ceus.", "simonides-lyric.",
    "solon.fragmenta", "terpander.", "theocritus-bucolic.",
    "theognis-elegy.", "timotheus-lyric.", "tyrtaeus.",
    "xenophanes.fragmenta", "xenophanes.testimonia",
}

# Ancient and later exegetical witnesses remain reference records, separate
# from the authored poetry. Large unrelated scholia/prose collections are out.
REFERENCE_PREFIXES = {
    # Distinct from Aratus of Soli: these are historical fragments attributed
    # to Aratus of Sicyon, retained only as a disambiguation/reference witness.
    "aratus-sicyonius.",
    "cougny-appendix-nova.", "jacobs-anthologia-graeca-t13.",
    "scholia-in-apollonium-rhodium.", "scholia-in-callimachum.",
    "scholia-in-hesiodum.", "scholia-in-homerum.",
    "scholia-in-lycophronem.", "scholia-in-pindarum.",
    "scholia-in-theocritum.",
    "porphyrius.quaestionum-homericarum",
    "certamen-homeri-et-hesiodi.",
    "vitae-homeri.", "vitae-hesiodi-particula.",
    "vitae-pindari-et-varia-de-pindaro.",
}


def get_bytes(url: str, *, retries: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code in (400, 401, 403, 404):
                break
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def save_raw(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def fetch_cached(url: str, path: Path, expected_size: int | None = None) -> bytes:
    if path.exists():
        cached = path.read_bytes()
        if expected_size is None or len(cached) == expected_size:
            return cached
    content = get_bytes(url)
    if expected_size is not None and len(content) != expected_size:
        raise ValueError(f"Wrong byte count for {url}: {len(content)} != {expected_size}")
    save_raw(path, content)
    return content


def selected(path: str) -> str | None:
    if not (path.startswith("data/corpus/") and path.endswith(".jsonl")):
        return None
    name = path.rsplit("/", 1)[-1]
    if ".testimonia" in name:
        return "reference" if any(name.startswith(prefix) for prefix in POET_PREFIXES) else None
    if any(name.startswith(prefix) for prefix in POET_PREFIXES):
        return "poetry"
    if any(name.startswith(prefix) for prefix in REFERENCE_PREFIXES):
        return "reference"
    return None


GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LATIN = re.compile(r"[A-Za-z]")

# Audited against the pinned OGC Callimachus Aetia JSONL: these prefatory
# loci contain prose bibliography/testimony, interleaved with verse loci.
REFERENCE_LOCI = {"callimachus.aetia": {"0.1", "0.4", "0.5"}}


OCR_STATUSES = {"raw ocr", "auto-corrected", "manual"}


def ocr_status_table(readme: str) -> dict[str, str]:
    """Edition-level OCR status per URN from the pinned OGC README table."""
    table: dict[str, str] = {}
    for line in readme.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[-1].lower() in OCR_STATUSES:
            table[cells[0].strip("`")] = cells[-1].lower()
    return table


def classify(row: dict, category: str, ocr_status: str | None = None) -> tuple[str, str, str]:
    """Language, kind and quality of one OGC row.

    OCR rows keep the poet named by their collection file (the source's own
    attribution) and are labelled by how the upstream corpus produced them:
    ``machine_corrected_ocr`` when its README marks the edition auto-corrected,
    ``machine_ocr`` when it is raw. Latin-heavy blocks (apparatus, testimonia
    and bibliography) remain ``mixed_content`` reference material. Owner
    decision 2026-09-30; see docs/decisions.md.
    """
    body = row["text"]
    greek = len(GREEK.findall(body))
    latin = len(LATIN.findall(body))
    ocr = row.get("source") == "ocr"
    testimony = "testimonia" in str(row.get("urn", "")).lower()
    audited_reference = str(row.get("locus", "")) in REFERENCE_LOCI.get(str(row.get("urn", "")), set())
    mixed = testimony or audited_reference or (latin >= 20 and latin > greek * 0.15)
    language = "grc" if greek >= latin else ("lat" if latin else "other")
    if category == "reference" or mixed or language != "grc":
        kind = "reference"
    else:
        kind = "text"
    if mixed or language != "grc":
        quality = "mixed_content"
    elif ocr:
        quality = "machine_corrected_ocr" if ocr_status == "auto-corrected" else "machine_ocr"
    else:
        quality = "source_text"
    return language, kind, quality


def convert_file(entry: dict, category: str, commit: str,
                 ocr_statuses: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    ocr_statuses = ocr_statuses or {}
    source_path = entry["path"]
    filename = source_path.rsplit("/", 1)[-1]
    url = f"{RAW_BASE}/{commit}/{source_path}"
    raw_file = RAW / commit / "corpus" / filename
    content = fetch_cached(url, raw_file, entry.get("size"))
    sha256 = hashlib.sha256(content).hexdigest()
    relative_raw = raw_file.relative_to(ROOT).as_posix()
    records = []
    skipped_empty = 0
    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            skipped_empty += 1
            continue
        try:
            row = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid JSON/UTF-8 at {source_path}:{line_no}") from error
        for field in ("urn", "edition", "locus", "source", "license", "text"):
            if field not in row:
                raise ValueError(f"Missing {field} at {source_path}:{line_no}")
        if not isinstance(row["text"], str) or not row["text"].strip():
            skipped_empty += 1
            continue
        urn = str(row["urn"])
        language, kind, quality = classify(row, category, ocr_statuses.get(urn))
        urn_parts = urn.split(".", 1)
        source_author = urn_parts[0]
        # Anthologies and mixed historical collections carry no poet in their
        # file name. A poet's own fragment collection keeps that poet as its
        # source attribution; a Latin-heavy block inside it stays mixed.
        collection = source_author in {
            "anthologia-graeca", "cougny-appendix-nova", "jacobs-anthologia-graeca-t13",
            "aratus-sicyonius",
        }
        author = "unknown" if quality == "mixed_content" or collection else source_author
        # OGC's own LICENSE grants its OCR of public-domain editions under
        # CC BY 4.0 in addition to the aggregate CC BY-SA 4.0 license. Source
        # JSONL marks the printed/base edition PD; retain that original label.
        effective_license = "CC-BY-4.0" if row["source"] == "ocr" and row["license"] == "PD" else row["license"]
        record = {
            "id": f"ogc:{filename}:{line_no}",
            "source": "ogc",
            "source_url": url,
            "raw_path": relative_raw,
            "raw_sha256": sha256,
            "author": author,
            "work": urn_parts[1] if len(urn_parts) > 1 else urn,
            "edition": row["edition"],
            "citation": row["locus"],
            "language": language,
            "text": row["text"],
            "kind": kind,
            "quality": quality,
            "license": effective_license,
            "metadata": {
                "ogc_urn": urn,
                "ogc_source": row["source"],
                "ogc_locus": row["locus"],
                "upstream_source": row["source"],
                "upstream_work_urn": urn,
                "upstream_edition": row["edition"],
                "source_collection_author": source_author,
                "source_row_number": line_no,
                "selection_category": category,
                "ogc_record_license": row["license"],
            },
        }
        if effective_license != row["license"]:
            record["metadata"]["effective_license_basis"] = (
                f"{RAW_BASE}/{commit}/LICENSE"
            )
        if "BY-NC" in row["license"].upper():
            # Recorded, not rejected: rights are per-record metadata (owner
            # decision 2026-09-30), so the reader can show the notice.
            record["metadata"]["noncommercial_license"] = True
        if row["source"] == "ocr":
            record["metadata"]["ocr_status"] = ocr_statuses.get(urn, "unknown")
            record["metadata"]["author_label_basis"] = "ogc_collection_file_name"
            record["metadata"]["text_verified_against_scan"] = False
        # Preserve any OGC fields not represented in the interchange schema.
        extras = {key: value for key, value in row.items()
                  if key not in {"urn", "edition", "locus", "source", "license", "text"}}
        if extras:
            record["metadata"]["ogc_extra"] = extras
        records.append(record)
    return records, {
        "path": source_path,
        "url": url,
        "raw_path": relative_raw,
        "sha256": sha256,
        "bytes": len(content),
        "records": len(records),
        "skipped_empty": skipped_empty,
        "category": category,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="specific OGC commit SHA; defaults to main HEAD")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.commit:
        commit = args.commit
    else:
        response = get_bytes(f"{API}/commits/main")
        commit = json.loads(response)["sha"]
        save_raw(RAW / commit / "commit.json", response)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--commit must be a full 40-character Git SHA")
    meta_dir = RAW / commit
    meta_dir.mkdir(parents=True, exist_ok=True)
    tree_bytes = fetch_cached(f"{API}/git/trees/{commit}?recursive=1", meta_dir / "tree.json")
    tree = json.loads(tree_bytes)
    if tree.get("truncated"):
        raise ValueError("GitHub tree is truncated; selection could be incomplete")
    ocr_statuses: dict[str, str] = {}
    for name in ("README.md", "LICENSE"):
        source_document = fetch_cached(f"{RAW_BASE}/{commit}/{name}", meta_dir / name)
        # Convenient current-run copy for downstream source-status parsers.
        save_raw(RAW / name, source_document)
        if name == "README.md":
            ocr_statuses = ocr_status_table(source_document.decode("utf-8-sig", errors="replace"))
            if not ocr_statuses:
                raise ValueError("No OCR-status table rows found in the pinned OGC README")
    for name in ("coverage.json", "corpus_editions.json"):
        fetch_cached(f"{RAW_BASE}/{commit}/data/{name}", meta_dir / name)
    choices = [(entry, category) for entry in tree["tree"]
               if (category := selected(entry["path"])) is not None]
    if not choices:
        raise ValueError("No OGC corpus files matched the configured selection")
    choices.sort(key=lambda item: item[0]["path"])
    results = {}
    errors = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(convert_file, entry, category, commit, ocr_statuses): entry["path"]
                   for entry, category in choices}
        for future in as_completed(futures):
            path = futures[future]
            try:
                results[path] = future.result()
                print(f"fetched {path}: {len(results[path][0])} records", flush=True)
            except Exception as error:
                errors.append({"path": path, "error": str(error)})
                print(f"FAILED {path}: {error}", flush=True)
    if errors:
        failure_report = {
            "status": "failed", "upstream_commit": commit, "errors": errors,
            "completed_files": len(results), "selected_files": len(choices),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(failure_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"{len(errors)} OGC files failed; processed output not updated")
    rows = []
    files = []
    for entry, _ in choices:
        file_rows, file_report = results[entry["path"]]
        rows.extend(file_rows)
        files.append(file_report)
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate generated OGC IDs")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    for attempt in range(20):
        try:
            temporary.replace(OUTPUT)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.5)
    report = {
        "status": "collected_pending_independent_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_repository": "https://github.com/open-greek/open-greek-corpus",
        "upstream_commit": commit,
        "upstream_attribution": {
            name: {
                "source_url": f"{RAW_BASE}/{commit}/{source_path}",
                "raw_path": (meta_dir / Path(source_path).name).relative_to(ROOT).as_posix(),
                "raw_sha256": hashlib.sha256((meta_dir / Path(source_path).name).read_bytes()).hexdigest(),
            }
            for name, source_path in {
                "readme": "README.md", "license": "LICENSE",
                "coverage": "data/coverage.json",
                "corpus_editions": "data/corpus_editions.json",
            }.items()
        },
        "attribution_note": (
            "OGC JSONL supplies edition/source/license per passage. The pinned coverage "
            "and corpus_editions registries are archived here; neither has editor "
            "names. Consult the upstream edition documents for editor-level credit."
        ),
        "individual_editor_attribution_unresolved": True,
        "selection": "curated file families for poetry and poetic reference; see scripts/ingest_ogc.py",
        "files": files,
        "file_count": len(files),
        "record_count": len(rows),
        "counts_by_kind": dict(Counter(row["kind"] for row in rows)),
        "counts_by_quality": dict(Counter(row["quality"] for row in rows)),
        "counts_by_language": dict(Counter(row["language"] for row in rows)),
        "counts_by_ogc_source": dict(Counter(row["metadata"]["ogc_source"] for row in rows)),
        "licenses": dict(Counter(row["license"] for row in rows)),
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "output_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records from {len(files)} files to {OUTPUT}")


if __name__ == "__main__":
    main()
