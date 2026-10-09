"""POST /api/words/headlines: headline headword, short gloss, parses and alternatives for every
word of a passage in one call, read from the corpus headword index (release O).

The headline is the index's ranked reading of each token (parser + recorded forms + generated
spellings, rescored by the contextual model where it ran); /api/word remains the full analysis.
A tie is never hidden: every other reading of the spelling is listed in `alternatives` with its
own parses, and the headline is still given. Contract: docs/api-contract.md.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .lemma_index import describe_source, get_index

router = APIRouter()
MAX_FORMS = 400


class HeadlineRequest(BaseModel):
    passage_id: str = Field("", max_length=300)
    forms: list[str] = Field(default_factory=list, max_length=MAX_FORMS)


def _readings(index, form_ids):
    """{form_id: [(lemma_id, prob, src, parses)]} in rank order."""
    out = {}
    ids = sorted(set(int(f) for f in form_ids))
    con = index.con()
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for form_id, lemma_id, prob, src, parses in con.execute(
                f"SELECT form_id,lemma_id,prob,src,parses FROM form_lemma WHERE form_id IN ({','.join('?' * len(chunk))}) "
                "ORDER BY form_id,rank", chunk):
            out.setdefault(form_id, []).append((lemma_id, prob, src, json.loads(parses) if parses else []))
    return out


def _lemmas(index, lemma_ids):
    ids = sorted(set(int(i) for i in lemma_ids))
    out = {}
    con = index.con()
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for row in con.execute(f"SELECT id,lemma,gloss,gloss_source,pos FROM lemma WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out[row[0]] = {"lemma": row[1], "gloss": row[2], "gloss_source": row[3], "pos": row[4]}
    return out


def _forms(index, form_ids):
    ids = sorted(set(int(i) for i in form_ids))
    out = {}
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for fid, form, status in index.con().execute(
                f"SELECT id,form,status FROM form WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out[fid] = (form, status)
    return out


def headlines(passage_id="", forms=()):
    try:
        index = get_index()
    except FileNotFoundError as exc:
        raise HTTPException(503, "The corpus headword index is not available on this deployment.") from exc
    tokens = []
    if passage_id:
        pid = index.id_pid.get(passage_id)
        if pid is None:
            raise HTTPException(404, "Passage not in the headword index (not Greek, or unknown id).")
        lem, fid, conf, src, starts, lengths = index.tokens(pid)
        readings = _readings(index, fid.tolist())
        names = _forms(index, fid.tolist())
        for i in range(len(lem)):
            tokens.append({"i": i, "start": int(starts[i]), "end": int(starts[i]) + int(lengths[i]),
                           "form_id": int(fid[i]), "lemma_id": int(lem[i]), "confidence": round(int(conf[i]) / 255, 3),
                           "src": int(src[i])})
    else:
        from .lemma_tokens import clean_form
        cleaned = [clean_form(f) for f in forms]
        con = index.con()
        found = {}
        for form in set(cleaned):
            row = con.execute("SELECT id FROM form WHERE form=?", (form,)).fetchone()
            if row:
                found[form] = row[0]
        readings = _readings(index, found.values())
        names = _forms(index, found.values())
        for i, (printed, form) in enumerate(zip(forms, cleaned)):
            f = found.get(form)
            top = (readings.get(f) or [(0, 0, 0, [])])[0]
            tokens.append({"i": i, "printed": printed, "form_id": f or 0, "lemma_id": top[0],
                           "confidence": round(top[1], 3) if top[0] else 0.0, "src": top[2]})
    lemma_ids = {t["lemma_id"] for t in tokens if t["lemma_id"]}
    for rows in readings.values():
        lemma_ids.update(r[0] for r in rows)
    lemmas = _lemmas(index, lemma_ids)
    text = None
    if passage_id:
        from .server import connect
        with connect() as con:
            row = con.execute("SELECT text FROM passages WHERE id=?", (passage_id,)).fetchone()
        text = row[0] if row else ""
    out = []
    for t in tokens:
        form, status = names.get(t["form_id"], (None, "unknown"))
        rows = readings.get(t["form_id"]) or []
        head = lemmas.get(t["lemma_id"]) if t["lemma_id"] else None
        parses = next((r[3] for r in rows if r[0] == t["lemma_id"]), [])
        item = {"i": t["i"], "form": form, "form_status": status,
                "lemma": head["lemma"] if head else None, "lemma_id": t["lemma_id"] or None,
                "gloss": head["gloss"] if head else None, "gloss_source": head["gloss_source"] if head else None,
                "pos": head["pos"] if head else None, "parses": parses, "confidence": t["confidence"],
                "basis": describe_source(t["src"]),
                "alternatives": [{"lemma": lemmas.get(l, {}).get("lemma"), "lemma_id": l,
                                  "gloss": lemmas.get(l, {}).get("gloss"), "form_probability": round(p, 3),
                                  "parses": ps} for l, p, _, ps in rows if l != t["lemma_id"]],
                "tie": bool(rows) and len(rows) > 1 and rows[1][1] >= 0.8 * rows[0][1]}
        if "start" in t:
            item.update(start=t["start"], end=t["end"], printed=text[t["start"]:t["end"]] if text else None)
        else:
            item["printed"] = t["printed"]
        out.append(item)
    stamp = index.manifest.get("built_at", "")
    digest = hashlib.sha256(json.dumps([stamp, passage_id, list(forms), (text or "")], ensure_ascii=False).encode()).hexdigest()
    return {"passage_id": passage_id or None, "index_version": index.manifest.get("version"), "index_built_at": stamp,
            "hash": digest, "tokens": out,
            "method": ("Headline = the corpus headword index's top reading of each token (parser, recorded forms, "
                       "generated dialect/elision spellings, rescored by the contextual model where it ran). "
                       "Alternatives are the spelling's other readings. Confidence is a normalised score, not a "
                       "probability. /api/word gives the full analysis.")}


@router.post("/api/words/headlines")
def words_headlines(request: HeadlineRequest):
    if not request.passage_id and not request.forms:
        raise HTTPException(422, "Give passage_id or forms.")
    payload = headlines(request.passage_id, request.forms)
    return JSONResponse(payload, headers={"ETag": '"' + payload["hash"] + '"',
                                          "Cache-Control": "public, max-age=3600"})


@router.get("/api/words/headlines")
def words_headlines_get(passage_id: str):
    """GET form for caching proxies; same payload as the POST with passage_id."""
    payload = headlines(passage_id, ())
    return JSONResponse(payload, headers={"ETag": '"' + payload["hash"] + '"',
                                          "Cache-Control": "public, max-age=3600"})
