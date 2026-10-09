"""Release S: optional cross-encoder reranking of the first fused results.

Configured by the ``rerank`` entry of ``search_stack_weights.json``:
``{"greek"|"english": {"model": hub id, "revision": ..., "top": 50, "beta": b}}``. Within the first ``top``
results the new order is by ``(1 - b) * fused-rank score + b * normalised cross-encoder score``; results
after ``top`` keep their place. The pair text is the passage's Greek text followed by its linked English
translation when one exists. Scores are cached per (query, passage). With no entry, nothing changes.
"""
from __future__ import annotations

import threading
from functools import lru_cache

_MODELS, _LOCK = {}, threading.Lock()
PAIR_CHARS = 1200


def passage_text(con, record):
    """Greek text plus the first linked English translation (parent_id link), truncated."""
    text = (record.get("text") or "")[:PAIR_CHARS]
    try:
        row = con.execute("SELECT text FROM passages WHERE json_extract(data,'$.parent_id')=? AND kind='translation' "
                          "AND language='eng' LIMIT 1", (record["id"],)).fetchone()
    except Exception:  # noqa: BLE001 - the translation is optional context
        row = None
    if row and row[0]:
        text += "\n" + row[0][:PAIR_CHARS]
    return text


def _model(name, revision):
    with _LOCK:
        if name not in _MODELS:
            from sentence_transformers import CrossEncoder
            from .encoders import model_cache
            _MODELS[name] = CrossEncoder(name, revision=revision, max_length=512, device="cpu",
                                         cache_folder=model_cache())
        return _MODELS[name]


@lru_cache(maxsize=20000)
def _score(name, revision, q, passage_id, text):
    return float(_model(name, revision).predict([(q, text)], show_progress_bar=False)[0])


def rerank(q, ranked, *, greek):
    from .search_stack import config
    cfg = (config().get("rerank") or {}).get("greek" if greek else "english")
    if not cfg or not cfg.get("beta") or not ranked:
        return ranked, None
    from .server import connect
    top_n = int(cfg.get("top", 50))
    top = ranked[:top_n]
    with connect() as con:
        texts = [passage_text(con, r) for r in top]
    scores = [_score(cfg["model"], cfg.get("revision"), q, r["id"], t) for r, t in zip(top, texts)]
    lo, hi = min(scores), max(scores)
    norm = [(s - lo) / (hi - lo) if hi > lo else 0.0 for s in scores]
    n, beta = len(top), float(cfg["beta"])
    order = sorted(range(n), key=lambda i: -((1 - beta) * (1 - i / max(1, n - 1)) + beta * norm[i]))
    return [top[i] for i in order] + ranked[top_n:], (
        f"The first {n} results are reordered by a cross-encoder ({cfg['model']}) blended with the fused rank "
        f"(weight {beta}, fitted on the development queries).")
