"""Extract source-local editorial claims from the already pinned Greek TEI.

The raw files were downloaded by ingest_perseus.py and ingest_commentary.py.
This script reads those saved artifacts, checks their recorded SHA-256 hashes,
and quotes byte-exact UTF-8 XML spans from them. It never supplies a reading.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from xml.parsers import expat
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/claims/p2_apparatus.jsonl"
REPORT = ROOT / "data/reports/p2_apparatus.json"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SPACE = re.compile(r"\s+")
MARKS = {"supplied", "gap", "unclear", "add", "del"}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def content(node: ET.Element) -> str:
    return SPACE.sub(" ", "".join(node.itertext())).strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def source_inventory() -> list[dict]:
    perseus = json.loads((ROOT / "data/reports/perseus.json").read_text(encoding="utf-8"))
    edition_by_path = {}
    for record in read_jsonl(ROOT / "data/processed/perseus.jsonl"):
        edition_by_path.setdefault(record["raw_path"], record["edition"])
    files = [
        {**item, "origin": "perseus", "edition": edition_by_path[item["path"]]}
        for item in perseus["sources"]
        if item["language"] == "grc"
    ]
    dclp = {}
    for record in read_jsonl(ROOT / "data/processed/commentary.jsonl"):
        if record["id"].count(":") == 1 and record["id"].startswith("dclp:"):
            dclp[record["raw_path"]] = {
                "path": record["raw_path"],
                "url": record["source_url"],
                "sha256": record["raw_sha256"],
                "author": record["author"],
                "work": record["work"],
                "origin": "dclp",
                "record_id": record["id"],
                "citation": record["citation"],
                "edition": record["edition"],
                "source_editions": record.get("metadata", {}).get("source_editions", []),
            }
    files.extend(dclp.values())
    return sorted(files, key=lambda item: item["path"])


def exact_element_spans(payload: bytes) -> list[tuple[str, int, int]]:
    """Map Expat's element events to exact source-byte ranges, preorder."""
    parser = expat.ParserCreate()
    stack: list[tuple[int, str, int]] = []
    spans: list[tuple[str, int, int] | None] = []

    def opening_end(begin: int) -> int:
        quote = None
        for position in range(begin + 1, len(payload)):
            byte = payload[position]
            if quote is not None:
                if byte == quote:
                    quote = None
            elif byte in (34, 39):
                quote = byte
            elif byte == 62:
                return position + 1
        raise ValueError("Unterminated XML opening tag")

    def start(name: str, _attrs: dict):
        index = len(spans)
        spans.append(None)
        stack.append((index, name, parser.CurrentByteIndex))

    def end(_name: str):
        index, name, begin = stack.pop()
        cursor = parser.CurrentByteIndex
        open_end = opening_end(begin)
        if payload[begin:open_end].rstrip().endswith(b"/>"):
            finish = open_end
        elif payload[cursor:cursor + 2] == b"</":
            finish = payload.index(b">", cursor) + 1
        else:
            raise ValueError(f"Missing closing tag for {name} at {begin}")
        spans[index] = (name.rsplit(":", 1)[-1], begin, finish)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(payload, True)
    if any(span is None for span in spans):
        raise ValueError("Unclosed XML span")
    return spans  # type: ignore[return-value]


def node_index(root: ET.Element, payload: bytes) -> dict[ET.Element, tuple[int, int, int]]:
    nodes = list(root.iter())
    spans = exact_element_spans(payload)
    if len(nodes) != len(spans):
        raise ValueError(f"XML event count mismatch: {len(nodes)} / {len(spans)}")
    indexed = {}
    for ordinal, (node, (tag, start, end)) in enumerate(zip(nodes, spans), 1):
        if local(node.tag) != tag or not payload[start:end].startswith(b"<"):
            raise ValueError(f"XML element alignment mismatch at {ordinal}")
        indexed[node] = (ordinal, start, end)
    return indexed


def ancestors(node: ET.Element, parents: dict[ET.Element, ET.Element]):
    cursor = parents.get(node)
    while cursor is not None:
        yield cursor
        cursor = parents.get(cursor)


