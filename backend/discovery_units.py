"""Deterministic, literal discovery spans within one stored source record.

No normalization, reconstruction, language inference, or cross-record joining is
performed. The caller is responsible for selecting eligible Greek source records.
Sentence and phrase boundaries are punctuation heuristics, not linguistic or
editorial claims. Stanzas require two nonempty blocks separated by a blank line.
Overlength records are omitted rather than truncated into fictitious full units;
large results retain only the first MAX_UNITS_PER_RECORD complete source spans.
"""

from collections.abc import Mapping
import hashlib
import json
import re
import unicodedata


SUPPORTED_UNITS = ("passage", "stanza", "line", "sentence", "phrase", "word")
MAX_SOURCE_LENGTH = 100_000
MAX_UNITS_PER_RECORD = 2_000
OFFSET_BASIS = "Unicode codepoints in original passage.text"

# Avoid treating the two characters of a single CRLF as two line breaks.
_NEWLINE = r"(?:\r\n|\r(?!\n)|(?<!\r)\n)"
_LINES = re.compile(_NEWLINE)
_BLANK_LINES = re.compile(_NEWLINE + r"[^\S\r\n]*" + _NEWLINE)
_SENTENCE_END = frozenset(".!?;\u037e")
_PHRASE_END = _SENTENCE_END | frozenset(",:\u00b7\u0387\u2013\u2014")
_CLOSERS = frozenset("\"'\u2019\u201d\u00bb)]}\u27e9")
_APOSTROPHES = frozenset("'\u2019\u1fbd\u02bc\u1fbf")
_METHODS = {
    "passage": "stored passage; complete original text",
    "stanza": "explicit blank-line-separated source blocks; no inferred stanza boundaries",
    "line": "literal source newline boundaries (CRLF, LF, or CR)",
    "sentence": "punctuation heuristic: period, exclamation, question mark, or Greek question mark/semicolon",
    "phrase": "punctuation heuristic: sentence punctuation plus comma, colon, middle dot, en/em dash",
    "word": "Unicode letter runs with attached combining marks and printed apostrophes; no normalization",
}


def _trim(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_spans(text, separator):
    start = 0
    for match in separator.finditer(text):
        yield _trim(text, start, match.start())
        start = match.end()
    yield _trim(text, start, len(text))


def _punctuation_spans(text, punctuation):
    start = index = 0
    while index < len(text):
        if text[index] in punctuation:
            index += 1
            while index < len(text) and (text[index] in punctuation or text[index] in _CLOSERS):
                index += 1
            yield _trim(text, start, index)
            start = index
        else:
            index += 1
    yield _trim(text, start, len(text))


def _word_spans(text):
    start = None
    index = 0
    while index < len(text):
        char = text[index]
        category = unicodedata.category(char)
        # Some printed apostrophes are Unicode modifier letters; check first.
        if char in _APOSTROPHES:
            if start is not None:
                index += 1
                if (index == len(text) or text[index] in _APOSTROPHES
                        or not unicodedata.category(text[index]).startswith("L")):
                    yield start, index
                    start = None
                continue
        elif category.startswith("L"):
            if start is None:
                start = index
        elif category.startswith("M") and start is not None:
            pass
        elif start is not None:
            yield start, index
            start = None
        index += 1
    if start is not None:
        yield start, len(text)


def segment_record(record: Mapping, unit: str) -> list[dict]:
    """Return stable, exact spans with exclusive ``end`` codepoint offsets.

    Each ``text`` and ``quote`` equals ``record['text'][start:end]``. Passage
    retains all whitespace; smaller units trim only boundary whitespace and
    preserve internal whitespace. Empty/invalid/overlength records return [].
    IDs encode the source ID, exact source text, unit, and offsets so repeated
    calls are stable and different records or source revisions cannot collide.
    Unsupported unit names raise ValueError. Records are never modified.
    """
    if unit not in SUPPORTED_UNITS:
        raise ValueError(f"Unsupported discovery unit: {unit!r}")
    if not isinstance(record, Mapping):
        return []
    text = record.get("text")
    parent_id = record.get("id")
    if (not isinstance(text, str) or len(text) > MAX_SOURCE_LENGTH
            or not text.strip()
            or not isinstance(parent_id, (str, int)) or isinstance(parent_id, bool)
            or parent_id == ""):
        return []

    if unit == "passage":
        spans = [(0, len(text))]
    elif unit == "stanza":
        spans = [(start, end) for start, end in _split_spans(text, _BLANK_LINES) if start < end]
        if len(spans) < 2:
            return []
    elif unit == "line":
        spans = _split_spans(text, _LINES)
    elif unit == "word":
        spans = _word_spans(text)
    else:
        spans = _punctuation_spans(text, _SENTENCE_END if unit == "sentence" else _PHRASE_END)

    identity = hashlib.sha256(json.dumps([parent_id, text], ensure_ascii=True).encode("ascii")).hexdigest()
    result = []
    for start, end in spans:
        if start == end:
            continue
        quote = text[start:end]
        result.append({
            "id": f"discovery:{identity}:{unit}:{start}:{end}",
            "parent_id": parent_id,
            "passage_id": parent_id,
            "unit": unit,
            "text": quote,
            "quote": quote,
            "start": start,
            "end": end,
            "offset_basis": OFFSET_BASIS,
            "segmentation_method": _METHODS[unit],
        })
        if len(result) >= MAX_UNITS_PER_RECORD:
            break
    return result
