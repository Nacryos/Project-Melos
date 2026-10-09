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


_LABELS = {}


def _indexed_reference(q, include_reference, limit):
    """The release-O reference search for `q`, reading only the records whose stated fragment number
    is the queried one (citation index table ref_number) instead of every record of the poet.
    Same record set, filters and ranking as server.search's reference branch; None when the index
    cannot answer (no table, another corpus file, or not a reference query), so the caller falls back."""
    from .server import DB, QUALITY_SQL, author_key, author_labels, connect, unpack
    from .reference_lookup import parse_reference_query, rank_reference_records
    index = _index()
    with connect() as con:
        stamp = (str(DB), DB.stat().st_mtime_ns if DB.exists() else 0)
        if stamp not in _LABELS:
            _LABELS.clear()
            _LABELS[stamp] = [row[0] for row in con.execute("SELECT DISTINCT author FROM works")]
        intent = parse_reference_query(q, _LABELS[stamp], selected_author="", alias_resolver=author_labels)
        if not intent:
            return None
        ids = index.ref_number_ids(intent.number, DB)
        if ids is None:
            return None
        keys = {author_key(label) for label in intent.author_labels}
        rows, parents = {}, {}

        def fetch(wanted, into):
            wanted = [i for i in dict.fromkeys(wanted) if i and i not in into]
            for start in range(0, len(wanted), 500):
                chunk = wanted[start:start + 500]
                for row in con.execute(f"SELECT id, author, kind, language, quality, data FROM passages "
                                       f"WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                    into[row["id"]] = row
        fetch(ids, rows)
        parent_of = {i: json.loads(r["data"]).get("parent_id") for i, r in rows.items()
                     if r["kind"] in ("translation", "commentary")}
        fetch(parent_of.values(), parents)
        allowed = None if include_reference else set(QUALITY_SQL.strip("()").replace("'", "").split(","))
        keep = []
        for i, r in rows.items():
            if author_key(r["author"]) in keys:
                keep.append(r)
                continue
            p = parents.get(parent_of.get(i)) or rows.get(parent_of.get(i))
            if (p is not None and p["kind"] == "text" and p["language"] == "grc"
                    and (allowed is None or p["quality"] in allowed) and author_key(p["author"]) in keys):
                keep.append(r)
        # A linked translation finds its parent in the record list (the poet's records include it).
        extra = [p for p in parents.values() if p["id"] not in rows and author_key(p["author"]) in keys]
        records = [unpack(r) for r in keep + extra]
    return rank_reference_records(intent, records, limit=limit, offset=0, include_reference=include_reference)


def _fragment(parsed, number, scheme, include_reference, limit):
    """Release-O exact fragment lookup for author + number (+ scheme it recognises)."""
    from .server import search
    suffix = f" {scheme}" if scheme in _REFERENCE_SCHEMES else ""
    query = f"{parsed['author']} fr. {number}{suffix}"
    result = _indexed_reference(query, include_reference, limit)
    if result is None:
        result = search(q=query, include_reference=include_reference, limit=limit)
    if result.get("mode") != "reference":
        return {"results": [], "total": 0, "warnings": ["The author has no fragment citations in this corpus."]}
    if scheme and not suffix:
        result.setdefault("warnings", []).append(
            f"{scheme} numbers are not recorded in this corpus's citations; matched the number in any numbering.")
    return result


_SUMMARY = ("id", "author", "work", "citation", "source", "edition", "quality", "kind")
_STRENGTH = {"query": 0, "printed": 1, "source": 1, "convention": 2}
_BASIS = {"record_citation": 0, "edition_heading": 0, "edition_heading_explicit": 0, "edition_numbering_statement": 1}
_BASIS_TEXT = {
    "record_citation": "the record's own citation names this numbering",
    "edition_heading": "the edition's own printed number",
    "edition_heading_explicit": "the edition prints this number with its edition's siglum",
    "edition_numbering_statement": "the edition states that it uses this numbering",
}


def _edge_text(edge):
    if edge.get("strength") == "printed":
        return f"printed in {edge.get('record')}: {edge.get('evidence')}"
    source = edge.get("source") or {}
    label = f"{source.get('title')} (Wikipedia, revision {source.get('revid')})" if source.get("kind") == "wikipedia" \
        else str(source.get("title") or source.get("kind") or "source")
    lead = "general statement, " if edge.get("strength") == "convention" else ""
    return f"{lead}{label}: \"{source.get('quote')}\""


def _scheme_fragment(q, parsed, include_reference, limit):
    """A fragment number in a named numbering ("Sappho fr. 31 V", "Alc. 346 L-P", "Sappho Campbell 16").

    Results: the records citable by that number in that numbering, then records citable by an equal
    number in another numbering (an equivalence printed by a record or stated by a cited source; a
    source's general statement that two numberings agree is used last and labelled 'convention').
    Each result says why (`numbering`). With no such record the release-O lookup answers."""
    from .citations import _locus_text
    index = _index()
    number = _locus_text(parsed["locus"]).lower()
    scheme = parsed["scheme"]
    warnings = []
    if parsed.get("author"):
        authors = [parsed["author"]]
    else:
        authors = index.fragment_authors(scheme, number)
        if not authors:
            return {"query": q, "parsed": parsed, "kind": "fragment", "results": [], "total": 0, "equivalents": [],
                    "warnings": [f"No poet in this corpus has a record citable as {scheme} {number}; "
                                 "name the poet (e.g. Sappho fr. 31 V)."]}
        if len(authors) > 1:
            warnings.append(f"{scheme} {number} names poems of several poets ({', '.join(authors)}); "
                            "add the poet's name to choose one.")
    hits, equivalents = {}, []
    for author in authors:
        for node in index.concordance(author, scheme, number):
            refs = index.fragment_refs(author, node["scheme"], node["number"])
            if node["strength"] != "query":
                equivalents.append({"author": author, "scheme": node["scheme"], "number": node["number"],
                                    "from_scheme": scheme, "strength": node["strength"],
                                    "evidence": [_edge_text(e) for e in node["via"]],
                                    "record": next((e.get("record") for e in node["via"] if e.get("record")), None),
                                    "passage_ids": [r["passage_id"] for r in refs][:10]})
            for ref in refs:
                info = {"author": author, "scheme": node["scheme"], "number": node["number"],
                        "strength": node["strength"], "basis": ref["basis"],
                        "basis_text": _BASIS_TEXT.get(ref["basis"], ref["basis"]), "evidence": ref["evidence"],
                        "equivalence": [_edge_text(e) for e in node["via"]]}
                key = (_STRENGTH[info["strength"]], _BASIS.get(info["basis"], 2))
                old = hits.get(ref["passage_id"])
                if old is None or key < (_STRENGTH[old["strength"]], _BASIS.get(old["basis"], 2)):
                    hits[ref["passage_id"]] = info
    if not hits:
        if not parsed.get("author"):
            return {"query": q, "parsed": parsed, "kind": "fragment", "results": [], "total": 0,
                    "equivalents": equivalents, "warnings": warnings}
        main = _fragment(parsed, number, scheme, include_reference, limit)
        return {"query": q, "parsed": parsed, "kind": "fragment", "results": main.get("results", []),
                "total": main.get("total", 0), "equivalents": equivalents,
                "warnings": warnings + list(main.get("warnings") or []),
                "method": "Exact author + fragment citation (release O rule); no record is citable in this numbering."}
    records = _records(list(hits))
    for eq in equivalents:
        eq["results"] = [{k: records[p].get(k) for k in _SUMMARY} for p in eq["passage_ids"] if p in records]
    rank = {"text": 0, "reference": 2, "commentary": 3, "apparatus": 4}
    results = []
    for pid, info in hits.items():
        record = records.get(pid)
        if not record:
            continue  # not served under this deployment's publication policy
        item = dict(record)
        item["numbering"] = info
        item["score"] = None
        how = ("same number" if info["strength"] == "query" else
               f"= {info['scheme']} {info['number']} ({'general convention' if info['strength'] == 'convention' else 'stated equivalence'})")
        item["match_reason"] = f"{scheme} {number}: {how}; {info['basis_text']}"
        results.append(item)
    results.sort(key=lambda r: (_STRENGTH[r["numbering"]["strength"]], _BASIS.get(r["numbering"]["basis"], 2),
                                rank.get(r.get("kind"), 5), r.get("quality") not in ("source_text", "machine_corrected_ocr"),
                                r.get("author") or "", str(r.get("id"))))
    if any(r["numbering"]["strength"] == "convention" for r in results) and \
            not any(r["numbering"]["strength"] != "convention" for r in results):
        warnings.append("Reached only through a general statement that the two numberings agree with minor variations "
                        "(see each result's evidence); this fragment's own equivalence is not stated by a source here.")
    elif any(r["numbering"]["strength"] == "convention" for r in results):
        warnings.append("Some results are reached only through a general numbering convention (labelled 'convention').")
    warnings.append("Fragment numbers are edition-specific: each result says which numbering it is cited by and why.")
    return {"query": q, "parsed": parsed, "kind": "fragment", "results": results[:limit], "total": len(results),
            "equivalents": equivalents, "warnings": warnings,
            "method": ("Records citable in the named numbering (their own citation, or their edition's printed number "
                       "and numbering statement), then equal numbers in other numberings stated by a record or a "
                       "cited source (data/fragment_concordance.json), then a source's general convention.")}


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
        if parsed.get("scheme"):
            return _scheme_fragment(q, parsed, include_reference, limit)
        number = _locus_text(parsed["locus"])
        scheme = ""
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
