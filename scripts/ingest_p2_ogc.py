"""Stage lyric-adjacent OGC editions missing from the first collector.

The pinned repository tree and edition registry are cached by ingest_ogc.py.
Run from the project root: python scripts/ingest_p2_ogc.py
All Greek text is copied from downloaded, commit-pinned JSONL rows. OCR
fragments remain reference records until independently checked against scans.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "f4062a5013e56d2727e3e88e7a8d8e13d207a06d"
BASE = f"https://raw.githubusercontent.com/open-greek/open-greek-corpus/{COMMIT}"
RAW = ROOT / "data/raw/p2_ogc"
OUTPUT = ROOT / "data/processed/p2_ogc.jsonl"
REPORT = ROOT / "data/reports/p2_ogc.json"
PRIOR_REPORT = ROOT / "data/reports/ogc.json"
PRIOR_RAW = ROOT / "data/raw/ogc" / COMMIT
EXISTING_OUTPUTS = (
    "ogc.jsonl", "perseus.jsonl", "lyra.jsonl", "reception.jsonl",
    "sappho.jsonl", "commentary.jsonl", "lyric_web.jsonl",
)
FILES = {
    "ananius.fragmenta.jsonl": "lyric_fragment_collection",
    "carmina-convivialia-pmg.fragmenta.jsonl": "lyric_collection",
    "carmina-popularia-pmg.fragmenta.jsonl": "lyric_collection",
    "erinna.fragmenta.jsonl": "lyric_fragment_collection",
    "praxilla.fragmenta.jsonl": "lyric_fragment_collection",
    "telesilla.fragmenta.jsonl": "lyric_fragment_collection",
    "telestes.fragmenta.jsonl": "lyric_fragment_collection",
    "timocreon.fragmenta.jsonl": "lyric_fragment_collection",
    "philoxenus.fragmenta.jsonl": "lyric_fragment_collection",
    "hephaestion-grammar.enchiridion-de-metris.jsonl": "metrical_commentary",
    "hephaestion-grammar.de-poematis.jsonl": "metrical_commentary",
    "hephaestion-grammar.introductio-metrica.jsonl": "metrical_commentary",
}
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LATIN = re.compile(r"[A-Za-z]")
EDITORIAL_REFERENCE = re.compile(
    r"(?<![A-Za-z])(?:Fr\.?\s*\d+[A-Za-z]?|Athen\.?\s*[IVXLCDM0-9]+(?:\s+[0-9]+)?"
    r"|Schol\.?\s+[A-Za-z]+|Herodian\.?|Diogenian\.?|Suidas?\.?|Eustath\.?)",
    re.IGNORECASE,
)
USER_AGENT = "melos-p2-ogc-collector/1.0 (research corpus; pinned cached fetch)"
FIRST1K_COMMIT = "8ee111eb44ecef4120c844e10749178d95d1f30c"
FIRST1K_BASE = f"https://raw.githubusercontent.com/OpenGreekAndLatin/First1KGreek/{FIRST1K_COMMIT}"
FIRST1K_TEI = {
    "hephaestion-grammar.enchiridion-de-metris.jsonl": "data/tlg1402/tlg001/tlg1402.tlg001.1st1K-grc1.xml",
    "hephaestion-grammar.introductio-metrica.jsonl": "data/tlg1402/tlg002/tlg1402.tlg002.1st1K-grc1.xml",
    "hephaestion-grammar.de-poematis.jsonl": "data/tlg1402/tlg003/tlg1402.tlg003.1st1K-grc1.xml",
}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def get_bytes(url: str) -> bytes:
    last_error = None
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code in {400, 401, 403, 404}:
                break
            if attempt < 3:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def fetch_file(entry: dict) -> tuple[str, bytes]:
    name = Path(entry["path"]).name
    url = f"{BASE}/{entry['path']}"
    target = RAW / COMMIT / "corpus" / name
    if target.exists():
        content = target.read_bytes()
        if len(content) != entry["size"]:
            raise ValueError(f"Cached byte count differs from pinned tree: {target}")
    else:
        content = get_bytes(url)
        if len(content) != entry["size"]:
            raise ValueError(f"Downloaded byte count differs from pinned tree: {url}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return name, content


def fetch_tei(name: str, source_path: str) -> dict:
    url = f"{FIRST1K_BASE}/{source_path}"
    target = RAW / "first1k" / FIRST1K_COMMIT / Path(source_path).name
    if target.exists():
        content = target.read_bytes()
    else:
        content = get_bytes(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    root = ET.fromstring(content)
    if not root.tag.endswith("}TEI"):
        raise ValueError(f"No TEI root in {url}")
    header = root.find("{http://www.tei-c.org/ns/1.0}teiHeader")
    if header is None:
        raise ValueError(f"No TEI header in {url}")
    namespace = "{http://www.tei-c.org/ns/1.0}"
    license_element = header.find(f".//{namespace}licence")
    rights_target = license_element.get("target", "") if license_element is not None else ""
    if "creativecommons.org/licenses/by-sa/4.0" not in rights_target.lower():
        raise ValueError(f"Missing CC BY-SA 4.0 rights notice in {url}")
    title_editor = header.find(f".//{namespace}titleStmt/{namespace}editor")
    source_editor = header.find(f".//{namespace}sourceDesc/{namespace}biblStruct/{namespace}monogr/{namespace}editor")
    return {"source_url": url, "raw_path": target.relative_to(ROOT).as_posix(),
            "raw_sha256": sha256(content), "bytes": len(content),
            "tei_header_present": True, "rights_url": rights_target,
            "title_statement_editor": title_editor.text if title_editor is not None else None,
            "source_description_editor": source_editor.text if source_editor is not None else None,
            "editor_name_discrepancy": (
                title_editor is not None and source_editor is not None and
                title_editor.text != source_editor.text
            ),
            "ogc_role": "upstream_edition_metadata_and_citation_check"}


def exact_text_overlaps(records: list[dict]) -> dict:
    """Report possible mirrors/repetitions; exact equality is not proof of identity."""
    targets = {sha256(record["text"].encode("utf-8")) for record in records}
    existing = {}
    source_counts = Counter()
    for name in EXISTING_OUTPUTS:
        path = ROOT / "data/processed" / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                old = json.loads(line)
                body = old.get("text")
                if not isinstance(body, str):
                    continue
                digest = sha256(body.encode("utf-8"))
                if digest in targets and digest not in existing:
                    existing[digest] = {"id": old.get("id"), "source_file": name}
                    source_counts[name] += 1
    overlaps = []
    for record in records:
        digest = sha256(record["text"].encode("utf-8"))
        match = existing.get(digest)
        if match:
            overlaps.append({"new_id": record["id"], "existing_id": match["id"],
                             "existing_source_file": match["source_file"],
                             "text_characters": len(record["text"])})
    return {"exact_text_record_overlaps": len(overlaps),
            "exact_text_overlaps_80_plus_chars": sum(item["text_characters"] >= 80 for item in overlaps),
            "matched_existing_sources": dict(source_counts),
            "examples": overlaps[:30],
            "interpretation": "Exact text equality flags possible mirrors or quotations, not independently established edition identity."}


def carmina_near_overlaps(records: list[dict]) -> dict:
    """Find likely repeated Bergk OCR page material across two collections."""
    groups = {}
    for stem in ("carmina-convivialia-pmg", "carmina-popularia-pmg"):
        groups[stem] = [record for record in records if
                        record["metadata"]["ogc_urn"].startswith(stem) and
                        len(record["text"]) >= 80]
    def shingles(body: str) -> set[str]:
        return {body[index:index + 5] for index in range(len(body) - 4)}
    right = [(row, shingles(row["text"])) for row in groups["carmina-popularia-pmg"]]
    pairs = []
    for left in groups["carmina-convivialia-pmg"]:
        left_text = left["text"]
        left_shingles = shingles(left_text)
        for other, other_shingles in right:
            length_ratio = min(len(left_text), len(other["text"])) / max(len(left_text), len(other["text"]))
            if length_ratio < 0.8:
                continue
            similarity = len(left_shingles & other_shingles) / len(left_shingles | other_shingles)
            if similarity < 0.25:
                continue
            ratio = SequenceMatcher(None, left_text, other["text"], autojunk=False).ratio()
            if ratio >= 0.85:
                pairs.append({"left_id": left["id"], "right_id": other["id"],
                              "similarity_ratio": round(ratio, 4),
                              "shared_edition": left["edition"]})
    return {"pair_count": len(pairs), "pairs": pairs,
            "interpretation": "OCR near matches from one Bergk edition are not independent witnesses."}


def main() -> None:
    tree = json.loads((PRIOR_RAW / "tree.json").read_text(encoding="utf-8"))
    registry = json.loads((PRIOR_RAW / "corpus_editions.json").read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_REPORT.read_text(encoding="utf-8"))
    if prior["upstream_commit"] != COMMIT or tree.get("truncated"):
        raise ValueError("Pinned OGC commit mismatch or truncated tree")
    by_path = {entry["path"]: entry for entry in tree["tree"]}
    old_paths = {item["path"] for item in prior["files"]}
    entries = []
    for name in FILES:
        path = f"data/corpus/{name}"
        if path in old_paths:
            raise ValueError(f"First collector already selected {path}")
        if path not in by_path or name.removesuffix(".jsonl") not in registry:
            raise ValueError(f"Absent from pinned tree/registry: {path}")
        entries.append(by_path[path])

    fetched = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_file, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            name, content = future.result()
            fetched[name] = content
            print(f"Fetched {name}: {len(content)} bytes", flush=True)
    tei_sources = {name: fetch_tei(name, source_path)
                   for name, source_path in FIRST1K_TEI.items()}

    records = []
    files = []
    for entry in entries:
        name = Path(entry["path"]).name
        family = FILES[name]
        content = fetched[name]
        urn = name.removesuffix(".jsonl")
        registry_row = registry[urn]
        source_url = f"{BASE}/{entry['path']}"
        raw_path = (RAW / COMMIT / "corpus" / name).relative_to(ROOT).as_posix()
        raw_hash = sha256(content)
        file_count = 0
        for line_no, raw_line in enumerate(content.splitlines(), 1):
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            for field in ("urn", "edition", "locus", "source", "license", "text"):
                if field not in row:
                    raise ValueError(f"Missing {field}: {name}:{line_no}")
            if not isinstance(row["text"], str) or not row["text"].strip():
                continue
            if row["urn"] != urn or row["edition"] != registry_row["edition"] or row["source"] != registry_row["source"]:
                raise ValueError(f"Pinned registry disagreement: {name}:{line_no}")
            if "BY-NC" in row["license"].upper():
                raise ValueError(f"Noncommercial license: {name}:{line_no}")
            source_author, work = urn.split(".", 1)
            is_ocr = row["source"] == "ocr"
            greek = len(GREEK.findall(row["text"]))
            latin = len(LATIN.findall(row["text"]))
            language = "grc" if greek >= latin else ("lat" if latin else "other")
            # Bergk fragment rows can contain ancient quotations, Latin
            # apparatus, testimonia and other poets. The filename is a
            # collection label, never proof of the quoted passage's author.
            if is_ocr:
                author = "unknown"
                kind = "reference"
                quality = "mixed_content" if latin >= 20 and latin > greek * 0.15 else "machine_ocr"
                license_name = "CC-BY-4.0" if row["license"] == "PD" else row["license"]
            else:
                author = source_author
                kind = "commentary"
                quality = "source_text" if language == "grc" else "needs_review"
                license_name = row["license"]
            record = {
                "id": f"p2_ogc:{name}:{line_no}",
                "source": "p2_ogc",
                "source_url": source_url,
                "raw_path": raw_path,
                "raw_sha256": raw_hash,
                "author": author,
                "work": work,
                "edition": row["edition"],
                "citation": row["locus"],
                "language": language,
                "text": row["text"],
                "kind": kind,
                "quality": quality,
                "license": license_name,
                "metadata": {
                    "ogc_urn": row["urn"],
                    "ogc_locus": row["locus"],
                    "ogc_source": row["source"],
                    "ogc_record_license": row["license"],
                    "source_collection_author": source_author,
                    "source_row_number": line_no,
                    "selection_category": family,
                    "author_label_basis": "ogc_work_urn" if not is_ocr else "unknown_due_to_mixed_fragment_collection",
                    "embedded_quote_author_verified": False,
                    "citation_scope": "ogc_row_locus_not_canonical_fragment_number" if is_ocr else "ogc_row_locus",
                    "text_verified_against_scan": False if is_ocr else None,
                    "upstream_registry_id": registry_row["id"],
                    "underlying_source_family": (
                        f"Bergk:{row['edition']}" if is_ocr else
                        f"First1KGreek:{row['urn']}:{row['edition']}"
                    ),
                },
            }
            if is_ocr:
                # Literal editorial references are triage cues, not parsed
                # witness or poet attributions. The exact source substring
                # and codepoint offsets permit later independent checking.
                record["metadata"]["embedded_reference_markers"] = [
                    {"start": marker.start(), "end": marker.end(), "text": marker.group()}
                    for marker in EDITORIAL_REFERENCE.finditer(row["text"])
                ]
            if license_name != row["license"]:
                record["metadata"]["effective_license_basis"] = f"{BASE}/LICENSE"
            if name in tei_sources:
                record["metadata"]["upstream_tei"] = tei_sources[name]
                record["metadata"]["ogc_transformation_warning"] = (
                    "OGC may omit TEI bibliography/citation content; verify exact quotations against upstream TEI."
                )
            extras = {key: value for key, value in row.items() if key not in
                      {"urn", "edition", "locus", "source", "license", "text"}}
            if extras:
                record["metadata"]["ogc_extra"] = extras
            records.append(record)
            file_count += 1
        files.append({"path": entry["path"], "source_url": source_url,
                      "raw_path": raw_path, "raw_sha256": raw_hash,
                      "bytes": len(content), "records": file_count,
                      "registry": registry_row})
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate generated IDs")
    overlaps = exact_text_overlaps(records)
    near_overlaps = carmina_near_overlaps(records)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(OUTPUT)
    report = {
        "status": "staged_pending_independent_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": COMMIT,
        "upstream_repository": "https://github.com/open-greek/open-greek-corpus",
        "rights_url": f"{BASE}/LICENSE",
        "upstream_tei_commit": FIRST1K_COMMIT,
        "upstream_tei_sources": tei_sources,
        "selection_note": "Previously unselected lyric OCR collections and First1K metrical commentaries; OCR is reference only.",
        "hephaestion_scope": {
            "selected_works": sorted(name.removesuffix(".jsonl") for name in FIRST1K_TEI),
            "other_ogc_works": sorted(
                urn for urn in registry if urn.startswith("hephaestion-grammar.")
                and f"{urn}.jsonl" not in FIRST1K_TEI
            ),
            "complete_author_coverage": False,
        },
        "first_pass_records_unchanged": prior["record_count"],
        "files": files,
        "file_count": len(files),
        "record_count": len(records),
        "counts_by_kind": dict(Counter(record["kind"] for record in records)),
        "counts_by_quality": dict(Counter(record["quality"] for record in records)),
        "counts_by_language": dict(Counter(record["language"] for record in records)),
        "counts_by_source": dict(Counter(record["metadata"]["ogc_source"] for record in records)),
        "counts_by_underlying_source_family": dict(Counter(
            record["metadata"]["underlying_source_family"] for record in records
        )),
        "ocr_records_with_literal_reference_markers": sum(
            bool(record["metadata"].get("embedded_reference_markers")) for record in records
        ),
        "overlaps_with_existing": overlaps,
        "carmina_near_overlaps": near_overlaps,
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "output_sha256": sha256(OUTPUT.read_bytes()),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {len(records)} records from {len(files)} files")


if __name__ == "__main__":
    main()
