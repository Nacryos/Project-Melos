"""Release V: the reader's scansion overlay for a stored poem (GET /api/scan/passage?id=...).

The server scans the stored text itself (the lines the reader prints, joined by newlines, so offsets match the
reader's word buttons). Brackets round a supplement and dots under uncertain letters are read through: the
supplement is the editor's text and scans like any other (the syllabifier skips the brackets). Only a gap, letters
lost or illegible, leaves a unit without a mark, and only a line with a gap or cut at either edge goes without
the metre lock (backend/scansion/lock.py), which applies when the poem's metre is recorded
(backend/scansion/recorded_metres.py). Results are cached per passage.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict

from fastapi import APIRouter, HTTPException

router = APIRouter()
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
CACHE = 512
# A gap: empty or dotted brackets, the editors' dots for illegible letters, an ellipsis, "***", an obelus, or a
# bracket opening on nothing at the end of the line.
GAP = re.compile(r"\[[\s.·]*\]|\.[\s.·]*\.|(?<![^\s\[\]])\.(?![^\s\[\]])|…|\*\*\*|[†‡]|\[[\s.·]*$")
# A line cut at its start, opening at a bracket ("]δώσην"): syllables may be missing, so the metre lock does not
# apply (a cut at the end, "ἔχη[", is a GAP). "λί]μενος" and "μέγ[αν" are read as restored whole.
EDGE = re.compile(r"^[\s.·]*\]")
DIALECT = {"lesbian": "aeolic", "boeotian": "aeolic", "doric": "doric"}


def _reader_text(passage: dict) -> str:
    lines = passage.get("lines")
    if isinstance(lines, list) and lines:
        return "\n".join(str((line or {}).get("text") or "") for line in lines)
    return str(passage.get("text") or "")


def gapped_line(line: str) -> bool:
    return bool(GAP.search(line) or EDGE.search(line))


def scan_passage(passage: dict) -> dict:
    from .passage_dialect import passage_dialect
    from .scansion import api as scan_api
    from .scansion.lock import lock_line
    from .scansion.recorded_metres import recorded_metre
    text = _reader_text(passage)
    dialect = DIALECT.get(passage_dialect(passage) or "", "none")
    scanner = scan_api._scanner(None, True, dialect)
    lines = scanner.scan_lines(text)
    record = recorded_metre(passage)
    raw_lines = text.split("\n")
    units, line_info = [], []
    for sylls in lines:
        line_no = sylls[0].line
        editorial_line = gapped_line(raw_lines[line_no]) if line_no < len(raw_lines) else True
        locked = lock_line(sylls, record["metre"]) if record and not editorial_line else None
        line_info.append({"line": line_no, "editorial": editorial_line,
                          "template": locked["template"] if locked else None,
                          "fits": locked["ok"] if locked else None,
                          "locked": bool(locked and locked["template"])})
        line_end = text.find("\n", sylls[0].start)
        line_end = len(text) if line_end < 0 else line_end
        for k, s in enumerate(sylls):
            d = s.as_dict()
            # A gap between this nucleus and the next (or the line's end) leaves the unit's coda unknown.
            stop = sylls[k + 1].start if k + 1 < len(sylls) else line_end
            gap = GAP.search(text, s.start, line_end)
            d["editorial"] = bool(gap and gap.start() < stop)
            if locked and s.index in locked["units"]:
                d["metre"] = locked["units"][s.index]
            units.append(d)
    return {"version": 1, "passage_id": passage.get("id"), "text": text, "dialect": dialect,
            "metre": ({"metre": record["metre"], "label": record["label"], "source": record["source"]} if record else None),
            "lock": {"band": [0.3, 0.7], "shift": 0.5, "applies": bool(record)},
            "lines": line_info, "units": units}


@router.get("/api/scan/passage")
def scan_stored_passage(id: str):
    with _lock:
        if id in _cache:
            _cache.move_to_end(id)
            return _cache[id]
    from .server import connect, unpack
    with connect() as con:
        row = con.execute("SELECT * FROM passages WHERE id=?", (id,)).fetchone()
    if not row:
        raise HTTPException(404, "Passage not found")
    passage = unpack(row)
    if passage.get("language") != "grc":
        raise HTTPException(422, {"code": "not_greek", "message": "Only Greek passages are scanned."})
    passage.setdefault("id", id)
    out = scan_passage(passage)
    with _lock:
        _cache[id] = out
        while len(_cache) > CACHE:
            _cache.popitem(last=False)
    return out
