"""Reader for the Hypotactic Iliad scansion (David Chamberlain, CC BY 4.0) used as gold data.

Source: https://hypotactic.com/wp-content/uploads/2017/05/IliadAllCSV.zip (linked from
https://hypotactic.com/use-the-source/; licence stated on
https://hypotactic.com/my-reading-of-homer-work-in-progress/: "Audio and text annotations licensed
as CC-BY, © 2016, 2017 by David Chamberlain", linking CC BY 4.0).

Each CSV row is one syllable: line number, the syllable's letters (with punctuation; an elided
word is written inside the next word's first syllable, e.g. "δ’ἰφ"), long/short, word number,
foot number, half-line. The line text is rebuilt from the syllables: syllables with the same word
number are joined, words are separated by a space, and an elision mark followed by letters inside
one syllable is a word boundary.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

ELISION = "’'᾽ʼ"


@dataclass
class GoldLine:
    book: int
    line: int
    text: str
    syllables: list[str]
    lengths: list[str]  # "L" / "S"


def default_zip() -> Path:
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data / "raw" / "scansion" / "hypotactic" / "IliadAllCSV.zip"


def load_iliad(path: Path | None = None, books: range | list[int] | None = None) -> list[GoldLine]:
    path = Path(path or default_zip())
    out: list[GoldLine] = []
    with zipfile.ZipFile(path) as zf:
        names = {int(m.group(1)): n for n in zf.namelist()
                 if (m := re.search(r"IliadAllCSV/iliad(\d+)\.csv$", n)) and "__MACOSX" not in n}
        for book in sorted(names):
            if books is not None and book not in books:
                continue
            rows = list(csv.reader(io.TextIOWrapper(zf.open(names[book]), encoding="utf-8-sig")))
            cur: dict | None = None
            for row in rows[1:]:
                if len(row) < 4 or not row[0].strip().isdigit():
                    continue
                ln, syl, length, word = int(row[0]), row[1], row[2].strip(), row[3].strip()
                if length not in ("long", "short"):
                    continue
                if cur is None or cur["line"] != ln:
                    if cur:
                        out.append(_finish(book, cur))
                    cur = {"line": ln, "syls": [], "lens": [], "words": []}
                cur["syls"].append(syl)
                cur["lens"].append("L" if length == "long" else "S")
                cur["words"].append(word)
            if cur:
                out.append(_finish(book, cur))
    return out


def _finish(book: int, cur: dict) -> GoldLine:
    parts: list[str] = []
    prev_word = None
    for syl, word in zip(cur["syls"], cur["words"]):
        syl = re.sub(rf"([{ELISION}])(?=\w)", r"\1 ", syl)
        if prev_word is not None and word != prev_word:
            parts.append(" ")
        parts.append(syl)
        prev_word = word
    return GoldLine(book, cur["line"], "".join(parts), cur["syls"], cur["lens"])
