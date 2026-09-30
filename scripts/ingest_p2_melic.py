"""Stage additional melic Greek from a revision-pinned Wikisource source.

The collector saves the unaltered MediaWiki API response before parsing. It
does not repair accents or infer an edition from the ancient attribution.
Wikisource contributor license: https://el.wikisource.org/wiki/Βικιθήκη:Πνευματικά_δικαιώματα
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlencode

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_melic"
OUT = ROOT / "data/processed/p2_melic.jsonl"
REPORT = ROOT / "data/reports/p2_melic.json"
API = "https://el.wikisource.org/w/api.php"
TITLE = "ΠΑΡΑΓΕΛΙΑΙ ΔΙΑ ΤΟ ΣΥΜΠΟΣΙΟΝ (Ανακρεων)"
REVISION = 60169
USER_AGENT = "MelosCorpus/0.2 (research corpus; contact: melos-corpus@example.org)"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


def request_url() -> str:
    return API + "?" + urlencode({
        "action": "query", "format": "json", "prop": "revisions",
        "revids": REVISION, "rvprop": "ids|content", "rvslots": "main",
    })


def download() -> tuple[dict, str, str]:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{REVISION}.json"
    if not path.exists():
        response = None
        for attempt in range(3):
            try:
                response = requests.get(request_url(), headers={"User-Agent": USER_AGENT}, timeout=30)
                response.raise_for_status()
                payload = response.json()
                if "query" not in payload:
                    raise ValueError(f"No query result: {payload}")
                path.write_bytes(response.content)
                break
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                retry = response.headers.get("Retry-After", "") if response is not None else ""
                time.sleep(min(int(retry), 30) if retry.isdigit() else 5 * (attempt + 1))
    raw = path.read_bytes()
    data = json.loads(raw)
    page = next(iter(data["query"]["pages"].values()))
    if page["title"] != TITLE or page["revisions"][0]["revid"] != REVISION:
        raise ValueError("Saved Wikisource page does not match pinned title/revision")
    return page, path.relative_to(ROOT).as_posix(), hashlib.sha256(raw).hexdigest()


def is_heading(line: str) -> bool:
    heading = line.split("(", 1)[0].strip()
    letters = [c for c in heading if GREEK.fullmatch(c)]
    return len(letters) >= 8 and all(c == c.upper() for c in letters)


def parse(page: dict, raw_path: str, raw_sha256: str) -> list[dict]:
    wikitext = page["revisions"][0]["slots"]["main"]["*"]
    sections: list[tuple[str, list[str]]] = []
    for raw_line in wikitext.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if is_heading(line):
            sections.append((line, []))
        elif sections:
            sections[-1][1].append(line)
        else:
            raise ValueError("Body before section heading")
    if len(sections) != 2 or any(not lines for _, lines in sections):
        raise ValueError(f"Expected two nonempty poem sections; got {len(sections)}")
    url = "https://el.wikisource.org/wiki/" + quote(TITLE.replace(" ", "_"))
    revision_url = "https://el.wikisource.org/w/index.php?" + urlencode({"title": TITLE, "oldid": REVISION})
    records = []
    for index, (heading, lines) in enumerate(sections, 1):
        if any("{{" in line or "[[" in line for line in lines):
            raise ValueError("Unparsed wiki markup in text")
        if not all(GREEK.search(line) for line in lines):
            raise ValueError("Non-Greek line in poem section")
        records.append({
            "id": f"p2_melic:elws:{page['pageid']}:{REVISION}:{index}",
            "source": "p2_melic", "source_url": url,
            "raw_path": raw_path, "raw_sha256": raw_sha256,
            "author": "Anacreon (Wikisource attribution)",
            "work": heading, "edition": "Greek Wikisource transcription; printed edition unspecified",
            "citation": heading, "language": "grc", "text": "\n".join(lines),
            "kind": "text", "quality": "needs_review", "license": "CC BY-SA 4.0",
            "metadata": {
                "page_id": page["pageid"], "revision_id": REVISION,
                "revision_url": revision_url,
                "source_project": "Greek Wikisource",
                "source_edition_status": "unspecified",
                "transcription_note": "Unaccented source orthography preserved; no fragment number inferred",
                "attribution_status": "page title attribution; epigram attribution requires review",
            },
        })
    return records


def normalized(text: str) -> str:
    decomp = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomp if unicodedata.category(c).startswith("L"))


def compare_existing(records: list[dict]) -> dict:
    candidates = []
    for path in [ROOT / "data/processed/lyric_web.jsonl", ROOT / "data/processed/ogc.jsonl"]:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                entry = json.loads(line)
                author = entry.get("author", "").casefold()
                if "ανακρ" not in author and "anacreon" not in author:
                    continue
                if entry.get("kind") != "text" or entry.get("language") != "grc":
                    continue
                candidates.append((entry["id"], normalized(entry["text"])))
    comparisons = {}
    for record in records:
        needle = normalized(record["text"])
        exact = [id_ for id_, text in candidates if needle == text]
        contained = [id_ for id_, text in candidates if len(needle) >= 40 and needle in text and needle != text]
        comparisons[record["id"]] = {
            "exact_normalized_matches": exact,
            "contained_in_existing": contained[:20],
            "candidate_count": len(candidates),
        }
    return comparisons


def main() -> None:
    page, raw_path, raw_sha256 = download()
    records = parse(page, raw_path, raw_sha256)
    duplicates = compare_existing(records)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    report = {
        "collector": "p2_melic", "source_url": records[0]["source_url"],
        "source_api_url": request_url(),
        "rights_url": "https://el.wikisource.org/wiki/Βικιθήκη:Πνευματικά_δικαιώματα",
        "raw_path": raw_path, "raw_sha256": raw_sha256,
        "output_path": OUT.relative_to(ROOT).as_posix(),
        "output_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "records": len(records), "by_work": dict(Counter(r["work"] for r in records)),
        "by_quality": dict(Counter(r["quality"] for r in records)),
        "duplicates": duplicates,
        "coverage_note": "Two page sections, one sympotic passage and one epigram; both unaccented and edition-unspecified. Source-level new records, not new manuscript witnesses.",
        "excluded_sources": [
            {"url": "https://el.wikisource.org/wiki/Ανακρεόντεια", "reason": "Page credits West's 1984 Teubner edition; edition-rights audit allowed metadata only"},
            {"url": "https://el.wikisource.org/wiki/Εις_Άρτεμιν_Ορθίαν", "reason": "Alcman 101-line partheneion duplicates first-pass lyric_web page 17910"},
            {"url": "https://el.wikisource.org/wiki/Επιγράμματα_Σιμωνίδη", "reason": "Index of attributed Palatine epigrams, not new melic text"},
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "duplicates": duplicates}, ensure_ascii=False))


if __name__ == "__main__":
    main()
