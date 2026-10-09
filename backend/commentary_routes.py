"""Release S: commentary notes linked to a passage, under the display rule of backend.commentary_context.

Also warms the stacked search at startup (in a background thread): the encoders and vector matrices load
in about a minute on the box, which the first visitor's search would otherwise wait for.
"""
import os
import threading

from fastapi import APIRouter, Query

from . import commentary_context


def _warm():
    def run():
        try:
            from .server import hybrid_search
            hybrid_search("moon", limit=1)
            hybrid_search("σελήνη", limit=1)
        except Exception:  # noqa: BLE001 - warming is an optimisation only
            pass
    if os.getenv("MELOS_SEARCH_WARM", "1") != "0":
        threading.Thread(target=run, daemon=True).start()


router = APIRouter(on_startup=[_warm])


@router.get("/api/commentary/status")
def commentary_status():
    return commentary_context.status()


@router.get("/api/commentary/notes")
def commentary_notes(passage_id: str, limit: int = Query(20, ge=1, le=50)):
    return {"passage_id": passage_id, "notes": commentary_context.notes_for_passage(passage_id, limit),
            "display_rule": commentary_context.status().get("display_rule")}
