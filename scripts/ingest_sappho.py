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
                            ".wp-caption, .mceTemp, fn, .footnote, .easy-footnote, .easy-footnote-margin-adjust"):
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


def digital_sections(soup: BeautifulSoup) -> list[dict]:
    """Preserve source headings, including malformed nested WordPress headings.

    Parallel labels describe one source-layout group, not a supplied division
    of its flattened columns. Explicit column subsections get separate records
    so repeated printed line numbers cannot cross-link commentary.
    """
    post = soup.select_one("div.post")
    if post is None:
        return []
    title_tag = post.select_one(".post_title")
    title = get_text(title_tag) if title_tag else "Untitled"
    sections = []
    heading, subsection, subtitle = title, "", ""
    lines = []
    footnotes = []
    editorial = []

    def flush():
        nonlocal lines, footnotes, editorial
        if lines or editorial:
            metadata = {"source_page_title": title, "source_heading": heading}
            if subsection:
                metadata["source_section"] = subsection
            if subtitle:
                metadata["source_subtitle"] = subtitle
            if footnotes:
                metadata["source_footnote_links"] = footnotes
            if is_fragment_heading(heading) and len(re.findall(r"\d+[a-zΑ-Ωα-ω]?", heading, re.I)) > 1:
                metadata["layout"] = "parallel_fragments"
                metadata["source_group_description"] = "Multiple fragment labels share the source's parallel-column layout; no individual-column allocation is inferred."
            sections.append({"citation": heading + (" — " + subsection if subsection else ""),
                             "lines": lines, "metadata": metadata, "editorial": list(dict.fromkeys(editorial))})
        lines, footnotes, editorial = [], [], []

    for node in post.descendants:
        if not isinstance(node, Tag):
            continue
        if (node.find_parent(class_="easy-footnotes-wrapper") or node.find_parent(class_="easy-footnote")
                or node.find_parent(class_='search_meta') or node.find_parent(class_='running_header_bottom')):
            continue
        if node.name == "h4":
            value = digital_heading_text(node)
            if not value:
                continue
            # An initial descriptive title is a subtitle, not a different
            # numbered fragment. Subsequent explicit headings are boundaries.
            if not sections and not lines and heading == title and not re.match(r"(?i)^(?:fragment\s+)?\d", value):
                subtitle = value
                editorial.append(value)
                continue
            flush()
            heading, subsection, subtitle = value, "", ""
            for child in node.children:
                if isinstance(child, Tag):
                    if child.name in {'h4', 'div', 'p', 'ol', 'table', 'hr'}:
                        break
                    for anchor in child.select('.easy-footnote a[href]') if 'easy-footnote' not in child.get('class', []) else child.select('a[href]'):
                        footnotes.append({'marker': get_text(anchor), 'href': anchor['href'],
                                          'title_html': anchor.get('title', ''),
                                          'description': get_text(soup_from(anchor.get('title', ''))), 'scope': 'heading'})
            continue
        if node.name in {"div", "p"} and node.get("lang") != "grc":
            # Only a self-contained printed column heading, not a container
            # whose descendants happen to include these words.
            if not node.find(["div", "p", "table", "h4"], recursive=False):
                value = verse_text(node)
                if re.fullmatch(r"\([a-z]\)\s+Column\s+[ivxlcdm]+", value, re.I):
                    flush()
                    subsection = value
                elif (node.name == 'p' and is_editorial_prose(value)
                      and not node.select('.easy-footnote-to-top')
                      and meaningful(value)):
                    editorial.append(value)
            continue
        if node.get("lang") != "grc" or node.find_parent(attrs={"lang": "grc"}):
            continue
        if node.name == "h4":
            continue
        if node.name == "ol":
            candidates = [(li, str(int(node.get("start", 1)) + i))
                          for i, li in enumerate(node.find_all("li", recursive=False))]
        else:
            children = node.find_all(["p", "div"], recursive=False)
            candidates = [(child, "") for child in children] if children else [(node, "")]
        for candidate, label in candidates:
            value = verse_text(candidate)
            if value and is_editorial_prose(value):
                editorial.append(value)
            if not value or not source_line(value) or is_editorial_prose(value):
                continue
            line = {"label": label or printed_line_label(value), "text": value}
            if subsection:
                line["section"] = subsection
            lines.append(line)
            for anchor in candidate.select(".easy-footnote a[href]"):
                footnotes.append({"marker": get_text(anchor), "href": anchor["href"],
                                  "title_html": anchor.get("title", ""),
                                  "description": get_text(soup_from(anchor.get('title', ''))),
                                  "line_index": len(lines) - 1})
    flush()
    return sections


