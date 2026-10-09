"""Release U: line-level loci for parallels (search results, concept examples).

A stored passage is often a whole fragment (Sappho 96, twenty lines); a parallel is one line or a few words
of it. ``line_at`` gives the printed line holding an offset, with its line number and a citation: the
edition's printed numbering when the passage prints it (a number standing alone at a line's start or end,
counted on from the nearest numbered line), else the line's position in the stored passage (labelled
`position_in_passage`). ``best_line`` picks, for a search result, the line holding the most distinct
query headwords (backend.lemma_index token readings), ties to the line with more matching words.
"""
from __future__ import annotations

import re

import numpy as np

_EDGE_NUMBER = re.compile(r"^\s*(\d{1,4})[a-z]?\.?\s+|\s+(\d{1,4})[a-z]?\s*$")
_ANY_NUMBER = re.compile(r"(?<!\S)\d{1,4}[a-z]?\.?(?!\S)")


def lines(text):
    """[(start, end, raw line)] for every line of the passage text."""
    out, pos = [], 0
    for raw in (text or "").split("\n"):
        out.append((pos, pos + len(raw), raw))
        pos += len(raw) + 1
    return out


def _printed_numbers(rows):
    """{line index: printed number} for lines with a number standing alone at their start or end."""
    found = {}
    for i, (_, _, raw) in enumerate(rows):
        m = _EDGE_NUMBER.search(raw)
        if m:
            found[i] = int(m.group(1) or m.group(2))
    return found


def line_at(text, offset, citation=None):
    rows = lines(text)
    index = next((i for i, (s, e, _) in enumerate(rows) if s <= offset <= e), len(rows) - 1)
    start, end, raw = rows[index]
    numbers = _printed_numbers(rows)
    basis, number = "position_in_passage", index + 1
    if numbers:
        nearest = min(numbers, key=lambda i: (abs(i - index), i))
        candidate = numbers[nearest] + (index - nearest)
        # numbering must run forward consistently (5, 10, 15 every five lines) to be trusted
        if candidate > 0 and all(numbers[j] - numbers[i] == j - i for i, j in zip(sorted(numbers), sorted(numbers)[1:])):
            basis, number = "printed", candidate
    clean = " ".join(_ANY_NUMBER.sub(" ", raw).split())
    cite = None
    if citation:
        cite = f"{citation}, l. {number}" if basis == "printed" else f"{citation}, line {number} of the stored text"
    return {"line": number, "line_basis": basis, "start": start, "end": end, "text": clean, "citation": cite}


def best_line(index, pid, lemma_ids, text, citation=None):
    """The line of passage `pid` holding the most distinct query headwords, or None."""
    toks = index.tokens(pid)
    if toks is None or not lemma_ids or not text:
        return None
    wanted = np.asarray(sorted(set(int(i) for i in lemma_ids)), dtype=np.uint32)
    hit = np.flatnonzero(np.isin(toks[0], wanted))
    if not len(hit):
        return None
    rows = lines(text)
    starts = np.asarray([s for s, _, _ in rows])
    per_line = {}
    for i in hit.tolist():
        offset = int(toks[4][i])
        li = int(np.searchsorted(starts, offset, side="right") - 1)
        lemmas, n = per_line.get(li, (set(), 0))
        lemmas.add(int(toks[0][i]))
        per_line[li] = (lemmas, n + 1)
    li = max(per_line, key=lambda k: (len(per_line[k][0]), per_line[k][1], -k))
    out = line_at(text, rows[li][0], citation)
    out["matched_headwords"] = len(per_line[li][0])
    return out


def query_lemma_ids(index, q, limit_per_word=3):
    """Headword ids a query names: Greek words read as their headwords, English words through their head
    meanings (whole words), else dictionary gloss words. The same readings search and concepts use."""
    from .lemma_index import GREEK
    ids = []
    words = [w for w in re.findall(r"\w+", q or "") if len(w) > 2]
    for word in words[:12]:
        if GREEK(word):
            rows = index.resolve(word, limit=2)
        else:
            rows = index.head_meaning_lemmas(word, limit=limit_per_word) or index.english_lemmas(word, limit=limit_per_word)
        for row in rows[:limit_per_word]:
            for i in index.expand_variants([row["lemma_id"]]):
                if i not in ids:
                    ids.append(i)
    return ids


def attach_result_lines(results, q, text_of=None):
    """Release U: add `best_line` to search results whose passage is in the headword index."""
    from .lemma_index import get_index
    index = get_index()
    ids = query_lemma_ids(index, q)
    if not ids:
        return 0
    count = 0
    for item in results:
        pid = index.id_pid.get(item.get("id"))
        if pid is None:
            continue
        text = item.get("text") if isinstance(item.get("text"), str) else (text_of(item["id"]) if text_of else None)
        line = best_line(index, pid, ids, text, item.get("citation"))
        if line:
            item["best_line"] = line
            count += 1
    return count


__all__ = ["line_at", "best_line", "query_lemma_ids", "attach_result_lines", "lines"]
