"""Label OGC passage reliability without changing the collector's source text.

Reads the collector's pinned OGC README and processed passages. Edition-level
OCR status comes only from the README table; block-level flags come from exact
spans of each preserved passage. Derived prefixes are reference-only slices,
never reconstructions or verified poet attestations.
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/ogc.jsonl"
README = ROOT / "data/raw/ogc/README.md"
REPORT = ROOT / "data/reports/ogc-quality.json"
COLLECTOR_REPORT = ROOT / "data/reports/ogc.json"
ANNOTATIONS = ROOT / "data/annotations/ogc-quality.jsonl"
DERIVED = ROOT / "data/processed/ogc_derived.jsonl"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LATIN_WORD = re.compile(r"(?<![A-Za-z])[A-Za-z]{3,}(?![A-Za-z])")
STRONG_EDITORIAL = re.compile(
    r"(?<![A-Za-z])(?:Cf\.|Athen\.|Diog\.|Suid\.|Aelian\.|Schol\."
    r"|scripsi\b|libri\b|codd?\.|Hermann\b|sed idem\b|V\.\s*\d+)",
    re.IGNORECASE,
)
REPLACEMENT = "\ufffd"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def edition_table(raw: str) -> dict[str, dict]:
    result = {}
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.startswith("| "):
            continue
        fields = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(fields) < 6 or not fields[0] or fields[0] == "URN":
            continue
        status = fields[-1].lower()
        if status not in {"raw ocr", "auto-corrected", "manual"}:
            continue
        result[fields[0]] = {
            "urn": fields[0],
            "edition": fields[2],
            "model": fields[3],
            "ocr_status": status,
            "readme_line": number,
            "readme_line_sha256": sha256(line.encode("utf-8")),
        }
    if not result:
        raise ValueError("No OCR-status table rows found in saved OGC README")
    return result


def evidence(text: str, pattern: re.Pattern, limit: int = 3) -> list[dict]:
    return [
        {"start": m.start(), "end": m.end(), "text": text[m.start():m.end()]}
        for m in itertools.islice(pattern.finditer(text), limit)
    ]


def classify(record: dict, status: dict | None, readme_hash: str) -> tuple[dict, dict | None]:
    text = record["text"]
    greek_count = len(GREEK.findall(text))
    latin = evidence(text, LATIN_WORD)
    editorial = evidence(text, STRONG_EDITORIAL)
    latin_count = len(re.findall(r"[A-Za-z]", text))
    source_method = (record.get("metadata") or {}).get("ogc_source", "")
    urn = (record.get("metadata") or {}).get("ogc_urn", "")
    edition = record.get("edition", "")
    is_dcc = source_method == "dcc" or edition == "dcc-sappho"
    is_edited = record.get("quality") == "source_text" and source_method != "ocr"
    flags = []
    if REPLACEMENT in text:
        flags.append("replacement_character")
    if record.get("quality") == "mixed_content":
        flags.append("collector_mixed_content")
    # Source review found that this complete file contains historical prose
    # witnesses about Aratus, while the Aetia file mixes poet text and Greek
    # biographical/testimonial prose. These are scope guards, not new text.
    if urn == "aratus-sicyonius.fragmenta":
        flags.append("historical_witness_collection")
    if urn == "callimachus.aetia":
        flags.append("source_review_required")
        if str(record.get("citation", "")).startswith("0.") and str(record.get("citation", "")) != "0.2":
            flags.append("introductory_witness")
    if greek_count < 3:
        flags.append("negligible_greek")
    elif greek_count < 15:
        flags.append("short_fragment")
    if editorial:
        flags.append("explicit_editorial_marker")
    elif len(latin) >= 2:
        flags.append("latin_prose_or_apparatus")
    if not is_dcc and greek_count and latin_count > 2 * greek_count:
        flags.append("latin_dominant")

    if is_dcc:
        method = "dcc_edited_source_text"
    elif source_method and source_method != "ocr":
        method = f"{source_method or 'unknown'}_source_text"
    elif status and status["ocr_status"] == "auto-corrected":
        method = "machine_corrected_ocr"
    elif status and status["ocr_status"] == "raw ocr":
        method = "raw_ocr"
    elif status and status["ocr_status"] == "manual":
        method = "manual_transcription"
    else:
        method = "unknown"

    if "replacement_character" in flags or "negligible_greek" in flags or "latin_dominant" in flags:
        block_label = "defective_block"
    elif ("collector_mixed_content" in flags or "explicit_editorial_marker" in flags
          or "latin_prose_or_apparatus" in flags or "introductory_witness" in flags):
        block_label = "mixed_author_commentary"
    elif is_edited:
        block_label = "clean_source_text"
    else:
        block_label = "ocr_text_candidate"

    selection_category = (record.get("metadata") or {}).get("selection_category")
    bibliographic_scope = "poetry" if selection_category == "poetry" and urn != "aratus-sicyonius.fragmenta" and not re.search(
        r"(?:testimonia|scholia|antholog|appendix)",
        " ".join((record.get("work", ""), (record.get("metadata") or {}).get("ogc_urn", ""))),
        re.IGNORECASE,
    ) else "reference_or_collection"
    annotation = {
        "id": f"ogc-quality:{record['id']}",
        "parent_id": record["id"],
        "parent_text_sha256": sha256(text.encode("utf-8")),
        "source_url": record["source_url"],
        "raw_path": record["raw_path"],
        "raw_sha256": record["raw_sha256"],
        "edition_method": method,
        "block_label": block_label,
        "bibliographic_scope": bibliographic_scope,
        "primary_search_eligible": (
            block_label == "clean_source_text" and record.get("kind") == "text"
            and bibliographic_scope == "poetry" and "source_review_required" not in flags
        ),
        "flags": flags,
        "evidence": {"editorial": editorial, "latin_words": latin},
        "counts": {"greek_letters": greek_count, "latin_letters": latin_count},
        "edition_evidence": (
            {"urn": status["urn"], "ocr_status": status["ocr_status"],
             "readme_line": status["readme_line"],
             "readme_line_sha256": status["readme_line_sha256"],
             "readme_sha256": readme_hash} if status else None
        ),
        "method": "scripts/label_ogc.py; deterministic Unicode and citation-marker scan",
    }

    # A citation marker can delimit a literal initial verse span. The slice
    # stays a reference candidate because the edition's attribution may be
    # wrong and the remaining Greek may still include quoted testimony.
    derived = None
    if source_method == "ocr" and block_label == "mixed_author_commentary" and editorial:
        cut = editorial[0]["start"]
        prefix = text[:cut].rstrip()
        prefix_greek = len(GREEK.findall(prefix))
        prefix_latin = len(re.findall(r"[A-Za-z]", prefix))
        if prefix_greek >= 20 and prefix_greek >= 4 * prefix_latin:
            end = len(prefix)
            derived = dict(record)
            derived["id"] = f"{record['id']}::prefix:0-{end}"
            derived["source"] = "ogc_derived"
            derived["text"] = prefix
            derived["parent_id"] = record["id"]
            derived["author"] = "unknown"
            derived["work"] = "Unverified OCR excerpt"
            derived["kind"] = "reference"
            derived["quality"] = "machine_ocr"
            derived["metadata"] = {
                **(record.get("metadata") or {}),
                "derivation": {
                    "method": "exact prefix before first strong editorial marker",
                    "script": "scripts/label_ogc.py",
                    "parent_text_sha256": annotation["parent_text_sha256"],
                    "span_start": 0,
                    "span_end": end,
                    "boundary_evidence": editorial[0],
                    "source_collection_author": record.get("author"),
                    "source_collection_work": record.get("work"),
                    "author_attribution_verified": False,
                    "reconstruction": False,
                },
            }
            annotation["derived_id"] = derived["id"]
    return annotation, derived


def main() -> None:
    if not INPUT.is_file() or not README.is_file() or not COLLECTOR_REPORT.is_file():
        raise FileNotFoundError("Run the OGC collector first; processed JSONL, report, and saved README are required")
    collector = json.loads(COLLECTOR_REPORT.read_text(encoding="utf-8"))
    expected_hash = collector["output_sha256"]
    input_hash = sha256(INPUT.read_bytes())
    if input_hash != expected_hash:
        raise ValueError("OGC collector report and processed JSONL hashes differ; wait for collection to finish")
    raw_readme = README.read_bytes()
    readme_hash = sha256(raw_readme)
    pinned_readme = ROOT / "data/raw/ogc" / collector["upstream_commit"] / "README.md"
    if not pinned_readme.is_file() or sha256(pinned_readme.read_bytes()) != readme_hash:
        raise ValueError("Saved OGC README does not match the pinned collector artifact")
    table = edition_table(raw_readme.decode("utf-8-sig"))
    stats = collections.Counter()
    missing_editions = set()
    seen = set()
    for path in (ANNOTATIONS, DERIVED, REPORT):
        path.parent.mkdir(parents=True, exist_ok=True)
    count = derived_count = 0
    with INPUT.open(encoding="utf-8-sig") as source, ANNOTATIONS.open("w", encoding="utf-8") as labels, DERIVED.open("w", encoding="utf-8") as slices:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record["id"] in seen:
                raise ValueError(f"duplicate input id at line {number}: {record['id']}")
            seen.add(record["id"])
            urn = (record.get("metadata") or {}).get("ogc_urn")
            if not urn:
                urn = Path(record["raw_path"]).stem
            status = table.get(urn)
            if not status and (record.get("metadata") or {}).get("ogc_source") == "ocr":
                missing_editions.add(urn)
            annotation, candidate = classify(record, status, readme_hash)
            labels.write(json.dumps(annotation, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
            stats[(annotation["edition_method"], annotation["block_label"])] += 1
            if candidate:
                if candidate["text"] != record["text"][:candidate["metadata"]["derivation"]["span_end"]]:
                    raise AssertionError("derived text is not an exact parent span")
                slices.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
                derived_count += 1
    if not count:
        raise ValueError("No OGC records found")
    if sha256(INPUT.read_bytes()) != expected_hash or json.loads(COLLECTOR_REPORT.read_text(encoding="utf-8"))["output_sha256"] != expected_hash:
        raise ValueError("OGC input changed while labelling; outputs must be regenerated")
    report = {
        "input": str(INPUT.relative_to(ROOT)).replace("\\", "/"),
        "input_sha256": expected_hash,
        "upstream_commit": collector["upstream_commit"],
        "readme": str(README.relative_to(ROOT)).replace("\\", "/"),
        "readme_sha256": readme_hash,
        "records": count,
        "derived_reference_prefixes": derived_count,
        "method_block_counts": [{"edition_method": key[0], "block_label": key[1], "count": value}
                                for key, value in sorted(stats.items())],
        "missing_readme_urns": sorted(missing_editions),
        "annotation_output": str(ANNOTATIONS.relative_to(ROOT)).replace("\\", "/"),
        "derived_output": str(DERIVED.relative_to(ROOT)).replace("\\", "/"),
        "limitations": [
            "OCR method is edition-level evidence; block-level flags do not certify author attribution.",
            "Derived prefixes are exact substrings and reference-only, never repaired Greek.",
            "Unflagged OCR blocks remain candidates rather than verified poet text.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
