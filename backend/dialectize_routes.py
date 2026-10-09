"""Release U: POST /api/dialectize (Attic/standard -> Lesbian, Doric, Ionic candidate spellings)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .dialectize import DIALECTS, MAX_FORMS, get_dialectizer

router = APIRouter()


class DialectizeRequest(BaseModel):
    forms: Optional[List[str]] = Field(default=None, max_length=MAX_FORMS)
    form: Optional[str] = Field(default=None, max_length=60)
    dialect: str = "all"
    author: str = Field(default="", max_length=80)
    debug: bool = False
    parse_attested: bool = False
    use_parser: bool = True


@router.post("/api/dialectize")
def dialectize(request: DialectizeRequest):
    forms = list(request.forms or []) + ([request.form] if request.form else [])
    forms = [f.strip() for f in forms if isinstance(f, str) and f.strip()]
    if not forms:
        raise HTTPException(422, "Give form or forms (Greek words).")
    if len(forms) > MAX_FORMS:
        raise HTTPException(422, f"At most {MAX_FORMS} forms per request.")
    if any(len(f) > 60 or any(ch.isspace() for ch in f) for f in forms):
        raise HTTPException(422, "Each form must be one word of at most 60 characters.")
    dialect = (request.dialect or "all").strip().lower()
    if dialect not in DIALECTS + ("all",):
        raise HTTPException(422, "dialect must be lesbian, doric, ionic or all")
    try:
        return get_dialectizer().dialectize(forms, dialect, author=request.author.strip(), debug=request.debug,
                                            parse_attested=request.parse_attested, use_parser=request.use_parser)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Lemma index not available: " + str(exc)) from exc
