"""The single gate between the owner's private store and every public response (release T).

Rule (docs/private-mode.md): private material MAY steer public search ranking, but every
text a signed-out visitor sees comes from public material, except at most one short cited
excerpt (30 words or fewer, with its source and page) per result, and only when the operator
turns excerpts on (``MELOS_PRIVATE_PUBLIC_EXCERPTS=1``; off by default).

Public code calls exactly one function here, ``apply_public_search``. Nothing in this module
returns private page text except through ``cited_excerpt``, which enforces the limit.
"""
from __future__ import annotations

import os
import re

from . import private_store

MAX_EXCERPT_WORDS = 30
PUBLIC_EXCERPT = "public-excerpt"
_RRF_K = 60
_PRIVATE_WEIGHT = 0.5


def signals_enabled() -> bool:
    return os.environ.get("MELOS_PRIVATE_SIGNALS", "1") != "0"


def excerpts_enabled() -> bool:
    return os.environ.get("MELOS_PRIVATE_PUBLIC_EXCERPTS", "0") == "1"


def cited_excerpt(text: str, terms: list[str], source: str, page: str, max_words: int = MAX_EXCERPT_WORDS) -> dict | None:
    """At most ``max_words`` (never more than 30) words around the first matching term, with citation."""
    if not source or not page:
        return None
    max_words = min(max_words, MAX_EXCERPT_WORDS)
    words = text.split()
    if not words:
        return None
    folded = [private_store.fold(w) for w in words]
    keys = [private_store.fold(t) for t in terms if t]
    hit = next((i for i, w in enumerate(folded) if any(k and k in w for k in keys)), 0)
    start = max(0, min(hit - max_words // 3, len(words) - max_words))
    chosen = words[start:start + max_words]
    excerpt = " ".join(chosen)
    assert len(excerpt.split()) <= MAX_EXCERPT_WORDS
    return {"visibility": PUBLIC_EXCERPT, "text": ("… " if start else "") + excerpt +
            (" …" if start + max_words < len(words) else ""), "source": source, "page": page,
            "words": len(chosen)}


def rank_signals(q: str, pages: int = 25) -> tuple[dict[str, float], dict[str, tuple[str, int]]]:
    """Public passage ids linked from the private pages that best match ``q``: score and best page."""
    scores: dict[str, float] = {}
    best: dict[str, tuple[str, int]] = {}
    hits = private_store._search_pages(q, pages)
    page_rank = {(h["doc_id"], h["page_no"]): r for r, h in enumerate(hits)}
    for link in private_store._links_for_pages(list(page_rank)):
        rank = page_rank[(link["doc_id"], link["page_no"])]
        value = link["score"] / (_RRF_K + rank)
        if value > scores.get(link["passage_id"], 0.0):
            scores[link["passage_id"]] = value
            best[link["passage_id"]] = (link["doc_id"], link["page_no"])
    return scores, best


def apply_public_search(q: str, result: dict) -> dict:
    """Re-rank one public search page with private signals. Adds no private text (see module doc).

    Only results already in the public page move; nothing is added or removed, so every
    displayed record is still public. Failures leave the public result untouched.
    """
    results = result.get("results") if isinstance(result, dict) else None
    if not results or not q or not signals_enabled():
        return result
    try:
        scores, best = rank_signals(q)
    except Exception:  # noqa: BLE001 - a private-store problem must never break public search
        return result
    if not scores:
        return result
    order = sorted(scores, key=scores.get, reverse=True)
    private_rank = {pid: r for r, pid in enumerate(order)}

    def linked(record: dict) -> str | None:
        copies = record.get("copy_ids") or []
        copies = copies if isinstance(copies, list) else str(copies).split("\x1f")
        ids = [record.get("id")] + [str(i) for i in copies if i]
        found = [i for i in ids if i in private_rank]
        return min(found, key=private_rank.get) if found else None

    fused = []
    for public_rank, record in enumerate(results):
        pid = linked(record)
        score = 1.0 / (_RRF_K + public_rank)
        if pid is not None:
            score += _PRIVATE_WEIGHT / (_RRF_K + private_rank[pid])
        fused.append((score, -public_rank, record, pid))
    fused.sort(key=lambda item: (item[0], item[1]), reverse=True)
    reordered = []
    terms = re.findall(r"\w+", q)
    for _, _, record, pid in fused:
        record.pop("reference_excerpt", None)
        if pid is not None and excerpts_enabled():
            row = private_store._page_row(*best[pid])
            if row is not None:
                label = row["page_label"] or str(row["page_no"])
                excerpt = cited_excerpt(row["text"], terms, row["citation"], label)
                if excerpt:
                    record["reference_excerpt"] = excerpt
        reordered.append(record)
    result["results"] = reordered
    return result
