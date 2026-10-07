"""One-hop, source-linked dictionary meaning candidates, never new parses.

An Ancient_Greek page link does not identify an etymology, POS section, or
sense. Every exact target entry retains its own identity; no target morphology
is inherited and no second crossreference is followed. This module is isolated
from the production word API and contextual rankers pending independent audit.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .candidate_senses import _accepted, _binding
from .lexical_variants import (
    ENTRY_ID, _entry_senses, _nfc, _proof_equals,
    literal_sense_crossreferences, lookup_variants,
)

VERSION = "source-linked-dictionary-crossreferences-v1"


def _entry_proof(entry_id, claims, records):
    head = claims.get(entry_id + ":lemma:entry")
    morph = claims.get(entry_id + ":morphology:entry")
    if not head or not morph:
        return None
    binding = _binding(head)
    word = (head.get("object") or {}).get("lemma")
    pos = (head.get("object") or {}).get("pos")
    record = records.get(entry_id) or {}
    raw = record.get("entry") or {}
    if (not binding or binding[0] != entry_id
            or not all(_accepted(c) and _binding(c) == binding for c in (head, morph))
            or head.get("predicate") != "lemma" or morph.get("predicate") != "morphology"
            or not isinstance(word, str) or not word
            or not isinstance(pos, str) or not pos
            or head["subject"].get("form") != word
            or morph["subject"].get("form") != word
            or morph["object"].get("lemma") != word or morph["object"].get("pos") != pos
            or not _proof_equals(head, word, "/entry/word")
            or not isinstance(morph["object"].get("forms"), list)
            or record.get("id") != entry_id
            or sha256(json.dumps(record, ensure_ascii=False).encode("utf-8")).hexdigest() != binding[3]
            or record.get("raw_sha256") != binding[1] or record.get("raw_line_sha256") != binding[2]
            or record.get("source_url") != binding[4]
            or raw.get("word") != word or raw.get("pos") != pos
            or raw.get("forms", []) != morph["object"]["forms"]
            or raw.get("head_templates", []) != head["object"].get("head_templates", [])):
        return None
    return head, morph


def _form_page(head, claims):
    if any(str(row.get("name", "")).casefold().endswith(" form")
           for row in head["object"].get("head_templates", []) if isinstance(row, dict)):
        return True
    binding = _binding(head)
    for claim in claims:
        if not _accepted(claim) or _binding(claim) != binding:
            continue
        obj = claim.get("object") or {}
        if claim.get("predicate") == "lemma" and obj.get("relation") == "form_of":
            return True
        sense = obj.get("source_sense") or {}
        if claim.get("predicate") == "sense_gloss" and (
                sense.get("form_of") or "form-of" in sense.get("tags", [])):
            return True
    return False


def project_crossreference_meanings(form, claims, source_records):
    """Reconstruct every edge and target from complete accepted source claims.

    Callers must supply all retrieved target-entry claims. The adapter below
    supplies them without a result limit. Empty target senses are disclosed as
    unresolved/terminal rather than promoted into invented English definitions.
    """
    if not isinstance(form, str) or not form:
        return {"candidates": [], "relations": [], "supporting_claims": [], "method": VERSION}
    counts = Counter(c.get("id") for c in claims)
    unique = {c["id"]: c for c in claims if counts[c.get("id")] == 1 and _accepted(c) and _binding(c)}
    record_counts = Counter(r.get("id") for r in source_records)
    records = {r["id"]: r for r in source_records if record_counts[r.get("id")] == 1}
    # The accepted claim's gloss quote alone does not quote its links. Check
    # every complete sense object against its hash-bound archived parent.
    for identifier, claim in list(unique.items()):
        if claim.get("predicate") != "sense_gloss":
            continue
        number = (claim.get("metadata") or {}).get("sense_index")
        raw_senses = (records.get(_binding(claim)[0], {}).get("entry") or {}).get("senses", [])
        if (type(number) is not int or number < 0 or number >= len(raw_senses)
                or raw_senses[number] != (claim.get("object") or {}).get("source_sense")):
            del unique[identifier]
    entries = {}
    for c in unique.values():
        entry_id = _binding(c)[0]
        if entry_id not in entries:
            entries[entry_id] = _entry_proof(entry_id, unique, records)
    candidates, relations, wanted = [], [], set()
    for claim in unique.values():
        source_id = _binding(claim)[0]
        proof = entries.get(source_id)
        if not proof:
            continue
        source_head, source_morph = proof
        if _binding(claim) != _binding(source_head):
            continue
        anchors = [{"claim_id": source_morph["id"], "entry_id": source_id,
                    "form_index": ordinal, "source_form": deepcopy(row),
                    "source_locator": f"/entry/forms/{ordinal}"}
                   for ordinal, row in enumerate(source_morph["object"]["forms"])
                   if isinstance(row, dict) and _nfc(row.get("form")) == _nfc(form)]
        if not anchors:
            continue
        for edge in literal_sense_crossreferences(claim):
            target_proofs = [pair for pair in entries.values() if pair
                             and _nfc(pair[0]["object"]["lemma"]) == _nfc(edge["target_headword"])]
            target_proofs.sort(key=lambda pair: pair[0]["id"])
            target_ids = [_binding(pair[0])[0] for pair in target_proofs]
            relation_id = f"{claim['id']}:linked-target:{edge['target_link']}"
            relation = {**deepcopy(edge), "id": relation_id,
                        "query_anchors": anchors, "source_headword_claim_id": source_head["id"],
                        "target_entry_ids": target_ids,
                        "target_identity_status": "ambiguous_page_target" if len(target_ids) > 1 else
                                                  "unique_retrieved_entry" if target_ids else "target_not_available",
                        "target_results": [], "method": VERSION}
            wanted.update((source_head["id"], source_morph["id"], claim["id"]))
            for head, morph in target_proofs:
                target_id = _binding(head)[0]
                wanted.update((head["id"], morph["id"]))
                terminal = _form_page(head, list(unique.values()))
                senses = [] if terminal else [s for s in _entry_senses(head, list(unique.values()))
                    if not (unique[s["claim_id"]]["object"]["source_sense"].get("form_of")
                            or unique[s["claim_id"]]["object"]["source_sense"].get("alt_of")
                            or set(unique[s["claim_id"]]["object"]["source_sense"].get("tags", []))
                            & {"form-of", "alt-of"})]
                state = "terminal_form_page" if terminal else "candidate_senses_available" if senses else "no_safe_english_senses"
                relation["target_results"].append({"entry_id": target_id, "status": state,
                                                   "sense_claim_ids": [s["claim_id"] for s in senses]})
                if terminal:
                    wanted.update(c["id"] for c in unique.values() if _binding(c) == _binding(head)
                                  and c.get("predicate") in {"sense_gloss", "lemma"})
                for sense in senses:
                    wanted.add(sense["claim_id"])
                    candidates.append({
                        "id": f"{relation_id}:sense:{sense['claim_id']}",
                        "candidate_kind": "dictionary_crossreference_meaning",
                        "matched_form": form, "source_entry_id": source_id,
                        "source_headword": source_head["object"]["lemma"],
                        "target_entry_id": target_id, "target_headword": head["object"]["lemma"],
                        "target_etymology_number": records[target_id]["entry"].get("etymology_number"),
                        "target_identity_status": relation["target_identity_status"],
                        "alternative_target_entry_ids": target_ids,
                        "source_dictionary_pos": source_head["object"]["pos"],
                        "target_dictionary_pos": head["object"]["pos"],
                        "literal_pos_agreement": source_head["object"]["pos"] == head["object"]["pos"],
                        "relation_id": relation_id, "relation_claim_id": claim["id"],
                        "query_anchors": deepcopy(anchors), "sense": deepcopy(sense),
                        "claim_ids": [source_head["id"], source_morph["id"], claim["id"],
                                      head["id"], morph["id"], sense["claim_id"]],
                        "analysis": None, "features": None, "contextually_selected": False,
                        "scope": "one_hop_dictionary_target_sense_candidate_not_occurrence_analysis",
                        "status": "source_linked_candidate", "method": VERSION,
                    })
            # Source relation remains real; only candidate retrieval is resolved.
            relation["resolution_status"] = "target_candidates_retrieved" if target_ids else "target_not_available"
            relations.append(relation)
    return {"form": form, "candidates": candidates, "relations": relations,
            "supporting_claims": [deepcopy(unique[i]) for i in sorted(wanted)],
            "supporting_source_records": [deepcopy(records[i]) for i in sorted(
                {_binding(unique[c])[0] for c in wanted})],
            "method": VERSION, "scope": "one_hop_candidate_retrieval_no_contextual_selection"}


def lookup_crossreference_meanings(form, evidence_index, source_index_path=None):
    """Local index adapter, no network, mutations, model calls or recursive walk."""
    source = lookup_variants(form, evidence_index)
    record_ids = {r["entry_id"] for r in source["dictionary_crossreferences"]}
    targets = {r["target_headword"] for r in source["dictionary_crossreferences"]}
    for target in sorted(targets):
        found = evidence_index.lookup(target, limit=None)
        for claim in found.get("claims", []):
            binding = _binding(claim)
            if (binding and _accepted(claim) and claim.get("predicate") == "lemma"
                    and claim.get("id") == binding[0] + ":lemma:entry"
                    and _nfc((claim.get("object") or {}).get("lemma")) == _nfc(target)):
                record_ids.add(binding[0])
    complete = []
    with closing(evidence_index._connect()) as con:
        for entry_id in sorted(record_ids):
            if ENTRY_ID.fullmatch(entry_id):
                complete.extend(evidence_index._claim(row, strength="general_source_record",
                    reason="One-hop explicit dictionary crossreference target; not occurrence attestation.")
                    for row in con.execute("SELECT * FROM claims WHERE id GLOB ? ORDER BY id", (entry_id + ":*",)))
    source_index_path = Path(source_index_path) if source_index_path else Path(__file__).resolve().parents[1] / "data/wiktionary.sqlite"
    records = []
    with closing(sqlite3.connect(f"file:{source_index_path.resolve().as_posix()}?mode=ro", uri=True)) as con:
        for entry_id in sorted(record_ids):
            row = con.execute("SELECT record_json FROM entries WHERE id=?", (entry_id,)).fetchone()
            if row:
                records.append(json.loads(row[0]))
    result = project_crossreference_meanings(form, complete, records)
    result["source_retrieval_scope"] = "existing exact-variant adapter; at most 20 source entries; all exact retrieved targets retained"
    return result
