"""Release S: commentary notes linked to a passage, under the display rule of backend.commentary_context."""
from fastapi import APIRouter, Query

from . import commentary_context

router = APIRouter()


@router.get("/api/commentary/status")
def commentary_status():
    return commentary_context.status()


@router.get("/api/commentary/notes")
def commentary_notes(passage_id: str, limit: int = Query(20, ge=1, le=50)):
    return {"passage_id": passage_id, "notes": commentary_context.notes_for_passage(passage_id, limit),
            "display_rule": commentary_context.status().get("display_rule")}
