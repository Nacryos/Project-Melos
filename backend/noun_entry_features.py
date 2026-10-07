"""Literal same-entry noun gender metadata, separate from occurrence parses.

Only English gender tags already present on a source noun's canonical form or
own senses are projected. No template argument interpretation, word-ending
rules, sense-target inheritance, or cross-entry/homograph merging occurs.
"""
from collections import Counter
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unicodedata

from .candidate_senses import _accepted, _binding
from .dictionary_crossrefs import _entry_proof, _form_page
from .lexical_variants import ENTRY_ID, _proof_equals

VERSION = "same-entry-noun-gender-v1"
GENDER_TAGS = frozenset({"masculine", "feminine", "neuter"})


def project_noun_inherent_features(entry_id, claims, source_records):
    """Return owned metadata and its completeness, never rewrite form tags."""
    result = {"entry_id": entry_id, "dictionary_gender_options": [],
              "unambiguous_entry_gender": None, "gender_status": "unavailable",
              "evidence_groups": [], "features": None, "method": VERSION,
              "scope": "same_source_noun_entry_metadata_not_occurrence_disambiguation",
              "supporting_claims": [], "supporting_source_records": []}
    if not isinstance(entry_id, str) or not ENTRY_ID.fullmatch(entry_id):
        return result
    counts = Counter(c.get("id") for c in claims)
    unique = {c["id"]: c for c in claims if counts[c.get("id")] == 1 and _accepted(c) and _binding(c)}
    counts = Counter(r.get("id") for r in source_records)
    records = {r["id"]: r for r in source_records if counts[r.get("id")] == 1}
    proof = _entry_proof(entry_id, unique, records)
    if not proof:
        return result
    head, morph = proof
    if head["object"]["pos"] != "noun":
        result["gender_status"] = "not_a_noun_entry"
        return result
    record = records[entry_id]
    raw = record["entry"]
    # The full source is hash-bound even when a caller omits form-of claims.
    # Such omissions must never turn an inflected-form page into a noun lemma.
    raw_form_page = (bool(raw.get("form_of")) or any(
        sense.get("form_of") or "form-of" in sense.get("tags", [])
        for sense in raw.get("senses", [])) or any(
        template.get("name") == "head" and str(template.get("args", {}).get("2", "")).endswith(" form")
        for template in raw.get("head_templates", [])))
    if raw_form_page or _form_page(head, list(unique.values())):
        result["gender_status"] = "form_page_not_lexical_noun"
        return result
    result.update(entry_headword=raw["word"], dictionary_pos=raw["pos"],
                  source_etymology_number=raw.get("etymology_number"))
    wanted = {head["id"], morph["id"]}
    groups = []
    canonical_count = 0
    for index, row in enumerate(raw.get("forms", [])):
        tags = row.get("tags", []) if isinstance(row, dict) else []
        genders = sorted(GENDER_TAGS.intersection(tags))
        if ("canonical" not in tags or not genders or any(t in tags for t in ("romanization", "transliteration"))
                or not any("GREEK" in unicodedata.name(c, "") for c in row.get("form", ""))):
            continue
        groups.append({"scope": "canonical_noun_form_metadata", "source_locator": f"/entry/forms/{index}/tags",
                       "source_form": row["form"], "literal_source_tags": deepcopy(tags),
                       "gender_options": genders, "claim_id": morph["id"]})
        canonical_count += 1
    sense_count = len(raw.get("senses", []))
    covered_senses = []
    missing_proofs = []
    for index, source_sense in enumerate(raw.get("senses", [])):
        genders = sorted(GENDER_TAGS.intersection(source_sense.get("tags", [])))
        if not genders:
            continue
        identifier = f"{entry_id}:sense:{index}"
        claim = unique.get(identifier)
        obj = (claim or {}).get("object") or {}
        if (not claim or _binding(claim) != _binding(head) or claim.get("predicate") != "sense_gloss"
                or obj.get("source_sense") != source_sense
                or obj.get("lemma") != raw["word"] or obj.get("pos") != "noun"
                or claim["subject"].get("form") != raw["word"]
                or claim["metadata"].get("source_sense_id") != source_sense.get("id")
                or claim["metadata"].get("sense_index") != index
                or not _proof_equals(claim, source_sense.get("glosses"), f"/entry/senses/{index}/glosses")):
            missing_proofs.append(identifier)
            continue
        groups.append({"scope": "owned_noun_sense_metadata", "source_locator": f"/entry/senses/{index}/tags",
                       "sense_index": index, "source_sense_id": source_sense.get("id"),
                       "literal_source_tags": deepcopy(source_sense.get("tags", [])),
                       "gender_options": genders, "claim_id": identifier})
        wanted.add(identifier)
        covered_senses.append(index)
    gender_options = sorted({gender for group in groups for gender in group["gender_options"]})
    # An entry-wide default cannot override explicit differently gendered
    # paradigm cells. These are conflict evidence, NOT new inherent genders.
    paradigm_conflicts = []
    for index, row in enumerate(raw.get("forms", [])):
        tags = row.get("tags", []) if isinstance(row, dict) else []
        genders = sorted(GENDER_TAGS.intersection(tags))
        if (gender_options and row.get("source") in {"declension", "inflection"}
                and "canonical" not in tags and set(genders) - set(gender_options)
                and any("GREEK" in unicodedata.name(c, "") for c in row.get("form", ""))):
            paradigm_conflicts.append({"source_locator": f"/entry/forms/{index}",
                                       "source_form": deepcopy(row), "claim_id": morph["id"],
                                       "scope": "literal_paradigm_gender_conflict_not_inherent_gender"})
    complete_scope = bool(canonical_count or sense_count and len(covered_senses) == sense_count)
    differing_sets = len({tuple(group["gender_options"]) for group in groups}) > 1
    if not gender_options:
        status = "missing_sense_proof" if missing_proofs else "no_explicit_gender_tags"
    elif missing_proofs:
        status = "incomplete_source_proofs"
    elif paradigm_conflicts:
        status = "explicit_paradigm_gender_conflict"
    elif differing_sets:
        status = "conflicting_or_differently_scoped_source_genders"
    elif len(gender_options) > 1:
        status = "multiple_source_genders"
    elif not complete_scope:
        status = "some_senses_only"
    else:
        status = "single_source_gender"
    result.update(dictionary_gender_options=gender_options, gender_status=status,
                  unambiguous_entry_gender=gender_options[0] if status == "single_source_gender" else None,
                  evidence_groups=groups, canonical_gender_group_count=canonical_count,
                  source_sense_count=sense_count, gender_covered_sense_indices=covered_senses,
                  missing_sense_proof_ids=missing_proofs,
                  paradigm_gender_conflicts=paradigm_conflicts,
                  application_note="Entry metadata only; never override explicit form gender or treat this as contextual gender selection.",
                  supporting_claims=[deepcopy(unique[i]) for i in sorted(wanted)],
                  supporting_source_records=[deepcopy(record)])
    return result


def lookup_noun_inherent_features(entry_id, evidence_index, source_index_path=None):
    """Lookup by source identity only; spelling and target lemmas cannot join."""
    if not isinstance(entry_id, str) or not ENTRY_ID.fullmatch(entry_id):
        return project_noun_inherent_features(entry_id, [], [])
    with closing(evidence_index._connect()) as con:
        claims = [evidence_index._claim(row, strength="general_source_record",
                    reason="Same-entry noun metadata; no occurrence sense or gender adjudication.")
                  for row in con.execute("SELECT * FROM claims WHERE id GLOB ? ORDER BY id", (entry_id + ":*",))]
    source_index_path = Path(source_index_path) if source_index_path else Path(__file__).resolve().parents[1] / "data/wiktionary.sqlite"
    with closing(sqlite3.connect(f"file:{source_index_path.resolve().as_posix()}?mode=ro", uri=True)) as source:
        raw = source.execute("SELECT record_json FROM entries WHERE id=?", (entry_id,)).fetchone()
    return project_noun_inherent_features(entry_id, claims, [json.loads(raw[0])] if raw else [])
