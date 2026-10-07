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


def create_router(passage_lookup, word_lookup, *, machine_service=None, syntax_provider=None, ranker=None, sense_ranker=None, rerank_allowed=None, machine_subentry_lookup=None):
    router = APIRouter()
    service = PassageAnalysisService(passage_lookup, word_lookup, machine_service=machine_service,
                                    syntax_provider=syntax_provider, ranker=ranker, sense_ranker=sense_ranker,
                                    machine_subentry_lookup=machine_subentry_lookup)

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

    class WarmRequest(BaseModel):
        model_config = {"extra": "forbid"}
        passage_id: str = Field(min_length=1, max_length=500)
        max_fetches: StrictInt = Field(default=10, ge=0, le=10)

    @router.post("/api/passage-morphology/warm")
    def warm_passage_morphology(payload: WarmRequest, request: Request):
        """Fetch and cache parser analyses for a passage's words, a few at a time.

        Called by the reader when a passage is opened, so that every fragment
        progressively gains full parses without per-word clicks. Bounded by
        max_fetches per call and by the morphology service's global allowance;
        a server-side visitor identity is used so the reader's own per-visitor
        allowance stays available for explicit requests.
        """
        from hashlib import sha256
        from .aeolic_variants import variants
        from .passage_analysis import tokenize_span
        if machine_service is None:
            return {"status": "unavailable", "fetched": 0, "missing": 0}
        passage = passage_lookup(payload.passage_id)
        if not passage or not isinstance(passage.get("text"), str):
            raise HTTPException(404, detail={"code": "unknown_passage", "message": "Unknown passage."})
        text = passage["text"]
        forms = []
        for token in tokenize_span(text, 0, len(text)):
            if token["kind"] == "word" and not token.get("editorial_fragment") and token["form"] not in forms:
                forms.append(token["form"])
        fetched, missing, statuses = 0, 0, {}
        for index, form in enumerate(forms):
            visitor = sha256(f"warm:{payload.passage_id}:{index // 9}".encode()).hexdigest()
            try:
                result = machine_service.analyze(form, visitor, fetch=False)
                if result["status"] == "cache_miss":
                    if fetched >= payload.max_fetches:
                        missing += 1
                        continue
                    fetched += 1
                    result = machine_service.analyze(form, visitor, fetch=True)
                if result["status"] == "no_analyses":
                    for variant in variants(form):
                        probe = machine_service.analyze(variant["form"], visitor, fetch=False)
                        if probe["status"] == "cache_miss":
                            if fetched >= payload.max_fetches:
                                missing += 1
                                break
                            fetched += 1
                            probe = machine_service.analyze(variant["form"], visitor, fetch=True)
                        statuses["variant:" + probe["status"]] = statuses.get("variant:" + probe["status"], 0) + 1
                statuses[result["status"]] = statuses.get(result["status"], 0) + 1
                if result["status"] == "rate_limited":
                    break
            except Exception:
                statuses["error"] = statuses.get("error", 0) + 1
        return {"status": "ok", "passage_id": payload.passage_id, "forms": len(forms),
                "fetched": fetched, "missing": missing, "statuses": statuses}

    @router.get("/api/passage-analysis/status")
    def analysis_status():
        try:
            syntax = syntax_provider.status() if syntax_provider is not None else {"state": "unavailable"}
        except Exception:
            syntax = {"state": "unavailable"}
        return {"version": 1, "syntax": syntax, "machine_default": "cache_only", "max_characters": MAX_CHARACTERS,
                "meaning": {"language": "eng", "published_whole_selection": True,
                            "partial_phrase_translation": "unavailable", "joint_translation_ranking": "unavailable"}}

    return router
