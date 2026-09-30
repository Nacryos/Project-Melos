"""Collect traceable ancient Greek lyric passages from Greek Wikisource.

The author pages supply the candidate links. Only pages whose own Wikisource
header names the expected ancient author are eligible. Raw API responses are
saved before parsing. The Wikisource project license is CC BY-SA 4.0; see
https://el.wikisource.org/wiki/Βικιθήκη:Πνευματικά_δικαιώματα .
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/lyric_web"
OUT = ROOT / "data/processed/lyric_web.jsonl"
REPORT = ROOT / "data/reports/lyric_web.json"
API = "https://el.wikisource.org/w/api.php"
AUTHORS = [
    "Ίβυκος", "Στησίχορος", "Ανακρέων", "Αλκμάν", "Κόριννα",
    "Αρχίλοχος", "Μίμνερμος", "Τυρταίος", "Σιμωνίδης ο Κείος",
    "Σημωνίδης ο Αμοργίνος",
]
HEAD = re.compile(r"(?m)^(={2,5})\s*(.*?)\s*\1\s*$")
LINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
POEM = re.compile(r"<poem[^>]*>(.*?)</poem>", re.I | re.S)
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
MARKUP = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")
HEADER = re.compile(r"\{\{Κεφαλίδα\b(.*?)\}\}", re.I | re.S)
USER_AGENT = "MelosCorpus/0.1 (Wikisource research corpus; polite API client)"


def fetch(session: requests.Session, title: str) -> tuple[dict, str, str]:
    # Reruns reuse immutable saved revisions instead of requesting pages again.
    for saved in RAW.glob("*.json") if RAW.exists() else []:
        data = saved.read_bytes()
        try:
            page = next(iter(json.loads(data)["query"]["pages"].values()))
        except (ValueError, KeyError, StopIteration):
            continue
        if page.get("title") == title and "revisions" in page:
            return page, str(saved.relative_to(ROOT)).replace("\\", "/"), hashlib.sha256(data).hexdigest()
    params = {"action": "query", "format": "json", "redirects": "1",
              "titles": title, "prop": "revisions", "rvprop": "ids|content",
              "rvslots": "main"}
    response = None
    for attempt in range(3):
        try:
            response = session.get(API, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            retry = response.headers.get("Retry-After", "") if response is not None else ""
            time.sleep(min(float(retry), 30) if retry.isdigit() else 5 * (attempt + 1))
    assert response is not None
    pages = list(payload["query"]["pages"].values())
    page = pages[0]
    if "missing" in page:
        raise ValueError(f"Missing page: {title}")
    rev = page["revisions"][0]
    raw_name = f"{page['pageid']}_{rev['revid']}.json"
    raw_path = RAW / raw_name
    RAW.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(response.content)
    return page, str(raw_path.relative_to(ROOT)).replace("\\", "/"), hashlib.sha256(response.content).hexdigest()


def wikitext(page: dict) -> str:
    return page["revisions"][0]["slots"]["main"]["*"]


def header_author(raw: str) -> str:
    match = HEADER.search(raw)
    if not match:
        return ""
    field = re.search(r"\|\s*συγγραφέας\s*=\s*([^|\n}]+)", match.group(1), re.I)
    return field.group(1).strip() if field else ""


def clean_line(line: str) -> str:
    line = line.strip().lstrip(":").strip()
    line = MARKUP.sub(lambda m: m.group(2) or m.group(3), line)
    # Greek letters in angle brackets are editorial supplements, not HTML.
    line = re.sub(r"</?(?:br|span|small|sup|sub|i|b)(?:\s+[^>]*)?/?>", "", line, flags=re.I)
    return line.strip()


def passages(raw: str, title: str) -> list[tuple[str, list[str], str]]:
    """Take tagged verse or wikitext verse lines, split by source headings.

    Sections containing modern translation markers are withheld; section text
    mixing Greek text and ancient testimonia receives needs_review quality.
    """
    body = HEADER.sub("", raw, count=1)
    headings = list(HEAD.finditer(body))
    spans = []
    start = 0
    label = title
    for heading in headings:
        spans.append((label, body[start:heading.start()]))
        label = re.sub(r"\[\[|\]\]", "", heading.group(2)).strip()
        start = heading.end()
    spans.append((label, body[start:]))
    # Some anthology pages use indented inline fragment labels instead of
    # heading syntax (e.g. Simonides' encomia).
    expanded = []
    for label, section in spans:
        markers = list(re.finditer(r"(?mi)^::\s*(απόσπ\.[^\r\n]*)$", section))
        if not markers:
            expanded.append((label, section))
            continue
        expanded.append((label, section[:markers[0].start()]))
        for n, marker in enumerate(markers):
            end = markers[n + 1].start() if n + 1 < len(markers) else len(section)
            expanded.append((marker.group(1).strip(), section[marker.end():end]))
    output = []
    for label, section in expanded:
        if re.search(r"μετάφρασ|νεοελλην|translation", label, re.I):
            continue
        poem_blocks = POEM.findall(section)
        if poem_blocks:
            for n, block in enumerate(poem_blocks, 1):
                # splitlines() also splits U+0085, which occurs in this source
                # as an editorial lacuna marker inside a verse line.
                lines = [clean_line(x) for x in block.split("\n")]
                lines = [x for x in lines if x and GREEK.search(x)]
                if not lines:
                    continue
                # A long prose line is testimony, not a lyric verse.
                prose_signal = re.search(r"ΑΠΟΣΠΑΣΜΑ|ΣΗΜΕΙΩΣΗ|Κόριννα δὲ|παρὰ δὲ|''", block, re.I)
                quality = "needs_review" if prose_signal or any(len(x) > 100 for x in lines) else "source_text"
                citation = f"{label} / block {n}" if len(poem_blocks) > 1 else label
                output.append((citation, lines, quality))
            continue
        colon_lines = []
        for x in section.split("\n"):
            if x.lstrip().startswith(":"):
                clean = clean_line(x)
                if GREEK.search(clean):
                    colon_lines.append(clean)
        if colon_lines:
            quality = "needs_review" if any(len(x) > 100 for x in colon_lines) else "source_text"
            output.append((label, colon_lines, quality))
    return output


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    failures = []
    author_pages = {}
    candidates = {}
    for author in AUTHORS:
        try:
            page, path, digest = fetch(session, "Συγγραφέας:" + author)
        except Exception as exc:
            failures.append({"title": "Συγγραφέας:" + author, "error": str(exc)})
            continue
        author_pages[author] = {"url": f"https://el.wikisource.org/wiki/{quote(page['title'].replace(' ', '_'))}", "raw_path": path, "raw_sha256": digest}
        for line in wikitext(page).split("\n"):
            if line.lstrip().startswith("**"):
                continue
            for link in LINK.findall(line):
                if link.startswith(("Συγγραφέας:", "Κατηγορία:", "Στέφανος (", "Image:", "Αρχείο:")) or "επιγράμμα" in link.casefold():
                    continue
                candidates.setdefault(link.strip(), set()).add(author)
        time.sleep(.15)

    records = []
    skipped = []
    for title, authors in sorted(candidates.items()):
        try:
            page, path, digest = fetch(session, title)
        except Exception as exc:
            failures.append({"title": title, "error": str(exc)})
            continue
        raw = wikitext(page)
        author = header_author(raw)
        if author not in authors:
            skipped.append({"title": title, "reason": "author header mismatch or absent", "header_author": author})
            continue
        if re.search(r"\|\s*μεταφραστής\s*=\s*[^\s|}]", raw[:1200], re.I):
            skipped.append({"title": title, "reason": "translator in page header"})
            continue
        source_url = f"https://el.wikisource.org/wiki/{quote(page['title'].replace(' ', '_'))}"
        parsed_passages = passages(raw, page["title"])
        for index, (citation, lines, quality) in enumerate(parsed_passages, 1):
            if author == "Κόριννα" and not (re.match(r"^(?:\d{1,2}[a-z]?\s|\[)", lines[0]) and quality == "source_text"):
                quality = "needs_review"
            # Wikisource headers sometimes label fragments only by incipit.
            record = {
                "id": f"lyric_web:elws:{page['pageid']}:{page['revisions'][0]['revid']}:{index}",
                "source": "lyric_web", "source_url": source_url,
                "raw_path": path, "raw_sha256": digest,
                "author": author, "work": page["title"],
                "edition": "Greek Wikisource community transcription (source edition unspecified)",
                "citation": citation, "language": "grc", "text": "\n".join(lines),
                "kind": "text" if quality == "source_text" else "reference",
                "quality": quality, "license": "CC BY-SA 4.0",
                "lines": [{"label": str(n), "text": line} for n, line in enumerate(lines, 1)],
                "metadata": {"page_id": page["pageid"], "revision_id": page["revisions"][0]["revid"], "source_project": "Greek Wikisource", "revision_url": f"https://el.wikisource.org/w/index.php?title={quote(page['title'].replace(' ', '_'))}&oldid={page['revisions'][0]['revid']}"},
            }
            records.append(record)
        if not parsed_passages:
            skipped.append({"title": title, "reason": "no safely parsed verse"})
        time.sleep(.15)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    staged_out = OUT.with_suffix(".jsonl.tmp")
    staged_out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8")
    os.replace(staged_out, OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    staged_report = REPORT.with_suffix(".json.tmp")
    staged_report.write_text(json.dumps({
        "source": "Greek Wikisource", "api": API,
        "license_url": "https://el.wikisource.org/wiki/Βικιθήκη:Πνευματικά_δικαιώματα",
        "author_pages": author_pages, "candidate_pages": len(candidates),
        "records": len(records), "by_author": dict(Counter(r["author"] for r in records)),
        "by_quality": dict(Counter(r["quality"] for r in records)),
        "skipped": skipped, "failures": failures,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staged_report, REPORT)
    print(f"records={len(records)} candidates={len(candidates)} failures={len(failures)}")


if __name__ == "__main__":
    main()
