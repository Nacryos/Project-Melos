"""Stage Greek elegiac and iambic witnesses with file-level provenance.

The Greek Wikisource Theognidean anthology is a composite collection with no
identified printed edition. Its lines must not be equated with Theognis' own
authorship or counted as an independent critical edition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_elegy"
OUT = ROOT / "data/processed/p2_elegy.jsonl"
REPORT = ROOT / "data/reports/p2_elegy.json"
API = "https://el.wikisource.org/w/api.php"
TITLE = "Ελεγείαι Θεόγνιδος"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
MARKER = re.compile(r"\{\{r\|(\d+)\}\}")
BOOK = re.compile(r"(?m)^ΕΛΕΓΕΙΩΝ ([ΑΒ])\s*$")
PERSEUS_URL = "https://www.perseus.tufts.edu/hopper/dltext?doc=Perseus%3Atext%3A2008.01.0477"
TEI = "{http://www.tei-c.org/ns/1.0}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def retrieve_wikisource() -> tuple[dict, Path, str, str]:
    """Download once, then reuse the immutable saved MediaWiki revision."""
    RAW.mkdir(parents=True, exist_ok=True)
    params = {"action": "query", "format": "json", "titles": TITLE,
              "prop": "revisions", "rvprop": "ids|content", "rvslots": "main"}
    url = API + "?" + urllib.parse.urlencode(params)
    for path in sorted(RAW.glob("theognis_*.json")):
        data = path.read_bytes()
        payload = json.loads(data)
        page = next(iter(payload["query"]["pages"].values()))
        if page.get("title") == TITLE and page.get("revisions"):
            return page, path, sha256(data), url
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "MelosCorpus/0.2 (research; source audit)"})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"DOWNLOAD FAILED {url}: {exc}") from exc
            time.sleep(2 ** attempt)
    payload = json.loads(data)
    page = next(iter(payload["query"]["pages"].values()))
    if "missing" in page or not page.get("revisions"):
        raise RuntimeError(f"Missing source page: {TITLE}")
    path = RAW / f"theognis_{page['pageid']}_{page['revisions'][0]['revid']}.json"
    path.write_bytes(data)
    return page, path, sha256(data), url


def retrieve_perseus() -> tuple[ET.Element, Path, str]:
    """Save the complete Edmonds vol. I TEI, including its restrictive header."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / "edmonds_elegy_iambus_v1_2008.01.0477.xml"
    if not path.exists():
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    PERSEUS_URL, headers={"User-Agent": "MelosCorpus/0.2 (noncommercial research; source audit)"}
                )
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = response.read()
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"DOWNLOAD FAILED {PERSEUS_URL}: {exc}") from exc
                time.sleep(2 ** attempt)
        path.write_bytes(data)
    data = path.read_bytes()
    return ET.fromstring(data), path, sha256(data)


def inspect_perseus(root: ET.Element) -> dict:
    def sample(element: ET.Element) -> str:
        return " ".join("".join(element.itertext()).split())[:120]

    return {
        "root_tag": root.tag,
        "availability": [sample(x) for x in root.iter() if x.tag.endswith("availability")],
        "headings": [{"tag": x.tag, "attributes": x.attrib, "text": sample(x)}
                     for x in root.iter() if x.tag.endswith("head")][:55],
        "tag_counts": Counter(x.tag.split("}")[-1] for x in root.iter()),
        "sample_divs": [{"attributes": x.attrib, "head": sample(x.find(TEI + "head")) if x.find(TEI + "head") is not None else ""}
                        for x in root.iter() if x.tag.endswith("div")][:40],
    }


def edmonds_inventory(root: ET.Element) -> dict:
    """Inventory loci and note counts without exporting restricted Greek text."""
    requested = {"tlg-0255": "Mimnermus", "tlg-0263": "Solon", "tlg-0002": "Theognidean anthology"}
    result = {}
    for section in root.iter("div1"):
        author = requested.get(section.get("id", ""))
        if not author:
            continue
        fragment_units = [node for node in section.iter("div4") if node.get("n")]
        elegy_units = [node for node in section.iter("lg") if node.get("type") == "elegy"]
        result[author] = {
            "source_textgroup_id": section.get("id"),
            "source_heading_beta_code": "".join(section.find("head").itertext()).strip(),
            "numbered_fragment_units": len(fragment_units),
            "fragment_loci": [
                {"fragment_label": node.get("n"), "meter_or_form": node.get("type"),
                 "ancient_source_bibl": " ".join("".join(bibl.itertext()).split())
                 if (bibl := node.find("cit/bibl")) is not None else None}
                for node in fragment_units
            ],
            "numbered_elegy_units": len(elegy_units),
            "elegy_loci": ["".join(node.find("head").itertext()).strip()
                             for node in elegy_units if node.find("head") is not None],
            "note_elements": sum(1 for _ in section.iter("note")),
            "greek_line_elements_including_quoters_and_biodata": sum(1 for _ in section.iter("l")),
            "scope_warning": "Line count includes quoted testimonia; do not equate with authored verse.",
        }
    return result