def digital_heading_text(node: Tag) -> str:
    """Read only heading inline content, not accidentally nested later text."""
    pieces = []
    for child in node.children:
        if isinstance(child, Tag):
            if child.name in {"h4", "div", "p", "ol", "table", "hr"}:
                break
            if any(cls.startswith("easy-footnote") for cls in child.get("class", [])):
                continue
            pieces.append(verse_text(child))
        else:
            pieces.append(str(child))
    return clean(" ".join(pieces))


def digital_passages(soup: BeautifulSoup) -> list[tuple[str, list[dict]]]:
    return [(section["citation"], section["lines"]) for section in digital_sections(soup) if section['lines']]


def digital_label_key(value: str) -> str:
    """Source-page heading key, NOT Greek word/dialect normalization.

    The downloaded body/sidebar use Greek Α/Β versus Latin A/B as numeric
    heading suffix typography. Only an unambiguous match on this same page is
    usable; exact printed labels are retained in each linked record.
    """
    value = re.sub(r"(?i)^fragment\s+", "", clean(value))
    if is_fragment_heading(value) and len(value.split()) > 1:
        return value.casefold()
    # An explicit edition qualifier is not disposable typography: "178
    # Campbell" must never silently match "178 Voigt" or even bare "178".
    match = re.fullmatch(r"(\d+)([a-zΑΒαβ]?)", value, re.I)
    if match:
        return match.group(1) + match.group(2).upper().translate(str.maketrans({'Α': 'A', 'Β': 'B'}))
    return value.casefold()


