"""Release U: typed Greek (a composer's draft) analysed like a stored passage (POST /api/analyze-text).

``draft_passage`` validates the request and builds the ephemeral passage plus the internal passage-analysis
request; ``attach_headlines`` adds, for every word of the interlinear reading, the headword, gloss and parse
the reader shows on a click (js/word-panel.js headlineDetail, release R rule; the same rule
scripts/eval_lyric_gold.py scores), so a client needs no frontend logic to read the result.
"""
from __future__ import annotations

import hashlib
import unicodedata

from .passage_analysis import MAX_CHARACTERS, PassageAnalysisError

DIALECTS = {"lesbian": "lesbian", "aeolic": "lesbian", "doric": "doric", "laconian": "doric",
            "boeotian": "boeotian", "ionic": "ionic", "attic": "attic", "epic": "epic", "none": "attic"}
ELISION = "’'ʼ᾽"
ALLOWED = {"version", "text", "dialect", "author", "fetch_machine", "detail"}
GLOSS_FIELDS = ("text", "short_text", "status", "source", "entry_id", "selection_basis")


def draft_passage(request):
    if not isinstance(request, dict) or set(request) - ALLOWED:
        raise PassageAnalysisError("invalid_request", "Only text, dialect, author and fetch_machine are accepted.")
    if request.get("version", 1) != 1:
        raise PassageAnalysisError("unsupported_version", "Unsupported analysis version.")
    text = request.get("text")
    if not isinstance(text, str):
        raise PassageAnalysisError("invalid_text", "text must be a string of Greek.")
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip("\n ")
    if not text or len(text) > MAX_CHARACTERS:
        raise PassageAnalysisError("invalid_text", f"Send 1–{MAX_CHARACTERS} characters of Greek.")
    if not any("Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿" for c in text):
        raise PassageAnalysisError("invalid_text", "The text has no Greek letters.")
    dialect = request.get("dialect")
    if dialect is not None:
        if not isinstance(dialect, str) or dialect.strip().casefold() not in DIALECTS:
            raise PassageAnalysisError("invalid_dialect", "dialect must be one of: " + ", ".join(sorted(DIALECTS)))
        dialect = DIALECTS[dialect.strip().casefold()]
    author = request.get("author")
    if author is not None and (not isinstance(author, str) or len(author) > 120):
        raise PassageAnalysisError("invalid_author", "author must be a short author name.")
    if request.get("detail", "compact") not in ("compact", "full"):
        raise PassageAnalysisError("invalid_detail", "detail must be compact or full.")
    fetch = request.get("fetch_machine", True)
    if type(fetch) is not bool:
        raise PassageAnalysisError("invalid_flag", "fetch_machine must be a boolean.")
    digest = hashlib.sha256(text.encode()).hexdigest()
    passage = {"id": "draft:" + digest[:16], "text": text, "language": "grc", "kind": "text",
               "detail": request.get("detail", "compact"),
               "author": (author or "").strip(), "source": "draft", "work": None, "citation": None,
               "translation_previews": [], "related": []}
    if dialect:
        passage["dialect"] = dialect
    internal = {"version": 1, "passage_id": passage["id"], "start": 0, "end": len(text), "offset_unit": "codepoint",
                "selected_text": text, "rerank": False, "fetch_machine": fetch}
    return passage, internal


def _key(s):
    s = unicodedata.normalize("NFD", str(s or "")).casefold()
    return "".join(c for c in s if not unicodedata.combining(c)).rstrip("0123456789 ")


