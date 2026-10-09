"""Render the ranked open-sources table into docs/open-sources-survey-2026-10-09.md.

Input: the survey rows in data/open/survey-2026-10-09/*.json (one row per resource, collected
2026-10-09 with licences quoted from the source) and data/open/survey-2026-10-09/status.json
(ingestion status recorded after this pass: {url_or_name_substring: "status text"}).
The table replaces the text between the TABLE markers in the doc; the prose around it is kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURVEY = ROOT / "data" / "open" / "survey-2026-10-09"
DOC = ROOT / "docs" / "open-sources-survey-2026-10-09.md"
START, END = "<!-- TABLE:START -->", "<!-- TABLE:END -->"
VALUE = {"high": 3, "medium": 2, "low": 1}
EFFORT = {"low": 0, "medium": 1, "high": 2}


def cell(text: object, limit: int = 400) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip().replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def url_key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).rstrip("/")


def main() -> None:
    status = json.loads((SURVEY / "status.json").read_text(encoding="utf-8")) if (SURVEY / "status.json").exists() else {}
    rows, seen = [], set()
    for path in sorted(SURVEY.glob("survey_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            key = url_key(row.get("url", "")) or row["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            row["_file"] = path.stem
            rows.append(row)
    rows.sort(key=lambda r: (-VALUE.get(r.get("value", "low"), 0), EFFORT.get(r.get("effort", "high"), 3), r["name"].lower()))
    out = [
        "| # | Resource | Category | Contents | Size | Licence (quoted) | Have it? | Value | Effort | Restrictions / status |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        extra = [v for k, v in status.items() if k.lower() in (r["name"] + " " + r.get("url", "")).lower()]
        restr = cell(r.get("restrictions"), 250) + ("" if not extra else " **This pass:** " + cell("; ".join(extra), 300))
        out.append(
            f"| {i} | [{cell(r['name'], 120)}]({r.get('url', '')}) | {cell(r.get('category'))} | {cell(r.get('contents'), 300)} "
            f"| {cell(r.get('size'), 80)} | {cell(r.get('licence'), 250)} | {cell(r.get('have_it'), 120)} "
            f"| **{cell(r.get('value'))}**: {cell(r.get('value_why'), 220)} | **{cell(r.get('effort'))}**: {cell(r.get('effort_why'), 160)} | {restr} |"
        )
    table = "\n".join(out)
    doc = DOC.read_text(encoding="utf-8")
    head, rest = doc.split(START, 1)
    _, tail = rest.split(END, 1)
    DOC.write_text(f"{head}{START}\n\n{len(rows)} resources (duplicates across the three survey files merged by URL).\n\n{table}\n\n{END}{tail}", encoding="utf-8")
    print(f"{len(rows)} rows written to {DOC}")


if __name__ == "__main__":
    main()
