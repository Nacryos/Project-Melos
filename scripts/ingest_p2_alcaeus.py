"""Stage Alcaeus lyric fragments from a pinned Greek Wikisource revision.

The source page says that its text follows J. M. Edmonds, Lyra Graeca I
(1922), with fragments reordered after Bergk. MediaWiki's parse API expands
the page's transcluded subpages; both the revision response and expanded HTML
are saved as raw evidence. Modern Greek translations are excluded by selecting
only the first verse block under each numbered fragment heading.

Usage: python scripts/ingest_p2_alcaeus.py [--refresh]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_alcaeus"
OUT = ROOT / "data/processed/p2_alcaeus.jsonl"
REPORT = ROOT / "data/reports/p2_alcaeus.json"
API = "https://el.wikisource.org/w/api.php"
TITLE = "Επιγράμματα Αλκαίου του Μυτιληναίου"
PAGE_URL = "https://el.wikisource.org/wiki/" + quote(TITLE.replace(" ", "_"))
USER_AGENT = "MelosCorpus/0.1 (source-cited research; polite cached Wikimedia API client)"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
FRAGMENT = re.compile(r"^(?:Επίγραμμα\s+([0-9]+[AB]?))|(?:Edmonds\s+([0-9]+))$", re.I)
# Edmonds I, p. 390 n. 1 explicitly raises the comic poet Alcaeus as an
# alternative author for his no. 114 (Wikisource main heading 146).
WITHHELD_AMBIGUOUS_MAIN = {"146"}
SCAN_SAMPLE_PAGES = (316, 318, 320, 322, 350, 390)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(session: requests.Session, name: str, params: dict, refresh: bool) -> bytes:
    path = RAW / name
    if path.exists() and not refresh:
        return path.read_bytes()
    response = None
    for attempt in range(3):
        try:
            response = session.get(API, params=params, timeout=35)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty response")
            payload = response.json()
            if "error" in payload:
                raise ValueError(payload["error"])
            RAW.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            time.sleep(0.4)
            return response.content
        except (requests.RequestException, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(f"DOWNLOAD FAILED {API}: {exc}") from exc
            retry = response.headers.get("Retry-After", "") if response else ""
            time.sleep(min(float(retry), 30) if retry.isdigit() else 2 * (attempt + 1))
    raise AssertionError("unreachable")


def clean_line(value: str) -> str:
    return re.sub(r"[\t \u00a0]+", " ", value).strip()


def is_editorial_heading(value: str) -> bool:
    # Short Greek headings in source verse blocks are labels, not Alcaeus's verse.
    value = re.sub(r"^\[\s*|\s*\]$", "", value).strip()
    return bool(re.fullmatch(r"(?i)(?:εἰς|Εις|πρὸς)\s+\S+(?:\s+\S+){0,2}", value))


def is_dd_heading(dd: Tag) -> bool:
    value = clean_line(dd.get_text(" ", strip=True))
    # The source marks editorial addressee/topic labels in bold, including
    # bracketed labels. All other <dd> lines are retained as supplied.
    return bool(dd.find("b") and len(value) < 60 and is_editorial_heading(value))


def remove_counter_spans(node: Tag) -> None:
    for span in node.select("span[id]"):
        if (span.select_one("a.mw-selflink-fragment")
                and re.fullmatch(r"\[\d+\]", span.get_text(strip=True))):
            span.decompose()


def retain_lacuna_lines(lines: list[str]) -> list[str]:
    """Keep internal ellipsis-only lines so source gaps remain visible."""
    useful = [x for x in lines if x and (GREEK.search(x) or re.fullmatch(r"[.·… ]+", x))]
    while useful and not GREEK.search(useful[0]):
        useful.pop(0)
    while useful and not GREEK.search(useful[-1]):
        useful.pop()
    return useful


def poem_lines(block: Tag) -> list[str]:
    clone = BeautifulSoup(str(block), "html.parser")
    remove_counter_spans(clone)
    for node in clone.select("sup.reference, span.mw-editsection"):
        node.decompose()
    for br in clone.find_all("br"):
        br.replace_with(NavigableString("\n"))
    raw_lines = [clean_line(x) for x in clone.get_text().split("\n")]
    return retain_lacuna_lines([x for x in raw_lines if not is_editorial_heading(x)])


def dl_lines(block: Tag) -> list[str]:
    result = []
    for dd in block.find_all("dd"):
        if is_dd_heading(dd):
            continue
        clone = BeautifulSoup(str(dd), "html.parser")
        remove_counter_spans(clone)
        value = clean_line(clone.get_text(" ", strip=True))
        if value and not is_editorial_heading(value):
            result.append(value)
    return retain_lacuna_lines(result)


def block_lines(block: Tag) -> list[str]:
    if block.name == "dl":
        return dl_lines(block)
    if block.name == "div" and "poem" in block.get("class", []):
        return poem_lines(block)
    return []


def edition_comments(wikitext: str) -> dict[str, str]:
    """Read Wikisource's own heading comments, often Edmonds numbers."""
    result = {}
    for heading, comment in re.findall(r"(?m)^===(.*?)===\s*<!--(.*?)-->", wikitext):
        visible = heading.rsplit("|", 1)[-1].replace("]]", "").strip()
        match = re.fullmatch(r"Επίγραμμα\s+([0-9]+[AB]?)", visible)
        if match:
            result[match.group(1)] = comment.strip()
    return result


