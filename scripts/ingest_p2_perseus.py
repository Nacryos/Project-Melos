"""Collect the pinned Pindar scholia and related testimonia from First1KGreek.

The eight TEI files are a distinct source from the already ingested Pindar
poems. They are scholia and ancient biographical material, never Pindar verse.
Every record is derived from a locally saved TEI file fetched by this script.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_perseus"
OUT = ROOT / "data/processed/p2_perseus.jsonl"
REPORT = ROOT / "data/reports/p2_perseus.json"
ORIGINAL_REPORT = ROOT / "data/reports/perseus.json"
ORIGINAL_RECORDS = ROOT / "data/processed/perseus.jsonl"
COMMIT = "8ee111eb44ecef4120c844e10749178d95d1f30c"
REPO = "https://github.com/OpenGreekAndLatin/First1KGreek"
BASE = f"https://raw.githubusercontent.com/OpenGreekAndLatin/First1KGreek/{COMMIT}/"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
SPACE = re.compile(r"[\t\r\f\v ]+")
EDITORIAL = {"add", "del", "gap", "supplied", "choice", "app", "sic", "corr"}

# File paths identify the eight independently scoped source artifacts, not data rows.
FILES = [
    f"data/tlg5034/tlg001{x}/tlg5034.tlg001{x}.perseus-grc1.xml"
    for x in "abcd"
] + [
    f"data/tlg4170/tlg001{x}/tlg4170.tlg001{x}.1st1K-grc1.xml"
    for x in "abcd"
]


def fetch(url: str) -> bytes:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "melos-p2-perseus/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise RuntimeError(f"DOWNLOAD FAILED {url}: {exc}") from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(value: str | None) -> str:
    return SPACE.sub(" ", value or "").strip()


def content(node: ET.Element, *, skip_notes: bool = True) -> str:
    """Extract only source characters; note/witness metadata is kept separately."""
    pieces: list[str] = []

    def visit(element: ET.Element) -> None:
        if element.tag == NS + "note" and skip_notes:
            return
        if element.tag in {NS + "lb", NS + "l"}:
            pieces.append("\n")
        if element.text:
            pieces.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                pieces.append(child.tail)

    visit(node)
    return "\n".join(clean(line) for line in "".join(pieces).splitlines() if clean(line))


def value(node: ET.Element, path: str) -> str:
    found = node.find(path)
    return clean("".join(found.itertext())) if found is not None else ""


def source_info(root: ET.Element, path: str) -> dict:
    title = value(root, f".//{NS}titleStmt/{NS}title")
    author = value(root, f".//{NS}titleStmt/{NS}author")
    editor = value(root, f".//{NS}titleStmt/{NS}editor")
    bibliographic_title = value(root, f".//{NS}sourceDesc//{NS}biblStruct/{NS}monogr/{NS}title")
    bibliographic_editor = value(root, f".//{NS}sourceDesc//{NS}biblStruct/{NS}monogr/{NS}editor")
    bibliographic_year = value(root, f".//{NS}sourceDesc//{NS}biblStruct/{NS}monogr/{NS}imprint/{NS}date")
    lic = root.find(f".//{NS}publicationStmt/{NS}availability/{NS}licence")
    if lic is None or not clean("".join(lic.itertext())) or not lic.attrib.get("target"):
        raise ValueError("TEI has no explicit licence statement and URL")
    license_text = clean("".join(lic.itertext()))
    if lic.attrib["target"] != "https://creativecommons.org/licenses/by-sa/4.0/":
        raise ValueError(f"Unexpected TEI licence URL: {lic.attrib['target']}")
    if not title or not author or not editor:
        raise ValueError("TEI lacks title, author, or editor")
    return {
        "title": title, "author": author, "editor": editor,
        "bibliographic_title": bibliographic_title,
        "bibliographic_editor": bibliographic_editor,
        "bibliographic_year": bibliographic_year,
        "license": license_text,
        "license_url": lic.attrib["target"],
        "bibliographic_title_mismatch": bool(path.startswith("data/tlg4170/") and bibliographic_title != title),
    }


def element_annotations(node: ET.Element, citation: str) -> dict:
    notes = [ET.tostring(n, encoding="unicode") for n in node.iter(NS + "note")]
    marks = [{"line": citation, "tag": n.tag.removeprefix(NS),
              "tei": ET.tostring(n, encoding="unicode")}
             for n in node.iter() if n.tag.removeprefix(NS) in EDITORIAL]
    result: dict = {}
    if notes:
        result["tei_notes"] = notes
    if marks:
        result["editorial_markup"] = marks
    return result


def source_nodes(root: ET.Element, family: str):
    body = root.find(f".//{NS}text/{NS}body")
    if body is None:
        raise ValueError("TEI has no text body")
    if family == "scholia":
        # Olympian TEI has eight part divs at 9.156 outside their expected
        # line parent. Their source xml:base supplies the exact CTS line.
        for part in body.iter(NS + "div"):
            if part.attrib.get("subtype") != "part":
                continue
            part_n = part.attrib.get("n")
            line_ref = part.attrib.get(XML + "base", "").rsplit(":", 1)[-1]
            if not part_n or len(line_ref.split(".")) != 2:
                raise ValueError("Scholia part lacks valid n or CTS xml:base")
            poem_n, line_n = line_ref.split(".")
            yield f"{line_ref}.{part_n}", part, {"poem": poem_n, "line": line_n, "part": part_n}
        for poem in body.iter(NS + "div"):
            if poem.attrib.get("subtype") != "poem":
                continue
            poem_n = poem.attrib.get("n")
            if not poem_n:
                raise ValueError("Scholia poem lacks n")
            for line in poem.iter(NS + "div"):
                if line.attrib.get("subtype") != "line":
                    continue
                line_n = line.attrib.get("n")
                if not line_n:
                    raise ValueError("Scholia line lacks n")
                # Other volumes encode lettered scholia as separate direct p nodes.
                for index, paragraph in enumerate((x for x in line if x.tag == NS + "p"), 1):
                    yield f"{poem_n}.{line_n}", paragraph, {"poem": poem_n, "line": line_n, "paragraph_index": index}
    else:
        chapters = [x for x in body.iter(NS + "div") if x.attrib.get("subtype") == "chapter"]
        if not chapters:
            raise ValueError("Vita TEI has no chapters")
        for chapter in chapters:
            chapter_n = chapter.attrib.get("n")
            if not chapter_n:
                raise ValueError("Vita chapter lacks n")
            yield chapter_n, chapter, {"chapter": chapter_n}


def existing() -> tuple[set[str], set[str]]:
    old_files = json.loads(ORIGINAL_REPORT.read_text(encoding="utf-8"))["sources"]
    raw_hashes = {source["sha256"] for source in old_files}
    text_hashes = set()
    with ORIGINAL_RECORDS.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            text_hashes.add(digest(record["text"].encode("utf-8")))
    return raw_hashes, text_hashes


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    old_raw_hashes, old_text_hashes = existing()
    sources: list[dict] = []
    records: list[dict] = []
    counts: collections.Counter[str] = collections.Counter()
    issues: list[dict] = []
    exact_text_overlap = 0
    empty_nodes: list[dict] = []

    for source_path in FILES:
        url = BASE + source_path
        raw_file = RAW / source_path.removeprefix("data/")
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        if not raw_file.exists():
            raw_file.write_bytes(fetch(url))
        payload = raw_file.read_bytes()
        raw_sha = digest(payload)
        if raw_sha in old_raw_hashes:
            raise ValueError(f"Already ingested identical raw TEI: {source_path}")
        root = ET.fromstring(payload)
        info = source_info(root, source_path)
        family = "scholia" if "/tlg5034/" in source_path else "vitae"
        if info["bibliographic_title_mismatch"]:
            issues.append({"path": source_path, "issue": "sourceDesc bibliographic title differs from actual titleStmt/work; titleStmt retained"})
        urn = source_path.rsplit("/", 1)[-1].removesuffix(".xml")
        seen: collections.Counter[str] = collections.Counter()
        source_count = 0
        for cite, node, source_locator in source_nodes(root, family):
            passage = content(node)
            if not passage:
                empty_nodes.append({"path": source_path, "citation": cite})
                continue
            seen[cite] += 1
            annotations = element_annotations(node, cite)
            record = {
                "id": f"p2_perseus:{urn}:{cite}:{seen[cite]}",
                "source": "p2_perseus", "source_url": url,
                "raw_path": raw_file.relative_to(ROOT).as_posix(),
                "raw_sha256": raw_sha,
                "author": info["author"], "work": info["title"],
                "edition": f"{info['editor']}; {info['bibliographic_year']}; {urn}",
                "citation": cite, "language": "grc", "text": passage,
                "kind": "commentary" if family == "scholia" else "reference",
                "quality": "needs_review" if annotations.get("editorial_markup") else "source_text",
                "license": info["license"],
                "metadata": {
                    "cts_urn": f"urn:cts:greekLit:{urn}", "commit": COMMIT,
                    "source_family": "Perseus/Drachmann Scholia Vetera in Pindari Carmina",
                    "source_locator": source_locator,
                    "source_editor": info["editor"],
                    "source_bibliography": {
                        "title": info["bibliographic_title"],
                        "editor": info["bibliographic_editor"],
                        "year": info["bibliographic_year"],
                        "title_mismatch": info["bibliographic_title_mismatch"],
                    },
                    "license_url": info["license_url"], **annotations,
                },
            }
            records.append(record)
            source_count += 1
            counts[record["kind"]] += 1
            if digest(passage.encode("utf-8")) in old_text_hashes:
                exact_text_overlap += 1
        if source_count == 0:
            raise ValueError(f"No passages from {source_path}")
        sources.append({
            "path": raw_file.relative_to(ROOT).as_posix(), "url": url,
            "sha256": raw_sha, "work": info["title"], "author": info["author"],
            "edition": info["editor"], "source_year": info["bibliographic_year"],
            "license": info["license"], "license_url": info["license_url"],
            "records": source_count,
        })

    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = {
        "repository": REPO, "commit": COMMIT,
        "source_file_count": len(sources), "record_count": len(records),
        "kind_counts": dict(counts),
        "distinct_raw_files_against_original_197": len(sources),
        "exact_text_overlap_with_original_records": exact_text_overlap,
        "source_family": "Perseus/Drachmann Scholia Vetera in Pindari Carmina",
        "sources": sources, "issues": issues, "empty_source_nodes": empty_nodes,
        "output_sha256": digest(OUT.read_bytes()),
        "scope_note": "Scholia are commentary; Vitae are testimonia/reference; neither is Pindar-authored poetry.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("source_file_count", "record_count", "kind_counts", "exact_text_overlap_with_original_records", "output_sha256")}, indent=2))


if __name__ == "__main__":
    main()
