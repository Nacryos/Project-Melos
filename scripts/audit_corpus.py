#!/usr/bin/env python3
"""Audit collector JSONL against the saved source artifacts.

This is a conservative gate. A text trace proves that words occur in a saved
artifact; it cannot by itself prove authorship, edition, or a correct parser.
Those claims still need collector-code and source review.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import unicodedata
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


REQUIRED = (
    "id", "source", "source_url", "raw_path", "raw_sha256", "author",
    "work", "edition", "citation", "language", "text", "kind",
    "quality", "license",
)
KINDS = {"text", "translation", "commentary", "apparatus", "reference"}
QUALITIES = {"source_text", "machine_corrected_ocr", "machine_ocr", "mixed_content", "needs_review"}
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
PLACEHOLDER = re.compile(
    r"\b(?:translation goes here|insert (?:translation|text) here|"
    r"lorem ipsum|\[\[?placeholder\]?\])\b", re.I
)


class VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFC", unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def all_json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in all_json_strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in all_json_strings(item)]
    return []


def extract_raw_text(path: Path) -> tuple[str | None, str]:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix == ".pdf":
        return None, "PDF requires a saved, source-linked OCR/text artifact"
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "raw artifact is not UTF-8 text"
    if suffix in {".xml", ".tei"}:
        try:
            root = ET.fromstring(content)
            # TEI may embed notes and alternate readings in a line. Render its
            # main reading independently of the collector, then retain a raw
            # itertext fallback for sources that use other XML vocabularies.
            def local(node: ET.Element) -> str:
                return node.tag.rsplit("}", 1)[-1]

            def main_reading(node: ET.Element) -> str:
                tag = local(node)
                if tag == "gap":
                    return "<gap/>"
                if tag in {"note", "bibl", "rdg"}:
                    return ""
                if tag in {"app", "choice"}:
                    preferences = ("lem", "rdg") if tag == "app" else ("corr", "reg", "orig", "sic")
                    for name in preferences:
                        chosen = next((child for child in node if local(child) == name), None)
                        if chosen is not None:
                            return main_reading(chosen)
                    return ""
                pieces = [node.text or ""]
                for child in node:
                    pieces.append(main_reading(child))
                    pieces.append(child.tail or "")
                return "".join(pieces)

            blocks = [main_reading(node) for node in root.iter() if local(node) in {"l", "p", "lg"}]
            blocks += ["<gap/>" for node in root.iter() if local(node) == "gap"]
            return "\n".join(blocks + ["".join(root.itertext())]), "XML main-reading text blocks"
        except ET.ParseError as exc:
            return None, f"XML parse error: {exc}"
    if suffix in {".html", ".htm"}:
        parser = VisibleHTML()
        parser.feed(content)
        return " ".join(parser.parts), "HTML visible text"
    if suffix in {".json", ".jsonl"}:
        try:
            if suffix == ".jsonl":
                values = [json.loads(line) for line in content.splitlines() if line.strip()]
            else:
                values = json.loads(content)
            return " ".join(all_json_strings(values)), "JSON string values"
        except json.JSONDecodeError as exc:
            return None, f"JSON parse error: {exc}"
    return content, "decoded raw text"


def source_contains(record: dict, haystack: str, xml_source: bool = False) -> bool:
    def comparable(value: str) -> str:
        if xml_source:
            value = re.sub(r"<gap\b[^>]*?/>", "<gap/>", value)
            value = re.sub(r"</?(?:choice|add|del|supplied)>", "", value)
        return normalized(value)

    text = comparable(record["text"])
    if text in haystack:
        return True
    lines = record.get("lines")
    if isinstance(lines, list) and lines:
        checks = [comparable(item.get("text", "")) for item in lines if isinstance(item, dict)]
        substantive = [line for line in checks if line]
        return bool(substantive) and all(line in haystack for line in substantive)
    # A TEI passage may join separately marked-up lines. Each substantive line
    # must still appear verbatim in the saved source.
    parts = [comparable(part) for part in record["text"].splitlines()]
    return len(parts) > 1 and all(part and part in haystack for part in parts)


def ordered_html_commentary(record: dict, haystack: str) -> bool:
    """Allow HTML commentary flattened across omitted tables or inline nodes."""
    tokens = re.findall(r"\w+|[^\w\s]", normalized(record["text"]), re.UNICODE)
    if len(tokens) < 8:
        return False
    source_tokens = iter(re.findall(r"\w+|[^\w\s]", haystack, re.UNICODE))
    return all(any(source == token for source in source_tokens) for token in tokens)


def issue(stage: str, severity: str, code: str, file: Path, line: int, detail: str) -> dict:
    return {
        "stage": stage, "severity": severity, "code": code,
        "file": str(file), "line": line, "detail": detail,
    }


def lyra_page_index(raw_path: Path) -> dict:
    """Independently align IA DjVu OCR objects, scandata leaves, and IIIF canvases."""
    folder = raw_path.parent
    ocr = ET.parse(raw_path).getroot()
    objects = ocr.findall(".//BODY/OBJECT")
    pages = []
    for obj in objects:
        paragraphs = []
        for para in obj.findall(".//HIDDENTEXT//PARAGRAPH"):
            lines = []
            for line in para.findall(".//LINE"):
                words = [(w.text or "").strip() for w in line.findall("WORD")]
                if any(words):
                    lines.append(" ".join(w for w in words if w))
            if lines:
                paragraphs.append("\n".join(lines))
        pages.append("\n\n".join(paragraphs))
    scan_path = folder / "scandata.xml"
    if not scan_path.is_file():
        candidates = list(folder.glob("*_scandata.xml"))
        if len(candidates) != 1:
            raise ValueError("missing or ambiguous scandata XML")
        scan_path = candidates[0]
    scan_bytes = scan_path.read_bytes()
    scan_root = ET.fromstring(scan_bytes)
    for element in scan_root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    leaves = []
    for page in scan_root.findall("./pageData/page"):
        if page.findtext("addToAccessFormats") == "true":
            leaves.append({"leaf": int(page.attrib["leafNum"]), "printed": page.findtext("pageNumber")})
    manifest_bytes = (folder / "iiif-manifest.json").read_bytes()
    canvases = json.loads(manifest_bytes)["items"]
    if not (len(pages) == len(leaves) == len(canvases)):
        raise ValueError(f"OCR/access/IIIF count mismatch: {len(pages)}/{len(leaves)}/{len(canvases)}")
    return {
        "pages": pages, "leaves": leaves, "canvases": canvases,
        "scan_sha256": hashlib.sha256(scan_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def audit(files: list[Path], root: Path, sample_size: int, seed: int, manual: dict | None = None) -> dict:
    findings: list[dict] = []
    samples_pool: list[tuple[Path, int, dict, str]] = []
    record_count = 0
    rng = random.Random(seed)
    seen_ids: dict[str, tuple[Path, int]] = {}
    raw_cache: dict[Path, tuple[str, str | None, str]] = {}
    raw_rows: dict[Path, list[bytes]] = {}
    editorial_cache: dict[Path, set[str]] = {}
    xml_fragment_cache: dict[Path, set[str]] = {}
    lyra_cache: dict[Path, dict] = {}
    overlays: dict[str, dict] = {}
    counts: dict[str, int] = {}
    file_hashes: dict[str, str] = {}
    root = root.resolve()

    for file in files:
        count = 0
        annotation_stream = None
        annotation_hasher = hashlib.sha256()
        annotation_path = root / "data/annotations/ogc-quality.jsonl"
        if file.name == "ogc.jsonl":
            if annotation_path.is_file():
                annotation_stream = annotation_path.open("rb")
            else:
                findings.append(issue("integration", "FAIL", "missing_ogc_overlay", file, 0, str(annotation_path)))
        try:
            file_bytes = file.read_bytes()
            file_hashes[str(file)] = hashlib.sha256(file_bytes).hexdigest()
            # JSON strings may contain U+0085 (an editorial lacuna mark),
            # which str.splitlines() would incorrectly treat as a row break.
            lines = file_bytes.decode("utf-8-sig").split("\n")
        except (OSError, UnicodeError) as exc:
            findings.append(issue("output", "FAIL", "file_unreadable", file, 0, str(exc)))
            continue
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            count += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                findings.append(issue("output", "FAIL", "invalid_json", file, number, str(exc)))
                continue
            if not isinstance(record, dict):
                findings.append(issue("output", "FAIL", "not_object", file, number, "JSONL row is not an object"))
                continue
            ogc_label = None
            if file.name == "ogc.jsonl" and annotation_stream is not None:
                try:
                    annotation_bytes = next(annotation_stream)
                    annotation_hasher.update(annotation_bytes)
                    ogc_label = json.loads(annotation_bytes)
                    if (ogc_label.get("parent_id") != record.get("id")
                            or ogc_label.get("parent_text_sha256") != hashlib.sha256(record.get("text", "").encode("utf-8")).hexdigest()
                            or ogc_label.get("raw_path") != record.get("raw_path")
                            or ogc_label.get("raw_sha256") != record.get("raw_sha256")
                            or not isinstance(ogc_label.get("primary_search_eligible"), bool)):
                        raise ValueError("annotation ID/text/raw binding mismatch")
                except (StopIteration, ValueError, TypeError, json.JSONDecodeError) as exc:
                    findings.append(issue("integration", "FAIL", "ogc_overlay_mismatch", file, number, str(exc)))
            missing = [key for key in REQUIRED if key not in record]
            if missing:
                findings.append(issue("output", "FAIL", "missing_fields", file, number, ", ".join(missing)))
                continue
            invalid = [key for key in REQUIRED if not isinstance(record[key], str) or not record[key].strip()]
            if invalid:
                findings.append(issue("output", "FAIL", "empty_or_nonstring", file, number, ", ".join(invalid)))
                continue
            if record["kind"] not in KINDS or record["quality"] not in QUALITIES:
                findings.append(issue("output", "FAIL", "invalid_category", file, number, f"kind={record['kind']}; quality={record['quality']}"))
            if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)?", record["language"]):
                findings.append(issue("output", "WARN", "language_code", file, number, record["language"]))
            if not SHA256.fullmatch(record["raw_sha256"]):
                findings.append(issue("download", "FAIL", "invalid_sha256", file, number, record["raw_sha256"]))
            parsed = urlparse(record["source_url"])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                findings.append(issue("discovery", "FAIL", "invalid_source_url", file, number, record["source_url"]))
            if record["id"] in seen_ids:
                first_file, first_line = seen_ids[record["id"]]
                findings.append(issue("output", "FAIL", "duplicate_id", file, number, f"first: {first_file}:{first_line}"))
            else:
                seen_ids[record["id"]] = (file, number)
            if "parent_id" in record and (not isinstance(record["parent_id"], str) or not record["parent_id"].strip()):
                findings.append(issue("output", "FAIL", "invalid_parent_id", file, number, "parent_id must be a nonempty string"))
            if "lines" in record and (not isinstance(record["lines"], list) or any(
                not isinstance(item, dict) or not isinstance(item.get("label"), str)
                or not isinstance(item.get("text"), str) for item in record["lines"]
            )):
                findings.append(issue("output", "FAIL", "invalid_lines", file, number, "lines must contain {label,text} objects"))
            if "metadata" in record and not isinstance(record["metadata"], dict):
                findings.append(issue("output", "FAIL", "invalid_metadata", file, number, "metadata must be an object"))
            if ("date_start" in record or "date_end" in record) and not record.get("date_source"):
                findings.append(issue("transform", "FAIL", "unsourced_date", file, number, "date_source required for chronology"))
            for key in ("date_start", "date_end"):
                if key in record and (isinstance(record[key], bool) or not isinstance(record[key], int)):
                    findings.append(issue("output", "FAIL", "invalid_date", file, number, f"{key} must be an integer year"))
            if PLACEHOLDER.search(record["text"]):
                findings.append(issue("parse", "FAIL", "placeholder", file, number, record["text"][:120]))
            linguistic_text = re.sub(r"</?(?:choice|add|del|supplied)>|<gap\b[^>]*?/>", "", record["text"])
            greek_count = len(GREEK.findall(linguistic_text))
            latin_count = sum(len(word) for word in LATIN_WORD.findall(linguistic_text))
            if record["language"] == "grc" and record["kind"] == "text":
                if greek_count == 0:
                    findings.append(issue("transform", "FAIL", "no_greek", file, number, "Greek text record contains no Greek characters"))
                if latin_count > greek_count / 2 and latin_count >= 12:
                    if record["source"] != "ogc" or ogc_label is None or ogc_label.get("primary_search_eligible"):
                        severity = "FAIL" if record["quality"] == "source_text" else "WARN"
                        findings.append(issue("parse", severity, "mixed_language", file, number, f"Greek chars={greek_count}, Latin word chars={latin_count}"))
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            if record["quality"] == "source_text" and (
                re.search(r"</?(?:choice|add|del|supplied)>|<gap\b", record["text"])
                or metadata.get("editorial_markup")
            ):
                findings.append(issue("transform", "FAIL", "unquarantined_editorial", file, number, "TEI editorial markup requires needs_review quality and original evidence"))
            try:
                raw_path = (root / record["raw_path"]).resolve()
                if not raw_path.is_relative_to(root):
                    raise ValueError("raw_path escapes repository")
                if not raw_path.is_file():
                    raise FileNotFoundError(str(raw_path))
            except (ValueError, OSError) as exc:
                findings.append(issue("download", "FAIL", "raw_missing", file, number, str(exc)))
                continue
            if raw_path not in raw_cache:
                raw_bytes = raw_path.read_bytes()
                digest = hashlib.sha256(raw_bytes).hexdigest()
                if record["source"] in {"ogc", "ogc_derived"} and raw_path.suffix.lower() == ".jsonl":
                    raw_rows[raw_path] = raw_bytes.splitlines()
                    raw_text, method = None, "exact JSONL source row"
                else:
                    raw_text, method = extract_raw_text(raw_path)
                raw_cache[raw_path] = (digest, normalized(raw_text) if raw_text is not None else None, method)
            digest, raw_text, method = raw_cache[raw_path]
            if digest.lower() != record["raw_sha256"].lower():
                findings.append(issue("download", "FAIL", "hash_mismatch", file, number, f"expected {record['raw_sha256']}; actual {digest}"))
            if record["source"] in {"ogc", "ogc_derived"} and raw_path in raw_rows:
                try:
                    source_row = json.loads(raw_rows[raw_path][metadata["source_row_number"] - 1])
                    checks = {
                        "urn": (metadata["ogc_urn"], source_row["urn"]),
                        "edition": (record["edition"], source_row["edition"]),
                        "citation": (record["citation"], source_row["locus"]),
                        "upstream_source": (metadata["ogc_source"], source_row["source"]),
                        "original_license": (metadata["ogc_record_license"], source_row["license"]),
                    }
                    mismatched = [name for name, (actual, original) in checks.items() if actual != original]
                    if mismatched:
                        raise ValueError(f"source row mismatch: {', '.join(mismatched)}")
                    if record["source"] == "ogc_derived":
                        derivation = metadata["derivation"]
                        start, end = derivation["span_start"], derivation["span_end"]
                        if (record["text"] != source_row["text"][start:end]
                                or derivation["parent_text_sha256"] != hashlib.sha256(source_row["text"].encode("utf-8")).hexdigest()
                                or record["kind"] != "reference" or record["quality"] != "machine_ocr"
                                or record["author"] != "unknown"
                                or derivation.get("author_attribution_verified") is not False
                                or derivation.get("reconstruction") is not False
                                or not record["id"].startswith(record["parent_id"] + "::prefix:")):
                            raise ValueError("derived span, parent hash, or reference quarantine mismatch")
                        boundary = derivation["boundary_evidence"]
                        if boundary["start"] < end or source_row["text"][boundary["start"]:boundary["end"]] != boundary["text"]:
                            raise ValueError("derived boundary evidence mismatch")
                    elif record["text"] != source_row["text"]:
                        raise ValueError("source row text mismatch")
                    trace = "pass_exact_row"
                except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    findings.append(issue("parse", "FAIL", "ogc_row_mismatch", file, number, str(exc)))
                    trace = "fail"
            elif raw_text is None:
                severity = "FAIL" if record["quality"] == "source_text" else "WARN"
                findings.append(issue("parse", severity, "raw_text_unavailable", file, number, method))
                trace = "unverifiable"
            elif raw_path.suffix.lower() in {".xml", ".tei"} and record["kind"] == "apparatus" and record["text"].lstrip().startswith("<"):
                if raw_path not in xml_fragment_cache:
                    try:
                        tree = ET.parse(raw_path)
                        fragments = set()
                        for node in tree.iter():
                            clone = copy.deepcopy(node)
                            clone.tail = None
                            fragments.add(ET.tostring(clone, encoding="unicode"))
                        xml_fragment_cache[raw_path] = fragments
                    except ET.ParseError:
                        xml_fragment_cache[raw_path] = set()
                if record["text"] not in xml_fragment_cache[raw_path]:
                    findings.append(issue("parse", "FAIL", "xml_fragment_not_in_raw", file, number, f"serialized apparatus absent: {record['text'][:120]!r}"))
                    trace = "fail"
                else:
                    trace = "pass"
            elif source_contains(record, raw_text, raw_path.suffix.lower() in {".xml", ".tei"}):
                trace = "pass"
            elif (record["kind"] == "commentary" and raw_path.suffix.lower() in {".html", ".htm"}
                  and ordered_html_commentary(record, raw_text)):
                trace = "pass_ordered_html"
            else:
                findings.append(issue("parse", "FAIL", "text_not_in_raw", file, number, f"{method}; text={record['text'][:120]!r}"))
                trace = "fail"
            if record["source"] == "lyra":
                try:
                    if raw_path not in lyra_cache:
                        lyra_cache[raw_path] = lyra_page_index(raw_path)
                    index = lyra_cache[raw_path]
                    metadata = record["metadata"]
                    position = metadata["archive_access_page"]
                    leaf = index["leaves"][position]
                    canvas = index["canvases"][position]
                    image_url = canvas["items"][0]["items"][0]["body"]["id"]
                    if normalized(index["pages"][position]) != normalized(record["text"]):
                        raise ValueError("OCR text differs from cited page OBJECT")
                    if leaf["leaf"] != metadata["scan_leaf"] or leaf["printed"] != metadata["printed_page"]:
                        raise ValueError("scandata leaf/printed page mismatch")
                    if canvas["id"] != metadata["iiif_canvas_url"] or image_url != metadata["page_image_url"]:
                        raise ValueError("IIIF canvas/image URL mismatch")
                    if index["scan_sha256"] != metadata["scan_metadata_xml_sha256"]:
                        raise ValueError("scandata XML hash mismatch")
                    if index["manifest_sha256"] != metadata["iiif_manifest_sha256"]:
                        raise ValueError("IIIF manifest hash mismatch")
                except (KeyError, IndexError, ValueError, TypeError, OSError, ET.ParseError) as exc:
                    findings.append(issue("parse", "FAIL", "lyra_page_mapping", file, number, str(exc)))
                    trace = "fail"
            evidence = metadata.get("editorial_markup")
            if evidence is not None:
                if not isinstance(evidence, list) or any(not isinstance(item, dict) or not isinstance(item.get("tei"), str) for item in evidence):
                    findings.append(issue("transform", "FAIL", "invalid_editorial_evidence", file, number, "editorial_markup must list TEI fragments"))
                elif raw_path.suffix.lower() in {".xml", ".tei"}:
                    if raw_path not in editorial_cache:
                        try:
                            tree = ET.parse(raw_path)
                            editorial_cache[raw_path] = {ET.tostring(node, encoding="unicode") for node in tree.iter()}
                        except ET.ParseError:
                            editorial_cache[raw_path] = set()
                    missing_evidence = [item for item in evidence if item["tei"] not in editorial_cache[raw_path]]
                    if missing_evidence:
                        findings.append(issue("transform", "FAIL", "editorial_evidence_not_in_raw", file, number, f"{len(missing_evidence)} TEI fragments absent"))
            record_count += 1
            sample_record = (file, number, record, trace)
            if len(samples_pool) < sample_size:
                samples_pool.append(sample_record)
            else:
                position = rng.randrange(record_count)
                if position < sample_size:
                    samples_pool[position] = sample_record
        counts[str(file)] = count
        if annotation_stream is not None:
            extra = annotation_stream.readline()
            annotation_stream.close()
            if extra:
                findings.append(issue("integration", "FAIL", "ogc_overlay_extra_rows", file, 0, "annotation rows outnumber OGC records"))
            overlays[file.name] = {
                "path": str(annotation_path.relative_to(root)).replace("\\", "/"),
                "sha256": annotation_hasher.hexdigest(), "records": count,
            }
            quality_report = root / "data/reports/ogc-quality.json"
            if quality_report.is_file():
                report = json.loads(quality_report.read_text(encoding="utf-8"))
                if report.get("input_sha256") != file_hashes.get(str(file)):
                    findings.append(issue("integration", "FAIL", "ogc_overlay_input_hash", file, 0, "label report was built for a different OGC JSONL hash"))
        if str(file) in file_hashes:
            try:
                current_hash = hashlib.sha256(file.read_bytes()).hexdigest()
                if current_hash != file_hashes[str(file)]:
                    findings.append(issue("output", "FAIL", "changed_during_audit", file, 0, "collector rewrote JSONL during validation"))
            except OSError as exc:
                findings.append(issue("output", "FAIL", "changed_during_audit", file, 0, str(exc)))

    selected = samples_pool
    samples = [{
        "id": rec["id"], "file": str(file), "line": number,
        "source_url": rec["source_url"], "raw_path": rec["raw_path"],
        "raw_sha256": rec["raw_sha256"], "text_trace": trace,
        "author": rec["author"], "work": rec["work"],
        "kind": rec["kind"], "quality": rec["quality"],
    } for file, number, rec, trace in selected]
    severity_counts = {level: sum(f["severity"] == level for f in findings) for level in ("FAIL", "WARN")}
    if not files or not counts:
        findings.append(issue("output", "FAIL", "no_input", root / "data/processed", 0, "no collector JSONL files found"))
        severity_counts["FAIL"] += 1
    file_verdicts: dict[str, dict] = {}
    for file in files:
        path = str(file)
        related = [finding for finding in findings if finding["file"] == path]
        failure_count = sum(finding["severity"] == "FAIL" for finding in related)
        warning_count = sum(finding["severity"] == "WARN" for finding in related)
        verdict = "FAIL" if failure_count else ("WARN" if warning_count else "PASS")
        if path not in counts or not counts[path]:
            verdict = "FAIL"
        file_verdicts[file.name] = {
            "verdict": verdict, "sha256": file_hashes.get(path),
            "records": counts.get(path, 0), "failures": failure_count,
            "warnings": warning_count,
            "mechanical_verdict": verdict,
        }
        if file.name in overlays:
            file_verdicts[file.name]["required_overlay"] = overlays[file.name]
        review = (manual or {}).get("files", {}).get(file.name)
        if isinstance(review, dict) and review.get("verdict") in {"PASS", "FAIL", "WARN"}:
            file_verdicts[file.name]["manual_verdict"] = review["verdict"]
            file_verdicts[file.name]["manual_reason"] = review.get("reason", "manual review")
            if isinstance(review.get("scope"), str):
                file_verdicts[file.name]["scope"] = review["scope"]
            if review["verdict"] == "FAIL" or (review["verdict"] == "WARN" and verdict == "PASS"):
                file_verdicts[file.name]["verdict"] = review["verdict"]
        else:
            file_verdicts[file.name]["manual_verdict"] = "PENDING"
            if verdict == "PASS":
                file_verdicts[file.name]["verdict"] = "PENDING"
    return {
        "verdict": "FAIL" if any(f["verdict"] == "FAIL" for f in file_verdicts.values()) or severity_counts["FAIL"] else ("WARN" if any(f["verdict"] == "WARN" for f in file_verdicts.values()) or severity_counts["WARN"] else ("PENDING" if any(f["verdict"] == "PENDING" for f in file_verdicts.values()) else "PASS")),
        "counts": counts, "records_checked": record_count, "raw_artifacts_checked": len(raw_cache),
        "severity_counts": severity_counts, "findings": findings,
        "files": file_verdicts,
        "sample_seed": seed, "sample_requested": sample_size, "samples": samples,
        "limitations": [
            "Text occurrence and hash match do not establish author, edition, or citation accuracy.",
            "PDF and other binary sources require an auditable text/OCR artifact for text tracing.",
            "Collector code, live source identity, licensing, and metadata claims require manual review.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="collector JSONL paths (default: data/processed/*.jsonl)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--json", type=Path, help="write full JSON report to this path")
    parser.add_argument("--acceptance", type=Path, help="write atomic per-file acceptance manifest")
    parser.add_argument("--manual", type=Path, help="manual verdict ledger (default: data/reports/audit-manual.json)")
    args = parser.parse_args()
    files = [Path(p).resolve() for p in args.paths] if args.paths else sorted((args.root / "data/processed").glob("*.jsonl"))
    manual_path = args.manual or args.root / "data/reports/audit-manual.json"
    manual = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path.exists() else {}
    result = audit(files, args.root, max(0, args.sample), args.seed, manual)
    acceptance = {"files": result["files"]}
    if args.acceptance and args.acceptance.exists():
        try:
            previous = json.loads(args.acceptance.read_text(encoding="utf-8"))
            if isinstance(previous.get("files"), dict):
                acceptance["files"] = {**previous["files"], **result["files"]}
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    for destination, payload in ((args.json, result), (args.acceptance, acceptance)):
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                temporary = Path(handle.name)
            os.replace(temporary, destination)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"{result['verdict']}: {result['records_checked']} records; {result['raw_artifacts_checked']} raw artifacts; {result['severity_counts']['FAIL']} FAIL, {result['severity_counts']['WARN']} WARN")
    for finding in result["findings"][:100]:
        print(f"{finding['severity']} {finding['stage']} {finding['code']} {finding['file']}:{finding['line']}: {finding['detail']}")
    if len(result["findings"]) > 100:
        print(f"... {len(result['findings']) - 100} further findings in JSON report")
    return 1 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