def parse_fragments(expanded_html: str) -> tuple[list[dict], list[dict]]:
    soup = BeautifulSoup(expanded_html, "html.parser")
    body = soup.select_one(".mw-parser-output")
    if body is None:
        raise ValueError("MediaWiki parser output missing")
    records = []
    skipped = []
    children = [x for x in body.children if isinstance(x, Tag)]
    for index, child in enumerate(children):
        heading = child.select_one("h3") if "mw-heading3" in child.get("class", []) else None
        if heading is None:
            continue
        label = clean_line(heading.get_text(" ", strip=True))
        match = FRAGMENT.fullmatch(label)
        if not match:
            continue
        series, number = ("Bergk-order", match.group(1)) if match.group(1) else ("Edmonds-additional", match.group(2))
        blocks = []
        for following in children[index + 1:]:
            if any(x.startswith("mw-heading") for x in following.get("class", [])):
                break
            if following.name == "dl" or (following.name == "div" and "poem" in following.get("class", [])):
                lines = block_lines(following)
                if lines:
                    blocks.append((following, lines))
        if not blocks:
            skipped.append({"heading": label, "reason": "no Greek verse block"})
            continue
        # Multiple <dl> blocks under one heading are independent quotations
        # (main 26 has two); a subsequent <div class=poem> is a translation.
        chosen = blocks if len(blocks) > 1 and all(block.name == "dl" for block, _ in blocks) else blocks[:1]
        for part, (selected_block, selected_lines) in enumerate(chosen, 1):
            text = "\n".join(selected_lines)
            if not GREEK.search(text):
                skipped.append({"heading": label, "reason": "no Greek text"})
                continue
            # Preserve all editorial punctuation and uncertain letters. A
            # suspicious glyph remains visible but is flagged for review.
            quality = "needs_review" if ("�" in text or "~" in text or "['" in text
                                         or re.search(r"\w\?\w", text)) else "source_text"
            records.append({
                "series": series,
                "number": number,
                "part": part if len(chosen) > 1 else None,
                "heading": label,
                "lines": selected_lines,
                "text": text,
                "quality": quality,
                "source_block": selected_block.name + (".poem" if "poem" in selected_block.get("class", []) else ""),
                "candidate_blocks": len(blocks),
                "editorial_labels": [clean_line(dd.get_text(" ", strip=True))
                                     for dd in selected_block.find_all("dd") if is_dd_heading(dd)]
                                    if selected_block.name == "dl" else [],
                "source_line_counters": [span.get_text(strip=True)
                                         for span in selected_block.select("span[id]")
                                         if span.select_one("a.mw-selflink-fragment")
                                         and re.fullmatch(r"\[\d+\]", span.get_text(strip=True))],
            })
    if not records:
        raise ValueError("No numbered Alcaeus fragments parsed")
    return records, skipped


def existing_alcaeus_texts() -> set[str]:
    found = set()
    for file in (ROOT / "data/processed").glob("*.jsonl"):
        if file == OUT:
            continue
        for line in file.open(encoding="utf-8"):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if (record.get("language") == "grc" and record.get("kind") == "text"
                    and re.search(r"(?i)alcaeus|αλκαῖος|αλκαίος", str(record.get("author", "")))):
                found.add(re.sub(r"\s+", "", record.get("text", "")))
    return found


