#!/usr/bin/env python3
"""LatinCy sidecar for the Latin composer (docs/latin/lemma-index.md): lemma, POS and morphology for drafts and for
forms the LASLA index never prints. Runs from .venv-nlp (spaCy + la_core_web_lg) on 127.0.0.1:8802; melos-api calls
it through MELOS_LATINCY_URL (backend/latin_lemma.readings falls back to it). Model weights MIT; trained on licensed
data, so server-side only (owner's licensed-data policy).

POST /lemmatize {"text": "..."} -> {"tokens": [{"text", "lemma", "pos", "morph", "start", "end"}], "ms"}
GET  /health -> {"model", "version"}
Usage: .venv-nlp/bin/python scripts/latincy_service.py   (LATINCY_PORT, LATINCY_HOST)
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

CONVENTIONS = {"neque": "nec", "atque": "ac"}       # match LASLA's lemmatisation of nec and ac
app = FastAPI(title="LatinCy sidecar")
_nlp = None


def nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("la_core_web_lg")
    return _nlp


class In(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)


@app.get("/health")
def health():
    m = nlp()
    return {"model": m.meta.get("name"), "version": m.meta.get("version"), "pipes": m.pipe_names}


@app.post("/lemmatize")
def lemmatize(body: In):
    t0 = time.perf_counter()
    doc = nlp()(body.text)
    toks = []
    for t in doc:
        if t.is_space or t.is_punct:
            continue
        lemma = t.lemma_.lower().replace("v", "u").replace("j", "i")
        toks.append({"text": t.text, "lemma": CONVENTIONS.get(lemma, lemma), "pos": t.pos_, "morph": str(t.morph),
                     "start": t.idx, "end": t.idx + len(t.text)})
    return {"tokens": toks, "ms": round((time.perf_counter() - t0) * 1000, 1)}


if __name__ == "__main__":
    import uvicorn
    nlp()
    uvicorn.run(app, host=os.environ.get("LATINCY_HOST", "127.0.0.1"), port=int(os.environ.get("LATINCY_PORT", "8802")), log_level="warning")
