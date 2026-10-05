"""HTTP boundary for corpus-bound selections, with injectable reader services."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .passage_analysis import MAX_CHARACTERS, PassageAnalysisError, PassageAnalysisService


class PassageRequest(BaseModel):
    model_config = {"extra": "forbid"}
    version: StrictInt = 1
    passage_id: str = Field(min_length=1, max_length=500)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(ge=1)
    offset_unit: Literal["utf16", "codepoint"] = "utf16"
    selected_text: str = Field(min_length=1, max_length=MAX_CHARACTERS)
    rerank: StrictBool = False
    fetch_machine: StrictBool = False


def create_router(passage_lookup, word_lookup, *, machine_service=None, syntax_provider=None, ranker=None, rerank_allowed=None):
    router = APIRouter()
    service = PassageAnalysisService(passage_lookup, word_lookup, machine_service=machine_service,
                                    syntax_provider=syntax_provider, ranker=ranker)

    def run(payload, request):
        if payload.rerank and (rerank_allowed is None or not rerank_allowed(request)):
            raise HTTPException(403, detail="Context reranking is not enabled for this request.")
        try:
            return service.analyze(payload.model_dump(), visitor_id=getattr(request.state, "machine_visitor", None),
                                   ranker_visitor_id=getattr(request.state, "classifier_visitor", None))
        except PassageAnalysisError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc

    @router.post("/api/analyze-passage")
    @router.post("/api/passage-analysis", include_in_schema=False)
    def analyze_post(payload: PassageRequest, request: Request):
        return run(payload, request)

    @router.get("/api/passage-analysis/status")
    def analysis_status():
        try:
            syntax = syntax_provider.status() if syntax_provider is not None else {"state": "unavailable"}
        except Exception:
            syntax = {"state": "unavailable"}
        return {"version": 1, "syntax": syntax, "machine_default": "cache_only", "max_characters": MAX_CHARACTERS}

    return router
