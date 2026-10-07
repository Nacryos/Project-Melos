"""Literal Wiktionary form-link spelling aliases; no diacritic stripping.

The displayed form, link label, destination and grammatical tags all remain
source data. A page destination permits candidate retrieval, not a claim that
every occurrence on that page has this analysis. No production integration.
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
from .evidence import _grammatical_label
from .lexical_variants import ENTRY_ID, _entry_senses, _nfc, _proof_equals

VERSION = "literal-source-form-link-alias-v1"


def _greek_link(link, display):
    if not isinstance(link, list) or len(link) != 2 or not all(isinstance(x, str) for x in link):
        return None
    label, href = link
    if _nfc(label) != _nfc(display) or not href.endswith("#Ancient_Greek"):
        return None
    target = href.removesuffix("#Ancient_Greek")
    if not target or not all((unicodedata.category(c).startswith("L") and "GREEK" in unicodedata.name(c, ""))
                             or unicodedata.category(c).startswith("M") for c in target):
        return None
    return target


def project_form_link_aliases(form, claims, source_records):
    """Exact destination matches only, validated against hash-bound parents."""
    counts = Counter(c.get("id") for c in claims)
    unique = {c["id"]: c for c in claims if counts[c.get("id")] == 1 and _accepted(c) and _binding(c)}
    counts = Counter(r.get("id") for r in source_records)
    records = {r["id"]: r for r in source_records if counts[r.get("id")] == 1}
    proofs = {i: _entry_proof(i, unique, records) for i in records}
    # Sense/link objects need full-parent validation, not only gloss quotes.
    for key, claim in list(unique.items()):
        if claim.get("predicate") != "sense_gloss":
            continue
        number = (claim.get("metadata") or {}).get("sense_index")
        senses = (records.get(_binding(claim)[0], {}).get("entry") or {}).get("senses", [])
        if (type(number) is not int or number < 0 or number >= len(senses)
                or senses[number] != (claim.get("object") or {}).get("source_sense")):
            del unique[key]
    aliases, relations, meanings, wanted = [], [], [], set()
    for entry_id, pair in sorted(proofs.items()):
        if not pair or _form_page(pair[0], list(unique.values())):
            continue
        head, morph = pair
        for ordinal, row in enumerate(morph["object"]["forms"]):
            grammar = _grammatical_label(row.get("tags"), wiktionary=True) if isinstance(row, dict) else None
            if not grammar or _nfc(row.get("form")) == _nfc(form):
                continue
            for link_index, link in enumerate(row.get("links", [])):
                target = _greek_link(link, row.get("form"))
                if target is None or _nfc(target) != _nfc(form):
                    continue
                alias = {"id": f"{morph['id']}#form:{ordinal}:link:{link_index}",
                         "candidate_kind": "source_listed_form_link_alias", "entry_id": entry_id,
                         "entry_headword": head["object"]["lemma"], "dictionary_pos": head["object"]["pos"],
                         "matched_link_target": target, "query_form": form, "printed_form": row["form"],
                         "matched_object_form": deepcopy(row), "form_index": ordinal,
                         "source_grammatical_tags": grammar, "features": None,
                         "source_locator": f"/entry/forms/{ordinal}/links/{link_index}",
                         "source_link": deepcopy(link), "claim_ids": [head["id"], morph["id"]],
                         "match_method": "exact NFC linked destination; printed quantity/accent marks retained",
                         "scope": "source_form_page_link_candidate_not_exact_printed_surface_or_occurrence_analysis",
                         "contextually_selected": False, "method": VERSION}
                aliases.append(alias)
                wanted.update(alias["claim_ids"])
    for alias in aliases:
        source_id = alias["entry_id"]
        head, morph = proofs[source_id]
        target_options = [(source_id, None)]
        for claim in unique.values():
            if claim.get("predicate") != "sense_gloss" or _binding(claim) != _binding(head):
                continue
            obj = claim["object"]
            sense = obj.get("source_sense") or {}
            index = claim["metadata"].get("sense_index")
            if (claim["id"] != f"{source_id}:sense:{index}"
                    or obj.get("lemma") != head["object"]["lemma"]
                    or obj.get("pos") != head["object"]["pos"]
                    or claim["subject"].get("form") != head["object"]["lemma"]
                    or claim["metadata"].get("source_sense_id") != sense.get("id")
                    or not _proof_equals(claim, sense.get("glosses"), f"/entry/senses/{index}/glosses")):
                continue
            # Only an explicit structured lexical alternative; no guessed
            # equivalence from differing spellings or free-form prose.
            for relation_index, alt in enumerate(sense.get("alt_of", [])):
                if not isinstance(alt, dict) or not isinstance(alt.get("word"), str):
                    continue
                for link_index, link in enumerate(sense.get("links", [])):
                    target = _greek_link(link, alt["word"])
                    if target is None:
                        continue
                    relation_id = f"{claim['id']}:alt:{relation_index}:link:{link_index}"
                    relation = {"id": relation_id, "source_entry_id": source_id,
                                "source_sense_claim_id": claim["id"], "target_headword": target,
                                "source_display": alt["word"], "source_link": deepcopy(link),
                                "source_alt_of": deepcopy(alt), "relation_text": deepcopy(sense.get("glosses", [])),
                                "link_locator": f"/entry/senses/{index}/links/{link_index}",
                                "relation_locator": f"/entry/senses/{index}/alt_of/{relation_index}",
                                "relation": "explicit_structured_alt_of_link", "method": VERSION}
                    if not any(r["id"] == relation_id for r in relations):
                        relations.append(relation)
                    wanted.add(claim["id"])
                    for target_id, proof in sorted(proofs.items()):
                        if proof and _nfc(proof[0]["object"]["lemma"]) == _nfc(target):
                            target_options.append((target_id, relation_id))
        for target_id, relation_id in dict.fromkeys(target_options):
            target_head, target_morph = proofs[target_id]
            if _form_page(target_head, list(unique.values())):
                continue
            senses = _entry_senses(target_head, list(unique.values()))
            for sense in senses:
                raw_sense = unique[sense["claim_id"]]["object"]["source_sense"]
                if raw_sense.get("form_of") or raw_sense.get("alt_of") or set(raw_sense.get("tags", [])) & {"form-of", "alt-of"}:
                    continue
                proof_ids = [*alias["claim_ids"], target_head["id"], target_morph["id"], sense["claim_id"]]
                if relation_id:
                    proof_ids.append(next(r["source_sense_claim_id"] for r in relations if r["id"] == relation_id))
                meanings.append({"id": f"{alias['id']}:via:{relation_id or 'same-entry'}:sense:{sense['claim_id']}",
                                 "alias_id": alias["id"], "source_entry_id": source_id,
                                 "target_entry_id": target_id, "target_headword": target_head["object"]["lemma"],
                                 "target_etymology_number": records[target_id]["entry"].get("etymology_number"),
                                 "relation_id": relation_id, "sense": deepcopy(sense),
                                 "claim_ids": list(dict.fromkeys(proof_ids)),
                                 "candidate_kind": "source_link_alias_meaning", "features": None,
                                 "contextually_selected": False, "method": VERSION})
                wanted.update(proof_ids)
    return {"form": form, "aliases": aliases, "relations": relations, "meaning_candidates": meanings,
            "supporting_claims": [deepcopy(unique[i]) for i in sorted(wanted)],
            "supporting_source_records": [deepcopy(records[i]) for i in sorted({_binding(unique[c])[0] for c in wanted})],
            "method": VERSION, "scope": "source_candidates_only_no_contextual_selection"}


def lookup_form_link_aliases(form, evidence_index, source_index_path=None):
    """Retrieve source records, then follow only one explicit alt_of page link."""
    found = evidence_index.lookup(form, limit=None)
    entry_ids = {_binding(c)[0] for c in found.get("claims", []) if _accepted(c) and _binding(c)}
    source_index_path = Path(source_index_path) if source_index_path else Path(__file__).resolve().parents[1] / "data/wiktionary.sqlite"
    with closing(sqlite3.connect(f"file:{source_index_path.resolve().as_posix()}?mode=ro", uri=True)) as source, closing(evidence_index._connect()) as con:
        def load(ids):
            claims, records = [], []
            for identifier in sorted(ids):
                if not ENTRY_ID.fullmatch(identifier):
                    continue
                claims.extend(evidence_index._claim(r, strength="general_source_record",
                    reason="Literal source form link, not an occurrence attestation.") for r in con.execute(
                        "SELECT * FROM claims WHERE id GLOB ? ORDER BY id", (identifier + ":*",)))
                raw = source.execute("SELECT record_json FROM entries WHERE id=?", (identifier,)).fetchone()
                if raw:
                    records.append(json.loads(raw[0]))
            return claims, records
        claims, records = load(entry_ids)
        first = project_form_link_aliases(form, claims, records)
        for target in {r["target_headword"] for r in first["relations"]}:
            for claim in evidence_index.lookup(target, limit=None).get("claims", []):
                binding = _binding(claim)
                if (binding and _accepted(claim) and claim.get("id") == binding[0] + ":lemma:entry"
                        and _nfc((claim.get("object") or {}).get("lemma")) == _nfc(target)):
                    entry_ids.add(binding[0])
        return project_form_link_aliases(form, *load(entry_ids))
