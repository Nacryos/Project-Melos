"""Download (pinned) and stage Dodson's Greek Lexicon as entries.jsonl rows.

Run:  python -I scripts/ingest_dodson_lexicon.py [--download]

Source: github.com/biblicalhumanities/Dodson-Greek-Lexicon at a pinned commit,
file dodson.xml (TEI-like, one <entry n="lemma | Strong's no."> with <orth>,
<def role="brief"> and <def role="full">). Licence: the repository LICENSE is
CC0 1.0 and the README states "This lexicon, in all of its forms, is in the
public domain." Dodson is a New Testament lexicon: its glosses describe Koine
usage. Melos therefore ranks it last and only as a fallback short gloss.

Each raw file is verified against the git blob SHA-1 listed in the pinned
commit's tree. Nothing is authored; definitions are copied verbatim
(whitespace collapsed).
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.request import Request, urlopen

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "biblicalhumanities/Dodson-Greek-Lexicon"
COMMIT = "74f70358d4acfaf2f980bf2feb58ab7115cbbcbc"   # 2018-01-11 "Normalized to NFKC."
RAW_DIR = ROOT / "data" / "raw" / "lexica" / f"dodson-{COMMIT[:12]}"
STAGING = ROOT / "data" / "staging" / "lexica"
LABEL = "Dodson Greek Lexicon (NT; public domain)"
LICENSE = "CC0-1.0"
ATTRIBUTION = ("John Jeffrey Dodson, A Greek Lexicon (public domain); XML by Ulrik Sandborg-Petersen and "
               "biblicalhumanities.org (github.com/biblicalhumanities/Dodson-Greek-Lexicon, CC0 1.0)")
USER_AGENT = "melos-source-ingestion/1.0 (research corpus)"
ENTRY = re.compile(rb"<entry\b[^>]*>.*?</entry>", re.S)
SPACE = re.compile(r"\s+")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
FILES = ("dodson.xml", "LICENSE", "README.md")


def _get(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, **({"Accept": accept} if accept else {})}
    with urlopen(Request(url, headers=headers), timeout=300) as response:
        return response.read()


def git_blob_sha1(body: bytes) -> str:
    return hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()


def download() -> dict:
    tree = json.loads(_get(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}",
                           "application/vnd.github+json"))
    blobs = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"repository": REPOSITORY, "commit": COMMIT, "files": {}}
    for name in FILES:
        body = _get(f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{name}")
        if git_blob_sha1(body) != blobs[name]:
            raise RuntimeError(f"Git blob checksum mismatch: {name}")
        (RAW_DIR / name).write_bytes(body)
        manifest["files"][name] = {"git_blob_sha1": blobs[name], "bytes": len(body),
                                   "sha256": hashlib.sha256(body).hexdigest()}
    (RAW_DIR / "download-manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def compact(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = download() if args.download else json.loads(
        (RAW_DIR / "download-manifest.json").read_text(encoding="utf-8"))
    path = RAW_DIR / "dodson.xml"
    body = path.read_bytes()
    if git_blob_sha1(body) != manifest["files"]["dodson.xml"]["git_blob_sha1"]:
        raise RuntimeError("dodson.xml changed since download")
    digest = manifest["files"]["dodson.xml"]["sha256"]
    rel = path.relative_to(ROOT).as_posix()
    source_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/dodson.xml"
    counters: Counter = Counter()
    STAGING.mkdir(parents=True, exist_ok=True)
    with (STAGING / "dodson.entries.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for match in ENTRY.finditer(body):
            counters["entries_seen"] += 1
            entry = etree.fromstring(match.group(0))
            n = entry.get("n") or ""
            lemma, _, number = (part.strip() for part in n.partition("|"))
            lemma = unicodedata.normalize("NFC", lemma)
            if not GREEK.search(lemma) or not number:
                counters["skipped_no_greek_lemma_or_number"] += 1
                continue
            defs = {d.get("role"): compact("".join(d.itertext())) for d in entry.iter("def")}
            orth = entry.find("orth")
            out.write(json.dumps({
                "id": f"dodson:{number}", "lemma": lemma, "lemma_beta": None,
                "headword_printed": unicodedata.normalize("NFC", compact("".join(orth.itertext()))) if orth is not None else None,
                "gloss": defs.get("brief", ""), "entry_text": compact("".join(entry.itertext())),
                "entry_text_encoding": "Unicode (source, NFKC)", "language": "en",
                "source": LABEL, "source_url": source_url, "raw_path": rel, "raw_sha256": digest,
                "license": LICENSE, "attribution": ATTRIBUTION, "entry_id": number, "entry_url": None,
                "senses": [{"role": role, "text": text} for role, text in defs.items()],
                "locator": {"xpath": f'//entry[@n="{n}"]', "byte_start": match.start(), "byte_end": match.end()},
            }, ensure_ascii=False) + "\n")
            counters["entries_written"] += 1
            counters["entries_without_brief_def"] += not defs.get("brief")
    summary = {"source": LABEL, "repository": REPOSITORY, "commit": COMMIT, "license": LICENSE,
               "attribution": ATTRIBUTION, "raw_sha256": digest, "raw_bytes": len(body), "counts": dict(counters)}
    (STAGING / "dodson.manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
