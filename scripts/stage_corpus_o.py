"""Stage the release O corpus: a copy of the release L corpus with two general repairs.

1. A sign printed before a poem's first line in the source markup ("⊗", Digital Sappho,
   DCC Sappho via OGC, CGL anthology) is removed from the start of the stored text (text,
   first line, normalised text, full-text row). The removed sign and the rule are recorded in
   the record's metadata (``leading_sign_removed``). A ⊗ inside a text (a new poem starting
   within one stored fragment) is kept.
2. Author columns (author_canonical, passage_authors, works.author_canonical) are recomputed
   from the extended owner alias table (scripts/migrate_corpus_schema.py, no OCR promotion), so
   one poet is one author (Apollonius Rhodius = apollonius-rhodius-epic).

Usage: python scripts/stage_corpus_o.py --source /home/alvin/melos-l/data/corpus.sqlite --out /home/alvin/melos-o/data/corpus.sqlite
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.textutils import normalize  # noqa: E402
from scripts.migrate_corpus_schema import migrate  # noqa: E402

LEADING_SIGNS = re.compile(r"^[ \t]*(⊗)[ \t]*")
RULE = ("Edition sign printed before the first line of a poem in the source markup; removed from the start of "
        "the stored text by scripts/stage_corpus_o.py (release O). Signs inside the text are kept.")


def strip_leading_signs(con):
    changed = []
    rows = con.execute("SELECT id, text, data FROM passages WHERE text LIKE '%⊗%'").fetchall()
    for identifier, text, data in rows:
        match = LEADING_SIGNS.match(text)
        if not match:
            continue
        new_text = text[match.end():]
        record = json.loads(data)
        record["text"] = new_text
        lines = record.get("lines")
        if isinstance(lines, list) and lines and isinstance(lines[0], dict) and isinstance(lines[0].get("text"), str):
            first = LEADING_SIGNS.match(lines[0]["text"])
            if first:
                lines[0]["text"] = lines[0]["text"][first.end():]
        metadata = record.get("metadata")
        note = {"sign": match.group(1), "characters_removed": match.end(), "rule": RULE}
        if isinstance(metadata, dict):
            metadata["leading_sign_removed"] = note
        else:
            record["leading_sign_removed"] = note
        normalized = normalize(new_text)
        con.execute("UPDATE passages SET text=?, normalized=?, data=? WHERE id=?",
                    (new_text, normalized, json.dumps(record, ensure_ascii=False), identifier))
        con.execute("UPDATE passage_fts SET normalized=? WHERE id=?", (normalized, identifier))
        changed.append(identifier)
    return changed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists; remove it first")
    shutil.copyfile(args.source, out)
    con = sqlite3.connect(out)
    with con:
        changed = strip_leading_signs(con)
    con.close()
    report = migrate(out, promote=False, readme_path=None, backup=False)
    report["leading_sign_removed"] = changed
    (out.parent / "stage-corpus-o.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"leading_sign_removed": len(changed), "passages": report.get("passages"),
                      "merged_authors": report.get("merged_authors")}))


if __name__ == "__main__":
    main()