def digital_records(url: str, path: Path, data: bytes, existing_records: list[dict] | None = None) -> list[dict]:
    soup = soup_from(data)
    slug = urlparse(url).path.strip("/").split("/")[-1]
    records = []
    sections = digital_sections(soup)
    readings = [section for section in sections if section['lines']]
    passages = [(section['citation'], section['lines']) for section in readings]
    previous = {item['citation']: item['id'] for item in existing_records or [] if item['kind'] == 'text'}
    for i, section in enumerate(readings, 1):
        citation, lines = section['citation'], section['lines']
        if citation in previous:
            record_id = previous[citation]
        elif not existing_records:
            record_id = f"digital-sappho:{slug}:{i}"
        else:
            suffix = hashlib.sha256(citation.encode('utf-8')).hexdigest()[:16]
            record_id = f"digital-sappho:{slug}:section:{suffix}"
        record = base_record(url, path, data, record_id, "The Digital Sappho",
                             citation, "text", "\n".join(line["text"] for line in lines),
                             "grc", "CC BY-SA 4.0", {"source_collection": "The Digital Sappho", **section['metadata']})
        record["lines"] = lines
        if section['metadata'].get('layout') == 'parallel_fragments':
            record['quality'] = 'mixed_content'
        mark_dialogue_attribution(record)
        records.append(record)
    if not records:
        return records
    parent = records[0]["id"]
    page_title = get_text(soup.select_one("div.post .post_title"))
    grouped_page = len(passages) > 1 or any(section['metadata'].get('layout') == 'parallel_fragments' for section in readings)
    text_records = [item for item in records if item['kind'] == 'text']

    def resolve_sidebar(label, section=''):
        caption = lambda value: clean(value.translate(str.maketrans('', '', '“”"'))).casefold()
        candidates = [item for item in text_records
                      if (digital_label_key(item['metadata']['source_heading']) == digital_label_key(label)
                          or (item['metadata'].get('source_subtitle') and
                              caption(item['metadata']['source_subtitle']) == caption(label)))
                      and item['metadata'].get('source_section', '').casefold() == section.casefold()
                      and item['metadata'].get('layout') != 'parallel_fragments']
        return candidates[0] if len(candidates) == 1 else None
    post = soup.select_one("div.post")
    for section in sections:
        editorial = section.get('editorial', [])
        if not editorial:
            continue
        parent_record = next((item for item in text_records if item['citation'] == section['citation']), None)
        if parent_record and parent_record['metadata'].get('layout') == 'parallel_fragments':
            parent_record = None
        for notice in editorial:
            if parent_record and "different poems" in notice.casefold():
                parent_record["quality"] = "mixed_content"
                parent_record.setdefault("metadata", {})["source_group_description"] = notice
        editorial_id = (f"digital-sappho:{slug}:editorial" if parent_record is text_records[0]
                        else (parent_record['id'] if parent_record else f"digital-sappho:{slug}:section:" + hashlib.sha256(section['citation'].encode('utf-8')).hexdigest()[:16]) + ':editorial')
        item = base_record(url, path, data, editorial_id,
                           "The Digital Sappho", section['citation'],
                           "commentary", "\n".join(dict.fromkeys(editorial)), "eng",
                           "CC BY-SA 4.0", {"subtype": "editorial_notice",
                                            "scope": "passage" if parent_record else "source_section",
                                            **section['metadata']})
        if parent_record:
            item["parent_id"] = parent_record['id']
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
            active_heading, active_section = page_title, ''
            active_heading_row = None
            active_parent = resolve_sidebar(active_heading) if grouped_page else records[0]
            j = 0
            # Headings also occur BETWEEN tables. Flattening table rows alone
            # silently carries a previous poem's parent across witness changes.
            events = [tag for tag in node.descendants if isinstance(tag, Tag)
                      and (tag.name == 'tr' or (tag.name == 'h4' and not tag.find_parent('tr')))]
            for row in events:
                if row.name == 'h4':
                    heading_value = digital_heading_text(row)
                    if heading_value:
                        active_heading, active_section, active_heading_row = heading_value, '', None
                        active_parent = resolve_sidebar(active_heading)
                    continue
                j += 1
                value = get_text(row)
                if not value or not meaningful(value) or placeholder(value):
                    continue
                label = get_text(row.find("td")) if row.find("td") else ""
                if grouped_page or row.find('h4'):
                    heading_node = row.find('h4')
                    if heading_node or is_fragment_heading(value):
                        active_heading = digital_heading_text(heading_node) if heading_node else value
                        active_heading_row = j
                        active_section = ''
                        active_parent = resolve_sidebar(active_heading)
                    elif re.fullmatch(r"\([a-z]\)\s+Column\s+[ivxlcdm]+", value, re.I):
                        active_section = value
                        active_parent = resolve_sidebar(active_heading, active_section)
                if row.find('h4') or is_fragment_heading(value) or re.fullmatch(r"\([a-z]\)\s+Column\s+[ivxlcdm]+", value, re.I):
                    continue
                item = base_record(url, path, data, f"digital-sappho:{slug}:vocab:{j}",
                                   "The Digital Sappho",
                                   active_parent["citation"] if active_parent else page_title,
                                   "commentary", value, "eng", "CC BY-SA 4.0",
                                   {"subtype": "vocabulary", "line_label": label,
                                    "scope": "passage" if active_parent else "page"})
                if active_parent:
                    item["parent_id"] = active_parent["id"]
                    if grouped_page:
                        item['metadata']['source_heading_link'] = {
                            'sidebar_heading': active_heading,
                            'body_heading': active_parent['metadata']['source_heading'],
                            'section': active_section,
                            'method': 'Unique same-page source heading and explicit subsection match; heading suffix typography only.'}
                        if active_heading_row is not None:
                            alias = {'label': active_heading, 'body_heading': active_parent['metadata']['source_heading'],
                                     'source_url': url, 'locator': f'#activity_sidebar table tr {active_heading_row}',
                                     'scope': 'fragment_heading',
                                     'method': 'Unique same-page body/sidebar heading match; original printed labels retained.'}
                            aliases = active_parent['metadata'].setdefault('source_citation_aliases', [])
                            if alias not in aliases:
                                aliases.append(alias)
                elif active_heading:
                    item['metadata']['unresolved_source_heading'] = active_heading
                    if active_section:
                        item['metadata']['source_section'] = active_section
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
    existing_pages = {}
    if OUTPUT.exists():
        for line in OUTPUT.read_text(encoding='utf-8').splitlines():
            old = json.loads(line)
            existing_pages.setdefault(old['source_url'], []).append(old)
    for edition, urls, parser_fn in (("digital", digital_urls, digital_records),
                                     ("dcc", dcc_urls, dcc_records)):
        for number, url in enumerate(urls, 1):
            try:
                path, data = fetch(session, url, args.refresh)
                parsed = (digital_records(url, path, data, existing_pages.get(url))
                          if edition == 'digital' else parser_fn(url, path, data))
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
