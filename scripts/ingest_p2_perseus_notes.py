"""Extract previously omitted lyric notes from the pinned Perseus TEI.

Prerequisite: ``python scripts/ingest_perseus.py`` has saved the 197 original
raw files and provenance report. This collector reads those exact source files
without re-downloading duplicates. It excludes papyrus column markers and
does not recast translator or Perseus editorial notes as ancient poetry.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPORT = ROOT / "data/reports/perseus.json"
SOURCE_RECORDS = ROOT / "data/processed/perseus.jsonl"
OUT = ROOT / "data/processed/p2_perseus_notes.jsonl"
REPORT = ROOT / "data/reports/p2_perseus_notes.json"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
SPACE = re.compile(r"\s+")
TEXTUAL_CUE = re.compile(
    r"\b(?:read(?:ing)?|mss?|manuscripts?|punctuat\w*|commas?|periods?|"
    r"omit(?:ted)?|adding|gaps?|papyrus|fragmentary|missing|lost)\b",
    re.IGNORECASE,
)
TARGET_AUTHORS = {"Pindar", "Bacchylides"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def citation(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    labels: list[str] = []
    cursor: ET.Element | None = parents.get(node)
    while cursor is not None:
        if cursor.tag in {NS + "div", NS + "l", NS + "p", NS + "lg", NS + "seg"}:
            label = cursor.attrib.get("n") or cursor.attrib.get(XML + "id")
            if label and not label.startswith("urn:cts:"):
                labels.append(label)
        cursor = parents.get(cursor)
    return ".".join(reversed(labels))


def original_indexes() -> tuple[dict[str, str], dict[tuple[str, str], str], set[str]]:
    editions: dict[str, str] = {}
    greek_lines: dict[tuple[str, str], str] = {}
    old_text_hashes: set[str] = set()
    with SOURCE_RECORDS.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            editions.setdefault(record["raw_path"], record["edition"])
            old_text_hashes.add(digest(record["text"].encode("utf-8")))
            if record["language"] != "grc":
                continue
            work_urn = ".".join(record["metadata"]["cts_urn"].split(".")[:2])
            for source_line in record.get("lines", []):
                greek_lines.setdefault((work_urn, source_line["label"]), record["id"])
    return editions, greek_lines, old_text_hashes


def responsibility(root: ET.Element, raw_resp: str | None) -> tuple[str | None, str | None]:
    if not raw_resp:
        return None, None
    authority = root.find(f".//{NS}publicationStmt/{NS}authority")
    if authority is not None:
        name = clean("".join(authority.itertext()))
        if raw_resp.casefold() in name.casefold():
            return name, "editorial_project"
    title_stmt = root.find(f".//{NS}fileDesc/{NS}titleStmt")
    if title_stmt is not None:
        for child in title_stmt:
            name = clean("".join(child.itertext()))
            if raw_resp.casefold() in name.casefold() and name:
                return name, child.attrib.get("role") or child.tag.removeprefix(NS)
    return raw_resp, "unresolved_source_label"


def main() -> None:
    sources = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))["sources"]
    editions, greek_lines, old_text_hashes = original_indexes()
    selected = [source for source in sources if source["author"] in TARGET_AUTHORS]
    records: list[dict] = []
    source_rows: list[dict] = []
    excluded: collections.Counter[str] = collections.Counter()
    kinds: collections.Counter[str] = collections.Counter()
    overlap = 0

    for source in selected:
        raw_path = source["path"]
        raw_file = ROOT / raw_path
        if not raw_file.exists():
            raise FileNotFoundError(f"Run scripts/ingest_perseus.py first: {raw_path}")
        payload = raw_file.read_bytes()
        if digest(payload) != source["sha256"]:
            raise ValueError(f"Original source hash mismatch: {raw_path}")
        root = ET.fromstring(payload)
        body = root.find(f".//{NS}text/{NS}body")
        if body is None:
            raise ValueError(f"No TEI text body: {raw_path}")
        parents = {child: parent for parent in body.iter() for child in parent}
        urn = raw_file.stem
        work_urn = ".".join(urn.split(".")[:2])
        source_count = 0
        for index, note in enumerate(body.iter(NS + "note"), 1):
            note_type = note.attrib.get("type", "")
            if note_type == "Papyr":
                excluded["Papyr_column_markers"] += 1
                continue
            note_text = clean("".join(note.itertext()))
            if not note_text:
                excluded["empty_notes"] += 1
                continue
            cite = citation(note, parents)
            if not cite:
                raise ValueError(f"Note without source locator: {raw_path} note {index}")
            cue = TEXTUAL_CUE.search(note_text)
            kind = "apparatus" if note_type.casefold() == "text" or cue else "commentary"
            note_lang = note.attrib.get(XML + "lang") or source["language"]
            if note_lang not in {"eng", "grc", "lat"}:
                raise ValueError(f"Unexpected note language {note_lang}: {raw_path}")
            resp_name, resp_role = responsibility(root, note.attrib.get("resp"))
            record = {
                "id": f"p2_perseus_notes:{urn}:{cite}:note-{index}",
                "source": "p2_perseus_notes", "source_url": source["url"],
                "raw_path": raw_path, "raw_sha256": source["sha256"],
                "author": source["author"], "work": source["work"],
                "edition": editions[raw_path], "citation": cite,
                "language": note_lang, "text": note_text, "kind": kind,
                "quality": "source_text", "license": source["license"],
                "metadata": {
                    "cts_urn": urn, "source_note_index": index,
                    "source_note_type": note_type or None,
                    "source_note_responsibility": note.attrib.get("resp"),
                    "source_note_responsible_name": resp_name,
                    "source_note_responsible_role": resp_role,
                    "classification_method": "TEI type=text or source-text textual cue regex v1" if kind == "apparatus" else "TEI note without textual cue regex v1",
                    "classification_cue": cue.group(0) if cue else None,
                    "rights_basis": "repository_default_unverified_in_tei" if "repository default" in source["license"] else "explicit_tei_license",
                    "source_family": "Perseus pinned canonical-greekLit source edition",
                    "original_collector": "scripts/ingest_perseus.py",
                    "original_source_commit": json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))["commit"],
                },
            }
            parent_id = greek_lines.get((work_urn, cite))
            if parent_id:
                record["parent_id"] = parent_id
            records.append(record)
            source_count += 1
            kinds[kind] += 1
            if digest(note_text.encode("utf-8")) in old_text_hashes:
                overlap += 1
        source_rows.append({
            "path": raw_path, "url": source["url"], "sha256": source["sha256"],
            "work": source["work"], "author": source["author"],
            "license": source["license"], "notes_extracted": source_count,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = {
        "original_pinned_repository": json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))["repository"],
        "original_pinned_commit": json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))["commit"],
        "original_raw_files_inspected": len(selected),
        "source_files_with_notes": sum(row["notes_extracted"] > 0 for row in source_rows),
        "record_count": len(records), "kind_counts": dict(kinds),
        "excluded": dict(excluded), "exact_text_overlap_with_original_records": overlap,
        "sources": source_rows, "output_sha256": digest(OUT.read_bytes()),
        "rights_review": {
            "pindar_translation_notes": "PASS with repository-default CC BY-SA 4.0 caveat; individual TEI files lack availability statements",
            "repository_rights_url": "https://github.com/PerseusDL/canonical-greekLit/blob/bcc5df0602f3b3fe6fefe1e1d575602a25ab1db6/README.md",
            "credit_and_condition": "Credit translator Diane Arnson Svarlien and Perseus; preserve share-alike and the repository modification-offer condition",
            "bacchylides_notes": "Explicit TEI CC BY-SA 4.0",
        },
        "scope_note": "Only source-authored notes omitted by the original Perseus collector; Papyr column labels excluded. Translator and editor observations remain distinct from ancient verse.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("record_count", "kind_counts", "excluded", "exact_text_overlap_with_original_records", "output_sha256")}, indent=2))


if __name__ == "__main__":
    main()
