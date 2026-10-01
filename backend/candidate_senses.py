"""Literal dictionary senses joined by accepted source-entry identity, not spelling.

This is a read-only projection of existing accepted Kaikki claims. It never
decides which sense applies in a passage and never resolves a form-of target
to one of several same-spelling dictionary entries.
"""

from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any, Mapping, Sequence


_ENTRY = re.compile(r"wiktionary:kaikki:line:[0-9]+\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
SCOPE_NOTE = "Dictionary entry senses only; no contextual sense or passage attestation is asserted."


def _accepted(claim: Mapping[str, Any]) -> bool:
    return (isinstance(claim, Mapping) and claim.get("status") == "source_claim"
            and claim.get("assertion_type") == "extracted_annotation"
            and claim.get("method") == "accepted-kaikki-snapshot-scoped-claims-v1"
            and str(claim.get("source_family", "")).startswith("enwiktionary-kaikki-")
            and isinstance(claim.get("subject"), Mapping)
            and not claim["subject"].get("passage_id"))


def _binding(claim: Mapping[str, Any]) -> tuple | None:
    metadata = claim.get("metadata") or {}
    entry = metadata.get("source_record_id")
    raw_hash, line_hash = metadata.get("source_raw_sha256"), metadata.get("source_raw_line_sha256")
    if (not isinstance(entry, str) or not _ENTRY.fullmatch(entry)
            or not all(isinstance(value, str) and _HASH.fullmatch(value)
                       for value in (raw_hash, line_hash))
            or metadata.get("source_quality") != "machine_extracted_unreviewed"):
        return None
    evidence = claim.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping):
        return None
    proof = evidence[0]
    parent_hash, url = proof.get("parent_sha256"), proof.get("source_url")
    wrapper_hash = proof.get("raw_sha256")
    if (proof.get("record_id") != entry
            or not isinstance(parent_hash, str) or not _HASH.fullmatch(parent_hash)
            or not isinstance(wrapper_hash, str) or not _HASH.fullmatch(wrapper_hash)
            or not isinstance(url, str) or not url.startswith(("https://", "http://"))):
        return None
    return entry, raw_hash, line_hash, parent_hash, url, claim.get("source_family"), wrapper_hash


def candidate_entry_id(candidate: Mapping[str, Any], morphology: Mapping[str, Any]) -> str | None:
    """Require a directly owned morphology entry, never a target-name join."""
    if (not _accepted(morphology) or morphology.get("predicate") != "morphology"
            or candidate.get("candidate_kind") != "grammatical_analysis"
            or candidate.get("lemma_targets")
            or candidate.get("source_family") != morphology.get("source_family")):
        return None
    binding = _binding(morphology)
    if not binding:
        return None
    entry = binding[0]
    identifier = entry + ":morphology:entry"
    obj = morphology.get("object") or {}
    lemma = obj.get("lemma")
    candidate_id = str(candidate.get("id", ""))
    if (morphology.get("id") != identifier or candidate.get("claim_ids") != [identifier]
            or not candidate_id.startswith(identifier + "#form:")
            or not candidate_id.removeprefix(identifier + "#form:").isdecimal()
            or not isinstance(lemma, str) or not lemma
            or candidate.get("entry_headword") != lemma or candidate.get("lemma") != lemma
            or morphology["subject"].get("form") != lemma):
        return None
    ordinal = int(candidate_id.removeprefix(identifier + "#form:"))
    forms = obj.get("forms")
    if isinstance(forms, list):
        listed = forms[ordinal] if ordinal < len(forms) else None
    else:
        # Public lookup compacts full paradigms, retaining exact matched rows
        # and original ordinals. Do not reinterpret a compacted list index.
        rows = morphology.get("matched_object_forms") or []
        ordinals = morphology.get("matched_object_form_ordinals") or []
        matches = [row for number, row in zip(ordinals, rows) if number == ordinal]
        listed = matches[0] if len(rows) == len(ordinals) and len(matches) == 1 else None
    if not isinstance(listed, Mapping):
        return None
    # Reuse the existing deterministic Kaikki projection; no second grammar
    # interpretation is introduced by the sense-attachment layer.
    from .evidence import _grammatical_label
    if (candidate.get("matched_object_form") != listed
            or candidate.get("matched_form") != listed.get("form")
            or candidate.get("source_tags") != listed.get("tags")
            or candidate.get("analysis") != _grammatical_label(listed.get("tags"), wiktionary=True)
            or candidate.get("features") != listed.get("features")):
        return None
    return entry


def project_entry_senses(candidate: Mapping[str, Any], morphology: Mapping[str, Any],
                         senses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return all eligible source senses, with no contextual ranking or rewriting."""
    entry = candidate_entry_id(candidate, morphology)
    if not entry:
        return []
    binding = _binding(morphology)
    obj = morphology["object"]
    rows: list[dict[str, Any]] = []
    for sense in senses:
        if (not _accepted(sense) or sense.get("predicate") != "sense_gloss"
                or _binding(sense) != binding):
            continue
        metadata = sense.get("metadata") or {}
        index = metadata.get("sense_index")
        value = sense.get("object") or {}
        source_sense = value.get("source_sense") or {}
        proof = sense["evidence"][0]
        glosses = value.get("glosses")
        text_arrays = [value.get("raw_glosses", []), source_sense.get("tags", []),
                       source_sense.get("raw_tags", [])]
        if (not isinstance(index, int) or isinstance(index, bool) or index < 0
                or sense.get("id") != f"{entry}:sense:{index}"
                or proof.get("locator") != f"/entry/senses/{index}/glosses"
                or sense["subject"].get("form") != obj.get("lemma")
                or value.get("lemma") != obj.get("lemma") or value.get("pos") != obj.get("pos")
                or source_sense.get("form_of") or source_sense.get("alt_of")
                or any(tag in (source_sense.get("tags") or []) for tag in ("form-of", "alt-of"))
                or any(not isinstance(values, list) or not all(isinstance(v, str) for v in values)
                       for values in text_arrays)
                or not isinstance(glosses, list) or not glosses
                or not all(isinstance(gloss, str) and gloss for gloss in glosses)):
            continue
        if (any(key in source_sense and source_sense[key] != value.get(key, [])
                for key in ("glosses", "raw_glosses"))
                or metadata.get("source_sense_id") != source_sense.get("id")):
            continue
        try:
            if json.loads(proof.get("quote", "")) != glosses:
                continue
        except (ValueError, TypeError):
            continue
        rows.append({
            "claim_id": sense["id"], "entry_id": entry, "sense_index": index,
            "source_sense_id": metadata.get("source_sense_id"),
            "glosses": list(glosses), "raw_glosses": list(value.get("raw_glosses") or []),
            "tags": list(source_sense.get("tags") or []),
            "raw_tags": list(source_sense.get("raw_tags") or []),
            "source_url": proof["source_url"], "locator": proof["locator"],
            "quote": proof["quote"], "scope": "general_dictionary_entry",
            "scope_note": SCOPE_NOTE, "source_quality": metadata["source_quality"],
            "license": metadata.get("license"),
        })
    counts = Counter(row["sense_index"] for row in rows)
    # An ambiguous duplicated ordinal cannot identify one source sense.
    return sorted((row for row in rows if counts[row["sense_index"]] == 1),
                  key=lambda row: row["sense_index"])