def inside_edition(node: ET.Element, parents: dict[ET.Element, ET.Element], origin: str) -> bool:
    chain = list(ancestors(node, parents))
    if origin == "dclp":
        return any(local(a.tag) == "div" and a.get("type") == "edition" for a in chain)
    return any(local(a.tag) == "body" for a in chain)


def locus(node: ET.Element, parents: dict[ET.Element, ET.Element], ordinal: int, origin: str) -> dict:
    branch = list(reversed(list(ancestors(node, parents))))
    parts = [
        {"type": a.get("subtype", "textpart"), "n": a.get("n", "")}
        for a in branch
        if local(a.tag) == "div" and a.get("type") == "textpart"
    ]
    if origin == "perseus":
        numbered = [a.get("n") or a.get(XML_ID) for a in [*branch, node]
                    if local(a.tag) in {"div", "l", "p", "lg", "seg"}
                    and (a.get("n") or a.get(XML_ID))
                    and not (a.get("n") or a.get(XML_ID)).startswith("urn:cts:")]
        line = next((a.get("n", "") for a in reversed(branch) if local(a.tag) == "l"), "")
    else:
        numbered = [p["n"] for p in parts if p["n"]]
        line = ""
        # The last preceding lb within the closest textpart is a source-local
        # line locator; it does not imply equivalence to another edition.
        container = next((a for a in reversed(branch) if local(a.tag) == "div" and a.get("type") == "textpart"), None)
        if container is not None:
            for element in container.iter():
                if element is node:
                    break
                if local(element.tag) == "lb":
                    line = element.get("n", "")
    return {"element_ordinal": ordinal, "textpart_path": parts,
            "source_citation": ".".join(numbered), "line": line}


def marks_within(node: ET.Element) -> list[dict]:
    return [{"tag": local(child.tag), "text": content(child), "attributes": dict(child.attrib)}
            for child in node.iter() if child is not node and local(child.tag) in MARKS]


def nested_tei(node: ET.Element) -> list[dict]:
    # Includes certainty, expansion, line-break, and other source-specific
    # markup, so no interpretation silently disappears from a reading object.
    return [{"tag": local(child.tag), "text": content(child), "attributes": dict(child.attrib)}
            for child in node.iter() if child is not node]


def reading(node: ET.Element) -> dict:
    return {"text": content(node), "attributes": dict(node.attrib),
            "editorial_marks": marks_within(node), "nested_tei": nested_tei(node)}


def claim_for(node: ET.Element, info: dict, raw: bytes, span: tuple[int, int, int],
              where: dict, app_index: int | None) -> dict:
    ordinal, begin, end = span
    tag = local(node.tag)
    source_id = Path(info["path"]).stem
    claim_id = f"p2-apparatus:{info['origin']}:{source_id}:{tag}:{ordinal}"
    quote = raw[begin:end].decode("utf-8")
    source_family = (f"perseus:{source_id}" if info["origin"] == "perseus"
                     else f"dclp:{source_id}")
    if tag == "app":
        lemma = node.find(TEI + "lem")
        alternatives = node.findall(TEI + "rdg")
        if lemma is None or not alternatives:
            raise ValueError(f"Incomplete app in {info['path']} at element {ordinal}")
        obj = {"kind": "explicit_apparatus", "apparatus_type": node.get("type"),
               "lemma": reading(lemma), "alternatives": [reading(a) for a in alternatives],
               "attributes": dict(node.attrib)}
    else:
        obj = {"kind": {"supplied": "restoration", "gap": "loss",
                        "unclear": "uncertain_surviving_text", "add": "addition",
                        "del": "deletion"}[tag],
               "tei_tag": tag, "text": content(node) if tag != "gap" else None,
               "attributes": dict(node.attrib), "nested_editorial_marks": marks_within(node),
               "is_explicit_alternative": False}
    record_id = (f"dclp:{source_id}:app:{app_index}" if app_index is not None else None)
    evidence = {"source_url": info["url"], "raw_path": info["path"],
                "raw_sha256": info["sha256"], "quote": quote,
                "locator": {**where, "byte_start": begin, "byte_end": end}}
    if record_id:
        evidence["record_id"] = record_id
    subject = {"type": "edition_locus", "id": f"{source_family}:element:{ordinal}"}
    return {"id": claim_id, "subject": subject,
            "predicate": "variant_reading" if tag == "app" else "editorial_state",
            "object": obj, "evidence": [evidence],
            "assertion_type": "extracted_annotation", "status": "source_claim",
            "method": "p2_tei_exact_byte_span_v1", "source_family": source_family,
            "metadata": {"author_label": info["author"], "work_label": info["work"],
                         "edition_label": info["edition"],
                         "source_citation_label": info.get("citation"),
                         "source_editions": info.get("source_editions", []),
                         "attribution_scope": "papyrus_witness" if info["origin"] == "dclp" else "source_edition",
                         "locus": where,
                         "scope_note": "Source-local TEI locus; no cross-edition fragment equivalence asserted."}}


