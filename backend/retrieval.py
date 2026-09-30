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


def _key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold().strip()


def _eligible(record: Mapping[str, Any], *, authors: set[str], language: str,
              edition: str, include_reference: bool) -> bool:
    if authors and _key(record.get("author")) not in authors:
        return False
    if language and record.get("language") != language:
        return False
    if edition and record.get("edition") != edition:
        return False
    if not include_reference and record.get("kind") in {"reference", "apparatus"}:
        return False
    if not include_reference and record.get("quality") in {"mixed_content", "machine_ocr", "needs_review"}:
        return False
    return True


def _mirror_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Collapse copies only where the *same edition and text* are identifiable.

    A shared work, citation, or similar text alone can represent distinct
    editorial witnesses and must not erase a result.
    """
    metadata = record.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    edition_id = metadata.get("cts_urn") or metadata.get("tei_edition_urn")
    edition = edition_id or record.get("edition")
    if not edition or not record.get("text"):
        return ("id", record["id"])
    return (
        "edition", _key(edition), _key(record.get("author")),
        _key(record.get("work")), _key(record.get("citation")),
        record.get("language"), record.get("kind"),
        " ".join(str(record["text"]).split()),
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

    authors = {_key(label) for label in (author_labels or ()) if _key(label)}
    if author:
        authors.add(_key(author))

    cached: dict[str, Mapping[str, Any] | None] = {}

    def resolve(hit: Mapping[str, Any]) -> Mapping[str, Any] | None:
        identifier = hit.get("id")
        if not isinstance(identifier, str) or not identifier:
            return None
        if identifier not in cached:
            # A full record can save a lookup. An index hit has no source text.
            cached[identifier] = hit if "text" in hit and "kind" in hit else fetch_record(identifier)
        return cached[identifier]

    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    skipped_unresolved = 0
    for signal, hits in zip(SIGNALS, (lexical, forms, semantic)):
        seen_this_signal: set[tuple[Any, ...]] = set()
        rank = 0
        for hit in hits:
            record = resolve(hit)
            if record is None:
                skipped_unresolved += 1
                continue
            if not include_reference and record.get("quality") in {"mixed_content", "machine_ocr", "needs_review"}:
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
                                      edition=edition, include_reference=include_reference)):
                    target = parent
            if not _eligible(target, authors=authors, language=language,
                             edition=edition, include_reference=include_reference):
                continue
            group_key = _mirror_key(target)
            if group_key not in groups:
                groups[group_key] = {"record": dict(target), "rrf": 0.0,
                                     "ranks": {}, "matched_evidence": [], "evidence_keys": set(),
                                     "mirror_ids": set()}
            group = groups[group_key]
            group["mirror_ids"].add(target["id"])
            evidence_key = (signal, record["id"])
            if evidence_key not in group["evidence_keys"]:
                group["evidence_keys"].add(evidence_key)
                group["matched_evidence"].append({
                    "id": record["id"],
                    "signal": signal,
                    "kind": record.get("kind"),
                    "quality": record.get("quality"),
                    "language": record.get("language"),
                    "author": record.get("author"),
                    "edition": record.get("edition"),
                    "citation": record.get("citation"),
                    "source_url": record.get("source_url"),
                    "parent_id": parent_id,
                    "match_reason": hit.get("match_reason") or (
                        "Ranked word match" if signal == "lexical" else
                        "Ranked source-backed form match" if signal == "forms" else
                        "Dense embedding similarity"),
                    "raw_score": hit.get("score"),
                })
            # Multiple matches to one Greek passage or mirrored edition in a
            # single list provide one RRF vote. Their evidence is still shown.
            if group_key not in seen_this_signal:
                rank += 1
                seen_this_signal.add(group_key)
                group["ranks"][signal] = rank
                group["rrf"] += 1.0 / (K + rank)

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
        signals = [name for name in SIGNALS if name in group["ranks"]]
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
