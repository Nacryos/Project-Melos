"""POST /api/words/headlines: headline headword, short gloss, parses and alternatives for every
word of a passage in one call, read from the corpus headword index (release O).

The headline is the index's ranked reading of each token (parser + recorded forms + generated
spellings, rescored by the contextual model where it ran); /api/word remains the full analysis.
A tie is never hidden: every other reading of the spelling is listed in `alternatives` with its
own parses, and the headline is still given. Contract: docs/api-contract.md.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
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
    dictionary: bool = False  # release P: first dictionary's first senses per headline lemma
    # Release U (forms mode): the dialect of the text the forms come from, or an author whose dialect it is.
    dialect: str = Field("", max_length=20)
    author: str = Field("", max_length=120)


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


def _token_alternatives(index, pid):
    """{token i: (lemma_id, probability)} for tokens with a genuine second reading (release Q
    index table token_alt; empty for an older index)."""
    import sqlite3
    try:
        return {i: (lemma_id, round(prob, 3)) for i, lemma_id, prob in index.con().execute(
            "SELECT i, lemma_id, prob FROM token_alt WHERE pid=?", (int(pid),))}
    except sqlite3.OperationalError:
        return {}


def _token_flags(index, pid):
    """{token i: flags} (release Q index table token_flag; bit 1 = the contextual model named another
    reading of the spelling). Empty for an older index."""
    getter = getattr(index, "token_flags", None)
    if getter is not None:
        try:
            return getter(pid) or {}
        except Exception:  # noqa: BLE001 - an older index without the table
            return {}
    return {}


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


from .lemma_calibration import calibration, probability, summary as calibration_summary  # noqa: E402


def headlines(passage_id="", forms=(), dialect="", author=""):
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
        token_alts = _token_alternatives(index, pid)
        token_flags = _token_flags(index, pid)
        names = _forms(index, fid.tolist())
        for i in range(len(lem)):
            tokens.append({"i": i, "start": int(starts[i]), "end": int(starts[i]) + int(lengths[i]),
                           "form_id": int(fid[i]), "lemma_id": int(lem[i]), "confidence": round(int(conf[i]) / 255, 3),
                           "raw": int(conf[i]), "src": int(src[i]), "flags": token_flags.get(i, 0)})
    else:
        from .lemma_tokens import clean_form
        from .lemma_tokens import fold as fold_key
        from .headline_rules import folded_lookup, pronoun_vocative_only
        cleaned = [clean_form(f) for f in forms]
        con = index.con()
        found, matched = {}, {}
        for form in set(cleaned):
            row = con.execute("SELECT id FROM form WHERE form=?", (form,)).fetchone()
            if row:
                found[form] = row[0]
            else:
                # Release U: a spelling the index lacks, read by its letters (enclitic accent, psilosis).
                hit = folded_lookup(con, form, fold_key)
                if hit:
                    found[form] = hit[0]
                    matched[form] = {"spelling": hit[1], "rule": hit[2]}
        readings = _readings(index, found.values())
        names = _forms(index, found.values())
        pos_of = _lemmas(index, {r[0] for rows in readings.values() for r in rows})
        for i, (printed, form) in enumerate(zip(forms, cleaned)):
            f = found.get(form)
            rows = readings.get(f) or [(0, 0, 0, [])]
            top = rows[0]
            if len(rows) > 1 and pronoun_vocative_only(top[3], (pos_of.get(top[0]) or {}).get("pos")):
                # Release U: pronouns are not addressed; another headword of the spelling heads (αὖτε).
                other = next((r for r in rows[1:] if not pronoun_vocative_only(r[3], (pos_of.get(r[0]) or {}).get("pos"))), None)
                if other:
                    top = other
                    matched.setdefault(form, {})["pronoun_vocative"] = True
            tokens.append({"i": i, "printed": printed, "cleaned": form, "form_id": f or 0, "lemma_id": top[0],
                           "confidence": round(top[1], 3) if top[0] else 0.0,
                           "raw": max(1, min(255, round(top[1] * 255))) if top[0] else 0, "src": top[2]})
    if not passage_id:
        token_alts = {}
    lemma_ids = {t["lemma_id"] for t in tokens if t["lemma_id"]}
    lemma_ids.update(a[0] for a in token_alts.values())
    for rows in readings.values():
        lemma_ids.update(r[0] for r in rows)
    lemmas = _lemmas(index, lemma_ids)
    text = None
    if passage_id:
        from .server import connect
        with connect() as con:
            row = con.execute("SELECT text FROM passages WHERE id=?", (passage_id,)).fetchone()
        text = row[0] if row else ""
    from .passage_dialect import passage_dialect as _dialect_of
    if passage_id:
        text_dialect = _dialect_of({"author": index.author_of[pid] if pid < len(index.author_of) else "", "id": passage_id})
    else:
        text_dialect = (_dialect_of({"dialect": dialect}) if dialect else None) or (_dialect_of({"author": author}) if author else None)
    group = None
    if passage_id:
        # Release R: the passage's genre and dialect select the calibration group.
        from .lemma_calibration import context_group
        from .passage_dialect import passage_dialect
        label = index.author_of[pid] if pid < len(index.author_of) else ""
        info = index.authors.get(label) or {}
        group = context_group(info.get("genre"), passage_dialect({"author": label, "id": passage_id}))
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
                "probability": probability(t["raw"], t["src"], t.get("flags", 0), group) if t["lemma_id"] else None,
                "basis": describe_source(t["src"]),
                "alternatives": [{"lemma": lemmas.get(l, {}).get("lemma"), "lemma_id": l,
                                  "gloss": lemmas.get(l, {}).get("gloss"), "form_probability": round(p, 3),
                                  "parses": ps} for l, p, _, ps in rows if l != t["lemma_id"]],
                "tie": bool(rows) and len(rows) > 1 and rows[1][1] >= 0.8 * rows[0][1]}
        alt = token_alts.get(t["i"])
        if alt:
            # Release Q: an elided word whose two readings are both genuinely possible here.
            item["tie"] = True
            item["tie_basis"] = "elision_model"
            item["tie_alternative"] = {"lemma": lemmas.get(alt[0], {}).get("lemma"), "lemma_id": alt[0],
                                       "gloss": lemmas.get(alt[0], {}).get("gloss"), "token_probability": alt[1]}
            item["alternatives"].sort(key=lambda a: a["lemma_id"] != alt[0])
        if "start" in t:
            item.update(start=t["start"], end=t["end"], printed=text[t["start"]:t["end"]] if text else None)
        else:
            item["printed"] = t["printed"]
            extra = matched.get(t.get("cleaned")) if t.get("cleaned") else None
            if extra:
                if extra.get("rule"):
                    item["form_match"] = {"spelling": extra["spelling"], "rule": extra["rule"]}
                if extra.get("pronoun_vocative"):
                    item.setdefault("rules", []).append("pronoun_vocative")
        _apply_rules(item, head, text_dialect)
        out.append(item)
    stamp = index.manifest.get("built_at", "")
    calibrated = (calibration() or {}).get("built_at")
    digest = hashlib.sha256(json.dumps([stamp, calibrated, passage_id, list(forms), (text or ""), text_dialect, "u1"],
                                       ensure_ascii=False).encode()).hexdigest()
    return {"passage_id": passage_id or None, "index_version": index.manifest.get("version"), "index_built_at": stamp,
            "hash": digest, "tokens": out,
            "method": ("Headline = the corpus headword index's top reading of each token (parser, recorded forms, "
                       "generated dialect/elision spellings, rescored by the contextual model where it ran). "
                       "Alternatives are the spelling's other readings; for an elided word whose second reading is "
                       "genuinely possible in this context (release Q elision model) tie is true and "
                       "tie_alternative names it. Confidence is a normalised score; "
                       "probability is that score calibrated against treebank gold lemmas (release P, "
                       "/api/lemma/status calibration), null when no calibration is deployed. /api/word gives the "
                       "full analysis."), "calibration": calibration_summary()}


def _apply_rules(item, head, dialect):
    """Release U (backend.headline_rules): Lesbian/Doric ᾱ singulars, duals last, names in the vocative."""
    from .headline_rules import aeolic_singular, duals_last, name_vocative
    if not head:
        return
    parses, rule = aeolic_singular(item.get("printed") or item.get("form") or "", head["lemma"], head.get("pos"),
                                   list(item.get("parses") or []), dialect)
    rules = item.setdefault("rules", [])
    if rule:
        rules.append(rule)
    parses, rule = duals_last(parses, dialect)
    if rule:
        rules.append(rule)
    item["parses"] = parses
    named = name_vocative(item.get("printed") or "", head["lemma"], parses, head.get("gloss"))
    if named:
        item["dictionary_gloss"] = item.get("gloss")
        item["gloss"] = named
        rules.append("name_vocative")
    if dialect:
        item["dialect"] = dialect
    if not rules:
        item.pop("rules")


@lru_cache(maxsize=8192)
def _first_dictionary(lemma, senses=3):
    from .server import morph_service
    from .word_parser_candidates import lemma_dictionary_compact
    # Only the first few entries are rendered: the first dictionary with text is all that is sent.
    for limit in (1, 3):
        entries = lemma_dictionary_compact(lemma, lambda value: morph_service().headword_entries(value, limit=limit),
                                           senses=senses, first_only=True)
        if entries:
            return entries[0]
    return None


def with_dictionary(payload, senses=3):
    """Release P: `dictionaries` = {lemma: compact first dictionary entry (gloss, first senses, link)}
    for every headline lemma, so a tap needs no second request. The hash covers the option."""
    out = {}
    for token in payload["tokens"]:
        lemma = token.get("lemma")
        if lemma and lemma not in out:
            out[lemma] = _first_dictionary(lemma, senses)
    payload = dict(payload, dictionaries=out)
    payload["hash"] = hashlib.sha256((payload["hash"] + ":dictionary").encode()).hexdigest()
    return payload


@router.post("/api/words/headlines")
def words_headlines(request: HeadlineRequest):
    if not request.passage_id and not request.forms:
        raise HTTPException(422, "Give passage_id or forms.")
    payload = headlines(request.passage_id, request.forms, request.dialect, request.author)
    if request.dictionary:
        payload = with_dictionary(payload)
    return JSONResponse(payload, headers={"ETag": '"' + payload["hash"] + '"',
                                          "Cache-Control": "public, max-age=3600"})


@router.get("/api/words/headlines")
def words_headlines_get(passage_id: str, dictionary: bool = False):
    """GET form for caching proxies; same payload as the POST with passage_id."""
    payload = headlines(passage_id, ())
    if dictionary:
        payload = with_dictionary(payload)
    return JSONResponse(payload, headers={"ETag": '"' + payload["hash"] + '"',
                                          "Cache-Control": "public, max-age=3600"})
