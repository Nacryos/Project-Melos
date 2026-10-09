"""Release V: the reader's scansion overlay for a stored poem (GET /api/scan/passage?id=...).

The server scans the stored text itself (the lines the reader prints, joined by newlines, so offsets match the
reader's word buttons), marks units inside words with editorial signs (brackets, lacunae, dotted letters) so the
reader shows no mark there, and applies the metre lock (backend/scansion/lock.py) only when the poem's metre is
recorded (backend/scansion/recorded_metres.py). Results are cached per passage.
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
EDITORIAL = re.compile(r"[\[\]⟨⟩⟦⟧{}<>〈〉†‡…̣]|\.\s*\.")
DIALECT = {"lesbian": "aeolic", "boeotian": "aeolic", "doric": "doric"}


def _reader_text(passage: dict) -> str:
    lines = passage.get("lines")
    if isinstance(lines, list) and lines:
        return "\n".join(str((line or {}).get("text") or "") for line in lines)
    return str(passage.get("text") or "")


def _token_spans(text: str):
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def scan_passage(passage: dict) -> dict:
    from .passage_dialect import passage_dialect
    from .scansion import api as scan_api
    from .scansion.lock import lock_line
    from .scansion.recorded_metres import recorded_metre
    text = _reader_text(passage)
    dialect = DIALECT.get(passage_dialect(passage) or "", "none")
    scanner = scan_api._scanner(None, True, dialect)
    lines = scanner.scan_lines(text)
    spans = _token_spans(text)
    record = recorded_metre(passage)
    raw_lines = text.split("\n")
    units, line_info = [], []
    for sylls in lines:
        line_no = sylls[0].line
        editorial_line = bool(EDITORIAL.search(raw_lines[line_no])) if line_no < len(raw_lines) else True
        locked = lock_line(sylls, record["metre"]) if record and not editorial_line else None
        line_info.append({"line": line_no, "editorial": editorial_line,
                          "template": locked["template"] if locked else None,
                          "fits": locked["ok"] if locked else None,
                          "locked": bool(locked and locked["template"])})
        for s in sylls:
            d = s.as_dict()
            anchor = s.nend - 1
            token = next((text[a:b] for a, b in spans if a <= anchor < b), "")
            d["editorial"] = bool(EDITORIAL.search(token))
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
