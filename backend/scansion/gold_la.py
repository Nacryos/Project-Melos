"""Reader for the Hypotactic Latin hand scansion (David Chamberlain, CC BY 4.0) used as gold data
(data/open/latin/hypotactic/lines.jsonl.gz, built by scripts/ingest_open_hypotactic_latin.py).

Each line carries its syllables with q = L / S / E (elided) and modifier flags. `text_plain` is the line without
macrons: the scanner is scored on it. Development / held-out split for the Phalaecian poems: odd poem numbers are
development, even numbers held-out (docs/prd/latin-composer.md §4.4).
"""
from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoldLine:
    id: str
    work: str
    poem: str
    line_no: int
    metre: str
    text: str
    plain: str
    syllables: list[str]
    lengths: list[str]          # L / S / E per syllable
    flags: list[list[str]]
    words: list[dict] = field(default_factory=list)

    @property
    def poem_int(self) -> int:
        m = re.match(r"(\d+)", self.poem)
        return int(m.group(1)) if m else 0

    @property
    def split(self) -> str:
        return "dev" if self.poem_int % 2 == 1 else "held_out"

    @property
    def pattern(self) -> str:
        return "".join("–" if q == "L" else "⏑" for q in self.lengths if q != "E")


def default_path() -> Path:
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data / "open" / "latin" / "hypotactic" / "lines.jsonl.gz"


def load(path: Path | None = None, work: str | None = None, metre: str | None = None) -> list[GoldLine]:
    out: list[GoldLine] = []
    with gzip.open(path or default_path(), "rt", encoding="utf-8") as f:
        for raw in f:
            r = json.loads(raw)
            if work and r["work_file"] != work:
                continue
            if metre and r["metre"] != metre:
                continue
            syl = [s for w in r["words"] for s in w["syl"]]
            out.append(GoldLine(r["id"], r["work_file"], str(r["poem_number"]), int(r["line_no"]), r["metre"], r["text"],
                                r["text_plain"], [s["t"] for s in syl], [s["q"] for s in syl], [s["f"] for s in syl],
                                r["words"]))
    return out