def inspect_verse(raw: str) -> dict:
    headings = list(BOOK.finditer(raw))
    if len(headings) != 2:
        raise RuntimeError(f"Expected two source book headings, found {len(headings)}")
    diagnostics = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else raw.find("[[Κατηγορία:", heading.end())
        if end < 0:
            raise RuntimeError("Could not find end of Wikisource verse text")
        body = raw[heading.end():end]
        candidates = body.split("<br>")
        verses = []
        marker_mismatches = []
        last_number = 0 if index == 0 else 1230
        for candidate in candidates:
            markers = [int(x) for x in MARKER.findall(candidate)]
            clean = MARKER.sub("", candidate).strip()
            if not GREEK.search(clean):
                continue
            verses.append(clean)
            number = last_number + len(verses)
            if markers and markers != [number]:
                marker_mismatches.append({"expected": number, "markers": markers, "text": clean[:100]})
        diagnostics[heading.group(1)] = {
            "candidate_breaks": len(candidates), "verse_lines": len(verses),
            "marker_mismatch_count": len(marker_mismatches),
            "marker_mismatch_samples": marker_mismatches[:10],
            "first": verses[0] if verses else "", "last": verses[-1] if verses else "",
        }
    return diagnostics


def wikisource_blocks(raw: str, page: dict, path: Path, digest: str, api_url: str) -> list[dict]:
    """Extract source verse blocks; do not silently infer printed line numbers."""
    headings = list(BOOK.finditer(raw))
    if len(headings) != 2:
        raise RuntimeError("Expected books Α and Β in saved Wikisource revision")
    revision = page["revisions"][0]["revid"]
    page_url = "https://el.wikisource.org/w/index.php?" + urllib.parse.urlencode(
        {"title": TITLE, "oldid": revision}
    )
    records = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else raw.find("[[Κατηγορία:", heading.end())
        if end < 0:
            raise RuntimeError("Could not find end of source verse")
        for block_number, block in enumerate(re.split(r"\n\s*\n", raw[heading.end():end]), 1):
            verses = []
            markers = []
            for candidate in block.split("<br>"):
                found = [int(x) for x in MARKER.findall(candidate)]
                clean = MARKER.sub("", candidate).strip()
                if not clean:
                    continue
                if not GREEK.search(clean):
                    raise RuntimeError(f"Unexpected non-Greek in Book {heading.group(1)} block {block_number}: {clean[:80]}")
                verses.append(clean)
                if found:
                    markers.append({"verse_index": len(verses), "printed_marker": found})
            if not verses:
                continue
            text = "\n".join(verses)
            if re.search(r"<[^>]+>|\{\{|\[\[", text):
                raise RuntimeError(f"Unparsed markup in Book {heading.group(1)} block {block_number}")
            records.append({
                "id": f"p2_elegy:wikisource:{page['pageid']}:{revision}:{heading.group(1)}:{block_number}",
                "source": "p2_elegy", "source_url": page_url,
                "raw_path": path.relative_to(ROOT).as_posix(), "raw_sha256": digest,
                "author": "Theognidean anthology", "work": TITLE,
                "edition": "unspecified by Wikisource source page",
                "citation": f"Book {heading.group(1)}, source block {block_number}",
                "language": "grc", "text": text, "kind": "text",
                "quality": "source_text", "license": "CC BY-SA 4.0",
                "metadata": {"source_family": "Greek Wikisource Theognidean anthology",
                             "revision_id": revision, "api_fetch_url": api_url,
                             "revision_api_url": API + "?" + urllib.parse.urlencode(
                                 {"action": "query", "format": "json", "prop": "revisions",
                                  "revids": revision, "rvprop": "ids|content", "rvslots": "main"}),
                             "authorship_scope": "composite anthology, not individually attributed to Theognis",
                             "printed_line_markers": markers,
                             "locator_caveat": "Source markers drift from verse counts; block order is stable, inferred line numbers withheld"},
            })
    return records


def normalized_greek(text: str) -> str:
    return re.sub(r"[^\u0370-\u03ff\u1f00-\u1fff]+", "", unicodedata.normalize("NFC", text)).casefold()


