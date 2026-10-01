"""Collect Edmonds, *Elegy and Iambus* I–II (Loeb, 1931) from the Perseus open-source archive.

Source: the Perseus Digital Library Greco-Roman text archive
(hopper-texts-GreekRoman.tar.gz), files Classics/Elegy/opensource/{1,2}_{gk,eng}.xml:
TEI P4 with Greek in Beta Code and J. M. Edmonds's facing English. Every
fragment carries a stable identifier in its bibliography (``CURFRAG.tlg-0263.4``)
in both the Greek and the English volume, so each English rendering is linked
to its Greek fragment through ``parent_id`` without any alignment guessing.
Ancient testimonia (the quoting authors' prose) are kept as reference records
with their source citation; their English versions link to them likewise.

Rights: Perseus publishes these texts under its open-source programme (the
Hopper banner states CC BY-SA 3.0 US; the 2026-09-30 edition audit noted the
TEI availability notice adds non-commercial and modification-offer terms).
The 1931 Loeb edition is admitted under docs/decisions.md; the notice is
recorded on every record. Beta Code is converted to Unicode mechanically;
no Greek is authored or repaired here.

Usage: python scripts/ingest_p2_perseus_elegy.py [--archive PATH] [--refresh]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import re
import tarfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import betacode.conv as beta
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_perseus_elegy"
OUT = ROOT / "data/processed/p2_perseus_elegy.jsonl"
REPORT = ROOT / "data/reports/p2_perseus_elegy.json"
SOURCE = "p2_perseus_elegy"
ARCHIVE_URL = "https://www.perseus.tufts.edu/hopper/opensource/downloads/texts/hopper-texts-GreekRoman.tar.gz"
DOWNLOAD_PAGE = "https://www.perseus.tufts.edu/hopper/opensource/download"
MEMBERS = {1: ("Classics/Elegy/opensource/1_gk.xml", "Classics/Elegy/opensource/1_eng.xml"),
           2: ("Classics/Elegy/opensource/2_gk.xml", "Classics/Elegy/opensource/2_eng.xml")}
HOPPER_TEXT = {1: "Perseus:text:2008.01.0477", 2: "Perseus:text:2008.01.0478"}
EDITION = "J. M. Edmonds, Elegy and Iambus, with an English Translation (Loeb Classical Library; Cambridge MA and London, 1931)"
LICENSE = ("Perseus Digital Library open-source text: CC BY-SA 3.0 US per the Hopper banner; the TEI availability "
           "notice adds non-commercial use and an offer of modifications to Perseus (audit 2026-09-30). Admitted per docs/decisions.md.")
# Perseus P4 entities that the external DTDs define; mapped to characters so
# lxml can parse without fetching the DTD. Project credits expand to nothing.
ENTITIES = {"responsibility": "", "Perseus.publish": "", "fund.NEH": "", "fund.Google": "",
            "lpar": "(", "rpar": ")", "lsqb": "[", "rsqb": "]", "lsquo": "‘", "rsquo": "’",
            "ldquo": "“", "rdquo": "”", "mdash": "—", "ndash": "–", "dagger": "†",
            "colon": ":", "quest": "?", "macr": "¯", "breve": "˘", "ast": "*", "hellip": "…"}
ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9.]*);")
DOCTYPE = re.compile(r"<!DOCTYPE.*?\]>\s*", re.S)
SPACES = re.compile(r"[ \t ]+")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_archive(path: Path, refresh: bool) -> Path:
    if path.exists() and path.stat().st_size and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(ARCHIVE_URL, headers={"User-Agent": "melos-perseus-elegy-collector/1.0 (research corpus; single archive download)"})
    with urlopen(request, timeout=1800) as response, path.open("wb") as stream:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            stream.write(chunk)
    return path


def parse_tei(raw: bytes) -> etree._Element:
    text = raw.decode("utf-8", errors="replace")
    text = DOCTYPE.sub("", text, count=1)
    text = ENTITY.sub(lambda m: ENTITIES.get(m.group(1), m.group(0)) if m.group(1) not in ("lt", "gt", "amp", "quot", "apos") else m.group(0), text)
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    return etree.fromstring(text.encode("utf-8"), parser)


LITERAL_TAG = re.compile(r"<\s*/?\s*(?:note|bibl|hi|foreign|q|add|del|gap|milestone|pb|lb|ref)\b[^<>]{0,120}/?>")


def strip_literal_markup(text: str) -> str:
    """Remove TEI tags that the source escaped as text (``&lt;note .../&gt;`` inside a line)."""
    return LITERAL_TAG.sub(" ", html.unescape(text))


def greek(text: str) -> str:
    """Beta Code to Unicode; whitespace normalised, printed signs retained."""
    return SPACES.sub(" ", beta.beta_to_uni(strip_literal_markup(text))).strip()


def inner_text(element: etree._Element, *, skip: tuple[str, ...] = ("note", "bibl")) -> str:
    """Text of an element with footnotes and bibliography removed, lines joined by newlines."""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        # Comments and processing instructions carry editors' working notes
        # (``<!--note n="p.44.n.2"/-->``); they are not text.
        if not isinstance(node.tag, str) or node.tag in skip:
            return
        if node.tag == "l" or node.tag == "p":
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if node.tag in ("l", "p"):
            parts.append("\n")

    walk(element)
    joined = "".join(parts)
    lines = [SPACES.sub(" ", line).strip() for line in joined.split("\n")]
    return "\n".join(line for line in lines if line)


def quote_lines(quote: etree._Element, convert) -> list[dict]:
    lines = []
    for line in quote.iter("l"):
        text = convert(inner_text(line))
        if text:
            lines.append({"label": line.get("n", ""), "text": text})
    return lines


def nearest_fragment_div(cit: etree._Element) -> tuple[str, str]:
    """Metre type and fragment number from the enclosing div3/div4."""
    node = cit.getparent()
    while node is not None:
        if node.tag in ("div3", "div4") and node.get("type") not in (None, "biodata", "book", "section"):
            return node.get("type", "").lower(), node.get("n", "")
        node = node.getparent()
    return "", ""


def enclosing_source(cit: etree._Element) -> str:
    """Citation of the ancient author quoting a fragment, from the outer <cit>."""
    node = cit.getparent()
    while node is not None:
        if node.tag == "cit" and node is not cit:
            bibl = node.find("bibl")
            if bibl is not None:
                return SPACES.sub(" ", "".join(bibl.itertext())).strip()
        node = node.getparent()
    return ""


def own_bibl(cit: etree._Element) -> str:
    bibl = cit.find("bibl")
    return SPACES.sub(" ", "".join(bibl.itertext())).strip() if bibl is not None else ""


def clean_label(value: str) -> str:
    """English heading as printed, minus stray markup characters; all-capital headings are title-cased."""
    label = SPACES.sub(" ", re.sub(r"[<>\[\]{}|*]+", " ", value)).strip(" .,;:")
    if label and label.isupper():
        label = " ".join(word.capitalize() if word.lower() not in ("of", "the", "and") else word.lower() for word in label.split())
    return label


def author_labels(root_eng: etree._Element) -> dict[str, str]:
    labels = {}
    for div in root_eng.iter("div1"):
        head = div.find("head")
        if div.get("id") and head is not None:
            labels[div.get("id")] = clean_label("".join(inner_text(head).split("\n")))
    return labels


def collect_volume(volume: int, greek_root: etree._Element, english_root: etree._Element, raw_info: dict, labels: dict[str, str]) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    for language, root, convert in (("grc", greek_root, greek), ("eng", english_root, lambda t: SPACES.sub(" ", strip_literal_markup(t)).strip())):
        raw_path, raw_hash, url = raw_info[language]
        for div1 in root.iter("div1"):
            tlg = div1.get("id") or ""
            head = div1.find("head")
            greek_name = greek("".join(head.itertext())) if (head is not None and language == "grc") else ""
            author = labels.get(tlg) or (greek_name or tlg)
            for cit in div1.iter("cit"):
                bibl = own_bibl(cit)
                quote = cit.find("quote")
                if quote is None:
                    continue
                cit_id = cit.get("id") or ""
                fragment = bibl.removeprefix("CURFRAG.") if bibl.startswith("CURFRAG.") else ""
                if fragment:
                    lines = quote_lines(quote, convert) if language == "grc" else []
                    text = "\n".join(line["text"] for line in lines) if lines else convert(inner_text(quote))
                    if not text:
                        continue
                    metre, number = nearest_fragment_div(cit)
                    base_id = f"{SOURCE}:{fragment}"
                    record_id = base_id if language == "grc" else f"{base_id}:eng"
                    citation = f"fr. {fragment.split('.', 1)[1]} Edmonds" + (f" (section {number})" if number and number != fragment.split('.', 1)[1] else "")
                    kind = "text" if language == "grc" else "translation"
                else:
                    text = convert(inner_text(quote))
                    if not text or not cit_id:
                        continue
                    base_id = f"{SOURCE}:{cit_id}"
                    record_id = base_id if language == "grc" else f"{base_id}:eng"
                    metre, number = "", ""
                    citation = bibl or cit_id
                    kind = "reference" if language == "grc" else "translation"
                if record_id in seen:
                    continue
                seen.add(record_id)
                record = {
                    "id": record_id, "source": SOURCE, "source_url": url, "raw_path": raw_path, "raw_sha256": raw_hash,
                    "author": author, "work": f"Elegy and Iambus, volume {volume}" + (" (fragments)" if fragment else " (testimonia)"),
                    "edition": EDITION, "citation": citation, "language": language, "text": text, "kind": kind,
                    "quality": "source_text", "license": LICENSE,
                    "metadata": {"volume": volume, "tlg_id": tlg, "author_greek_head": greek_name or None, "cit_id": cit_id,
                                 "curfrag": fragment or None, "metre_type": metre or None, "fragment_section": number or None,
                                 "quoted_by": enclosing_source(cit) or None, "source_bibl": bibl or None,
                                 "hopper_text": HOPPER_TEXT[volume], "beta_code_converted": language == "grc",
                                 "perseus_archive": ARCHIVE_URL},
                }
                if language == "grc" and fragment and lines:
                    record["lines"] = lines
                if language == "eng":
                    record["parent_id"] = base_id
                records.append(record)
    # English renderings whose Greek counterpart was not emitted keep no dangling parent.
    ids = {record["id"] for record in records}
    for record in records:
        if record.get("parent_id") and record["parent_id"] not in ids:
            record["metadata"]["unlinked_parent"] = record.pop("parent_id")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, default=RAW / "hopper-texts-GreekRoman.tar.gz")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    archive = fetch_archive(args.archive, args.refresh)
    archive_hash = sha256(archive.read_bytes())
    extracted: dict[str, Path] = {}
    with tarfile.open(archive) as tar:
        for volume, members in MEMBERS.items():
            for member in members:
                info = tar.getmember(member)
                target = RAW / Path(member).name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(info) as stream:  # type: ignore[union-attr]
                    target.write_bytes(stream.read())
                extracted[member] = target
    records: list[dict] = []
    files = []
    english_roots = {}
    for volume, (gk, eng) in MEMBERS.items():
        english_roots[volume] = parse_tei(extracted[eng].read_bytes())
    labels = {}
    for root in english_roots.values():
        labels.update(author_labels(root))
    for volume, (gk, eng) in MEMBERS.items():
        greek_root = parse_tei(extracted[gk].read_bytes())
        raw_info = {}
        for language, member in (("grc", gk), ("eng", eng)):
            path = extracted[member]
            raw_info[language] = (path.relative_to(ROOT).as_posix(), sha256(path.read_bytes()),
                                  f"{ARCHIVE_URL}#{member}")
            files.append({"member": member, "raw_path": raw_info[language][0], "raw_sha256": raw_info[language][1], "bytes": path.stat().st_size})
        records.extend(collect_volume(volume, greek_root, english_roots[volume], raw_info, labels))
    if not records:
        raise RuntimeError("No records collected")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(OUT)
    report = {
        "status": "collected_pending_index_acceptance",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_url": ARCHIVE_URL, "archive_sha256": archive_hash, "download_page": DOWNLOAD_PAGE,
        "edition": EDITION, "license": LICENSE, "files": files,
        "policy": "docs/decisions.md 2026-09-30: 1931 Loeb edition admitted; rights recorded per record",
        "record_count": len(records),
        "counts_by_kind": dict(Counter(r["kind"] for r in records)),
        "counts_by_language": dict(Counter(r["language"] for r in records)),
        "counts_by_author_text": dict(Counter(r["author"] for r in records if r["kind"] == "text")),
        "linked_translations": sum(1 for r in records if r.get("parent_id")),
        "unlinked_translations": sum(1 for r in records if r["metadata"].get("unlinked_parent")),
        "output": OUT.relative_to(ROOT).as_posix(), "output_sha256": sha256(OUT.read_bytes()),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("record_count", "counts_by_kind", "counts_by_language", "linked_translations", "unlinked_translations")}, ensure_ascii=False))
    print(json.dumps(dict(sorted(report["counts_by_author_text"].items(), key=lambda kv: -kv[1])[:20]), ensure_ascii=False))


if __name__ == "__main__":
    main()
