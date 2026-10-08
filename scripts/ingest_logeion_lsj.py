"""Download (pinned) and stage Helma Dik's LSJLogeion as entries.jsonl rows.

Run:  python -I scripts/ingest_logeion_lsj.py [--download] [--report]

Source: github.com/helmadik/LSJLogeion at a pinned commit, "the heavily edited
local Chicago version of the Perseus LSJ; all Greek converted to Unicode"
(README). Licence: CC BY-SA 4.0 (LICENSE.md); credit requested for
"Perseus Tufts *and* Helma Dik/Logeion". This is the LSJ text that Logeion
serves; nothing is fetched from logeion.uchicago.edu itself.

Each raw file is verified against the git blob SHA-1 listed in the pinned
commit's tree before it is written, and its SHA-256 is recorded. Nothing is
authored: entry and sense text are the whitespace-normalised text content of
the TEI nodes. Output: data/staging/lexica/lsj-logeion.entries.jsonl (+ xrefs)
and a manifest. Production data/lexica/ is untouched; see
scripts/build_lexica_supplement.py for the merge.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html.entities import html5 as HTML5_ENTITIES
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.request import Request, urlopen

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "helmadik/LSJLogeion"
COMMIT = "6aa48692192db739fc7377e8783249b044624ac5"   # 2026-10-04 "last Pfeiffers"
RAW_DIR = ROOT / "data" / "raw" / "lexica" / f"lsj-logeion-{COMMIT[:12]}"
STAGING = ROOT / "data" / "staging" / "lexica"
USER_AGENT = "melos-source-ingestion/1.0 (research corpus)"
LABEL = "LSJ (Logeion edition, H. Dik) TEI"
LICENSE = "CC-BY-SA-4.0"
ATTRIBUTION = ("Liddell-Scott-Jones, A Greek-English Lexicon (1940); Perseus Digital Library, "
               "Tufts University; edited Unicode edition by Helma Dik / Logeion, University of Chicago "
               "(github.com/helmadik/LSJLogeion, CC BY-SA 4.0)")
SPACE = re.compile(r"\s+")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
ENTRY = re.compile(rb"<div2\b[^>]*>.*?</div2>", re.S)
ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9_.:-]*);")


def _get(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    with urlopen(Request(url, headers=headers), timeout=600) as response:
        return response.read()


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def git_blob_sha1(body: bytes) -> str:
    return hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()


def download() -> dict:
    """Fetch every greatscottNN.xml at the pinned commit; verify blob SHA-1."""
    tree = json.loads(_get(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}",
                           "application/vnd.github+json"))
    files = sorted((item for item in tree["tree"]
                    if item["type"] == "blob" and (item["path"].endswith(".xml")
                                                   or item["path"] in ("LICENSE.md", "README.md"))),
                   key=lambda item: item["path"])
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"repository": REPOSITORY, "commit": COMMIT, "files": {}}
    for item in files:
        target = RAW_DIR / item["path"]
        if target.exists() and git_blob_sha1(target.read_bytes()) == item["sha"]:
            body = target.read_bytes()
        else:
            body = _get(f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{item['path']}")
            if git_blob_sha1(body) != item["sha"]:
                raise RuntimeError(f"Git blob checksum mismatch: {item['path']}")
            target.write_bytes(body)
        manifest["files"][item["path"]] = {"git_blob_sha1": item["sha"], "bytes": len(body),
                                           "sha256": sha256_bytes(body)}
    (RAW_DIR / "download-manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def compact(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def resolve_entities(fragment: bytes, unresolved: list[str]) -> bytes:
    text = fragment.decode("utf-8")

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return match.group(0)
        value = HTML5_ENTITIES.get(name + ";")
        if value is None:
            unresolved.append(name)
            return "&amp;" + name + ";"
        return value.replace("&", "&amp;").replace("<", "&lt;")
    return ENTITY.sub(repl, text).encode("utf-8")


def text_of(node) -> str:
    return compact("".join(node.itertext()))


def parse_file(path: Path, rel: str, digest: str, entries, xrefs, counters: Counter, seen: set) -> None:
    body = path.read_bytes()
    source_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{path.name}"
    for match in ENTRY.finditer(body):
        counters["entries_seen"] += 1
        unresolved: list[str] = []
        entry = etree.fromstring(resolve_entities(match.group(0), unresolved),
                                 etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False,
                                                 huge_tree=True, recover=False))
        entry_id = entry.get("id")
        head = entry.find("head")
        lemma = nfc(text_of(head)) if head is not None else ""
        if not entry_id or not GREEK.search(lemma):
            counters["entries_skipped_no_id_or_greek_head"] += 1
            continue
        if entry_id in seen:
            counters["duplicate_ids_skipped"] += 1
            continue
        seen.add(entry_id)
        senses = [{"sense_id": s.get("id"), "n": s.get("n"), "level": s.get("level"),
                   "text": compact("".join(s.itertext()))} for s in entry.iter("sense")]
        record = {"id": f"lsj-logeion:{entry_id}", "lemma": lemma, "lemma_beta": entry.get("key"),
                  "key": entry.get("key"), "orig_id": entry.get("orig_id"), "entry_type": entry.get("type"),
                  "gloss": "", "entry_text": compact("".join(entry.itertext())),
                  "entry_text_encoding": "Unicode (source)", "language": "en",
                  "source": LABEL, "source_url": source_url, "raw_path": rel, "raw_sha256": digest,
                  "license": LICENSE, "attribution": ATTRIBUTION, "entry_id": entry_id,
                  "entry_url": None, "senses": senses,
                  "locator": {"xpath": f'//div2[@id="{entry_id}"]', "byte_start": match.start(),
                              "byte_end": match.end()}}
        if unresolved:
            record["unresolved_entities"] = sorted(set(unresolved))
        entries.write(json.dumps(record, ensure_ascii=False) + "\n")
        counters["entries_written"] += 1
        counters["senses_written"] += len(senses)
        for ref in entry.iter("ref"):
            value = text_of(ref)
            if value:
                xrefs.write(json.dumps({"from_id": record["id"], "from_lemma": lemma, "ref_text": nfc(value),
                                        "target": ref.get("target"),
                                        "relation": "source cross-reference (TEI ref); not an inflection",
                                        "source": LABEL, "source_url": source_url, "raw_path": rel,
                                        "raw_sha256": digest, "license": LICENSE}, ensure_ascii=False) + "\n")
                counters["xrefs_written"] += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = download() if args.download else json.loads(
        (RAW_DIR / "download-manifest.json").read_text(encoding="utf-8"))
    STAGING.mkdir(parents=True, exist_ok=True)
    counters: Counter = Counter()
    seen: set = set()
    out_entries = STAGING / "lsj-logeion.entries.jsonl"
    out_xrefs = STAGING / "lsj-logeion.xrefs.jsonl"
    with out_entries.open("w", encoding="utf-8", newline="\n") as entries, \
            out_xrefs.open("w", encoding="utf-8", newline="\n") as xrefs:
        for name, meta in sorted(manifest["files"].items()):
            if not name.endswith(".xml"):
                continue
            path = RAW_DIR / name
            body = path.read_bytes()
            if git_blob_sha1(body) != meta["git_blob_sha1"]:
                raise RuntimeError(f"Raw file changed since download: {path}")
            rel = path.relative_to(ROOT).as_posix()
            parse_file(path, rel, meta["sha256"], entries, xrefs, counters, seen)
    summary = {"source": LABEL, "repository": REPOSITORY, "commit": COMMIT, "license": LICENSE,
               "attribution": ATTRIBUTION, "counts": dict(counters),
               "raw_files": len([n for n in manifest["files"] if n.endswith(".xml")]),
               "raw_bytes": sum(m["bytes"] for n, m in manifest["files"].items() if n.endswith(".xml"))}
    (STAGING / "lsj-logeion.manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