def headline(row):
    """(lemma, features, parse) the reader shows for an interlinear row (release R frontend rule)."""
    ranking = row.get("morphology_ranking") or []
    feats_of = {m.get("candidate_id"): m.get("features") for m in row.get("candidate_meanings") or []}
    text = row.get("text") or ""
    elided = text[-1:] in ELISION
    if row.get("lemma"):
        if not row.get("parse_short"):
            own = next((i for i in ranking if i.get("lemma") and i.get("parse_short")
                        and _key(i["lemma"]) == _key(row["lemma"])), None)
            if own:
                return own["lemma"], feats_of.get(own.get("candidate_id")) or {}, own["parse_short"]
        return row["lemma"], row.get("features") or {}, row.get("parse_short") or ""

    def usable(item):
        return item.get("lemma") and item.get("parse_short") and not (
            elided and _key(item["lemma"]).rstrip(ELISION) == _key(text).rstrip(ELISION))
    head = row.get("headline_lemma")
    item = next((i for i in ranking if usable(i) and _key(i["lemma"]) == _key(head)), None) if head else None
    item = item or next((i for i in ranking if usable(i)), None)
    if item:
        return item["lemma"], feats_of.get(item.get("candidate_id")) or {}, item["parse_short"] or row.get("parse_short") or ""
    if head and not (elided and _key(head).rstrip(ELISION) == _key(text).rstrip(ELISION)):
        return head, {}, ""
    return "", {}, row.get("parse_short") or ""


def attach_headlines(result, passage):
    readings = (result.get("interlinear") or {}).get("readings") or [{}]
    words = []
    for row in readings[0].get("tokens", []) if readings else []:
        if row.get("kind") != "word":
            continue
        lemma, features, parse = headline(row)
        gloss = row.get("gloss") or {}
        alternatives = []
        for item in row.get("morphology_ranking") or []:
            if item.get("lemma") and (item.get("lemma"), item.get("parse_short")) not in alternatives:
                alternatives.append((item.get("lemma"), item.get("parse_short")))
        row["headline"] = {"lemma": lemma or None, "parse": parse or None, "features": features,
                           "gloss": gloss.get("short_text") or gloss.get("text"), "status": row.get("status")}
        words.append({"text": row.get("text"), "start": row.get("start"), "end": row.get("end"),
                      **row["headline"],
                      "alternatives": [{"lemma": a, "parse": b} for a, b in alternatives[:6]],
                      "dialect_rules": row.get("dialect_rules")})
    result["words"] = words
    from .passage_dialect import passage_dialect
    result["draft"] = {"id": passage["id"], "dialect": passage_dialect(passage) or passage.get("dialect"),
                       "author_hint": passage.get("author") or None, "stored": False,
                       "note": "Typed text analysed like a stored passage; it is not stored and is not a corpus attestation."}
    if passage.get("detail") == "full":
        return result
    return compact(result)


def compact(result):
    """The composer's view: what the reader shows per word and per phrase, without the source inventories
    (dictionary entries, every sense, claim records) that make the full analysis 10-20 MB for a stanza."""
    interlinear = dict(result.get("interlinear") or {})
    readings = []
    for reading in interlinear.get("readings") or []:
        rows = []
        for row in reading.get("tokens") or []:
            row = {k: v for k, v in row.items() if k not in ("candidate_meanings", "source_candidate")}
            if isinstance(row.get("gloss"), dict):
                row["gloss"] = {k: row["gloss"].get(k) for k in GLOSS_FIELDS if k in row["gloss"]}
            if isinstance(row.get("morphology_ranking"), list):
                row["morphology_ranking"] = row["morphology_ranking"][:8]
            rows.append(row)
        readings.append({**{k: v for k, v in reading.items() if k != "tokens"}, "tokens": rows})
    interlinear["readings"] = readings
    syntax = result.get("syntax") or {}
    meaning = result.get("meaning") or {}
    return {"version": result.get("version"), "status": result.get("status"), "detail": "compact",
            "draft": result.get("draft"), "words": result.get("words"), "interlinear": interlinear,
            "relationships": meaning.get("relationships"),
            "meaning": {k: meaning.get(k) for k in ("status", "summary", "interpretations") if k in meaning},
            "syntax": {k: syntax.get(k) for k in ("status", "state", "model", "annotation_scheme", "tokens", "warnings",
                                                  "limitations") if k in syntax},
            "lint": result.get("lint"), "limits": result.get("limits"), "warnings": result.get("warnings"),
            "detail_note": "Pass detail=full for every token's dictionary entries, candidates and source claims."}
