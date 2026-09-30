#!/usr/bin/env python3
"""Summarize indexed records per author, merging spellings of one poet.

Run from the project root: python scripts/report_coverage.py
The input is the accepted SQLite index built by scripts/build_corpus.py. This
script neither downloads material nor writes corpus passages. Author labels
are merged through the owner alias table (data/author-aliases.json); every
exact source label stays listed beside its merged name.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.author_aliases import canonical, canonical_key, is_mixed  # noqa: E402

CORE_LABELS = (
    "Ibycus", "Alcaeus", "Sappho", "Pindar", "Bacchylides", "Alcman",
    "Stesichorus", "Simonides", "Anacreon", "Archilochus", "Mimnermus",
    "Solon", "Hipponax", "Theognis", "Semonides", "Timotheus", "Corinna",
    "Homer", "Hesiod", "Homeric Hymns",
)
REFERENCE_KINDS = {"commentary", "apparatus", "reference"}
SEARCHABLE_QUALITIES = ("source_text", "machine_corrected_ocr")


def counts(connection: sqlite3.Connection, column: str, where: str = "", args: tuple = ()) -> dict[str, int]:
    # column is supplied only from fixed calls below, never from CLI input.
    rows = connection.execute(
        f"SELECT {column},count(*) FROM passages {where} GROUP BY {column} ORDER BY {column}", args
    )
    return {str(label if label is not None else "unknown"): number for label, number in rows}


def author_summary(connection: sqlite3.Connection, author: str) -> dict:
    where = "WHERE author=?"
    args = (author,)
    kinds = counts(connection, "kind", where, args)
    clean = connection.execute(
        "SELECT count(*) FROM passages WHERE author=? AND kind='text' "
        "AND language='grc' AND quality='source_text'", args
    ).fetchone()[0]
    searchable = connection.execute(
        "SELECT count(*) FROM passages WHERE author=? AND kind='text' "
        "AND language='grc' AND quality IN ('source_text','machine_corrected_ocr')", args
    ).fetchone()[0]
    return {
        "author_label": author,
        "merged_author": canonical(author),
        "records": sum(kinds.values()),
        "text_records": kinds.get("text", 0),
        "translation_records": kinds.get("translation", 0),
        "commentary_reference_records": sum(kinds.get(kind, 0) for kind in REFERENCE_KINDS),
        "clean_greek_text_records": clean,
        "searchable_greek_text_records": searchable,
        "by_kind": kinds,
        "by_quality": counts(connection, "quality", where, args),
        "by_language": counts(connection, "language", where, args),
        "by_source": counts(connection, "source", where, args),
    }


SUMMED = ("clean_greek_text_records", "searchable_greek_text_records", "text_records",
          "translation_records", "commentary_reference_records", "records")


def merged_summary(name: str, items: list[dict]) -> dict:
    return {"merged_author": name, "labels": [item["author_label"] for item in items],
            **{key: sum(item[key] for item in items) for key in SUMMED}}


def report(db: Path) -> dict:
    if not db.is_file():
        raise FileNotFoundError(f"Accepted index not found: {db}")
    connection = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        manifest_row = connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if manifest_row is None:
            raise ValueError("Index metadata manifest is missing")
        manifest = json.loads(manifest_row[0])
        authors = [row[0] for row in connection.execute("SELECT DISTINCT author FROM passages ORDER BY author")]
        summaries = [author_summary(connection, label) for label in authors]
        indexed_count = sum(item["records"] for item in summaries)
        if indexed_count != manifest["passages"]:
            raise ValueError(f"Index/manifest count mismatch: {indexed_count} vs {manifest['passages']}")
        by_canonical: dict[str, list[dict]] = {}
        for item in summaries:
            by_canonical.setdefault(canonical_key(item["author_label"]), []).append(item)
        merged = [merged_summary(canonical(items[0]["author_label"]), items)
                  for items in by_canonical.values()]
        merged.sort(key=lambda item: (-item["searchable_greek_text_records"], item["merged_author"].casefold()))
        targets = []
        for name in CORE_LABELS:
            items = by_canonical.get(canonical_key(name), [])
            exact = [item for item in items if item["author_label"].casefold() == name.casefold()]
            candidates = [label for label in authors
                          if name.casefold() in label.casefold()
                          and canonical_key(label) != canonical_key(name)]
            summed = merged_summary(name, items) if items else None
            targets.append({
                "requested_name": name,
                "exact_label_match": bool(exact),
                "merged_label_match": bool(items),
                "matched_author_labels": [item["author_label"] for item in items],
                "unmerged_similar_labels": candidates,
                "label_counts": [{key: item[key] for key in (
                    "author_label", "clean_greek_text_records", "searchable_greek_text_records",
                    "text_records", "commentary_reference_records"
                )} for item in items],
                "clean_greek_text_records": summed["clean_greek_text_records"] if summed else None,
                "searchable_greek_text_records": summed["searchable_greek_text_records"] if summed else None,
                "text_records": summed["text_records"] if summed else None,
                "commentary_reference_records": summed["commentary_reference_records"] if summed else None,
            })
        return {
            "scope": "Accepted indexed records in corpus.sqlite; not unique fragments, witnesses, or works",
            "index_built_at": manifest.get("built_at"),
            "index_files": manifest.get("files", []),
            "total_records": indexed_count,
            "author_labels": len(authors),
            "merged_authors": len(merged),
            "by_source": counts(connection, "source"),
            "by_kind": counts(connection, "kind"),
            "by_quality": counts(connection, "quality"),
            "by_language": counts(connection, "language"),
            "core_targets": targets,
            "core_targets_exact_label_only": targets,
            "merged": merged,
            "authors": summaries,
            "limitations": [
                "Counts are records, not unique fragments or independent textual witnesses; identical copies are counted once per record, not once per text.",
                "A source_text quality label does not remove editorial supplements or establish manuscript certainty.",
                "Searchable Greek text adds machine-corrected OCR to clean source text; raw OCR, mixed and review-needed rows are excluded from both.",
                "Author merging follows data/author-aliases.json; labels naming several poets are never merged and are listed separately.",
                "Translations and commentary are counted separately from Greek text; source datasets may overlap.",
            ],
        }
    finally:
        connection.close()


def render_markdown(data: dict) -> str:
    clean_total = sum(item["clean_greek_text_records"] for item in data["authors"])
    searchable_total = sum(item["searchable_greek_text_records"] for item in data["authors"])
    lines = [
        "# Indexed corpus coverage", "",
        f"Index snapshot: {data['index_built_at'] or 'unknown build time'}. "
        f"The accepted SQLite index contains {data['total_records']:,} records "
        f"across {data['author_labels']} exact author labels, merged into "
        f"{data['merged_authors']} authors. "
        f"{searchable_total:,} records are searchable Greek text, of which "
        f"{clean_total:,} are clean source text.", "",
        "A record is not necessarily a unique fragment, composition, or independent "
        "witness. Multiple editions and translations can repeat a passage; identical "
        "copies are grouped in the reader but counted here per record. "
        "The complete SQL-derived counts by author, quality, language, kind, "
        "and source are in [`coverage.json`](../data/reports/coverage.json).", "",
        '"Clean Greek text" means `kind=text`, `language=grc`, and '
        '`quality=source_text`. "Searchable Greek text" adds `machine_corrected_ocr`. '
        'Both are search eligibility labels; edition text may contain editorial supplements.', "",
        "## Accepted records by source", "",
        "| Source label | Records |", "| --- | ---: |",
    ]
    lines.extend(f"| {label} | {number:,} |" for label, number in data["by_source"].items())
    lines.extend(["", "## Core requested names", "",
        "Rows merge every source label that the alias table assigns to the named poet "
        "(English, Greek-script, aggregator slugs and 'name of place' forms). "
        "Labels naming several poets are not merged. A dash means no merged label matched.", "",
        "| Requested name | Merged source labels | Clean Greek text | Searchable Greek text | Commentary / reference |",
        "| --- | --- | ---: | ---: | ---: |"])
    for item in data["core_targets"]:
        labels = ", ".join(f"`{label}`" for label in item["matched_author_labels"]) or "—"
        clean = f"{item['clean_greek_text_records']:,}" if item["merged_label_match"] else "—"
        searchable = f"{item['searchable_greek_text_records']:,}" if item["merged_label_match"] else "—"
        reference = f"{item['commentary_reference_records']:,}" if item["merged_label_match"] else "—"
        lines.append(f"| {item['requested_name']} | {labels} | {clean} | {searchable} | {reference} |")
    unmerged = [item for item in data["merged"] if len(item["labels"]) == 1
                and (is_mixed(item["merged_author"]) or any(
                    "Ͱ" <= char <= "Ͽ" or "ἀ" <= char <= "῿" for char in item["merged_author"]))]
    if unmerged:
        lines.extend(["", "## Labels left unmerged", "",
            "Joint attributions and Greek-script labels that the alias table does not "
            "assign to a single poet. Add a label to `data/author-aliases.json` to merge it.", "",
            "| Exact source label | Clean Greek text | Searchable Greek text | Commentary / reference |",
            "| --- | ---: | ---: | ---: |"])
        for item in unmerged:
            lines.append(f"| {item['merged_author']} | {item['clean_greek_text_records']:,} | "
                         f"{item['searchable_greek_text_records']:,} | {item['commentary_reference_records']:,} |")
    candidate_rows = [(item["requested_name"], item["unmerged_similar_labels"])
                      for item in data["core_targets"] if item["unmerged_similar_labels"]]
    if candidate_rows:
        lines.extend(["", "## Similar spellings not merged", "",
            "String matches for discovery only; these labels belong to other poets, "
            "joint attributions or reference collections and are not counted above.", "",
            "| Requested name | Other source labels containing that spelling |",
            "| --- | --- |"])
        for name, labels in candidate_rows:
            lines.append(f"| {name} | {', '.join(f'`{label}`' for label in labels)} |")
    lines.extend(["", "## Limits", "",
        "The index includes reference, raw OCR, mixed, and review-needed records that "
        "are excluded from ordinary search. Source author labels can be inconsistent "
        "or disputed; merging follows the owner alias table, not an inferred identity. "
        "Similar labels in separate sources do not prove distinct witnesses. Coverage "
        "reports what the accepted index contains; it cannot establish comprehensive "
        "surviving-text coverage.", ""])
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/corpus.sqlite")
    parser.add_argument("--out", type=Path, default=ROOT / "data/reports/coverage.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs/coverage.md")
    args = parser.parse_args()
    data = report(args.db)
    write_atomic(args.out, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    write_atomic(args.markdown, render_markdown(data))
    print(f"{data['total_records']:,} records, {data['author_labels']} exact author labels, "
          f"{data['merged_authors']} merged authors -> {args.out}, {args.markdown}")


if __name__ == "__main__":
    main()
