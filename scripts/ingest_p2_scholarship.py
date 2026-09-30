"""Stage DCC's authored Pythian 4 notes and lyric-relevant Argonautica IV notes.

The page and rights statements are saved as raw HTML.  Records quote only
paragraphs parsed from those saved files; whitespace is normalized, and no
ancient Greek edition is asserted from this modern commentary page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_scholarship"
OUTPUT = ROOT / "data/processed/p2_scholarship.jsonl"
REPORT = ROOT / "data/reports/p2_scholarship.json"
BASE = "https://dcc.dickinson.edu/apollonius-argonautica/"
PYTHIAN = BASE + "parallel-texts/pindar-pythian-4-divine-clod"
RIGHTS = "https://dcc.dickinson.edu/terms-use"

# Page identifiers are source selectors, not authored corpus entries.  Each
# exact page is proposed for independent source/rights audit before collection.
BOOK4_RANGES = (
    "1-56", "109-182", "1108-1167", "1168-1225", "1368-1419",
    "1420-1482", "1535-1594", "1652-1728", "1729-1781", "183-235",
    "236-293", "294-349", "410-481", "550-624", "683-736",
    "737-830", "831-882", "883-979", "980-1050",
)
LYRIC = re.compile(
    r"\b(?:Pindar\b|Pind\.|Pyth(?:ian|\.)\s*\d|Simonides\b|Simonid\.|"
    r"Bacchylides\b|Bacchylid\.|Sappho\b|Archilochus\b|Archiloch\.|"
    r"Alcman\b|Anacreon\b|Stesichorus\b|Stesichor\.|Ibycus\b|Alcaeus\b)", re.I
)


def fetch(url: str, path: Path, *, from_cache: bool = False) -> tuple[Path, str]:
    if from_cache:
        if not path.is_file():
            raise FileNotFoundError(f"Explicit cache mode lacks {path} for {url}")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    request = Request(url, headers={"User-Agent": "Melos-research-corpus/1.0 (educational; source attribution)"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}: {url}")
                payload = response.read()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def parse_page(url: str, raw: Path, digest: str, *, kind: str) -> list[dict]:
    soup = BeautifulSoup(raw.read_bytes(), "html.parser")
    title = soup.find("h1")
    notes = soup.select_one(".field--name-field-notes")
    credit = soup.select_one(".field--name-body")
    if not title or not notes or not credit or "Peter Hulse" not in text(credit):
        raise RuntimeError(f"Missing DCC title, notes, or author credit: {url}")
    paragraphs = notes.find_all("p")
    if not paragraphs:
        raise RuntimeError(f"No note paragraphs in {url}")
    source_key = "pindar-pythian-4" if kind == "pythian" else f"argonautica-iv-{url.rsplit('-', 2)[-2]}-{url.rsplit('-', 1)[-1]}"
    records = []
    for index, paragraph in enumerate(paragraphs, 1):
        quote = text(paragraph)
        if not quote:
            continue
        if kind == "book4" and quote.casefold().startswith("bibliography:"):
            break
        if kind == "book4" and not LYRIC.search(quote):
            continue
        # The DCC note begins with a source line label in most cases.  This
        # label is retained verbatim, never interpreted as a verified alignment.
        label = re.match(r"^([0-9][0-9–—\- ,.]*)\s*:?", quote)
        locator = f"notes paragraph {index}"
        citation = "Pindar, Pythian 4" if kind == "pythian" else f"Apollonius, {text(title)}"
        record = {
            "id": f"dcc-hulse:{source_key}:note:{index}",
            "source": "p2_scholarship",
            "source_url": url,
            "raw_path": raw.relative_to(ROOT).as_posix(),
            "raw_sha256": digest,
            "author": "Peter Hulse",
            "work": text(title),
            "edition": "Dickinson College Commentaries, Apollonius Argonautica Book 4",
            "citation": f"{citation}, {locator}",
            "language": "eng",
            "text": quote,
            "kind": "commentary",
            "quality": "source_text",
            "license": "CC BY-SA (version unspecified)",
            "metadata": {
                "notes_author": "Peter Hulse",
                "ancient_target": citation,
                "source_family": "Dickinson College Commentaries: Hulse, Argonautica Book 4",
                "rights_url": RIGHTS,
                "locator": locator,
                "source_line_label": label.group(1).strip() if label else None,
                "lyric_name_matches": list(dict.fromkeys(m.group(0) for m in LYRIC.finditer(quote))),
                "selection": "all source notes" if kind == "pythian" else "note explicitly naming a lyric poet or Pythian ode",
                "whitespace_normalization": "HTML text nodes joined with spaces, runs of whitespace collapsed",
            },
        }
        records.append(record)
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-book4", action="store_true", help="Use only after the exact Book 4 page batch passes source audit")
    ap.add_argument("--from-cache", action="store_true", help="Reparse previously downloaded raw HTML without a network request")
    args = ap.parse_args()

    rights_raw, rights_hash = fetch(RIGHTS, RAW / "terms-use.html", from_cache=args.from_cache)
    rights_text = text(BeautifulSoup(rights_raw.read_bytes(), "html.parser"))
    if "Creative Commons Attribution-ShareAlike" not in rights_text:
        raise RuntimeError("DCC rights declaration changed; stop for review")
    urls = [PYTHIAN]
    if args.include_book4:
        urls += [BASE + f"argonautica-iv-{range_}" for range_ in BOOK4_RANGES]
    files = []
    records = []
    for number, url in enumerate(urls):
        slug = url.rsplit("/", 1)[-1]
        raw, digest = fetch(url, RAW / f"{slug}.html", from_cache=args.from_cache)
        page_records = parse_page(url, raw, digest, kind="pythian" if number == 0 else "book4")
        files.append({"url": url, "raw_path": raw.relative_to(ROOT).as_posix(), "raw_sha256": digest, "records": len(page_records)})
        records.extend(page_records)
        time.sleep(0.35)
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate record IDs")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter("Pythian 4" if "pindar-pythian-4" in r["id"] else "Book 4 lyric reference" for r in records)
    existing_texts = set()
    for other in OUTPUT.parent.glob("*.jsonl"):
        if other == OUTPUT:
            continue
        with other.open(encoding="utf-8") as source:
            for line in source:
                try:
                    existing_texts.add(json.loads(line).get("text"))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid existing JSONL {other}: {exc}") from exc
    report = {
        "collector": "p2_scholarship",
        "source_family": "Dickinson College Commentaries: Peter Hulse, Apollonius Argonautica Book 4",
        "rights_url": RIGHTS,
        "rights_raw_path": rights_raw.relative_to(ROOT).as_posix(),
        "rights_raw_sha256": rights_hash,
        "license": "CC BY-SA (version unspecified)",
        "raw_files": files,
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "records": len(records),
        "by_scope": dict(counts),
        "total_commentary_characters": sum(len(r["text"]) for r in records),
        "exact_duplicate_texts_vs_other_processed_files": sum(r["text"] in existing_texts for r in records),
        "new_ancient_greek_passages": 0,
        "new_commentary_passages": len(records),
        "download_failures": [],
        "unresolved_rights": ["DCC terms give CC BY-SA without a version number; preserve that scope."],
        "limitations": [
            "Ancient text and translation on the DCC page are not staged as new witnesses.",
            "Book 4 notes are selected by explicit lyric-name mention; nearby context may require reading the full page.",
            "The source states that Apollonius knew Pindar, but this collector does not independently infer intertextual edges.",
            "No digital license version is specified on the DCC terms page.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "by_scope": dict(counts), "raw_files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
