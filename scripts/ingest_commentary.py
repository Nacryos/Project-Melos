"""Collect lyric-papyrus metadata, commentary, and apparatus from DCLP TEI.

The source is papyri/idp.data (CC BY 3.0). A local sparse Git checkout is
used only to discover candidate file names; every selected XML file is fetched
again at the checkout's exact commit and saved unchanged under data/raw/.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = ROOT / "data/cache/idp.data"
RAW = ROOT / "data/raw/commentary"
OUTPUT = ROOT / "data/processed/commentary.jsonl"
REPORT = ROOT / "data/reports/commentary.json"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
AUTHORS = (
    "Sappho", "Alcaeus", "Ibycus", "Anacreon", "Pindar", "Simonides",
    "Bacchylides", "Alcman", "Stesichorus", "Archilochus",
)
LICENSE_URL = "http://creativecommons.org/licenses/by/3.0/"


def one(node: ET.Element, path: str) -> ET.Element | None:
    return node.find(path)


def content(node: ET.Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def xml_without_tail(node: ET.Element) -> str:
    detached = copy.deepcopy(node)
    detached.tail = None
    return ET.tostring(detached, encoding="unicode")


def target_checkout(checkout: Path) -> str:
    if not (checkout / ".git").exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
             "--single-branch", "https://github.com/papyri/idp.data.git", str(checkout)],
            check=True,
        )
        subprocess.run(["git", "sparse-checkout", "set", "DCLP"], cwd=checkout, check=True)
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=checkout, text=True
    ).strip()
    if remote.rstrip("/").removesuffix(".git") != "https://github.com/papyri/idp.data":
        raise RuntimeError(f"Unexpected source checkout remote: {remote}")
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()


def authors_in(root: ET.Element) -> list[str]:
    # Only ancient author labels in the bibliography; not modern editors.
    labels = []
    for bibl in root.findall(f".//{TEI}div[@type='bibliography']/{TEI}listBibl/{TEI}bibl"):
        if bibl.get("subtype") != "ancient":
            continue
        labels.extend(content(a) for a in bibl.findall(f"{TEI}author"))
    return list(dict.fromkeys(label for label in labels if label))


def discover(checkout: Path) -> list[Path]:
    found = []
    for path in (checkout / "DCLP").rglob("*.xml"):
        data = path.read_bytes()
        if not any(name.encode() in data for name in AUTHORS):
            continue
        root = ET.fromstring(data)
        labels = authors_in(root)
        if any(any(name.lower() in label.lower() for name in AUTHORS) for label in labels):
            found.append(path.relative_to(checkout))
    if not found:
        raise RuntimeError("No lyric-author records discovered in DCLP checkout")
    return sorted(found)


def download(item: tuple[Path, str]) -> tuple[Path, str, str]:
    path, commit = item
    url = f"https://raw.githubusercontent.com/papyri/idp.data/{commit}/{path.as_posix()}"
    request = Request(url, headers={"User-Agent": "melos-corpus-ingest/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}: {url}")
                data = response.read()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    # Save the downloaded bytes, not a reconstructed rendering of the TEI.
    destination = RAW / path.relative_to("DCLP")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination, url, hashlib.sha256(data).hexdigest()


def source_metadata(root: ET.Element) -> dict:
    pub = one(root, f"./{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt")
    source = one(root, f"./{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc")
    title = content(one(root, f"./{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title"))
    ids = {i.get("type", "untyped"): content(i) for i in pub.findall(f"{TEI}idno")} if pub is not None else {}
    license_refs = [r.get("target", "") for r in pub.findall(f".//{TEI}ref[@type='license']")] if pub is not None else []
    if LICENSE_URL not in license_refs:
        raise RuntimeError(f"Record {ids.get('dclp', title)} lacks explicit CC BY 3.0 license")
    origin = one(source, f".//{TEI}origin") if source is not None else None
    orig_date = one(origin, f"{TEI}origDate") if origin is not None else None
    head = one(root, f"./{TEI}text/{TEI}body/{TEI}head")
    editions = []
    if head is not None:
        for ref in head.findall(f"{TEI}ref"):
            editions.append({
                "title": content(one(ref, f"{TEI}title")) or content(ref),
                "year": content(one(ref, f"{TEI}date")),
                "url": ref.get("target", ""),
            })
    return {
        "title": title,
        "identifiers": ids,
        "author_labels": authors_in(root),
        "license_url": LICENSE_URL,
        "witness_origin": content(one(origin, f"{TEI}origPlace")) if origin is not None else "",
        "witness_date": ({"label": content(orig_date), "not_before": orig_date.get("notBefore"),
                          "not_after": orig_date.get("notAfter")}
                         if orig_date is not None else None),
        "inventory_numbers": [content(n) for n in root.findall(f".//{TEI}msIdentifier//{TEI}idno[@type='invNo']")],
        "source_editions": editions,
        "overview": [content(t) for t in root.findall(f".//{TEI}term[@type='overview']")],
    }


def context_of(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> dict:
    branch = []
    current = node
    while current in parents:
        current = parents[current]
        if current.tag == TEI + "div" and current.get("type") == "textpart":
            branch.append({"type": current.get("subtype", "textpart"), "n": current.get("n", "")})
    branch.reverse()
    anchor = parents.get(node)
    while anchor is not None and anchor.tag != TEI + "div":
        anchor = parents.get(anchor)
    line = ""
    if anchor is not None:
        for part in anchor.iter():
            if part is node:
                break
            if part.tag == TEI + "lb":
                line = part.get("n", "")
    return {"textpart_path": branch, "line": line}


def base_record(identifier: str, url: str, raw: Path, digest: str, meta: dict) -> dict:
    editions = meta["source_editions"]
    return {
        "id": identifier,
        "source": "commentary",
        "source_url": url,
        "raw_path": raw.relative_to(ROOT).as_posix(),
        "raw_sha256": digest,
        "author": " / ".join(meta["author_labels"]),
        "work": meta["title"],
        "edition": "Digital Corpus of Literary Papyri",
        "citation": editions[0]["title"] if editions else f"TM {identifier.split(':')[1]}",
        "language": "eng",
        "text": "",
        "kind": "reference",
        "quality": "source_text",
        "license": "CC BY 3.0",
    }


def parse(downloaded: tuple[Path, str, str]) -> list[dict]:
    raw, url, digest = downloaded
    root = ET.fromstring(raw.read_bytes())
    meta = source_metadata(root)
    dclp_id = meta["identifiers"].get("dclp")
    if not dclp_id or dclp_id != raw.stem:
        raise RuntimeError(f"DCLP ID/path mismatch: {raw}")
    base = base_record(f"dclp:{dclp_id}", url, raw, digest, meta)
    base["text"] = meta["overview"][0] if meta["overview"] else meta["title"]
    base["metadata"] = {"record_type": "papyrus_witness", **meta}
    records = [base]
    parents = {child: parent for parent in root.iter() for child in parent}

    for index, app in enumerate(root.findall(f".//{TEI}div[@type='edition']//{TEI}app"), 1):
        context = context_of(app, parents)
        lem = app.find(f"{TEI}lem")
        readings = app.findall(f"{TEI}rdg")
        if lem is None or not readings:
            raise RuntimeError(f"Incomplete apparatus in DCLP {dclp_id}, app {index}")
        rec = {**base, "id": f"dclp:{dclp_id}:app:{index}", "kind": "apparatus", "language": "grc"}
        rec["text"] = xml_without_tail(app)
        rec["parent_id"] = base["id"]
        location = " ".join(f"{part['type']} {part['n']}" for part in context["textpart_path"])
        rec["citation"] = " ".join(filter(None, [base["citation"], location, f"line {context['line']}" if context["line"] else ""]))
        rec["metadata"] = {
            "apparatus_type": app.get("type", ""),
            "lemma": {"text": content(lem), "attributes": lem.attrib},
            "readings": [{"text": content(r), "attributes": r.attrib} for r in readings],
            "source_author_labels": meta["author_labels"],
            "attribution_scope": "witness",
            **context,
        }
        records.append(rec)

    for div in root.findall(f".//{TEI}div[@type='commentary']"):
        subtype = div.get("subtype", "")
        if subtype == "frontmatter":
            continue  # editorial credits, not commentary on the papyrus
        if subtype == "linebyline":
            parts = div.findall(f".//{TEI}item")
        else:
            parts = div.findall(f"{TEI}p")
        for part in parts:
            paragraphs = part.findall(f"{TEI}p") if part.tag == TEI + "item" else [part]
            note = " ".join(filter(None, (content(p) for p in paragraphs)))
            if not note:
                continue
            idx = sum(r["kind"] == "commentary" for r in records) + 1
            rec = {**base, "id": f"dclp:{dclp_id}:commentary:{idx}", "kind": "commentary"}
            rec["text"] = note
            rec["parent_id"] = base["id"]
            rec["citation"] = f"{base['citation']} commentary {content(one(part, f'{TEI}ref'))}"
            rec["metadata"] = {
                "commentary_subtype": subtype,
                "line_reference": content(one(part, f"{TEI}ref")),
                "corresp": part.get("corresp", ""),
                "tei_xml": xml_without_tail(part),
                "source_author_labels": meta["author_labels"],
                "attribution_scope": "witness",
            }
            records.append(rec)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=CHECKOUT)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    commit = target_checkout(args.checkout)
    paths = discover(args.checkout)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        downloaded = list(executor.map(download, ((p, commit) for p in paths)))
    records = [record for item in downloaded for record in parse(item)]
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate output IDs")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter(record["kind"] for record in records)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "source_repository": "https://github.com/papyri/idp.data",
        "source_commit": commit,
        "license": "CC BY 3.0",
        "license_url": LICENSE_URL,
        "witnesses": len(paths),
        "records": len(records),
        "by_kind": dict(counts),
        "raw_directory": RAW.relative_to(ROOT).as_posix(),
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "scope": list(AUTHORS),
        "method": "Ancient-author bibliography match; each raw TEI downloaded at pinned commit; witness metadata, edition apparatus, and commentary extracted separately.",
        "limitations": [
            "Witness dates are in metadata only, not author-composition dates.",
            "Mixed or uncertain author labels are preserved as source labels.",
            "Apparatus readings are editor/source claims, not resolved text.",
            "Apparatus and commentary records are not ancient poem lines.",
            "Ancient scholia within Greek edition text are not isolated as modern commentary.",
        ],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_commit": commit, "witnesses": len(paths), "records": len(records), "by_kind": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
