"""Stage source-quoted literary dialect grammar from two audited DCC pages.

Usage: python scripts/ingest_p2_grammar.py [--refresh]
The resulting rows are commentary/reference, never ancient poem text. The table
is kept as source-specific comparisons, not productive replacement rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_grammar"
PROCESSED = ROOT / "data/processed/p2_grammar.jsonl"
CLAIMS = ROOT / "data/claims/p2_grammar.jsonl"
REPORT = ROOT / "data/reports/p2_grammar.json"
SAPPHO_URL = "https://dcc.dickinson.edu/sappho-introduction"
GOODELL_URL = "https://dcc.dickinson.edu/grammar/goodell/introduction"
TERMS_URL = "https://dcc.dickinson.edu/terms-use"
GOODELL_RIGHTS_URL = "https://dcc.dickinson.edu/grammar/goodell/credits-and-reuse"
SAPPHO_CREDITS_URL = "https://dcc.dickinson.edu/sappho-credits"
URLS = [SAPPHO_URL, GOODELL_URL, TERMS_URL, GOODELL_RIGHTS_URL, SAPPHO_CREDITS_URL]
HEADERS = {"User-Agent": "MelosCorpusResearch/0.1 (educational source citation; polite cached fetch)"}
LICENSE = "CC BY-SA (version unspecified)"


def normalize(value: str) -> str:
    """Only collapse whitespace; no Greek spelling or accent normalization."""
    return " ".join(value.split())


def text_of(node: Tag) -> str:
    # Preserve inline punctuation around <em>/<i>/<sup>; only block paragraphs
    # need a separator. The source's printed Greek spellings are left untouched.
    if node.name in {"td", "th"}:
        blocks = node.find_all("p", recursive=False)
        if blocks:
            return normalize(" ".join(block.get_text() for block in blocks))
    return normalize(node.get_text())


def raw_file(url: str) -> Path:
    parsed = urlparse(url)
    return RAW / (parsed.netloc + parsed.path.replace("/", "__") + ".html")


def fetch(session: requests.Session, url: str, refresh: bool) -> tuple[Path, bytes]:
    path = raw_file(url)
    if path.exists() and not refresh:
        return path, path.read_bytes()
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty HTTP response")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            time.sleep(0.4)
            return path, response.content
        except (requests.RequestException, ValueError) as error:
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DOWNLOAD FAILED {url}: {last_error}")


def artifact(url: str, path: Path, data: bytes) -> dict:
    return {
        "source_url": url,
        "raw_path": path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def exact_section(soup: BeautifulSoup, heading: str) -> Tag:
    candidates = soup.find_all(re.compile(r"^(?:h[1-6]|p)$"))
    for node in candidates:
        if text_of(node) == heading:
            return node
    raise ValueError(f"missing heading {heading!r}")


def following_paragraph(heading: Tag) -> str:
    node = heading.find_next_sibling()
    if node is None or node.name != "p":
        raise ValueError(f"missing paragraph after {text_of(heading)!r}")
    return text_of(node)


def source_record(record_id: str, info: dict, author: str, work: str,
                  citation: str, kind: str, body: str, metadata: dict) -> dict:
    return {
        "id": record_id,
        "source": "p2_grammar",
        "source_url": info["source_url"],
        "raw_path": info["raw_path"],
        "raw_sha256": info["raw_sha256"],
        "author": author,
        "work": work,
        "edition": "Dickinson College Commentaries",
        "citation": citation,
        "language": "eng",
        "text": body,
        "kind": kind,
        "quality": "source_text",
        "license": LICENSE,
        "metadata": metadata,
    }


def evidence(info: dict, quote: str, locator: str, record_id: str) -> dict:
    return {
        "record_id": record_id,
        "source_url": info["source_url"],
        "raw_path": info["raw_path"],
        "raw_sha256": info["raw_sha256"],
        "quote": quote,
        "locator": locator,
    }


def claim(claim_id: str, subject: dict, predicate: str, obj: dict,
          evidences: list[dict], family: str, method: str, metadata: dict) -> dict:
    return {
        "id": claim_id,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "evidence": evidences,
        "assertion_type": "extracted_annotation",
        "status": "source_claim",
        "method": method,
        "source_family": family,
        "metadata": metadata,
    }


def extract_sappho(soup: BeautifulSoup, info: dict) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    claims: list[dict] = []
    heading = exact_section(soup, "Sappho’s Dialect")
    paragraph = following_paragraph(heading)
    if "Sappho and the poet Alcaeus" not in paragraph:
        raise ValueError("Sappho/Alcaeus literary-dialect passage missing")
    rid = "dcc-sappho-intro:dialect"
    records.append(source_record(
        rid, info, "Heather Waddell", "Sappho: Introduction", "Sappho’s Dialect",
        "commentary", paragraph,
        {"section": "Sappho’s Dialect", "rights_url": TERMS_URL,
         "credit_url": SAPPHO_CREDITS_URL, "text_normalization": "whitespace only"},
    ))
    claims.append(claim(
        "dcc-sappho-intro:literary-aeolic", {"type": "literary_dialect", "id": "sappho-alcaeus"},
        "literary_dialect",
        {"source_label": "Aeolic", "authors_named": ["Sappho", "Alcaeus"],
         "scope": "primary literary representatives in this source; no token-level classification"},
        [evidence(info, paragraph, "Sappho’s Dialect", rid)],
        "dcc-sappho-heather-waddell", "dcc-sappho-paragraph-v1",
        {"credit": "Introduction and notes by Heather Waddell", "rights_url": TERMS_URL},
    ))

    table_heading = exact_section(soup, "Features of Aeloic Dialect")
    table = table_heading.find_next("table")
    if table is None:
        raise ValueError("Aeolic feature table missing")
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) >= 3:
            values = [text_of(cell) for cell in cells[:3]]
            if any(values):
                rows.append(values)
    if not rows or "Aeolic" not in " ".join(rows[0]):
        raise ValueError("Aeolic comparison table header missing")
    for index, (label, aeolic, comparator) in enumerate(rows[1:], start=1):
        if not label or not aeolic or not comparator:
            continue  # section separators and unpaired examples are not rules
        rid = f"dcc-sappho-intro:table:{index:02d}"
        records.append(source_record(
            rid, info, "Heather Waddell", "Sappho: Introduction",
            f"Features of Aeloic Dialect, row {index}", "reference",
            f"{label} | {aeolic} | {comparator}",
            {"section": "Features of Aeloic Dialect", "row_index": index,
             "column_labels": rows[0], "rights_url": TERMS_URL,
             "credit_url": SAPPHO_CREDITS_URL,
             "text_normalization": "cell whitespace collapsed; cells joined with ' | '"},
        ))
        claims.append(claim(
            f"dcc-sappho-intro:grammar:{index:02d}",
            {"type": "grammar_rule", "id": f"dcc-sappho-intro:table:{index:02d}"},
            "grammar_rule",
            {"source_feature": label, "source_aeolic_examples": aeolic,
             "source_attic_ionic_examples": comparator,
             "comparison": "source table juxtaposition, not a universal substitution",
             "scope": "DCC table headed Features of Aeloic Dialect in Sappho introduction"},
            [evidence(info, label, f"feature table row {index}, feature", rid),
             evidence(info, aeolic, f"feature table row {index}, Aeolic", rid),
             evidence(info, comparator, f"feature table row {index}, Attic & Ionic", rid)],
            "dcc-sappho-heather-waddell", "dcc-sappho-table-cells-v1",
            {"credit": "Introduction and notes by Heather Waddell", "rights_url": TERMS_URL},
        ))
    return records, claims


def extract_goodell(soup: BeautifulSoup, info: dict) -> tuple[list[dict], list[dict]]:
    candidates = [text_of(p) for p in soup.find_all("p")]
    matches = [p for p in candidates if "In the literature the dialects were somewhat mingled" in p]
    if len(matches) != 1:
        raise ValueError(f"expected one Goodell literary-dialect paragraph; found {len(matches)}")
    match = re.search(r"In the literature the dialects were somewhat mingled;.*?the Ionic\.", matches[0])
    if match is None:
        raise ValueError("Goodell literary-dialect sentence boundary missing")
    paragraph = match.group(0)
    rid = "dcc-goodell:introduction:literary-dialects"
    record = source_record(
        rid, info, "Thomas Dwight Goodell; DCC edition edited by Meagan Ayer et al.",
        "A School Grammar of Attic Greek", "Introduction", "reference", paragraph,
        {"rights_url": GOODELL_RIGHTS_URL,
         "credit": "Goodell 1902; DCC digital version edited by Meagan Ayer et al., 2018",
         "text_normalization": "whitespace only; exact sentence selected from longer source paragraph"},
    )
    claim_row = claim(
        "dcc-goodell:literary-dialect-mixture", {"type": "literary_dialect", "id": "goodell:introduction"},
        "literary_dialect",
        {"source_statement": paragraph,
         "scope": "broad historical literary-dialect characterization; dialects described as mingled; no passage or token-level assignment"},
        [evidence(info, paragraph, "Introduction, literary dialect paragraph", rid)],
        "dcc-goodell-ayer-2018", "dcc-goodell-paragraph-v1",
        {"credit": "Thomas Dwight Goodell; digital edition edited by Meagan Ayer et al.",
         "rights_url": GOODELL_RIGHTS_URL},
    )
    return [record], [claim_row]


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    with requests.Session() as session:
        session.headers.update(HEADERS)
        downloaded = {url: fetch(session, url, args.refresh) for url in URLS}
    artifacts = {url: artifact(url, *downloaded[url]) for url in URLS}
    if "Attribution-ShareAlike" not in BeautifulSoup(downloaded[TERMS_URL][1], "html.parser").get_text(" "):
        raise ValueError("DCC terms no longer contain Attribution-ShareAlike")
    if "Attribution-ShareAlike" not in BeautifulSoup(downloaded[GOODELL_RIGHTS_URL][1], "html.parser").get_text(" "):
        raise ValueError("Goodell reuse page no longer contains Attribution-ShareAlike")
    sappho = BeautifulSoup(downloaded[SAPPHO_URL][1], "html.parser")
    goodell = BeautifulSoup(downloaded[GOODELL_URL][1], "html.parser")
    s_records, s_claims = extract_sappho(sappho, artifacts[SAPPHO_URL])
    g_records, g_claims = extract_goodell(goodell, artifacts[GOODELL_URL])
    records, claims = s_records + g_records, s_claims + g_claims
    processed_hash = write_jsonl(PROCESSED, records)
    claims_hash = write_jsonl(CLAIMS, claims)
    report = {
        "source": "p2_grammar",
        "source_gate": "p2_source_audit PASS for bounded DCC Sappho Introduction and Goodell Introduction",
        "artifacts": list(artifacts.values()),
        "processed_path": PROCESSED.relative_to(ROOT).as_posix(),
        "processed_sha256": processed_hash,
        "processed_count": len(records),
        "claims_path": CLAIMS.relative_to(ROOT).as_posix(),
        "claims_sha256": claims_hash,
        "claims_count": len(claims),
        "license": LICENSE,
        "scope": "historical grammar commentary and source comparisons only; no poem text or generated paradigms",
        "normalization": "Whitespace is collapsed within DOM cells and paragraphs. Table cell text is joined with ' | ' for reference rows. Greek spelling and accent are unchanged.",
        "caveat": "Goodell is a broad historical generalization; the DCC table is Aeolic-labelled and cannot automatically classify every Lesbian lyric token.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"processed": len(records), "claims": len(claims),
                      "processed_sha256": processed_hash, "claims_sha256": claims_hash}, indent=2))


if __name__ == "__main__":
    main()