def scan_samples(session: requests.Session, refresh: bool) -> list[dict]:
    """Retain IA image witnesses at page numbers checked during source audit.

    The earlier Lyra collector's scan index supplies the exact IIIF URLs and
    physical leaf mapping; the Alcaeus collector saves its own image copies.
    """
    index = ROOT / "data/processed/lyra.jsonl"
    if not index.exists():
        raise FileNotFoundError("Lyra scan index required for edition comparison")
    candidates = {}
    for line in index.open(encoding="utf-8"):
        record = json.loads(line)
        metadata = record.get("metadata", {})
        if metadata.get("archive_item") != "lyragraecabeingr01edmouoft":
            continue
        page = metadata.get("printed_page")
        if page is not None and str(page).isdigit() and int(page) in SCAN_SAMPLE_PAGES:
            candidates[int(page)] = metadata
    if set(candidates) != set(SCAN_SAMPLE_PAGES):
        raise ValueError("Lyra scan index lacks a required Alcaeus sample page")
    saved = []
    for page in SCAN_SAMPLE_PAGES:
        metadata = candidates[page]
        url = metadata["page_image_url"].replace("/full/max/", "/full/1400,/")
        path = RAW / f"edmonds_p{page}.jpg"
        if path.exists() and not refresh:
            data = path.read_bytes()
        else:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            if not response.content or not response.headers.get("Content-Type", "").startswith("image/"):
                raise ValueError(f"Scan page {page} did not return an image")
            RAW.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            data = response.content
            time.sleep(0.4)
        saved.append({
            "printed_page": page,
            "scan_leaf": metadata["scan_leaf"],
            "source_url": url,
            "raw_path": path.relative_to(ROOT).as_posix(),
            "raw_sha256": sha256(data),
        })
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    query = fetch(session, "source_revision.json", {
        "action": "query", "format": "json", "titles": TITLE,
        "prop": "revisions", "rvprop": "ids|timestamp|content", "rvslots": "main",
    }, args.refresh)
    page = next(iter(json.loads(query)["query"]["pages"].values()))
    if "missing" in page or page.get("title") != TITLE:
        raise ValueError("Unexpected or missing Wikisource source page")
    revision = page["revisions"][0]
    wikitext = revision["slots"]["main"]["*"]
    if ("John Maxwell Edmonds (1922)" not in wikitext
            or "Poetae lyrici Graeci" not in wikitext
            or "Αλκαίος ο Μυτιληναίος" not in wikitext):
        raise ValueError("Source edition/author statement changed; review before ingest")
    revid = revision["revid"]
    parsed = fetch(session, f"expanded_{revid}.json", {
        "action": "parse", "format": "json", "oldid": revid, "prop": "text|revid",
    }, args.refresh)
    response = json.loads(parsed)["parse"]
    if response["revid"] != revid:
        raise ValueError("Expanded page revision differs from pinned source revision")
    fragments, skipped = parse_fragments(response["text"]["*"])
    comments = edition_comments(wikitext)
    withheld = [fragment for fragment in fragments
                if fragment["series"] == "Bergk-order"
                and fragment["number"] in WITHHELD_AMBIGUOUS_MAIN]
    fragments = [fragment for fragment in fragments if fragment not in withheld]
    source_url = f"https://el.wikisource.org/w/index.php?title={quote(TITLE.replace(' ', '_'))}&oldid={revid}"
    raw_path = f"data/raw/p2_alcaeus/expanded_{revid}.json"
    edition_images = scan_samples(session, args.refresh)
    previous = existing_alcaeus_texts()
    output = []
    for fragment in fragments:
        number = fragment["number"]
        series = fragment["series"]
        part = fragment["part"]
        source_comment = comments.get(number, "") if series == "Bergk-order" else ""
        edmonds_number = number if series == "Edmonds-additional" else ""
        if source_comment:
            pieces = [x.strip() for x in re.sub(r"^JME\s*", "", source_comment).split(",")]
            if part is not None and len(pieces) == 2:
                edmonds_number = pieces[part - 1]
            elif len(pieces) == 1 and re.fullmatch(r"\d+[A-Za-z]?", pieces[0]):
                edmonds_number = pieces[0]
        lines = [{"label": str(i), "text": line} for i, line in enumerate(fragment["lines"], 1)]
        output.append({
            "id": f"p2_alcaeus:elws:{page['pageid']}:{revid}:{series}:{number}"
                  + (f":part:{part}" if part is not None else ""),
            "source": "p2_alcaeus",
            "source_url": source_url,
            "raw_path": raw_path,
            "raw_sha256": sha256(parsed),
            "author": "Alcaeus of Mytilene",
            "work": "Lyric fragments",
            "edition": "J. M. Edmonds, Lyra Graeca, vol. I (1922); Greek Wikisource transcription",
            "citation": f"Wikisource {'main' if series == 'Bergk-order' else 'additional'} fragment {number}"
                        + (f", part {part}" if part is not None else "")
                        + (f"; Edmonds {edmonds_number}" if edmonds_number else ""),
            "language": "grc",
            "text": fragment["text"],
            "kind": "text",
            "quality": fragment["quality"],
            "license": "CC BY-SA 4.0 (Wikisource transcription; Edmonds 1922 public domain US)",
            "lines": lines,
            "metadata": {
                "source_page_url": PAGE_URL,
                "source_revision_id": revid,
                "source_revision_timestamp": revision["timestamp"],
                "source_revision_raw_path": "data/raw/p2_alcaeus/source_revision.json",
                "source_revision_raw_sha256": sha256(query),
                "fragment_heading": fragment["heading"],
                "numbering": "Wikisource page labels, Bergk ordering for main series",
                "source_block": fragment["source_block"],
                "candidate_blocks_in_section": fragment["candidate_blocks"],
                "editorial_labels_excluded": fragment["editorial_labels"],
                "source_line_counters_excluded": fragment["source_line_counters"],
                "edmonds_cross_reference_comment": source_comment,
                "edmonds_fragment_number": edmonds_number or None,
                "perseus_edition_urn": "urn:cts:greekLit:tlg0383.tlg001.opp-grc7",
                "perseus_edition_catalog_url": "https://catalog.perseus.org/catalog/urn%3Acts%3AgreekLit%3Atlg0383.tlg001.opp-grc7",
            },
        })
    ids = [record["id"] for record in output]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate fragment IDs")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in output), encoding="utf-8")
    report = {
        "source_page": PAGE_URL,
        "source_revision": revid,
        "source_revision_timestamp": revision["timestamp"],
        "source_edition": "J. M. Edmonds, Lyra Graeca, vol. I (1922)",
        "source_order": "Bergk order for main Wikisource series",
        "raw_files": [
            {"path": "data/raw/p2_alcaeus/source_revision.json", "sha256": sha256(query)},
            {"path": raw_path, "sha256": sha256(parsed)},
        ],
        "edition_scan_samples": edition_images,
        "visual_comparison": [
            {"printed_page": 318, "wiksource_heading": "Επίγραμμα 1", "finding": "Greek opening corresponds to Edmonds 1"},
            {"printed_page": 320, "wiksource_heading": "Επίγραμμα 5", "finding": "Four Greek lines correspond to Edmonds 2-5"},
            {"printed_page": 350, "wiksource_heading": "Επίγραμμα 21", "finding": "Melanchrus line corresponds to Edmonds 47"},
            {"printed_page": 390, "wiksource_heading": "Επίγραμμα 146", "finding": "Edmonds 114 is withheld for ambiguous lyric/comic Alcaeus attribution"},
        ],
        "counts": {
            "records": len(output),
            "series": dict(Counter(fragment["series"] for fragment in fragments)),
            "quality": dict(Counter(record["quality"] for record in output)),
            "duplicate_exact_text_against_existing_alcaeus": sum(
                re.sub(r"\s+", "", record["text"]) in previous for record in output
            ),
            "sections_without_verse": len(skipped),
            "withheld_ambiguous_attribution": len(withheld),
        },
        "sections_without_verse": skipped,
        "withheld_ambiguous": [{"heading": fragment["heading"], "reason":
            "Edmonds I, p. 390 n. 1: 'perh. the comic poet Alcaeus (Mein.)'"}
            for fragment in withheld],
        "method": "MediaWiki API source revision plus pinned expanded HTML; first Greek verse block per numbered heading",
        "caveat": "Edition text preserves editorial supplements. Wikisource transcriptions may contain errors; malformed text is flagged needs_review. No translations included.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
