"""Inspectable, bounded fusion of independently ranked passage candidates.

The inputs are already retrieved lists. This module does not infer meanings,
create passage links, or compare lexical and cosine scores on one scale.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
import unicodedata


SIGNALS = ("lexical", "forms", "semantic")
K = 60  # Conventional RRF damping; a rank, never a confidence probability.
# Raw OCR, mixed material and review-needed rows never enter fusion. Text
# labelled machine_corrected_ocr does, carrying that label into the result.
EXCLUDED_QUALITIES = frozenset({"mixed_content", "machine_ocr", "needs_review"})
EVIDENCE_EXCERPT_LIMIT = 200


def evidence_hit(record: Mapping[str, Any], hit: Mapping[str, Any], signal: str,
                 projection_scope: str = "direct_source_record") -> dict[str, Any]:
    """Keep a bounded literal source snippet with a retrieval breadcrumb."""
    source_text = record.get("text") if isinstance(record.get("text"), str) else ""
    excerpt = source_text[:EVIDENCE_EXCERPT_LIMIT]
    return {
        "id": record["id"],
        "signal": signal,
        "kind": record.get("kind"),
        "quality": record.get("quality"),
        "language": record.get("language"),
        "author": record.get("author"),
        "edition": record.get("edition"),
        "citation": record.get("citation"),
        "source_url": record.get("source_url"),
        "parent_id": record.get("parent_id"),
        "projection_scope": projection_scope,
        "text_excerpt": excerpt,
        "excerpt_truncated": len(source_text) > EVIDENCE_EXCERPT_LIMIT,
        "match_reason": hit.get("match_reason") or (
            "Ranked word match" if signal == "lexical" else
            "Ranked source-backed form match" if signal == "forms" else
            "Dense embedding similarity"),
        "raw_score": hit.get("score"),
    }


def _key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold().strip()


def _default_author_keys(label: Any) -> set[str]:
    return {_key(label)}


def _eligible(record: Mapping[str, Any], *, authors: set[str], language: str,
              edition: str, include_reference: bool,
              author_keys: Callable[[Any], Iterable[str]] = _default_author_keys) -> bool:
    if authors and not (set(author_keys(record.get("author"))) & authors):
        return False
    if language and record.get("language") != language:
        return False
    if edition and record.get("edition") != edition:
        return False
    if not include_reference and record.get("kind") in {"reference", "apparatus"}:
        return False
    if not include_reference and record.get("quality") in EXCLUDED_QUALITIES:
        return False
    return True


def _mirror_key(record: Mapping[str, Any], author_key: Callable[[Any], str] = _key) -> tuple[Any, ...]:
    """Collapse copies of one text: same author, language, kind, quality label and words.

    Aggregator mirrors of a Perseus or DCC edition, and distinct editions that
    print identical words, fold into one result. The collapsed IDs stay listed
    in ``mirrored_ids`` so every copy remains reachable. Differing words are
    never merged, however similar the citation.
    """
    if not record.get("text"):
        return ("id", record["id"])
    return (
        "text", author_key(record.get("author")),
        record.get("language"), record.get("kind"), record.get("quality"),
        " ".join(unicodedata.normalize("NFC", str(record["text"])).split()),
    )


def fuse(
    query: str,
    lexical: Iterable[Mapping[str, Any]],
    forms: Iterable[Mapping[str, Any]],
    semantic: Iterable[Mapping[str, Any]],
    fetch_record: Callable[[str], Mapping[str, Any] | None],
    *,
    author: str = "",
    author_labels: Iterable[str] | None = None,
    language: str = "",
    edition: str = "",
    include_reference: bool = False,
    limit: int = 30,
    offset: int = 0,
    commentary_assisted: bool = True,
    author_key: Callable[[Any], str] = _key,
    author_keys: Callable[[Any], Iterable[str]] | None = None,
    weights: Mapping[str, float] | None = None,
    extra: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Fuse ranked lists and return passage records with source-bearing hits.

    Each input is in relevance order and contains ``id``; full passage records
    and lightweight semantic hits are both accepted. ``fetch_record`` resolves
    an ID from the corpus, including an explicit ``parent_id``. Any
    ``author_labels`` must be externally verified aliases. Filtering is
    applied to the returned record after any parent projection. The caller
    should bound each input pool before this function, and disclose that bound.
    """
    if limit < 0 or offset < 0:
        raise ValueError("limit and offset must be nonnegative")
    if not query.strip():
        return {"results": [], "total": 0, "method": "Empty query", "warnings": []}

    # ``author_key`` names the group a record belongs to (its canonical author);
    # ``author_keys`` lists every author a record answers to, so a joint label
    # such as ``Sappho / Alcaeus`` passes a filter for either poet.
    if author_keys is None:
        author_keys = lambda label: {author_key(label)}  # noqa: E731
    authors = {author_key(label) for label in (author_labels or ()) if _key(label)}
    if author:
        authors.add(author_key(author))

    cached: dict[str, Mapping[str, Any] | None] = {}

    def resolve(hit: Mapping[str, Any]) -> Mapping[str, Any] | None:
        identifier = hit.get("id")
        if not isinstance(identifier, str) or not identifier:
            return None
        if identifier not in cached:
            # A full record can save a lookup. An index hit has no source text.
            cached[identifier] = hit if "text" in hit and "kind" in hit else fetch_record(identifier)
        return cached[identifier]

    def eligible_target(record: Mapping[str, Any]) -> bool:
        if _eligible(record, authors=authors, language=language, edition=edition,
                     include_reference=include_reference, author_keys=author_keys):
            return True
        # A selected output language/edition can prevent Greek-parent
        # projection. Retain the translation's real author and constraints,
        # but let an explicit eligible Greek parent establish author scope.
        if (not commentary_assisted or not authors
                or record.get("kind") not in {"translation", "commentary"}
                or not _eligible(record, authors=set(), language=language, edition=edition,
                                 include_reference=include_reference, author_keys=author_keys)):
            return False
        parent = resolve({"id": record.get("parent_id")})
        return bool(parent and parent.get("kind") == "text" and parent.get("language") == "grc"
                    and _eligible(parent, authors=authors, language="grc", edition="",
                                  include_reference=include_reference, author_keys=author_keys))

    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    skipped_unresolved = 0
    # ``weights`` scales each signal's reciprocal-rank votes (default 1.0);
    # ``extra`` adds further named ranked lists (for example a BM25 pass over
    # linked English records). Both keep the fusion a rank method, never a
    # sum of incomparable raw scores.
    weights = dict(weights or {})
    signal_lists = list(zip(SIGNALS, (lexical, forms, semantic))) + list((extra or {}).items())
    signal_names = [name for name, _ in signal_lists]
    for signal, hits in signal_lists:
        seen_this_signal: set[tuple[Any, ...]] = set()
        rank = 0
        for hit in hits:
            record = resolve(hit)
            if record is None:
                skipped_unresolved += 1
                continue
            if not include_reference and record.get("quality") in EXCLUDED_QUALITIES:
                continue
            if not commentary_assisted and (record.get("kind") != "text"
                                            or record.get("language") != "grc"):
                continue
            target = record
            parent_id = record.get("parent_id")
            if (commentary_assisted and record.get("kind") in {"translation", "commentary"}
                    and isinstance(parent_id, str) and parent_id):
                parent = resolve({"id": parent_id})
                if (parent and parent.get("kind") == "text" and parent.get("language") == "grc"
                        and _eligible(parent, authors=authors, language=language,
                                      edition=edition, include_reference=include_reference,
                                      author_keys=author_keys)):
                    target = parent
            if not eligible_target(target):
                # A grouped lexical hit may stand for copies that pass the
                # filter although its representative does not (the same words
                # in another edition). Fall back to the first eligible copy.
                substitute = None
                for copy_id in (target.get("mirrored_ids") or []):
                    candidate = resolve({"id": str(copy_id)})
                    if candidate and eligible_target(candidate):
                        substitute = candidate
                        break
                if substitute is None:
                    continue
                target = substitute
            group_key = _mirror_key(target, author_key)
            if group_key not in groups:
                groups[group_key] = {"record": dict(target), "rrf": 0.0,
                                     "ranks": {}, "matched_evidence": [], "evidence_keys": set(),
                                     "mirror_ids": set()}
                if authors and not (set(author_keys(target.get("author"))) & authors):
                    groups[group_key]["record"]["author_scope_reason"] = (
                        "Linked to the selected author by an explicit Greek parent passage; "
                        "translation/commentary authorship is retained.")
            group = groups[group_key]
            group["mirror_ids"].add(target["id"])
            # A lexical hit may already be a grouped representative carrying the
            # copies it collapsed; keep them visible through fusion as well.
            group["mirror_ids"].update(str(copy) for copy in (target.get("mirrored_ids") or []) if copy)
            evidence_key = (signal, record["id"])
            if evidence_key not in group["evidence_keys"]:
                group["evidence_keys"].add(evidence_key)
                scope = ("explicit_parent_id" if target["id"] != record["id"]
                         and parent_id == target["id"] else "direct_source_record")
                group["matched_evidence"].append(evidence_hit(record, hit, signal, scope))
            # Multiple matches to one Greek passage or mirrored edition in a
            # single list provide one RRF vote. Their evidence is still shown.
            if group_key not in seen_this_signal:
                rank += 1
                seen_this_signal.add(group_key)
                group["ranks"][signal] = rank
                group["rrf"] += float(weights.get(signal, 1.0)) / (K + rank)

    ranked = sorted(groups.values(), key=lambda group: (
        -group["rrf"],
        min(group["ranks"].values()),
        str(group["record"]["id"]),
    ))
    output = []
    for group in ranked[offset:offset + limit]:
        item = group["record"]
        item["score"] = round(group["rrf"], 8)
        item["retrieval_score_kind"] = "reciprocal_rank_fusion"
        item["retrieval_ranks"] = group["ranks"]
        item["matched_evidence"] = group["matched_evidence"]
        item["mirrored_ids"] = sorted(group["mirror_ids"] - {item["id"]})
        item["mirror_count"] = len(group["mirror_ids"])
        signals = [name for name in signal_names if name in group["ranks"]]
        bridged = any(e["id"] != item["id"] for e in group["matched_evidence"])
        item["match_reason"] = " + ".join(signals) + (
            "; linked translation/commentary evidence" if bridged else "; direct passage match")
        output.append(item)
    warnings = ["RRF scores rank this bounded candidate pool; they are not probabilities or evidence of literary influence."]
    if skipped_unresolved:
        warnings.append(f"Skipped {skipped_unresolved} unresolved candidate hits.")
    return {
        "results": output,
        "total": len(ranked),
        "method": "Reciprocal rank fusion of word, form, and dense candidates; linked evidence grouped by explicit parent ID.",
        "warnings": warnings,
    }
