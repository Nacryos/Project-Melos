"""Collect Greek lyric, elegy and iambus from the Eulogikon ancient-greek-texts repository.

Source: https://github.com/eulogikon/ancient-greek-texts (Public Domain Mark 1.0
as asserted by the publisher; 1,358 authors, 4,060 works in clean Unicode).
Eulogikon normalises and merges several digital copies of each work and does
not record which printed edition contributed a line; its work titles are the
site's own groupings, not edition titles. Both facts are recorded on every
record. The corpus is admitted under the owner decision of 2026-09-30
(docs/decisions.md); a missing edition name is metadata, not a gate.

The repository is pinned to a commit. Raw Markdown and the manifest are saved
with SHA-256 hashes before parsing. No Greek is authored or repaired here.

Usage:
  python scripts/ingest_p2_eulogikon.py                 # archaic lyric/elegy/iambus poets
  python scripts/ingest_p2_eulogikon.py --all-poetry    # every author in Eulogikon's Poetry domain
  python scripts/ingest_p2_eulogikon.py --author pindar --author bacchylides-of-ceos
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_eulogikon"
OUT = ROOT / "data/processed/p2_eulogikon.jsonl"
REPORT = ROOT / "data/reports/p2_eulogikon.json"
SOURCE = "p2_eulogikon"
REPO = "eulogikon/ancient-greek-texts"
API = f"https://api.github.com/repos/{REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
SITE = "https://eulogikon.org"
LICENSE = "Public Domain Mark 1.0 (asserted by Eulogikon; https://creativecommons.org/publicdomain/mark/1.0/)"
PROVENANCE_WARNING = ("Eulogikon normalises and merges multiple digital copies of a work without recording "
                      "which copy contributed each line, and does not name the printed edition; "
                      f"see {SITE}/sources.")
# Archaic and classical lyric, elegiac and iambic poets, matched against
# Eulogikon's English author names in any domain: the site files Theognis of
# Megara and Timotheus of Miletus under History, Pratinas under Drama and
# Xenophanes under Philosophy. --all-poetry adds the whole Poetry domain.
DEFAULT_AUTHORS = re.compile(
    r"\b(Ibycus|Stesichorus|Alcaeus of Mytilene|Alcman|Anacreon|Anacreontea|Archilochus|Bacchylides|Corinna|"
    r"Erinna|Hipponax|Mimnermus|Pindar|Praxilla|Sappho|Semonides|Simonides of Ceos|Solon of Athens|Telesilla|"
    r"Theognis of Megara|Timocreon|Tyrtaeus|Callinus|Lasus of Hermione|Terpander|Pratinas of Phlius|"
    r"Timotheus of Miletus|Telestes|Philoxenus of Cythera|Ananius|Xenophanes of Colophon|Carmina|Scolia|"
    r"Lyrica Adespota)\b", re.IGNORECASE)
MARKER = re.compile(r"\[(ln_\d+|para)\]")
# Eulogikon files scholia and testimonia as ordinary works ("Pindar Commentary",
# "Testimonies"). Their words are not the poet's; the record kind says so.
COMMENTARY_TITLE = re.compile(r"commentar|scholia|σχόλια|ὑπόμνημα", re.IGNORECASE)
REFERENCE_TITLE = re.compile(r"testimon|\blife of\b|\bvita\b|μαρτυρ|βίος", re.IGNORECASE)


def record_kind(author_name: str, title: str) -> str:
    label = f"{author_name} {title}"
    if COMMENTARY_TITLE.search(label):
        return "commentary"
    if REFERENCE_TITLE.search(label):
        return "reference"
    return "text"
HEADING = re.compile(r"^### (.+?)\s*$", re.MULTILINE)
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "melos-eulogikon-collector/1.0 (research corpus; pinned cached fetches)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str, path: Path, *, delay: float) -> bytes:
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=90)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty response")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            time.sleep(delay)
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed for {url}: {error}")


def frontmatter(markdown: str) -> tuple[dict, str]:
    if not markdown.startswith("---"):
        return {}, markdown
    end = markdown.find("\n---", 3)
    if end < 0:
        return {}, markdown
    fields: dict[str, str] = {}
    for line in markdown[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields, markdown[end + 4:]


def chunks(body: str) -> list[dict]:
    """Passages under `### heading` lines after `## Text`, with line markers resolved."""
    start = body.find("## Text")
    text_body = body[start + len("## Text"):] if start >= 0 else body
    parts = HEADING.split(text_body)
    output: list[dict] = []
    # parts = [preamble, heading1, text1, heading2, text2, ...]
    for index in range(1, len(parts) - 1, 2):
        heading = parts[index].strip()
        raw = parts[index + 1].strip()
        if not raw or not GREEK.search(raw):
            continue
        markers: list[dict] = []
        pieces: list[str] = []
        position = 0
        for match in MARKER.finditer(raw):
            pieces.append(raw[position:match.start()])
            token = match.group(1)
            if token == "para":
                pieces.append("\n\n")
            else:
                pieces.append("\n")
                markers.append({"label": token.removeprefix("ln_"), "offset": sum(len(piece) for piece in pieces)})
            position = match.end()
        pieces.append(raw[position:])
        text = re.sub(r"[ \t]+\n", "\n", "".join(pieces)).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        output.append({"heading": heading, "text": text, "line_markers": markers})
    return output


def select_authors(manifest: dict, pattern: re.Pattern | None, all_poetry: bool, extra: set[str]) -> list[dict]:
    chosen = []
    for author in manifest.get("authors", []):
        slug = author.get("author_display_string", "")
        name = author.get("name_english", "")
        domain = author.get("domain", "")
        if slug in extra:
            chosen.append(author)
        elif all_poetry and domain == "Poetry":
            chosen.append(author)
        elif pattern and pattern.search(name):
            chosen.append(author)
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", help="pin to this full commit SHA instead of the branch head")
    parser.add_argument("--all-poetry", action="store_true", help="collect every author in the Poetry domain")
    parser.add_argument("--author", action="append", default=[], help="Eulogikon author slug to add (repeatable)")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--limit-works", type=int, default=0, help="stop after N works (smoke test)")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.commit:
        commit = args.commit
    else:
        head = get(f"{API}/commits/HEAD", RAW / f"head-{datetime.now(timezone.utc):%Y%m%d}.json", delay=args.delay)
        commit = json.loads(head)["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full 40-character SHA")
    pinned = RAW / commit
    manifest_raw = get(f"{RAW_BASE}/{commit}/manifest.json", pinned / "manifest.json", delay=args.delay)
    manifest = json.loads(manifest_raw)
    readme_raw = get(f"{RAW_BASE}/{commit}/README.md", pinned / "README.md", delay=args.delay)
    authors = select_authors(manifest, None if args.all_poetry else DEFAULT_AUTHORS, args.all_poetry, set(args.author))
    if not authors:
        raise ValueError("No Eulogikon authors matched the selection")
    records: list[dict] = []
    files: list[dict] = []
    failures: list[dict] = []
    work_count = 0
    for author in authors:
        for work in author.get("works", []):
            if args.limit_works and work_count >= args.limit_works:
                break
            md_path = work.get("files", {}).get("md")
            if not md_path or not md_path.startswith("grc/"):
                continue
            work_count += 1
            url = f"{RAW_BASE}/{commit}/{md_path}"
            local = pinned / md_path
            try:
                content = get(url, local, delay=args.delay)
                fields, body = frontmatter(content.decode("utf-8"))
                passages = chunks(body)
            except Exception as exc:  # noqa: BLE001 - logged per work, collection continues
                failures.append({"work": work.get("eul_wid"), "url": url, "error": str(exc)})
                print(f"FAILED {md_path}: {exc}", flush=True)
                continue
            digest = sha256(content)
            raw_rel = local.relative_to(ROOT).as_posix()
            files.append({"path": md_path, "url": url, "raw_path": raw_rel, "raw_sha256": digest,
                          "passages": len(passages), "manifest_passages": work.get("passages")})
            author_label = fields.get("author") or author.get("name_english") or author.get("author_display_string")
            title = work.get("title_english") or fields.get("title") or work.get("work_display_string")
            title_greek = work.get("title_greek") or fields.get("title_greek") or ""
            kind = record_kind(author_label, title)
            for ordinal, passage in enumerate(passages, 1):
                # Eulogikon repeats headings such as "book 1a.1" for every
                # fragment, so the ordinal keeps citations distinct.
                citation = f"{passage['heading']} §{ordinal}"
                records.append({
                    "id": f"{SOURCE}:{work['eul_wid']}:{ordinal}", "source": SOURCE, "source_url": url,
                    "raw_path": raw_rel, "raw_sha256": digest,
                    "author": author_label, "work": f"{title} ({title_greek})" if title_greek else title,
                    "edition": "Eulogikon normalised aggregate; printed edition unspecified",
                    "citation": citation, "language": "grc", "text": passage["text"], "kind": kind,
                    "quality": "source_text", "license": LICENSE,
                    "metadata": {
                        "eul_aid": author.get("eul_aid"), "eul_wid": work.get("eul_wid"),
                        "eulogikon_author_name_greek": author.get("name_greek"),
                        "eulogikon_work_title_english": title, "eulogikon_work_title_greek": title_greek,
                        "eulogikon_canonical_url": fields.get("canonical") or f"{SITE}/works/{work.get('work_display_string')}-{work.get('eul_wid')}",
                        "period": fields.get("period") or author.get("period"),
                        "dialect_label_from_source": fields.get("dialect") or author.get("dialect"),
                        "domain": author.get("domain"), "format": fields.get("format") or author.get("format"),
                        "source_heading": passage["heading"], "heading_ordinal": ordinal,
                        "line_markers": passage["line_markers"],
                        "provenance_warning": PROVENANCE_WARNING,
                        "upstream_commit": commit,
                    },
                })
            print(f"{author_label}: {title} -> {len(passages)} passages", flush=True)
    if not records:
        raise RuntimeError("No records collected; output not written")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(OUT)
    report = {
        "status": "collected_pending_index_acceptance",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_repository": f"https://github.com/{REPO}", "upstream_commit": commit,
        "manifest_sha256": sha256(manifest_raw), "readme_sha256": sha256(readme_raw),
        "license": LICENSE, "provenance_warning": PROVENANCE_WARNING,
        "policy": "docs/decisions.md 2026-09-30: texts without a named printed edition admitted; edition recorded as unspecified",
        "selection": "all Poetry-domain authors" if args.all_poetry else f"Poetry-domain authors matching {DEFAULT_AUTHORS.pattern}" + (f" plus {sorted(args.author)}" if args.author else ""),
        "authors_selected": [{"eul_aid": a.get("eul_aid"), "name": a.get("name_english"), "works": len(a.get("works", []))} for a in authors],
        "files": files, "failures": failures,
        "record_count": len(records),
        "counts_by_kind": dict(Counter(r["kind"] for r in records)),
        "counts_by_author": dict(Counter(r["author"] for r in records)),
        "output": OUT.relative_to(ROOT).as_posix(), "output_sha256": sha256(OUT.read_bytes()),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records from {len(files)} works ({len(authors)} authors) to {OUT}; {len(failures)} failures", flush=True)


if __name__ == "__main__":
    main()