def extract_file(info: dict) -> tuple[list[dict], Counter, Counter]:
    path = ROOT / info["path"]
    payload = path.read_bytes()
    if sha256(payload) != info["sha256"]:
        raise ValueError(f"Raw hash mismatch: {path}")
    root = ET.fromstring(payload)
    parents = {child: parent for parent in root.iter() for child in parent}
    indexed = node_index(root, payload)
    records = []
    counts = Counter()
    nested_counts = Counter()
    app_index = 0
    for node in root.iter():
        tag = local(node.tag)
        if tag not in MARKS | {"app"} or not inside_edition(node, parents, info["origin"]):
            continue
        if tag == "app":
            app_index += 1
        elif any(local(a.tag) in MARKS | {"app"} for a in ancestors(node, parents)):
            # The enclosing claim carries nested editorial marks.
            nested_counts[tag] += 1
            continue
        ordinal = indexed[node][0]
        records.append(claim_for(node, info, payload, indexed[node],
                                 locus(node, parents, ordinal, info["origin"]),
                                 app_index if tag == "app" and info["origin"] == "dclp" else None))
        counts[tag] += 1
    return records, counts, nested_counts


def main() -> None:
    records = []
    counts = defaultdict(Counter)
    nested = defaultdict(Counter)
    files_with_claims = Counter()
    inventory = source_inventory()
    for info in inventory:
        claims, subcounts, nested_counts = extract_file(info)
        records.extend(claims)
        counts[info["origin"]].update(subcounts)
        nested[info["origin"]].update(nested_counts)
        if claims:
            files_with_claims[info["origin"]] += 1
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate claim IDs")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "claim_count": len(records),
        "by_source_and_tag": {source: dict(counter) for source, counter in counts.items()},
        "nested_marks_in_parent_claim": {source: dict(counter) for source, counter in nested.items()},
        "source_files_checked": len(inventory),
        "source_files_with_claims": dict(files_with_claims),
        "output": OUT.relative_to(ROOT).as_posix(),
        "output_sha256": sha256(OUT.read_bytes()),
        "method": "Byte-exact XML element spans from hash-checked, pinned TEI artifacts; nested markup retained as structured attributes.",
        "coverage_note": "All 119 DCLP apparatus entries duplicate the existing accepted DCLP apparatus records as structured claims; no new ancient text is asserted. Other claims expose editorial states already present in accepted raw TEI.",
        "limitations": [
            "Perseus selected TEI has editorial gaps/supplies but no explicit app/lem/rdg variants.",
            "DCLP readings are scoped to its papyrus witness and edition locus, not linked to other fragment numbering systems.",
            "A supplied reading is an editorial restoration; unclear marks uncertain surviving text; a gap asserts no recovered text.",
            "Raw wit/resp sigla and labels are retained without expansion or identification beyond the TEI.",
            "No token offsets or cross-edition passage links are inferred.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"claim_count": len(records), "by_source_and_tag": report["by_source_and_tag"]}))


if __name__ == "__main__":
    main()
