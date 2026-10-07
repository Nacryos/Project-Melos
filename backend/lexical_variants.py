"""Exact source-listed dialect alternatives, without invented morphology.

This isolated projection consumes the accepted claim index. A lexical variant
can carry a dictionary meaning without claiming a case, number, tense, or an
attestation in the user's passage. NFC is the only spelling equivalence.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from copy import deepcopy
import json
import re
import unicodedata

from .candidate_senses import _accepted, _binding

VERSION = "exact-dictionary-variants-v2"
ENTRY_ID = re.compile(r"wiktionary:kaikki:line:\d+\Z")


def _nfc(text):
    return unicodedata.normalize("NFC", text) if isinstance(text, str) else None


def _proof_equals(claim, value, locator):
    try:
        evidence = claim["evidence"][0]
        return evidence["locator"] == locator and json.loads(evidence["quote"]) == value
    except (KeyError, IndexError, ValueError, TypeError):
        return False


def _entry_senses(anchor, claims):
    binding = _binding(anchor)
    if not binding:
        return []
    entry_id = binding[0]
    lemma = anchor["object"]["lemma"]
    rows = []
    for claim in claims:
        if not _accepted(claim) or claim.get("predicate") != "sense_gloss" or _binding(claim) != binding:
            continue
        value = claim.get("object") or {}
        metadata = claim.get("metadata") or {}
        number = metadata.get("sense_index")
        source_sense = value.get("source_sense") or {}
        glosses = value.get("glosses")
        if (type(number) is not int or number < 0
                or claim.get("id") != f"{entry_id}:sense:{number}"
                or claim["subject"].get("form") != lemma or value.get("lemma") != lemma
                or value.get("pos") != anchor["object"].get("pos")
                or not isinstance(glosses, list) or not glosses
                or not all(isinstance(gloss, str) and gloss for gloss in glosses)
                # Kaikki can fold Greek examples/romanization into glosses.
                # Keep those in raw claims, never in an English short preview.
                or any("\n" in gloss or "\r" in gloss or any(
                    unicodedata.category(char).startswith("L") and "GREEK" in unicodedata.name(char, "")
                    for char in gloss) for gloss in glosses)
                or source_sense.get("glosses") != glosses
                or metadata.get("source_sense_id") != source_sense.get("id")
                or not _proof_equals(claim, glosses, f"/entry/senses/{number}/glosses")):
            continue
        rows.append({"claim_id": claim["id"], "entry_id": entry_id,
                     "sense_index": number, "glosses": deepcopy(glosses),
                     "source_sense_id": source_sense.get("id"),
                     "tags": deepcopy(source_sense.get("tags", [])),
                     "scope": "general_dictionary_entry_not_contextually_adjudicated",
                     "source_url": claim["evidence"][0]["source_url"],
                     "locator": claim["evidence"][0]["locator"],
                     "quote": claim["evidence"][0]["quote"],
                     "source_quality": metadata["source_quality"],
                     "license": metadata.get("license")})
    counts = Counter(row["sense_index"] for row in rows)
    return sorted((row for row in rows if counts[row["sense_index"]] == 1), key=lambda row: row["sense_index"])


def literal_sense_crossreferences(claim):
    """Expose explicit linked '... form of X' wording, never choose its sense.

    The destination comes from the archived link, not a generated lemma. This
    is an unresolved crossreference, not permission to inherit every meaning
    or grammatical property of the target dictionary entry.
    """
    if not _accepted(claim) or claim.get("predicate") != "sense_gloss" or not _binding(claim):
        return []
    obj = claim.get("object") or {}
    source = obj.get("source_sense") or {}
    metadata = claim.get("metadata") or {}
    index = metadata.get("sense_index")
    glosses = obj.get("glosses")
    if (type(index) is not int or index < 0 or not isinstance(glosses, list)
            or claim.get("id") != f"{_binding(claim)[0]}:sense:{index}"
            or claim["subject"].get("form") != obj.get("lemma")
            or metadata.get("source_sense_id") != source.get("id")
            or source.get("glosses") != glosses
            or not _proof_equals(claim, glosses, f"/entry/senses/{index}/glosses")):
        return []
    links = source.get("links") or []
    output = []
    for link in links:
        if not isinstance(link, list) or len(link) != 2 or not all(isinstance(v, str) for v in link):
            continue
        display, target = link
        if not target.endswith("#Ancient_Greek"):
            continue
        headword = target.removesuffix("#Ancient_Greek")
        if not headword or _nfc(display) != _nfc(headword):
            continue
        if not all((unicodedata.category(c).startswith("L") and "GREEK" in unicodedata.name(c, ""))
                   or unicodedata.category(c).startswith("M") for c in headword):
            continue
        pattern = re.compile(r"(?P<label>[A-Za-z][A-Za-z -]*) form of " + re.escape(display) + r"(?: \([^()]*\))?[.]?\Z")
        for gloss in glosses:
            match = pattern.fullmatch(gloss) if isinstance(gloss, str) else None
            if not match:
                continue
            output.append({"claim_id": claim["id"], "entry_id": _binding(claim)[0],
                           "target_headword": headword, "target_link": target,
                           "relation_text": gloss, "source_label": match.group("label"),
                           "relation": "explicit_linked_form_of_wording",
                           "resolution_status": "unresolved_dictionary_crossreference",
                           "source_url": claim["evidence"][0]["source_url"],
                           "source_locator": f"/entry/senses/{index}",
                           "scope": "dictionary_entry_relation_not_occurrence_parse",
                           "method": VERSION})
    return output


def project_variants(form, claims, limit=20):
    """Project only exact forms with mutually bound source record proofs."""
    if not isinstance(form, str) or not form:
        return []
    identities = Counter(claim.get("id") for claim in claims)
    unique = {claim["id"]: claim for claim in claims if identities[claim.get("id")] == 1}
    variants = []
    for claim in unique.values():
        if not _accepted(claim) or claim.get("predicate") != "dialect_label":
            continue
        binding = _binding(claim)
        obj = claim.get("object") or {}
        row = obj.get("source_form")
        ordinal = obj.get("form_index")
        if (not binding or not isinstance(row, dict) or type(ordinal) is not int or ordinal < 0
                or _nfc(row.get("form")) != _nfc(form)
                or _nfc(claim["subject"].get("form")) != _nfc(form)
                or not isinstance(row.get("tags"), list) or "alternative" not in row["tags"]
                or not all(isinstance(tag, str) for tag in row["tags"])
                or any(tag in row["tags"] for tag in ("romanization", "transliteration"))
                or not _proof_equals(claim, row, f"/entry/forms/{ordinal}")):
            continue
        entry_id = binding[0]
        if claim.get("id") != f"{entry_id}:dialect_form:{ordinal}":
            continue
        head = unique.get(entry_id + ":lemma:entry")
        morphology = unique.get(entry_id + ":morphology:entry")
        lemma = obj.get("lemma")
        if (not isinstance(lemma, str) or not lemma or not head or not morphology
                or not all(_accepted(item) and _binding(item) == binding for item in (head, morphology))
                or head.get("predicate") != "lemma" or morphology.get("predicate") != "morphology"
                or head["object"].get("lemma") != lemma or morphology["object"].get("lemma") != lemma
                or head["subject"].get("form") != lemma
                or not _proof_equals(head, lemma, "/entry/word")):
            continue
        forms = morphology["object"].get("forms")
        if not isinstance(forms, list) or ordinal >= len(forms) or forms[ordinal] != row:
            continue
        # Do not turn an inflected-form page's title into a lexical lemma.
        if any(str(t.get("name", "")).casefold().endswith(" form")
               for t in head["object"].get("head_templates", []) if isinstance(t, dict)):
            continue
        if any(_binding(sibling) == binding and sibling.get("predicate") == "lemma"
               and (sibling.get("object") or {}).get("relation") == "form_of" for sibling in unique.values()):
            continue
        senses = _entry_senses(head, list(unique.values()))
        variants.append({"id": claim["id"] + ":lexical-variant", "candidate_kind": "dictionary_variant",
                         "matched_form": row["form"], "entry_headword": lemma,
                         "lemma": lemma, "analysis": None, "features": None,
                         "source_tags": deepcopy(row["tags"]),
                         "claim_ids": [claim["id"], head["id"], morphology["id"]],
                         "entry_id": entry_id, "entry_senses": senses,
                         "entry_sense_claim_ids": [sense["claim_id"] for sense in senses],
                         "matched_object_form": deepcopy(row),
                         "source_family": claim["source_family"],
                         "scope": "exact_source_listed_lexical_variant_not_morphological_parse",
                         "status": "source_claim", "assertion_type": "extracted_annotation",
                         "match_method": "NFC only; accents, case, iota subscript and all letters preserved",
                         "method": VERSION})
        # This is the entry's literal part-of-speech label, not an occurrence
        # parse. A consumer may use the two independently projected source
        # fields to veto a contradictory model POS, but not infer case/number.
        dictionary_pos = head["object"].get("pos")
        if (isinstance(dictionary_pos, str) and dictionary_pos.strip()
                and dictionary_pos == morphology["object"].get("pos")):
            variants[-1]["dictionary_pos"] = dictionary_pos
            variants[-1]["dictionary_pos_claim_ids"] = [head["id"], morphology["id"]]
            variants[-1]["dictionary_pos_scope"] = "literal_entry_pos_not_complete_occurrence_morphology"
        if len(variants) >= max(1, min(int(limit), 20)):
            break
    return variants


def lookup_variants(form, evidence_index, limit=20):
    """Bounded read-only adapter; root may integrate its distinct output later."""
    found = evidence_index.lookup(form, limit=None)
    record_ids = set()
    for claim in found.get("claims", []):
        if not _accepted(claim) or not _binding(claim):
            continue
        forms = claim.get("matched_object_forms") or []
        source_form = (claim.get("object") or {}).get("source_form")
        if isinstance(source_form, dict):
            forms = [*forms, source_form]
        if any(isinstance(row, dict) and _nfc(row.get("form")) == _nfc(form) for row in forms):
            record_ids.add(_binding(claim)[0])
    all_claims = []
    with closing(evidence_index._connect()) as connection:
        for entry_id in sorted(record_ids)[:20]:
            if not ENTRY_ID.fullmatch(entry_id):
                continue
            all_claims.extend(evidence_index._claim(row, strength="general_source_record",
                reason="Complete source-entry proof for exact listed lexical variant; not passage attestation.")
                for row in connection.execute("SELECT * FROM claims WHERE id GLOB ? ORDER BY id", (entry_id + ":*",)))
    variants = project_variants(form, all_claims, limit)
    anchors = {}
    for claim in all_claims:
        binding = _binding(claim)
        if (not binding or not _accepted(claim) or claim.get("predicate") != "morphology"
                or claim.get("id") != binding[0] + ":morphology:entry"):
            continue
        for ordinal, source_form in enumerate((claim.get("object") or {}).get("forms") or []):
            if isinstance(source_form, dict) and _nfc(source_form.get("form")) == _nfc(form):
                anchors.setdefault(binding[0], []).append({
                    "claim_id": claim["id"], "entry_id": binding[0],
                    "source_form": deepcopy(source_form), "form_index": ordinal,
                    "source_locator": f"/entry/forms/{ordinal}",
                    "match_method": "NFC only; exact source-listed form, not contextual adjudication"})
    crossreferences = [{**row, "query_anchors": deepcopy(anchors[row["entry_id"]])}
                       for claim in all_claims for row in literal_sense_crossreferences(claim)
                       if anchors.get(row["entry_id"])]
    wanted = {identifier for variant in variants for identifier in [*variant["claim_ids"], *variant["entry_sense_claim_ids"]]}
    wanted.update(row["claim_id"] for row in crossreferences)
    wanted.update(anchor["claim_id"] for row in crossreferences for anchor in row["query_anchors"])
    return {"form": form, "lexical_variants": variants,
            "dictionary_crossreferences": crossreferences,
            "supporting_claims": [claim for claim in all_claims if claim.get("id") in wanted],
            "method": VERSION,
            "scope": "dictionary_evidence_only_no_resolved_occurrence_analysis"}
