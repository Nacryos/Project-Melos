"""HTTP API for citation resolution (release P). See docs/api-contract.md "Citations (release P)"."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
# Fragment numbering schemes the release-O reference lookup recognises in a query.
_REFERENCE_SCHEMES = {"Voigt", "Lobel-Page", "Page", "PMG", "PMGF", "Campbell", "Edmonds", "Bergk"}


def _index():
    from .citations import get_citation_index
    try:
        return get_citation_index()
    except FileNotFoundError as exc:
        raise HTTPException(503, "The citation index is not available on this deployment.") from exc


def _records(ids):
    """Full passage records (as /api/search returns them) for these ids, in order."""
    if not ids:
        return {}
    from .server import connect, unpack
    out = {}
    with connect() as con:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for row in con.execute(f"SELECT data FROM passages WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                record = unpack(row)
                out[record["id"]] = record
    return out


def _fragment(parsed, number, scheme, include_reference, limit):
    """Release-O exact fragment lookup for author + number (+ scheme it recognises)."""
    from .server import search
    suffix = f" {scheme}" if scheme in _REFERENCE_SCHEMES else ""
    result = search(q=f"{parsed['author']} fr. {number}{suffix}", include_reference=include_reference, limit=limit)
    if result.get("mode") != "reference":
        return {"results": [], "total": 0, "warnings": ["The author has no fragment citations in this corpus."]}
    if scheme and not suffix:
        result.setdefault("warnings", []).append(
            f"{scheme} numbers are not recorded in this corpus's citations; matched the number in any numbering.")
    return result


def resolve_citation(q, *, include_reference=False, limit=20):
    """The /api/cite payload, or None when q is not a citation."""
    from .citations import resolve, _locus_text
    try:
        result = resolve(q, limit=limit)
    except FileNotFoundError:
        return None
    if result is None:
        return None
    parsed = result["parsed"]
    if parsed.get("kind") == "fragment":
        number = _locus_text(parsed["locus"])
        scheme = parsed.get("scheme") or ""
        main = _fragment(parsed, number, scheme, include_reference, limit)
        equivalents = []
        for eq in _index().equivalents(parsed["author"], number, scheme):
            found = _fragment(parsed, eq["number"], eq["scheme"], include_reference, limit)
            equivalents.append(dict(eq, results=[{k: r.get(k) for k in ("id", "author", "work", "citation", "source",
                                                                         "edition", "quality", "kind")}
                                                 for r in found.get("results", [])][:10]))
        warnings = list(main.get("warnings") or [])
        if equivalents:
            warnings.append("Equivalent numbers are listed only where one record prints both numbers "
                            "(see each equivalence's evidence); no concordance is inferred.")
        return {"query": q, "parsed": parsed, "kind": "fragment", "results": main.get("results", []),
                "total": main.get("total", 0), "equivalents": equivalents, "warnings": warnings,
                "method": "Exact author + fragment citation (release O rule) plus printed equivalences."}
    records = _records([r["id"] for r in result["results"]])
    for row in result["results"]:
        record = records.get(row["id"]) or {}
        text = record.get("text") or ""
        row["text_preview"] = text[:240]
        row["language"] = record.get("language")
    result["kind"] = parsed.get("kind")
    return result


@router.get("/api/cite")
def cite(q: str, include_reference: bool = False, limit: int = Query(20, ge=1, le=100)):
    """Resolve a citation ("Il. 1.1", "Pind. O. 1.1", "Sappho fr. 31", "urn:cts:greekLit:tlg0012.tlg001:1.1")."""
    if not q.strip() or len(q) > 200:
        raise HTTPException(422, "Give a citation such as Il. 1.1, Pind. O. 1.1, Sappho fr. 31 or a CTS URN.")
    result = resolve_citation(q, include_reference=include_reference, limit=limit)
    if result is None:
        _index()  # 503 when the index is missing
        return {"query": q, "parsed": None, "results": [], "total": 0,
                "warnings": ["Not recognised as a citation (author or work abbreviation followed by a locus, "
                             "a fragment number, or a CTS URN)."]}
    return result


@router.get("/api/cite/status")
def cite_status():
    return _index().status()


@router.get("/api/cite/catalogue")
def cite_catalogue(author: str = ""):
    """TLG author/work numbers attached to the corpus's works, each with its source."""
    index = _index()
    rows = []
    for w in index.works:
        if author and w["author"].casefold() != author.casefold():
            continue
        rows.append({"author": w["author"], "work": w["display_work"], "loci": w["loci"],
                     "tlg": f"{w['tlg_author']}.{w['tlg_work']}" if w["tlg_work"] else None,
                     "tlg_source": w["tlg_source"], "tlg_evidence": json.loads(w["tlg_evidence"]) if w["tlg_evidence"] else None,
                     "first_passage": w["first_passage"], "labels": json.loads(w["labels"] or "{}"),
                     "sources": json.loads(w["sources"] or "{}")})
    rows.sort(key=lambda r: (r["author"], r["work"]))
    authors = {}
    for r in rows:
        if r["tlg"]:
            authors.setdefault(r["author"], set()).add(r["tlg"].split(".")[0])
    return {"works": rows, "authors": {a: sorted(v) for a, v in authors.items()},
            "sources_note": ("record_urn: the record's own CTS URN; ogc_readme: the Open Greek Corpus README; "
                             "cts_catalogue: the PerseusDL/First1KGreek CTS catalogue (__cts__.xml); text_match: the "
                             "same verse lines as records carrying the URN. No mapping comes from the TLG website."),
            **{k: index.manifest.get(k) for k in ("version", "built_at", "tlg_sources")}}


def citation_search(q, *, include_reference=False, limit=30, offset=0):
    """A search-shaped response for a line/book citation or URN typed in the search box, else None."""
    try:
        result = resolve_citation(q, include_reference=include_reference, limit=min(100, offset + limit))
    except HTTPException:
        return None
    if not result or result.get("kind") not in ("locus", "urn") or not result.get("results"):
        return None
    from .author_catalogue import display_fields
    from .source_labels import with_source_label
    records = _records([r["id"] for r in result["results"]])
    out = []
    for row in result["results"][offset:offset + limit]:
        record = records.get(row["id"])
        if not record:
            continue
        record = dict(record)
        record["match_reason"] = (f"Citation {q}: this passage is cited {row['citation']} "
                                  + ("(contains the locus)" if row["contains_locus"] else "(overlaps the locus)"))
        record["citation_match"] = {k: row[k] for k in ("locus_start", "locus_end", "contains_locus", "tlg")}
        record["score"] = None
        with_source_label(record)
        record.update(display_fields(record))
        out.append(record)
    return {"results": out, "total": result["total"], "mode": "citation", "method": result.get("method"),
            "warnings": result.get("warnings", []), "citation": result.get("parsed")}
