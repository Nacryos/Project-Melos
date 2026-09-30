"""Extract a small comparative Latin lyric corpus from pinned Perseus TEI files.

These are reception/context works, not asserted direct adaptations of Greek poems.
All text and bibliography come from raw downloaded TEI, not from constants below.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/reception"
OUTPUT = ROOT / "data/processed/reception.jsonl"
REPORT = ROOT / "data/reports/reception.json"
COMMIT = "cc843833e101992ba54549005273cfe61a33504b"
BASE = f"https://raw.githubusercontent.com/PerseusDL/canonical-latinLit/{COMMIT}/"
TEI = "{http://www.tei-c.org/ns/1.0}"
CTS = "{http://chs.harvard.edu/xmlns/cts}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
WORKS = ["phi0472/phi001", "phi0893/phi001", "phi0893/phi003", "phi0690/phi001"]
VERSIONS = ("perseus-lat2", "perseus-eng2", "perseus-eng3", "perseus-eng4")
MIXED_TAGS = {"note", "app", "choice", "corr", "sic", "del", "supplied", "add", "gap"}


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def element_text(element: ET.Element | None) -> str:
    return normalized("".join(element.itertext())) if element is not None else ""


def download(path: str, cached: bool, session: requests.Session) -> bytes:
    target = RAW / path
    if cached:
        if not target.is_file():
            raise FileNotFoundError(target)
        return target.read_bytes()
    error = None
    for attempt in range(5):
        try:
            response = session.get(BASE + path, timeout=45)
            response.raise_for_status()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return response.content
        except requests.RequestException as exc:
            error = exc
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Download failed for {BASE + path}: {error}")


def work_files(work_dir: str, cached: bool, session: requests.Session) -> tuple[dict, list[tuple[str, bytes]]]:
    metadata_path = f"data/{work_dir}/__cts__.xml"
    metadata_bytes = download(metadata_path, cached, session)
    metadata = ET.fromstring(metadata_bytes)
    versions = []
    for version in metadata:
        if version.tag.rsplit("}", 1)[-1] not in ("edition", "translation"):
            continue
        urn = version.attrib.get("urn", "")
        if not any(urn.endswith(v) for v in VERSIONS):
            continue
        filename = urn.rsplit(":", 1)[-1] + ".xml"
        path = f"data/{work_dir}/{filename}"
        versions.append((path, download(path, cached, session)))
    if not versions:
        raise ValueError(f"No configured TEI versions found in {metadata_path}")
    return {
        "metadata_path": (RAW / metadata_path).relative_to(ROOT).as_posix(),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "metadata_url": BASE + metadata_path,
        "title": next((element_text(e) for e in metadata if e.tag.rsplit("}", 1)[-1] == "title"), ""),
        "version_count": len(versions),
    }, versions


def poem_citation(poem: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    labels = [poem.attrib.get("n", "")]
    ancestor = parents.get(poem)
    while ancestor is not None:
        if ancestor.attrib.get("subtype") == "book" and ancestor.attrib.get("n", "").isdigit():
            labels.insert(0, ancestor.attrib["n"])
        ancestor = parents.get(ancestor)
    if not all(labels):
        raise ValueError("Poem lacks a usable CTS n label")
    return ".".join(labels)


def parse_version(path: str, data: bytes, repo_default_license: bool) -> list[dict]:
    root = ET.fromstring(data)
    header = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    body = root.find(f"{TEI}text/{TEI}body")
    if header is None or body is None:
        raise ValueError(f"TEI file missing fileDesc or body: {path}")
    title_stmt = header.find(f"{TEI}titleStmt")
    if title_stmt is None:
        raise ValueError(f"TEI file missing titleStmt: {path}")
    author = element_text(title_stmt.find(f"{TEI}author"))
    work = element_text(title_stmt.find(f"{TEI}title"))
    if not author or not work:
        raise ValueError(f"TEI file missing author/title: {path}")
    monograph = header.find(f"{TEI}sourceDesc/{TEI}biblStruct/{TEI}monogr")
    edition_biblio = element_text(monograph)
    urn = Path(path).stem
    file_lang = "eng" if ".perseus-eng" in urn else "lat"
    text_div = next((d for d in body.iter(f"{TEI}div") if d.attrib.get("type") in ("edition", "translation")), None)
    if text_div is None:
        raise ValueError(f"No edition or translation div: {path}")
    declared_lang = text_div.attrib.get(XML_LANG, file_lang)
    if declared_lang != file_lang:
        raise ValueError(f"Filename and TEI xml:lang disagree in {path}: {declared_lang}")
    licence = header.find(f"{TEI}publicationStmt/{TEI}availability/{TEI}licence")
    license_value = licence.attrib.get("target") if licence is not None else None
    license_source = BASE + path if license_value else BASE + "README.md"
    if not license_value:
        license_value = "CC BY-SA 4.0" if repo_default_license else "unknown"
    parents = {child: parent for parent in body.iter() for child in parent}
    output = []
    for poem in (d for d in text_div.iter(f"{TEI}div") if d.attrib.get("subtype") == "poem"):
        citation = poem_citation(poem, parents)
        line_elements = list(poem.iter(f"{TEI}l"))
        if not line_elements:
            raise ValueError(f"Poem without line elements: {path} {citation}")
        lines = []
        empty_source_lines = []
        for i, line in enumerate(line_elements, 1):
            item = {"label": line.attrib.get("n", str(i)), "text": element_text(line)}
            ancestor = parents.get(line)
            while ancestor is not None and ancestor is not poem:
                if ancestor.tag == f"{TEI}sp":
                    speaker = element_text(ancestor.find(f"{TEI}speaker"))
                    if speaker:
                        item["speaker"] = speaker
                    break
                ancestor = parents.get(ancestor)
            if not item["text"]:
                gaps = [dict(g.attrib) for g in line.iter(f"{TEI}gap")]
                if gaps:
                    item["tei_gaps"] = gaps
                else:
                    empty_source_lines.append(item["label"])
            lines.append(item)
        if not any(l["text"] for l in lines):
            raise ValueError(f"Poem has no extractable text: {path} {citation}")
        mixed = sorted({e.tag.rsplit("}", 1)[-1] for e in poem.iter()
                        if e.tag.rsplit("}", 1)[-1] in MIXED_TAGS})
        kind = "translation" if file_lang == "eng" else "text"
        work_urn = ".".join(urn.split(".")[:2])
        record = {
            "id": f"reception:{urn}:{citation}", "source": "reception",
            "source_url": BASE + path,
            "raw_path": (RAW / path).relative_to(ROOT).as_posix(),
            "raw_sha256": hashlib.sha256(data).hexdigest(),
            "author": author, "work": work,
            "edition": f"{urn}: {edition_biblio}" if edition_biblio else urn,
            "citation": citation, "language": file_lang,
            "text": "\n".join(l["text"] for l in lines if l["text"]),
            "kind": kind,
            "quality": "needs_review" if empty_source_lines else ("mixed_content" if mixed else "source_text"),
            "license": license_value,
            "lines": lines,
            "metadata": {
                "source_work_urn": work_urn, "tei_edition_urn": urn,
                "tei_license_source": license_source,
                "editorial_markup_present": mixed,
                "empty_source_line_labels": empty_source_lines,
                "heading": element_text(poem.find(f"{TEI}head")) or None,
                "reception_scope": "comparative Latin literature; no direct Greek influence asserted",
            },
        }
        if file_lang == "eng":
            record["parent_id"] = f"reception:{work_urn}.perseus-lat2:{citation}"
        output.append(record)
    if not output:
        raise ValueError(f"No poem records extracted from {path}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached", action="store_true", help="Reparse saved raw TEI")
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent": "MelosCorpus/0.1 (scholarly research corpus)"})
    readme = download("README.md", args.cached, session)
    download("license.md", args.cached, session)
    repo_default_license = b"Unless otherwise indicated, all contents of this repository are licensed under a" in readme
    all_records = []
    source_files = []
    works = []
    for work_dir in WORKS:
        work_metadata, versions = work_files(work_dir, args.cached, session)
        works.append(work_metadata)
        for path, raw in versions:
            records = parse_version(path, raw, repo_default_license)
            all_records.extend(records)
            source_files.append({"url": BASE + path, "raw_path": (RAW / path).relative_to(ROOT).as_posix(),
                                 "sha256": hashlib.sha256(raw).hexdigest(), "records": len(records)})
    ids = {r["id"] for r in all_records}
    if len(ids) != len(all_records):
        raise ValueError("Duplicate passage IDs")
    for record in all_records:
        if record.get("parent_id") and record["parent_id"] not in ids:
            record.pop("parent_id", None)
            record["metadata"]["parent_missing_in_subset"] = True
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in all_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    counts = Counter((r["author"], r["work"], r["language"], r["kind"], r["quality"]) for r in all_records)
    report = {
        "source": "PerseusDL/canonical-latinLit", "commit": COMMIT,
        "repository_url": f"https://github.com/PerseusDL/canonical-latinLit/tree/{COMMIT}",
        "license_policy_url": BASE + "README.md",
        "note": "Latin comparative literature and English translations; no assertion of a particular Greek source or direct adaptation. TEI headers may contain inaccuracies per repository README.",
        "works": works, "files": source_files,
        "records": len(all_records),
        "counts": [{"author": key[0], "work": key[1], "language": key[2], "kind": key[3],
                    "quality": key[4], "count": count} for key, count in sorted(counts.items())],
        "missing_parent_links": sum(bool(r["metadata"].get("parent_missing_in_subset")) for r in all_records),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(all_records)} passages from {len(source_files)} TEI files; report {REPORT}")


if __name__ == "__main__":
    main()