def compare_existing(records: list[dict]) -> dict:
    existing = set()
    for name in ("ogc", "lyric_web", "perseus"):
        path = ROOT / f"data/processed/{name}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if item.get("language") != "grc" or item.get("kind") != "text":
                    continue
                for verse in item.get("text", "").splitlines():
                    key = normalized_greek(verse)
                    if key:
                        existing.add(key)
    total = 0
    overlap = 0
    for record in records:
        for verse in record["text"].splitlines():
            total += 1
            overlap += normalized_greek(verse) in existing
    return {"verse_lines": total, "exact_normalized_overlap_lines": overlap,
            "comparison_sources": ["ogc", "lyric_web", "perseus"],
            "interpretation": "line-string overlap only; different source records are not new independent poems"}


def prior_target_coverage() -> dict:
    report_path = ROOT / "data/reports/ogc.json"
    if not report_path.exists():
        return {}
    files = json.loads(report_path.read_text(encoding="utf-8")).get("files", [])
    output = {}
    for author in ("archilochus", "hipponax", "semonides", "solon", "mimnermus", "theognis"):
        output[author] = [{"source_path": row["path"], "records": row["records"]}
                          for row in files if row["path"].split("/")[-1].startswith(author)]
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true", help="print a short raw wikitext sample")
    parser.add_argument("--inspect-perseus", action="store_true", help="inspect restricted local TEI structure")
    args = parser.parse_args()
    if args.inspect_perseus:
        root, path, digest = retrieve_perseus()
        print(json.dumps({"source_url": PERSEUS_URL, "path": str(path.relative_to(ROOT)),
                          "sha256": digest, "diagnostics": inspect_perseus(root)},
                         ensure_ascii=False, indent=2))
        return
    page, path, digest, url = retrieve_wikisource()
    raw = page["revisions"][0]["slots"]["main"]["*"]
    if args.inspect:
        print(json.dumps({"pageid": page["pageid"], "revid": page["revisions"][0]["revid"],
                          "path": str(path.relative_to(ROOT)), "sha256": digest,
                          "source_url": url, "diagnostics": inspect_verse(raw)},
                         ensure_ascii=False, indent=2))
        return
    records = wikisource_blocks(raw, page, path, digest, url)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records), encoding="utf-8")
    edmonds_path = RAW / "edmonds_elegy_iambus_v1_2008.01.0477.xml"
    edmonds_root = ET.parse(edmonds_path).getroot() if edmonds_path.exists() else None
    report = {
        "status": "staged_pending_independent_text_audit",
        "source": "Greek Wikisource revision-pinned Theognidean anthology",
        "source_url": records[0]["source_url"], "api_fetch_url": url,
        "rights_url": "https://el.wikisource.org/wiki/Βικιθήκη:Πνευματικά_δικαιώματα",
        "raw_path": path.relative_to(ROOT).as_posix(), "raw_sha256": digest,
        "processed_path": OUT.relative_to(ROOT).as_posix(), "processed_sha256": sha256(OUT.read_bytes()),
        "records": len(records), "by_quality": dict(Counter(x["quality"] for x in records)),
        "by_author": dict(Counter(x["author"] for x in records)),
        "source_diagnostics": inspect_verse(raw), "existing_overlap": compare_existing(records),
        "prior_ogc_target_coverage": prior_target_coverage(),
        "new_target_coverage": {"Archilochus": 0, "Hipponax": 0, "Semonides": 0,
                                "Solon": 0, "Mimnermus": 0,
                                "Theognidean anthology": len(records)},
        "caveats": ["No printed edition is identified on the source page.",
                    "Theognidean anthology is composite; individual authorship is not asserted.",
                    "Printed line markers drift from simple verse sequence; source block order is the citation key.",
                    "One source is one witness; count of blocks or verses is not count of independent poems."],
        "perseus_edmonds_local_research": {
            "source_url": PERSEUS_URL,
            "raw_path": "data/raw/p2_elegy/edmonds_elegy_iambus_v1_2008.01.0477.xml",
            "raw_sha256": sha256(edmonds_path.read_bytes()) if edmonds_path.exists() else None,
            "scope": "Mimnermus, Solon, Theognis with Greek critical loci and source citations",
            "local_only": True, "processed": False,
            "metadata_inventory": edmonds_inventory(edmonds_root) if edmonds_root is not None else None,
            "rights": "TEI availability permits noncommercial distribution with Perseus credit, intact notice, and offer of modifications to Perseus; Hopper CC banner conflicts. Do not publicly export pending clarification.",
            "volume_ii_failure": "Greek TEI endpoint returned 503; Archilochus, Semonides, Hipponax not ingested from Edmonds."
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "lines": report["existing_overlap"]["verse_lines"],
                      "overlap": report["existing_overlap"]["exact_normalized_overlap_lines"]}))


if __name__ == "__main__":
    main()
