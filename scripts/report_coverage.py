#!/usr/bin/env python3
"""Summarize indexed records without inferring author identities or witnesses.

Run from the project root: python scripts/report_coverage.py
The input is the accepted SQLite index built by scripts/build_corpus.py. This
script neither downloads material nor writes corpus passages.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CORE_LABELS = (
    "Ibycus", "Alcaeus", "Sappho", "Pindar", "Bacchylides", "Alcman",
    "Stesichorus", "Simonides", "Anacreon", "Archilochus", "Mimnermus",
    "Solon", "Hipponax", "Theognis", "Semonides", "Timotheus", "Corinna",
    "Homer", "Hesiod", "Homeric Hymns",
)
REFERENCE_KINDS = {"commentary", "apparatus", "reference"}


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
    return {
        "author_label": author,
        "records": sum(kinds.values()),
        "text_records": kinds.get("text", 0),
        "translation_records": kinds.get("translation", 0),
        "commentary_reference_records": sum(kinds.get(kind, 0) for kind in REFERENCE_KINDS),
        "clean_greek_text_records": clean,
        "by_kind": kinds,
        "by_quality": counts(connection, "quality", where, args),
        "by_language": counts(connection, "language", where, args),
        "by_source": counts(connection, "source", where, args),
    }


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
        lookup: dict[str, list[dict]] = {}
        for item in summaries:
            lookup.setdefault(item["author_label"].casefold(), []).append(item)
        targets = []
        for name in CORE_LABELS:
            matched = lookup.get(name.casefold(), [])
            candidates = [label for label in authors
                          if name.casefold() in label.casefold()
                          and label.casefold() != name.casefold()]
            targets.append({
                "requested_name": name,
                "exact_label_match": bool(matched),
                "matched_author_labels": [item["author_label"] for item in matched],
                "substring_label_candidates_not_merged": candidates,
                "label_counts": [{key: item[key] for key in (
                    "author_label", "clean_greek_text_records", "text_records",
                    "commentary_reference_records"
                )} for item in matched],
                "clean_greek_text_records": sum(item["clean_greek_text_records"] for item in matched) if matched else None,
                "text_records": sum(item["text_records"] for item in matched) if matched else None,
                "commentary_reference_records": sum(item["commentary_reference_records"] for item in matched) if matched else None,
            })
        return {
            "scope": "Accepted indexed records in corpus.sqlite; not unique fragments, witnesses, or works",
            "index_built_at": manifest.get("built_at"),
            "index_files": manifest.get("files", []),
            "total_records": indexed_count,
            "author_labels": len(authors),
            "by_source": counts(connection, "source"),
            "by_kind": counts(connection, "kind"),
            "by_quality": counts(connection, "quality"),
            "by_language": counts(connection, "language"),
            "core_targets_exact_label_only": targets,
            "authors": summaries,
            "limitations": [
                "Counts are records, not unique fragments or independent textual witnesses.",
                "A source_text quality label does not remove editorial supplements or establish manuscript certainty.",
                "Core target matching is exact case-insensitive label matching only; all matching source labels remain visible. Unmatched names may occur under other labels.",
                "Translations and commentary are counted separately from Greek text; source datasets may overlap.",
            ],
        }
    finally:
        connection.close()


def render_markdown(data: dict) -> str:
    clean_total = sum(item["clean_greek_text_records"] for item in data["authors"])
    lines = [
        "# Indexed corpus coverage", "",
        f"Index snapshot: {data['index_built_at'] or 'unknown build time'}. "
        f"The accepted SQLite index contains {data['total_records']:,} records "
        f"across {data['author_labels']} exact author labels. "
        f"{clean_total:,} records meet the clean Greek text search filter.", "",
        "A record is not necessarily a unique fragment, composition, or independent "
        "witness. Multiple editions and translations can repeat a passage. "
        "The complete SQL-derived counts by author, quality, language, kind, "
        "and source are in [`coverage.json`](../data/reports/coverage.json).", "",
        '"Clean Greek text" means `kind=text`, `language=grc`, and '
        '`quality=source_text`. It is a search eligibility label; edition text '
        'may contain editorial supplements.', "",
        "## Accepted records by source", "",
        "| Source label | Records |", "| --- | ---: |",
    ]
    lines.extend(f"| {label} | {number:,} |" for label, number in data["by_source"].items())
    lines.extend(["", "## Core requested names: exact labels only", "",
        "These rows match stored author labels only by case-insensitive exact spelling. "
        "They do not merge transliterations, titles, uncertain attributions, "
        "or Greek labels. A dash means no exact label match, not zero coverage.", "",
        "| Requested name | Matched source labels | Clean Greek text records | Commentary / reference records |",
        "| --- | --- | ---: | ---: |"])
    for item in data["core_targets_exact_label_only"]:
        labels = ", ".join(f"`{label}`" for label in item["matched_author_labels"]) or "—"
        clean = f"{item['clean_greek_text_records']:,}" if item["exact_label_match"] else "—"
        reference = f"{item['commentary_reference_records']:,}" if item["exact_label_match"] else "—"
        lines.append(f"| {item['requested_name']} | {labels} | {clean} | {reference} |")
    greek_labels = [item for item in data["authors"]
                    if any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff"
                           for char in item["author_label"])]
    if greek_labels:
        lines.extend(["", "## Additional Greek-script source labels", "",
            "These source labels are reported separately. The script does not "
            "assign them to an English author name.", "",
            "| Exact source label | Clean Greek text records | Other text records | Commentary / reference records |",
            "| --- | ---: | ---: | ---: |"])
        for item in greek_labels:
            other_text = item["text_records"] - item["clean_greek_text_records"]
            lines.append(f"| {item['author_label']} | {item['clean_greek_text_records']:,} | "
                         f"{other_text:,} | {item['commentary_reference_records']:,} |")
    candidate_rows = [(item["requested_name"], item["substring_label_candidates_not_merged"])
                      for item in data["core_targets_exact_label_only"]
                      if item["substring_label_candidates_not_merged"]]
    if candidate_rows:
        lines.extend(["", "## Similar spellings in source labels", "",
            "These are string matches for discovery only. Their records are not "
            "added to the exact-name counts above.", "",
            "| Requested name | Other source labels containing that spelling |",
            "| --- | --- |"])
        for name, labels in candidate_rows:
            lines.append(f"| {name} | {', '.join(f'`{label}`' for label in labels)} |")
    lines.extend(["", "## Limits", "",
        "The index includes reference, OCR, mixed, and review-needed records that "
        "are excluded from ordinary clean-text search. Source author labels can "
        "be inconsistent or disputed. Similar labels in separate sources do not "
        "prove distinct witnesses. Coverage reports what the accepted index "
        "contains; it cannot establish comprehensive surviving-text coverage.", ""])
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
    print(f"{data['total_records']:,} records, {data['author_labels']} exact author labels -> {args.out}, {args.markdown}")


if __name__ == "__main__":
    main()
