#!/usr/bin/env python3
"""Tally lyric text coverage and emit deterministic reviewer packets.

Read-only input: data/corpus.sqlite. No downloads or generated text are used.
Run from project root: python scripts/tally_visual_candidates.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.author_aliases import canonical  # noqa: E402

POETS = ("Archilochus", "Alcman", "Sappho", "Alcaeus", "Stesichorus",
         "Ibycus", "Anacreon", "Simonides", "Pindar", "Bacchylides")


def count_query(db, sql, args=()):
    return db.execute(sql, args).fetchone()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", type=Path, default=ROOT / "data/corpus.sqlite")
    ap.add_argument("--output", type=Path, default=ROOT / ".benchmarks/visual-themes")
    ap.add_argument("--packet-chars", type=int, default=80000,
                    help="maximum text characters in each reviewer packet")
    ap.add_argument("--tally-only", action="store_true", help="refresh tally without touching reviewer packets")
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.database.resolve().as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    all_greek = [dict(zip(("quality", "passages", "authors", "works"), row)) for row in db.execute(
        "SELECT quality,count(*),count(DISTINCT author_canonical),count(DISTINCT work_id) "
        "FROM passages WHERE kind='text' AND language='grc' GROUP BY quality ORDER BY quality")]
    all_english = [dict(zip(("quality", "passages", "translation_author_labels", "works", "linked_greek_parent_passages", "linked_greek_authors", "linked_greek_works"), row))
        for row in db.execute(
        "SELECT t.quality,count(*),count(DISTINCT t.author_canonical),count(DISTINCT t.work_id),"
        "sum(p.id IS NOT NULL),count(DISTINCT p.author_canonical),count(DISTINCT p.work_id) "
        "FROM passages t LEFT JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') "
        "AND p.kind='text' AND p.language='grc' WHERE t.kind='translation' "
        "AND lower(t.language) IN ('en','eng') GROUP BY t.quality ORDER BY t.quality")]
    all_modern_greek = [dict(zip(("quality", "passages", "linked_greek_parent_passages", "linked_greek_authors", "linked_greek_works"), row))
        for row in db.execute("SELECT t.quality,count(*),sum(p.id IS NOT NULL),count(DISTINCT p.author_canonical),count(DISTINCT p.work_id) FROM passages t LEFT JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') AND p.kind='text' AND p.language='grc' WHERE t.kind='translation' AND lower(t.language) IN ('el','ell') GROUP BY t.quality ORDER BY t.quality")]
    core = {}
    for poet in POETS:
        row = db.execute("SELECT "
            "sum(kind='text' AND language='grc' AND quality='source_text'),"
            "sum(kind='text' AND language='grc' AND quality='machine_corrected_ocr'),"
            "count(DISTINCT CASE WHEN kind='text' AND language='grc' AND quality='source_text' THEN work_id END),"
            "count(DISTINCT CASE WHEN kind='text' AND language='grc' AND quality='source_text' THEN text_key END),"
            "sum(kind='translation' AND lower(language) IN ('en','eng') AND quality='source_text'),"
            "count(DISTINCT CASE WHEN kind='translation' AND lower(language) IN ('en','eng') AND quality='source_text' THEN work_id END),"
            "sum(kind='translation' AND lower(language) IN ('el','ell') AND quality='source_text') "
            "FROM passages WHERE author_canonical=?", (poet,)).fetchone()
        modern = db.execute("SELECT count(*),count(DISTINCT t.work_id) FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') WHERE p.author_canonical=? AND p.kind='text' AND p.language='grc' AND t.kind='translation' AND lower(t.language) IN ('el','ell') AND t.quality='source_text'", (poet,)).fetchone()
        english = db.execute("SELECT count(*),count(DISTINCT t.work_id) FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') WHERE p.author_canonical=? AND p.kind='text' AND p.language='grc' AND t.kind='translation' AND lower(t.language) IN ('en','eng') AND t.quality='source_text'", (poet,)).fetchone()
        core[poet] = dict(zip(("greek_source_text_passages", "greek_machine_corrected_ocr_passages",
            "greek_source_text_works", "greek_source_text_distinct_text_keys",
            "english_source_text_passages", "english_source_text_works", "modern_greek_source_text_passages"), row))
        core[poet]["english_source_text_passages"], core[poet]["english_source_text_works"] = english
        core[poet]["modern_greek_source_text_passages"], core[poet]["modern_greek_source_text_works"] = modern
    sql = "SELECT id,work_id,author_canonical,work,citation,language,kind,quality,text,text_key,data FROM passages WHERE author_canonical=? AND kind='text' AND language='grc' AND quality='source_text' ORDER BY work_id,citation,id"
    packet = []
    seen_exact = set()
    for poet in POETS:
        for row in db.execute(sql, (poet,)):
            # Exact repeat removal is scoped to canonical author + work + citation;
            # fragment numbers and alternate work/citation loci remain distinct.
            exact_key = (poet, row["work_id"], row["citation"], row["text"])
            if exact_key in seen_exact:
                continue
            seen_exact.add(exact_key)
            data = json.loads(row["data"] or "{}")
            packet.append({"id": row["id"], "author": canonical(poet), "work_id": row["work_id"],
                "work": row["work"], "citation": row["citation"], "language": "grc",
                "kind": "text", "quality": "source_text", "text": row["text"],
                "source": data.get("source"), "source_url": data.get("source_url"),
                "note": "Aesthetic nature setting only; ignore poem subject."})
    # Include every confidently catalogued English segment available for the ten poets.
    placeholders = ",".join("?" for _ in POETS)
    for row in db.execute(f"SELECT t.id,t.work_id,p.author_canonical,t.work,t.citation,t.language,t.kind,t.quality,t.text,t.data,json_extract(t.data,'$.parent_id') parent_id FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') WHERE p.author_canonical IN ({placeholders}) AND p.kind='text' AND p.language='grc' AND t.kind='translation' AND lower(t.language) IN ('en','eng') AND t.quality='source_text' ORDER BY p.author_canonical,t.work_id,t.citation,t.id", POETS):
        data = json.loads(row["data"] or "{}")
        packet.append({"id": row["id"], "author": canonical(row["author_canonical"]),
            "work_id": row["work_id"], "work": row["work"], "citation": row["citation"],
            "language": row["language"], "kind": "translation", "quality": "source_text",
            "parent_id": data.get("parent_id"), "text": row["text"], "source": data.get("source"), "source_url": data.get("source_url"),
            "note": "Aesthetic nature setting only; ignore poem subject."})
    # Modern Greek translations are included only when their actual Greek parent
    # is one of the ten app poets, independent of the translation-side author label.
    for row in db.execute("SELECT t.id,t.work_id,p.author_canonical,t.work,t.citation,t.language,t.kind,t.quality,t.text,t.data,json_extract(t.data,'$.parent_id') parent_id FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id') WHERE p.author_canonical IN (%s) AND t.kind='translation' AND lower(t.language) IN ('el','ell') AND t.quality='source_text' ORDER BY p.author_canonical,t.work_id,t.citation,t.id" % placeholders, POETS):
        data = json.loads(row["data"] or "{}")
        packet.append({"id": row["id"], "author": canonical(row["author_canonical"]),
            "work_id": row["work_id"], "work": row["work"], "citation": row["citation"],
            "language": row["language"], "kind": "translation", "quality": "source_text",
            "parent_id": row["parent_id"], "text": row["text"], "source": data.get("source"),
            "source_url": data.get("source_url"), "note": "Aesthetic nature setting only; ignore poem subject."})
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"database": str(args.database), "scope": "passage/work records, not manuscripts; author_canonical from indexed corpus; no inference of translation quality beyond source_text metadata",
        "all_corpus": {"greek_text_by_quality": all_greek, "explicit_english_translation_by_quality": all_english, "explicit_modern_greek_translation_by_quality": all_modern_greek},
        "core_ten_app_poets": core,
        "core_ten_totals": {"greek_source_text_passages": sum(x["greek_source_text_passages"] or 0 for x in core.values()),
            "greek_source_text_distinct_text_keys_per_author": sum(x["greek_source_text_distinct_text_keys"] or 0 for x in core.values()),
            "greek_source_text_works_per_author": sum(x["greek_source_text_works"] or 0 for x in core.values()),
            "english_source_text_passages": sum(x["english_source_text_passages"] or 0 for x in core.values()),
            "english_source_text_works_per_author": sum(x["english_source_text_works"] or 0 for x in core.values()),
            "modern_greek_source_text_passages": sum(x["modern_greek_source_text_passages"] or 0 for x in core.values()),
            "modern_greek_source_text_works_per_author": sum(x["modern_greek_source_text_works"] or 0 for x in core.values())},
        "review_packet": {"greek_records": len(packet) - sum(1 for x in packet if x["kind"] == "translation"), "all_available_english_translation_records": sum(1 for x in packet if x["kind"] == "translation" and x["language"] in ("en", "eng")), "all_available_modern_greek_translation_records": sum(1 for x in packet if x["kind"] == "translation" and x["language"] in ("el", "ell")), "distinct_poets": len(POETS), "max_chars_per_packet": args.packet_chars}}
    (args.output / "tally.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    batches, batch, chars = [], [], 0
    if not args.tally_only:
        packet_dir = args.output / "packets"
        packet_dir.mkdir(parents=True, exist_ok=True)
        for record in packet:
            size = len(record["text"])
            if batch and chars + size > args.packet_chars:
                batches.append(batch)
                batch, chars = [], 0
            batch.append(record)
            chars += size
        if batch:
            batches.append(batch)
        for old in packet_dir.glob("packet-*.json"):
            old.unlink()
        for i, records in enumerate(batches, 1):
            (packet_dir / f"packet-{i:02d}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"core_ten_totals": report["core_ten_totals"], "review_packet": report["review_packet"], "packet_files": len(batches)}, indent=2))
    db.close()


if __name__ == "__main__":
    main()
