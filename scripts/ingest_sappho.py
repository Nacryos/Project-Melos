"""Collect the linked Digital Sappho and Dickinson Sappho editions.

Usage: python scripts/ingest_sappho.py [--refresh]
Only URLs present in the downloaded source navigation are followed. Raw HTML and
the two rights pages are retained so every output record can be rechecked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/sappho"
OUTPUT = ROOT / "data/processed/sappho.jsonl"
REPORT = ROOT / "data/reports/sappho.json"
DIGITAL_HOME = "https://digitalsappho.org/"
DCC_SEED = "https://dcc.dickinson.edu/sappho/frag-1"
DCC_TERMS = "https://dcc.dickinson.edu/terms-use"
HEADERS = {"User-Agent": "MelosCorpusResearch/0.1 (educational source citation; polite cached fetch)"}


def clean(value: str) -> str:
    return re.sub(r"[\t \u00a0]+", " ", value).strip()


def get_text(tag: Tag) -> str:
    return clean(tag.get_text(" ", strip=True))


def verse_text(tag: Tag) -> str:
    """Read a verse container after removing WordPress controls and footnotes."""
    copy = soup_from(str(tag))
    for node in copy.select(".para_marker, .commenticonbox, .captioned_image, "
                            ".wp-caption, .mceTemp, fn, .footnote"):
        node.decompose()
    return clean(copy.get_text(" ", strip=True))


def has_greek(value: str) -> bool:
    return bool(re.search(r"[\u0370-\u03ff\u1f00-\u1fff]", value))


def is_editorial_prose(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]{4,}", value))


def meaningful(value: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u0370-\u03ff\u1f00-\u1fff]", value))


def source_line(value: str) -> bool:
    return has_greek(value) or bool(re.search(r"[\[\]⟨⟩…*]", value))


def placeholder(value: str) -> bool:
    return bool(re.fullmatch(
        r"(?is)(?:\[insert [^]]+\]|test|translation goes here|placeholder|coming soon)\.?",
        value.strip(),
    ))


def printed_line_label(value: str) -> str:
    match = re.match(r"^(\d+)\s*\.", value)
    return match.group(1) if match else ""


def mark_dialogue_attribution(record: dict) -> None:
    speakers = []
    for line in record.get("lines", []):
        match = re.match(r"^\(([^)]+)\)\s+", line["text"])
        if match and has_greek(match.group(1)):
            speakers.append(match.group(1))
    speakers = list(dict.fromkeys(speakers))
    if len(speakers) > 1:
        record.setdefault("metadata", {})["speaker_labels"] = speakers
        if record["citation"] == "137":
            # The downloaded Digital Sappho vocabulary for 137 explicitly calls
            # the Alcaeus/Sappho speaker identification spurious.
            record["quality"] = "mixed_content"
            record["author"] = "uncertain"
            record["metadata"]["attribution_note"] = (
                "The source commentary calls the Alcaeus/Sappho speaker identification spurious."
            )
            record["metadata"]["attribution_note_source_url"] = (
                "https://digitalsappho.org/fragments/fr118-168/"
            )


def is_fragment_heading(value: str) -> bool:
    return bool(re.fullmatch(
        r"(?i)(?:fragment\s+)?\d+[a-zΑ-Ωα-ω]?(?:\s+\d+[a-zΑ-Ωα-ω]?)*",
        value,
    ))


def raw_file(url: str) -> Path:
    parsed = urlparse(url)
    slug = (parsed.netloc + parsed.path).strip("/").replace("/", "__")
    slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", slug)
    return RAW / (slug + ".html")


def fetch(session: requests.Session, url: str, refresh: bool) -> tuple[Path, bytes]:
    path = raw_file(url)
    if path.exists() and not refresh:
        return path, path.read_bytes()
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty HTTP response")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            time.sleep(0.35)
            return path, response.content
        except (requests.RequestException, ValueError) as error:
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DOWNLOAD FAILED {url}: {last_error}")


def soup_from(data: bytes) -> BeautifulSoup:
    return BeautifulSoup(data, "html.parser")


def discover_digital(soup: BeautifulSoup) -> list[str]:
    links = []
    for anchor in soup.select("#toc_sidebar a[href]"):
        url = urljoin(DIGITAL_HOME, anchor["href"]).split("#", 1)[0]
        parsed = urlparse(url)
        if (parsed.netloc == "digitalsappho.org"
                and parsed.path.startswith("/fragments/")
                and parsed.path.rstrip("/") != "/fragments"):
            links.append(url)
    return list(dict.fromkeys(links))


def discover_dcc(soup: BeautifulSoup) -> list[str]:
    links = []
    for anchor in soup.select("a[href]"):
        url = urljoin(DCC_SEED, anchor["href"]).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.netloc == "dcc.dickinson.edu" and re.fullmatch(
            r"/sappho/(?:frag-[0-9][0-9a-z-]*|brothers-poem)", parsed.path
        ):
            links.append(url)
    return list(dict.fromkeys(links))


def base_record(url: str, path: Path, data: bytes, record_id: str, edition: str,
                citation: str, kind: str, text: str, language: str,
                license_name: str, metadata: dict | None = None) -> dict:
    record = {
        "id": record_id,
        "source": "sappho",
        "source_url": url,
        "raw_path": path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "author": "Sappho" if kind == "text" else ("Heather Waddell" if edition == "Dickinson College Commentaries" else "The Digital Sappho"),
        "work": "Fragments",
        "edition": edition,
        "citation": citation,
        "language": language,
        "text": text,
        "kind": kind,
        "quality": "source_text",
        "license": license_name,
    }
    if metadata:
        record["metadata"] = metadata
    return record


def digital_passages(soup: BeautifulSoup) -> list[tuple[str, list[dict]]]:
    post = soup.select_one("div.post")
    if post is None:
        return []
    title_tag = post.select_one(".post_title")
    title = get_text(title_tag) if title_tag else "Untitled"
    passages: list[tuple[str, list[dict]]] = []
    # Group pages use explicit h4 fragment labels followed by Greek divs.
    grouped: list[tuple[str, list[dict]]] = []
    current_label = title
    current_lines: list[dict] = []
    saw_subheading = False
    for child in post.find_all(recursive=False):
        if child.name == "h4" and re.fullmatch(r"\d+[a-zA-ZΑ-Ωα-ω]?", get_text(child)):
            if current_label and current_lines:
                grouped.append((current_label, current_lines))
            current_label = get_text(child)
            current_lines = []
            saw_subheading = True
        elif current_label and child.get("lang") == "grc":
            value = verse_text(child)
            if value and source_line(value) and not is_editorial_prose(value):
                current_lines.append({"label": printed_line_label(value), "text": value})
    if current_label and current_lines:
        grouped.append((current_label, current_lines))
    if saw_subheading and grouped:
        return grouped
    combined_lines = []
    for block in post.select("[lang='grc']"):
        if block.find_parent(attrs={"lang": "grc"}) is not None:
            continue
        if block.name == "ol":
            start = int(block.get("start", 1))
            lines = [{"label": str(start + i), "text": verse_text(li)}
                     for i, li in enumerate(block.find_all("li", recursive=False))
                     if verse_text(li) and source_line(verse_text(li))
                     and not is_editorial_prose(verse_text(li))]
        else:
            lines = [{"label": printed_line_label(verse_text(item)), "text": verse_text(item)}
                     for i, item in enumerate(block.find_all(["p", "div"], recursive=False), 1)
                     if verse_text(item) and source_line(verse_text(item))
                     and not is_editorial_prose(verse_text(item))]
            value = verse_text(block)
            if not lines and value and source_line(value) and not is_editorial_prose(value):
                lines = [{"label": printed_line_label(value), "text": value}]
        combined_lines.extend(lines)
    if combined_lines:
        passages.append((title, combined_lines))
    return passages


def digital_records(url: str, path: Path, data: bytes) -> list[dict]:
    soup = soup_from(data)
    slug = urlparse(url).path.strip("/").split("/")[-1]
    records = []
    passages = digital_passages(soup)
    for i, (citation, lines) in enumerate(passages, 1):
        record_id = f"digital-sappho:{slug}:{i}"
        record = base_record(url, path, data, record_id, "The Digital Sappho",
                             citation, "text", "\n".join(line["text"] for line in lines),
                             "grc", "CC BY-SA 4.0", {"source_collection": "The Digital Sappho"})
        record["lines"] = lines
        mark_dialogue_attribution(record)
        records.append(record)
    if not records:
        return records
    parent = records[0]["id"]
    page_title = get_text(soup.select_one("div.post .post_title"))
    grouped_page = len(passages) > 1
    passage_map = {re.sub(r"\s+", "", item["citation"]).casefold(): item
                   for item in records if item["kind"] == "text"}
    post = soup.select_one("div.post")
    editorial = []
    if post:
        for block in post.select("[lang='grc']"):
            if block.find_parent(attrs={"lang": "grc"}) is not None:
                continue
            for candidate in ([block] if not block.find(["p", "div"], recursive=False)
                              else block.find_all(["p", "div"], recursive=False)):
                value = verse_text(candidate)
                if value and is_editorial_prose(value):
                    editorial.append(value)
    if editorial:
        for notice in editorial:
            if "different poems" in notice.casefold():
                records[0]["quality"] = "mixed_content"
                records[0].setdefault("metadata", {})["source_group_description"] = notice
        item = base_record(url, path, data, f"digital-sappho:{slug}:editorial",
                           "The Digital Sappho", page_title if grouped_page else records[0]["citation"],
                           "commentary", "\n".join(dict.fromkeys(editorial)), "eng",
                           "CC BY-SA 4.0", {"subtype": "editorial_notice",
                                            "scope": "page" if grouped_page else "passage"})
        if not grouped_page:
            item["parent_id"] = parent
        records.append(item)
    # The Comments sidebar contains meter, sources and bibliography. The Activity
    # sidebar contains a line-indexed vocabulary/commentary table where present.
    for selector, subtype in (("#comments_sidebar .comments_container", "notes"),
                              ("#activity_sidebar .comments_container", "vocabulary")):
        node = soup.select_one(selector)
        if node is None:
            continue
        for removable in node.select("#respond_wrapper, #respond, .cancel-comment-reply"):
            removable.decompose()
        if subtype == "vocabulary":
            rows = node.select("table tr")
            active_parent = None if grouped_page else records[0]
            for j, row in enumerate(rows, 1):
                value = get_text(row)
                if not value or not meaningful(value) or placeholder(value):
                    continue
                label = get_text(row.find("td")) if row.find("td") else ""
                if grouped_page:
                    matched = passage_map.get(re.sub(r"\s+", "", label).casefold())
                    if matched:
                        active_parent = matched
                if re.fullmatch(r"\d+[a-zA-ZΑ-Ωα-ω]?", value):
                    continue
                item = base_record(url, path, data, f"digital-sappho:{slug}:vocab:{j}",
                                   "The Digital Sappho",
                                   active_parent["citation"] if active_parent else page_title,
                                   "commentary", value, "eng", "CC BY-SA 4.0",
                                   {"subtype": "vocabulary", "line_label": label,
                                    "scope": "passage" if active_parent else "page"})
                if active_parent:
                    item["parent_id"] = active_parent["id"]
                records.append(item)
            # Other explanatory prose may precede or follow the table.
            for table in node.select("table"):
                table.decompose()
            for anchor in node.select("a[href$='.pdf']"):
                anchor.decompose()
        value = get_text(node)
        if value and value != "Download" and meaningful(value) and not placeholder(value):
            item = base_record(url, path, data, f"digital-sappho:{slug}:{subtype}",
                               "The Digital Sappho",
                               page_title if grouped_page else records[0]["citation"],
                               "commentary", value, "eng", "CC BY-SA 4.0",
                               {"subtype": subtype,
                                "scope": "page" if grouped_page else "passage"})
            if not grouped_page:
                item["parent_id"] = parent
            records.append(item)
    author_tag = soup.select_one("div.post cite.fn")
    if author_tag:
        for item in records:
            if item["kind"] != "text":
                item["author"] = get_text(author_tag)
    return records


def dcc_records(url: str, path: Path, data: bytes) -> list[dict]:
    soup = soup_from(data)
    article = soup.select_one("article.article-sappho")
    if article is None:
        return []
    heading = soup.select_one("h1.page-header, h1.page-title, article h1")
    citation = get_text(heading) if heading else urlparse(url).path.rsplit("/", 1)[-1]
    body = article.select_one(".field--name-body")
    if body is None:
        return []
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    nodes = [node for node in body.find_all(recursive=False)
             if node.name in {"h4", "p"} or
             (node.name == "div" and node.get("lang") == "grc")]
    h4_labels = [get_text(node) for node in nodes if node.name == "h4"
                 and is_fragment_heading(get_text(node))]
    bare_labels = [get_text(node) for node in nodes if node.name == "p"
                   and is_fragment_heading(get_text(node))]
    grouped = bool(h4_labels) or bool(bare_labels)
    passages: list[tuple[str, list[dict], list[str]]] = []
    current_citation = citation
    lines: list[dict] = []
    editorial: list[str] = []

    def flush() -> None:
        nonlocal lines, editorial
        if lines:
            passages.append((current_citation, lines, editorial))
        lines = []
        editorial = []

    for node in nodes:
        value = get_text(node)
        if grouped and node.name == "h4" and is_fragment_heading(value):
            flush()
            current_citation = value
            continue
        if node.name not in {"p", "div"}:
            continue
        if grouped and is_fragment_heading(value):
            flush()
            current_citation = value
            continue
        if grouped and not has_greek(value) and re.match(r"^\d+[a-zA-Z]?(?:\s|$)", value):
            match = re.match(r"^(\d+[a-zA-ZΑ-Ωα-ω]?)(?:\s+(.*))?$", value)
            if match:
                flush()
                current_citation = match.group(1)
                if match.group(2):
                    editorial.append(match.group(2))
                continue
        for footnote in node.select("fn, .footnote"):
            note = get_text(footnote)
            if note:
                editorial.append(note)
            footnote.decompose()
        marker = node.select_one(".line-number")
        line_label = get_text(marker) if marker else ""
        if marker:
            marker.decompose()
        value = get_text(node)
        # Parenthetic edition credits accompany some Greek variant lines.
        value = re.sub(r"\s*(\((?:Voigt|Campbell|Page|Lobel[^)]*|broken)\))",
                       lambda match: editorial.append(match.group(1)) or "", value)
        if value and is_editorial_prose(value):
            editorial.append(value)
            continue
        if value and source_line(value):
            lines.append({"label": line_label or printed_line_label(value), "text": value})
    flush()
    if not passages:
        return []
    records = []
    for index, (passage_citation, passage_lines, passage_editorial) in enumerate(passages, 1):
        record_id = (f"dcc-sappho:{slug}:{passage_citation}" if grouped
                     else f"dcc-sappho:{slug}")
        record = base_record(url, path, data, record_id, "Dickinson College Commentaries",
                             passage_citation, "text",
                             "\n".join(line["text"] for line in passage_lines),
                             "grc", "CC BY-SA (version unspecified)",
                             {"editorial_credit": "Introduction and notes by Heather Waddell",
                              "source_page": citation})
        if is_fragment_heading(passage_citation) and len(passage_citation.split()) > 1:
            record["quality"] = "mixed_content"
            record["metadata"]["layout"] = "parallel_fragments"
        record["lines"] = passage_lines
        mark_dialogue_attribution(record)
        for notice in passage_editorial:
            if "different poems" in notice.casefold():
                record["quality"] = "mixed_content"
                record["metadata"]["source_group_description"] = notice
        records.append(record)
        if passage_editorial:
            item = base_record(url, path, data, f"{record_id}:editorial",
                               "Dickinson College Commentaries", passage_citation,
                               "commentary", "\n".join(passage_editorial), "eng",
                               "CC BY-SA (version unspecified)",
                               {"subtype": "editorial_notice"})
            item["parent_id"] = record_id
            records.append(item)
    page_parent = records[0]["id"] if not grouped else None
    page_id = f"dcc-sappho:{slug}"
    for field, subtype in (("field-vocab", "vocabulary"), ("field-notes", "notes")):
        node = article.select_one(f".field--name-{field}")
        if node is None:
            continue
        for removable in node.select(".msocomoff, .msocomtxt"):
            removable.decompose()
        value = "\n".join(get_text(p) for p in node.find_all("p") if get_text(p))
        if not value:
            value = get_text(node)
        if value and not placeholder(value):
            item = base_record(url, path, data, f"{page_id}:{subtype}",
                               "Dickinson College Commentaries", citation,
                               "commentary", value, "eng", "CC BY-SA (version unspecified)",
                               {"subtype": subtype, "scope": "page" if grouped else "passage"})
            if page_parent:
                item["parent_id"] = page_parent
            records.append(item)
    translation = article.select_one(".field--name-field-translation")
    if translation:
        value = get_text(translation)
        if value and not placeholder(value) and not re.fullmatch(
            r"(?is)translation\s+(?:goes here|coming soon)", value
        ):
            item = base_record(url, path, data, f"{page_id}:translation",
                               "Dickinson College Commentaries", citation,
                               "translation", value, "eng", "CC BY-SA (version unspecified)")
            if page_parent:
                item["parent_id"] = page_parent
            records.append(item)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="redownload cached HTML")
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update(HEADERS)
    raw_metadata = {}
    for url in (DIGITAL_HOME, DCC_SEED, DCC_TERMS):
        path, data = fetch(session, url, args.refresh)
        raw_metadata[url] = {"raw_path": path.relative_to(ROOT).as_posix(),
                             "sha256": hashlib.sha256(data).hexdigest()}
    digital_urls = discover_digital(soup_from(raw_file(DIGITAL_HOME).read_bytes()))
    dcc_urls = discover_dcc(soup_from(raw_file(DCC_SEED).read_bytes()))
    if not digital_urls or not dcc_urls:
        raise RuntimeError("Source navigation yielded no fragment URLs")
    rights_digital = get_text(soup_from(raw_file(DIGITAL_HOME).read_bytes()).select_one("#commentpress_text-2"))
    rights_dcc = get_text(soup_from(raw_file(DCC_TERMS).read_bytes()).select_one("article") or
                          soup_from(raw_file(DCC_TERMS).read_bytes()).select_one("main"))
    if "Attribution-ShareAlike 4.0" not in rights_digital or "Creative Commons Attribution-ShareAlike" not in rights_dcc:
        raise RuntimeError("Expected rights statements absent from saved source pages")
    records = []
    failures = []
    empty = []
    for edition, urls, parser_fn in (("digital", digital_urls, digital_records),
                                     ("dcc", dcc_urls, dcc_records)):
        for number, url in enumerate(urls, 1):
            try:
                path, data = fetch(session, url, args.refresh)
                parsed = parser_fn(url, path, data)
                if not parsed:
                    empty.append(url)
                records.extend(parsed)
            except Exception as error:
                failures.append({"url": url, "error": str(error)})
            if number % 20 == 0:
                print(f"{edition}: processed {number}/{len(urls)}", flush=True)
    ids = [record["id"] for record in records]
    for record in records:
        if (record["kind"] == "commentary" and has_greek(record["text"])
                and not re.search(r"[A-Za-z]", record["text"])):
            record["language"] = "grc"
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate IDs detected")
    id_set = set(ids)
    if any(record.get("parent_id") not in id_set for record in records if record.get("parent_id")):
        raise RuntimeError("Dangling commentary/translation parent ID")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    counts = Counter((record["edition"], record["kind"]) for record in records)
    placeholder_pages = [url for url in digital_urls + dcc_urls
                         if re.search(rb"\[insert table\]|translation goes here|>test<",
                                      raw_file(url).read_bytes(), re.IGNORECASE)]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_discovery": {"digital_home": DIGITAL_HOME, "digital_link_count": len(digital_urls),
                             "dcc_seed": DCC_SEED, "dcc_link_count": len(dcc_urls)},
        "rights": {"digital": {"license": "CC BY-SA 4.0", "url": DIGITAL_HOME},
                   "dcc": {"license": "CC BY-SA (version unspecified)", "url": DCC_TERMS}},
        "raw_seed_artifacts": raw_metadata,
        "records": len(records),
        "counts": [{"edition": edition, "kind": kind, "count": count}
                   for (edition, kind), count in sorted(counts.items())],
        "linked_child_records": sum(bool(record.get("parent_id")) for record in records),
        "page_scoped_records": sum(record.get("metadata", {}).get("scope") == "page"
                                   for record in records),
        "excluded_placeholder_pages": placeholder_pages,
        "parallel_fragment_records": sum(record.get("metadata", {}).get("layout") == "parallel_fragments"
                                         for record in records),
        "failures": failures,
        "pages_without_extracted_text": empty,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "counts": report["counts"],
                      "failures": len(failures), "empty": len(empty)}, ensure_ascii=False), flush=True)
    if failures or empty:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
