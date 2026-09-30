"""Reproducibly collect selected Greek poetry and its English translations from Perseus.

The source is PerseusDL/canonical-greekLit, pinned to a Git commit. Run with
``python scripts/ingest_perseus.py --inventory`` to inspect CTS metadata, then
without the flag to write the corpus. No ancient text or translations are
embedded in this program.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "perseus"
OUT = ROOT / "data" / "processed" / "perseus.jsonl"
REPORT = ROOT / "data" / "reports" / "perseus.json"
API = "https://api.github.com/repos/PerseusDL/canonical-greekLit/commits/master"
REPO = "https://github.com/PerseusDL/canonical-greekLit"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
CTS = "{http://chs.harvard.edu/xmlns/cts}"
SPACE = re.compile(r"\s+")
EDITORIAL_TAGS = {"gap", "add", "del", "supplied", "choice", "app"}

# Selection terms are the user's requested author/collection names. Actual
# author and work labels are always taken from downloaded CTS/TEI metadata.
REQUESTED = (
    "homer", "hesiod", "pindar", "bacchylides", "theocritus",
    "callimachus", "apollonius", "aeschylus", "sophocles",
    "euripides", "aristophanes", "antholog", "sappho",
)


def fetch(url: str) -> bytes:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "melos-perseus-ingest/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise RuntimeError(f"DOWNLOAD FAILED {url}: {exc}") from exc
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(value: str | None) -> str:
    return SPACE.sub(" ", value or "").strip()


def text_of(node: ET.Element | None) -> str:
    return norm("".join(node.itertext())) if node is not None else ""


def direct_text(node: ET.Element) -> str:
    """Textual reading with visible TEI editorial boundaries.

    Variant apparatus is represented by its lemma (or first reading); the full
    source element is retained separately in ``editorial_markup`` metadata.
    """
    pieces: list[str] = []

    def first_child(element: ET.Element, names: tuple[str, ...]) -> ET.Element | None:
        for name in names:
            found = element.find(TEI + name)
            if found is not None:
                return found
        return None

    def visit(element: ET.Element) -> None:
        if element.tag in {TEI + "note", TEI + "bibl"}:
            return
        if element.tag == TEI + "app":
            choice = first_child(element, ("lem", "rdg"))
            if choice is not None:
                pieces.append("<app>")
                visit(choice)
                pieces.append("</app>")
            return
        if element.tag == TEI + "choice":
            choice = first_child(element, ("corr", "reg", "orig", "sic"))
            if choice is not None:
                pieces.append("<choice>")
                visit(choice)
                pieces.append("</choice>")
            return
        editorial = element.tag.removeprefix(TEI)
        if editorial == "gap":
            attrs = " ".join(f'{key.removeprefix(TEI)}={value}' for key, value in element.attrib.items())
            pieces.append(f"<gap {attrs}/>" if attrs else "<gap/>")
            return
        if editorial in {"add", "del", "supplied"}:
            pieces.append(f"<{editorial}>")
        if element.text:
            pieces.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                pieces.append(child.tail)
        if editorial in {"add", "del", "supplied"}:
            pieces.append(f"</{editorial}>")

    visit(node)
    return norm("".join(pieces))


def editorial_evidence(node: ET.Element, label: str) -> list[dict[str, str]]:
    return [{"line": label, "tag": element.tag.removeprefix(TEI),
             "tei": ET.tostring(element, encoding="unicode")}
            for element in node.iter()
            if element.tag.removeprefix(TEI) in EDITORIAL_TAGS]


def get_archive() -> tuple[str, zipfile.ZipFile]:
    RAW.mkdir(parents=True, exist_ok=True)
    commit_path = RAW / "commit.json"
    if commit_path.exists():
        commit = json.loads(commit_path.read_text(encoding="utf-8"))["sha"]
    else:
        payload = fetch(API)
        commit_path.write_bytes(payload)
        commit = json.loads(payload)["sha"]
    archive_path = RAW / f"canonical-greekLit-{commit}.zip"
    if not archive_path.exists():
        logging.info("Downloading pinned Perseus archive at %s", commit)
        payload = fetch(f"https://codeload.github.com/PerseusDL/canonical-greekLit/zip/{commit}")
        archive_path.write_bytes(payload)
    return commit, zipfile.ZipFile(archive_path)


def raw_member(zf: zipfile.ZipFile, member: str) -> bytes:
    return zf.read(member)


def inventory(zf: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    groups: dict[str, str] = {}
    works: dict[str, tuple[str, str]] = {}
    for member in zf.namelist():
        if not member.endswith("/__cts__.xml") or "/data/" not in member:
            continue
        try:
            root = ET.fromstring(raw_member(zf, member))
        except ET.ParseError as exc:
            logging.warning("Bad CTS XML %s: %s", member, exc)
            continue
        rel = member.split("/data/", 1)[1]
        parts = rel.split("/")
        if len(parts) == 2:
            label = text_of(root.find(CTS + "groupname"))
            if label:
                groups[parts[0]] = label
        elif len(parts) == 3:
            title = text_of(root.find(CTS + "title"))
            if title:
                works["/".join(parts[:2])] = (title, member)
    return groups, works


def selected_groups(groups: dict[str, str], works: dict[str, tuple[str, str]]) -> set[str]:
    selected = {code for code, name in groups.items()
                if any(term in name.casefold() for term in REQUESTED)}
    return selected


def header_field(root: ET.Element, path: str) -> str:
    return text_of(root.find(path))


def edition_description(cts_root: ET.Element | None, filename: str) -> str:
    if cts_root is not None:
        for node in cts_root:
            if node.attrib.get("urn", "").endswith(filename.removesuffix(".xml")):
                desc = text_of(node.find(CTS + "description"))
                if desc:
                    return desc
    return ""


def rights(root: ET.Element) -> str:
    statements = [text_of(node) for node in root.findall(f".//{TEI}publicationStmt/{TEI}availability/{TEI}licence")]
    statements += [text_of(node) for node in root.findall(f".//{TEI}publicationStmt/{TEI}availability/{TEI}p")]
    return " | ".join(s for s in statements if s) or "CC BY-SA 4.0 (repository default; check TEI rights)"


def citation(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    labels: list[str] = []
    cursor: ET.Element | None = node
    while cursor is not None:
        if cursor.tag in {TEI + "div", TEI + "l", TEI + "p", TEI + "lg", TEI + "seg"}:
            label = cursor.attrib.get("n") or cursor.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
            if label and not label.startswith("urn:cts:"):
                labels.append(label)
        cursor = parents.get(cursor)
    return ".".join(reversed(labels))


def passages(root: ET.Element, lang: str) -> list[tuple[str, str, list[dict[str, str]] | None, str, dict]]:
    body = root.find(f".//{TEI}text/{TEI}body")
    if body is None:
        return []
    parents = {child: parent for parent in body.iter() for child in parent}
    body_nodes = list(body.iter())
    node_positions = {node: index for index, node in enumerate(body_nodes)}
    numbered_lines = [node for node in body_nodes if node.tag == TEI + "l" and citation(node, parents)]

    def append_outside_editorial() -> None:
        """Retain TEI editorial signs outside lines/paragraphs as apparatus."""
        for element in body.iter():
            tag = element.tag.removeprefix(TEI)
            if tag not in EDITORIAL_TAGS:
                continue
            cursor = parents.get(element)
            nearest = cursor
            inside_passage = False
            while cursor is not None:
                if cursor.tag in {TEI + "l", TEI + "p"}:
                    inside_passage = True
                    break
                cursor = parents.get(cursor)
            if inside_passage:
                continue
            cite = citation(nearest, parents) if nearest is not None else ""
            passage_meta: dict = {"editorial_markup": editorial_evidence(element, cite),
                                  "editorial_context": nearest.tag.removeprefix(TEI) if nearest is not None else "body"}
            if not cite:
                following = next((line for line in numbered_lines
                                  if node_positions[line] > node_positions[element]), None)
                adjacent = following if following is not None else (numbered_lines[-1] if numbered_lines else None)
                cite = citation(adjacent, parents) if adjacent is not None else "unreferenced"
                passage_meta["citation_basis"] = "adjacent_source_line" if adjacent is not None else "source_has_no_numbered_line"
                passage_meta["editorial_markup"] = editorial_evidence(element, cite)
            output.append((cite, direct_text(element), None, "apparatus",
                           passage_meta))

    lines = list(body.iter(TEI + "l"))
    output: list[tuple[str, str, list[dict[str, str]] | None, str, dict]] = []
    if lines:
        # Group nearby lines while respecting poem/book boundaries. Single line
        # fragments retain the same source citation.
        batches: dict[tuple[str, ...], list[ET.Element]] = collections.OrderedDict()
        for line in lines:
            ancestors = []
            cursor = parents.get(line)
            while cursor is not None:
                if cursor.tag == TEI + "div" and cursor.attrib.get("n") and not cursor.attrib["n"].startswith("urn:cts:"):
                    ancestors.append(cursor.attrib["n"])
                cursor = parents.get(cursor)
            key = tuple(reversed(ancestors))
            batches.setdefault(key, []).append(line)
        for group in batches.values():
            for offset in range(0, len(group), 20):
                chunk = group[offset:offset + 20]
                rendered = []
                speakers: dict[int, tuple[ET.Element, str]] = {}
                for line in chunk:
                    entry = {"label": citation(line, parents), "text": direct_text(line)}
                    cursor = parents.get(line)
                    while cursor is not None:
                        if cursor.tag == TEI + "sp":
                            speaker_node = cursor.find(TEI + "speaker")
                            if speaker_node is not None:
                                speaker_label = direct_text(speaker_node)
                                if speaker_label:
                                    entry["speaker"] = speaker_label
                                speakers[id(speaker_node)] = (speaker_node, entry["label"])
                            break
                        cursor = parents.get(cursor)
                    rendered.append(entry)
                rendered = [entry for entry in rendered if entry["text"]]
                if not rendered:
                    continue
                first, last = rendered[0]["label"], rendered[-1]["label"]
                cite = first if first == last else f"{first}–{last}"
                passage_meta: dict = {}
                editorial = [entry for line in chunk
                             for entry in editorial_evidence(line, citation(line, parents))]
                editorial += [entry for speaker_node, label in speakers.values()
                              for entry in editorial_evidence(speaker_node, label)]
                if editorial:
                    passage_meta["editorial_markup"] = editorial
                cursor = parents.get(chunk[0])
                while cursor is not None:
                    label = text_of(cursor.find(TEI + "label"))
                    if label and "source_label" not in passage_meta:
                        passage_meta["source_label"] = label
                    poem_author = text_of(cursor.find(TEI + "docAuthor"))
                    if poem_author:
                        passage_meta["attributed_author"] = poem_author
                        break
                    cursor = parents.get(cursor)
                output.append((cite, "\n".join(e["text"] for e in rendered), rendered, "text" if lang == "grc" else "translation", passage_meta))
        append_outside_editorial()
        return output
    # Prose translations and unlineated material: retain source paragraph/stanza.
    blocks = list(body.iter(TEI + "p"))
    if not blocks:
        blocks = list(body.iter(TEI + "lg")) or list(body.iter(TEI + "div"))
    for index, block in enumerate(blocks, 1):
        rendered = direct_text(block)
        if rendered:
            cite = citation(block, parents) or f"block-{index}"
            passage_meta = {}
            editorial = editorial_evidence(block, cite)
            if editorial:
                passage_meta["editorial_markup"] = editorial
            output.append((cite, rendered, None, "text" if lang == "grc" else "translation", passage_meta))
    append_outside_editorial()
    return output


def collect(commit: str, zf: zipfile.ZipFile, groups: dict[str, str], works: dict[str, tuple[str, str]]) -> None:
    selected = selected_groups(groups, works)
    prefix = f"canonical-greekLit-{commit}/"
    counts: collections.Counter[str] = collections.Counter()
    failures: list[dict[str, str]] = []
    sources: list[dict[str, str | int]] = []
    records: list[dict] = []
    member_names = set(zf.namelist())
    for member in zf.namelist():
        if not member.startswith(prefix + "data/") or not member.endswith(".xml") or member.endswith("__cts__.xml"):
            continue
        rel = member.removeprefix(prefix)
        parts = rel.split("/")
        if len(parts) != 4 or parts[1] not in selected:
            continue
        filename = parts[-1]
        lang = "grc" if re.search(r"-grc\d+\.xml$", filename) else "eng" if re.search(r"-eng\d+\.xml$", filename) else ""
        if not lang:
            continue
        try:
            payload = raw_member(zf, member)
            root = ET.fromstring(payload)
            author = header_field(root, f".//{TEI}fileDesc/{TEI}titleStmt/{TEI}author") or groups.get(parts[1], "")
            work = works.get("/".join(parts[1:3]), ("", ""))[0] or header_field(root, f".//{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
            if not author or not work:
                raise ValueError("missing source author or work label")
            cts_member = prefix + "/".join(parts[:3]) + "/__cts__.xml"
            cts_root = ET.fromstring(raw_member(zf, cts_member)) if cts_member in member_names else None
            edition = edition_description(cts_root, filename)
            if not edition:
                edition = header_field(root, f".//{TEI}sourceDesc/{TEI}biblStruct/{TEI}monogr") or filename
            source_path = RAW / rel.removeprefix("data/")
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(payload)
            raw_rel = source_path.relative_to(ROOT).as_posix()
            digest = sha256(payload)
            source_url = f"https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/{commit}/{rel}"
            edition_urn = filename.removesuffix(".xml")
            extracted = passages(root, lang)
            if not extracted:
                raise ValueError("no textual passages")
            seen: collections.Counter[str] = collections.Counter()
            for cite, passage_text, line_data, kind, passage_meta in extracted:
                seen[cite] += 1
                record_id = f"perseus:{edition_urn}:{cite}:{seen[cite]}"
                record = {"id": record_id, "source": "perseus", "source_url": source_url,
                          "raw_path": raw_rel, "raw_sha256": digest, "author": author,
                          "work": work, "edition": edition, "citation": cite,
                          "language": lang, "text": passage_text, "kind": kind,
                          "quality": "needs_review" if passage_meta.get("editorial_markup") else "source_text", "license": rights(root),
                          "metadata": {"cts_urn": edition_urn, "commit": commit, **passage_meta}}
                if line_data:
                    record["lines"] = line_data
                records.append(record)
            counts[lang] += len(extracted)
            sources.append({"path": raw_rel, "url": source_url, "sha256": digest,
                            "author": author, "work": work, "language": lang,
                            "passages": len(extracted), "license": rights(root)})
        except (ET.ParseError, KeyError, ValueError) as exc:
            failures.append({"path": rel, "error": str(exc)})
            logging.warning("SKIPPED %s: %s", rel, exc)
    # Link an English passage only when its source citation names a Greek line
    # actually present in the matching work. No positional/semantic guesswork.
    greek_lines: dict[tuple[str, str], str] = {}
    for record in records:
        if record["language"] != "grc":
            continue
        work_urn = ".".join(record["metadata"]["cts_urn"].split(".")[:2])
        for line in record.get("lines", []):
            greek_lines.setdefault((work_urn, line["label"]), record["id"])
    for record in records:
        if record["language"] != "eng":
            continue
        work_urn = ".".join(record["metadata"]["cts_urn"].split(".")[:2])
        first_ref = record["citation"].split("–", 1)[0]
        parent_id = greek_lines.get((work_urn, first_ref))
        if parent_id:
            record["parent_id"] = parent_id
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {"repository": REPO, "commit": commit, "archive_sha256": sha256((RAW / f"canonical-greekLit-{commit}.zip").read_bytes()),
              "selected_groups": {code: groups[code] for code in sorted(selected) if code in groups},
              "record_count": len(records), "language_counts": dict(counts),
              "source_file_count": len(sources), "sources": sources, "failures": failures}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Wrote %s passages from %s files (%s failures)", len(records), len(sources), len(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    commit, zf = get_archive()
    groups, works = inventory(zf)
    if args.inventory:
        selected = selected_groups(groups, works)
        for code in sorted(selected):
            print(code, groups.get(code, "[no group label]"))
            for key, (title, _) in sorted(works.items()):
                if key.startswith(code + "/"):
                    print("  ", key, title)
    else:
        collect(commit, zf, groups, works)


if __name__ == "__main__":
    main()
