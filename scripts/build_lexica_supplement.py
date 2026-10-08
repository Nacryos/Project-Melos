"""Merge the staged open lexica into data/lexica/supplement-entries.jsonl.

Run (after the three staging scripts):
  python -I scripts/ingest_perseus_lexica.py           # Middle Liddell, Cunliffe
  python -I scripts/ingest_logeion_lsj.py --download   # LSJ, Logeion edition
  python -I scripts/ingest_dodson_lexicon.py --download
  python -I scripts/build_lexica_supplement.py
  python -I scripts/audit_lexica_supplement.py         # independent re-check -> PASS report

The production files entries.jsonl / forms.jsonl are not modified. The
supplement holds one row per source entry in the production entries schema,
plus a byte ``locator`` into the pinned raw XML. ``gloss`` is the first
English definition span that backend.lexicon_senses extracts from that raw
entry (the same extractor the reader uses), or "" when it finds none; no gloss
is written by hand or by a model.

LSJ (Logeion edition) rows are linked to the production Perseus LSJ row with
the same original Perseus entry id (``orig_id``) and the same NFC headword:
``perseus_lsj_id`` on the Logeion row. backend.morphology then shows the
Logeion text in place of that Perseus row; the Perseus row keeps its id.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.lexicon_senses import dictionary_senses  # noqa: E402

STAGING = ROOT / "data" / "staging" / "lexica"
OUTPUT = ROOT / "data" / "lexica" / "supplement-entries.jsonl"
MANIFEST = ROOT / "data" / "lexica" / "supplement.manifest.json"
PRODUCTION = ROOT / "data" / "lexica" / "entries.jsonl"
FIELDS = ("id", "lemma", "lemma_beta", "gloss", "entry_text", "entry_text_encoding", "language",
          "source", "source_url", "entry_url", "raw_path", "raw_sha256", "license", "attribution",
          "entry_id", "locator")
LICENSES = {
    "Perseus Middle Liddell TEI (Hopper open-source texts)": (
        "CC-BY-SA-3.0-US",
        "Liddell & Scott, An Intermediate Greek-English Lexicon (Oxford 1889); Perseus Digital Library, "
        "Tufts University (Hopper open-source texts, CC BY-SA 3.0 US)"),
    "Perseus Cunliffe TEI via Homerica": (
        "unknown",
        "R. J. Cunliffe, A Lexicon of the Homeric Dialect (London 1924); Perseus TEI ed. G. Crane, "
        "corrected by H. Dik (github.com/gregorycrane/Homerica; no licence file)"),
}
ORDER = ("middle-liddell", "lsj-logeion", "cunliffe", "dodson")
XML_ID = re.compile(rb'<div\b[^>]*\bxml:id="([^"]+)"[^>]*>')
DIV_TAG = re.compile(rb"<(/?)div\b[^>]*?(/?)>")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def cunliffe_offsets(raw: Path) -> dict[str, tuple[int, int]]:
    """Byte ranges of every top-level entry <div> (nesting-aware)."""
    body = raw.read_bytes()
    start_body = body.index(b"<body")
    result, depth, opened = {}, 0, None
    for match in DIV_TAG.finditer(body, start_body):
        closing, selfclosing = match.group(1), match.group(2)
        if selfclosing:
            continue
        if not closing:
            if depth == 0:
                identity = XML_ID.match(body, match.start())
                opened = (identity.group(1).decode() if identity else None, match.start())
            depth += 1
        else:
            depth -= 1
            if depth == 0 and opened and opened[0]:
                result[opened[0]] = (opened[1], match.end())
    return result


def perseus_lsj_index() -> dict[str, dict]:
    index = {}
    with PRODUCTION.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("source") == "PerseusDL LSJ TEI":
                index[row["entry_id"]] = {"id": row["id"], "lemma": row["lemma"]}
    return index


def rows(name: str):
    with (STAGING / f"{name}.entries.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="rows per source (testing only)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    began = time.time()
    perseus = perseus_lsj_index()
    cunliffe_ranges: dict[str, tuple[int, int]] = {}
    counts: dict[str, Counter] = {name: Counter() for name in ORDER}
    statuses: dict[str, Counter] = {name: Counter() for name in ORDER}
    raw_files: dict[str, dict] = {}
    tmp = OUTPUT.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        for name in ORDER:
            for index, row in enumerate(rows(name)):
                if args.limit and index >= args.limit:
                    break
                record = {key: row.get(key) for key in FIELDS}
                if name == "middle-liddell":
                    # Unicode rendering of the Beta Code Greek spans (same converter as
                    # the renderer); the raw Beta Code text stays in the staging file.
                    record["entry_text"] = row["entry_text_unicode"]
                    record["entry_text_encoding"] = "Unicode (Greek spans rendered from Perseus Beta Code)"
                    record["key"] = row.get("key")
                if row["source"] in LICENSES:
                    record["license"], record["attribution"] = LICENSES[row["source"]]
                if name == "cunliffe":
                    if not cunliffe_ranges:
                        cunliffe_ranges = cunliffe_offsets(ROOT / row["raw_path"])
                    span = cunliffe_ranges.get(row["entry_id"])
                    if not span:
                        counts[name]["skipped_no_byte_range"] += 1
                        continue
                    record["locator"] = {"xpath": row["locator"]["xpath"], "byte_start": span[0],
                                         "byte_end": span[1]}
                    record["headword_printed"] = row.get("headword_printed")
                if name == "lsj-logeion":
                    record["lemma_beta"] = None   # the Logeion key keeps Perseus homograph digits
                    record["key"] = row.get("key")
                    record["orig_id"] = row.get("orig_id")
                    target = perseus.get(row.get("orig_id") or "")
                    if target and unicodedata.normalize("NFC", target["lemma"]) == record["lemma"]:
                        record["perseus_lsj_id"] = target["id"]
                        counts[name]["linked_to_perseus_lsj"] += 1
                    elif target:
                        counts[name]["orig_id_headword_differs"] += 1
                    else:
                        counts[name]["no_perseus_counterpart"] += 1
                record["language"] = "en"
                record["lemma"] = unicodedata.normalize("NFC", record["lemma"])
                senses = dictionary_senses(record)
                status = senses.get("dictionary_senses_status")
                statuses[name][status] += 1
                found = senses.get("dictionary_senses") or []
                record["gloss"] = found[0]["text"] if found else ""
                record["gloss_method"] = ("first extracted definition span (backend.lexicon_senses "
                                          + str(found[0]["extraction_method"]) + ")") if found else None
                if status not in ("source_structured", "no_safe_definition_spans"):
                    counts[name]["unreadable_" + str(status)] += 1
                    continue
                raw_files.setdefault(record["raw_path"], {"sha256": record["raw_sha256"]})
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                counts[name]["entries_written"] += 1
                counts[name]["entries_with_gloss"] += bool(found)
            print(name, dict(counts[name]), dict(statuses[name]), f"{time.time() - began:.0f}s", flush=True)
    tmp.replace(OUTPUT)
    for rel, meta in raw_files.items():
        path = ROOT / rel
        meta["bytes"] = path.stat().st_size
        if sha256(path) != meta["sha256"]:
            raise RuntimeError(f"Raw file hash changed during build: {rel}")
    manifest = {"output": OUTPUT.relative_to(ROOT).as_posix(), "sha256": sha256(OUTPUT),
                "bytes": OUTPUT.stat().st_size, "built_at_unix": time.time(),
                "sources": {name: {"counts": dict(counts[name]),
                                   "sense_status": dict(statuses[name])} for name in ORDER},
                "raw_files": raw_files,
                "staging_manifests": {p.name: sha256(p) for p in sorted(STAGING.glob("*.manifest.json"))},
                "limit": args.limit or None}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "raw_files"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
