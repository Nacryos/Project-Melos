"""Evidence-bound contextual proposals; never a source of corpus facts.

The classifier accepts already retrieved candidates and independently accepted
claims.  Its optional Jev provider makes a real TypeSafe System One request.
No model is invoked when the passage, candidate provenance, or credentials are
missing.  The model can select an existing candidate ID or abstain, and cannot
create a lemma, Greek text, source claim, or dialect label.
"""

from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .textutils import normalize, search_text, tokenize


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = 'jev-1.13.0'
MAX_CANDIDATES = 32
MAX_CLAIMS = 32
MAX_STATE_CHARS = 32000
_ENTRY_METADATA_TAGS = frozenset({
    'canonical', 'alternative', 'romanization', 'transliteration', 'form-of', 'alt-of',
})
_PARSE_CANDIDATE_KINDS = frozenset({'grammatical_analysis', 'explicit_form_of'})
MACHINE_PACKET_SCHEMA = 'melos-machine-inflection-comparison-v1'


def _state_json(value: Any) -> str:
    """The exact JSON encoding used on the wire (no insignificant whitespace)."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


class DecisionProvider(Protocol):
    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _source_claim(row: Any) -> bool:
    return (isinstance(row, Mapping) and row.get("status") == "source_claim"
            and row.get("assertion_type") != "model_inference"
            and bool(row.get("id")) and isinstance(row.get("evidence"), list)
            and any(isinstance(e, Mapping) and e.get("source_url") and e.get("quote")
                    for e in row["evidence"]))


def _claim_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only source-bearing fields, preserving alternatives in object."""
    return {"id": str(row["id"]), "subject": row.get("subject"),
            "predicate": row.get("predicate"), "object": row.get("object"),
            "source_family": row.get("source_family"),
            "strength": row.get("strength"),
            "evidence": [{k: e.get(k) for k in
                          ("record_id", "source_url", "quote", "locator") if e.get(k) is not None}
                         for e in row["evidence"] if isinstance(e, Mapping)],
            "status": "source_claim"}


def _compact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Factor repeated candidate provenance, without discarding evidence.

    Null optional candidate fields convey no supplied analysis. Everything
    nested inside an analysis or quoted claim is retained verbatim, including
    explicit nulls/empty values. Source-reference IDs remain candidate-specific;
    only their repeated URL/scope payload is shared in a lookup catalogue.
    """
    options = [{key: value for key, value in candidate.items() if value is not None}
               for candidate in packet['candidates']]
    compact = {**packet, 'candidates': options}
    # Several grammatical alternatives can belong to the same dictionary
    # entry. Share literal sense payloads by exact claim ID, never by lemma.
    # Candidate-specific IDs still state precisely which senses it owns.
    sense_catalog = {sense['claim_id']: sense for candidate in options
                     for sense in candidate.get('entry_senses') or []}
    if sense_catalog:
        factored_senses = {**compact, 'candidates': [
            {key: value for key, value in candidate.items() if key != 'entry_senses'}
            for candidate in options], 'entry_sense_catalog': sense_catalog,
            'entry_sense_reference_format':
                'Each candidate entry_sense_claim_ids resolves to literal general dictionary-entry '
                'senses in entry_sense_catalog. Sharing a sense claim does not merge candidate IDs, '
                'homographs, grammatical alternatives, or establish a contextual sense.'}
        if len(_state_json(factored_senses)) < len(_state_json(compact)):
            compact = factored_senses
            options = compact['candidates']
    catalog: dict[str, dict[str, Any]] = {}
    index: dict[str, str] = {}
    factored = []
    for candidate in options:
        refs = []
        for ref in candidate['source_references']:
            payload = {key: value for key, value in ref.items() if key != 'id'}
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if signature not in index:
                source_id = f's{len(catalog) + 1}'
                index[signature] = source_id
                catalog[source_id] = payload
            refs.append({'id': ref['id'], 'source_ref': index[signature]})
        factored.append({**candidate, 'source_references': refs})
    if not catalog:
        return compact
    shared = {**compact, 'candidates': factored, 'source_catalog': catalog,
              'source_reference_format':
              'Each candidate source_references item preserves its evidence id; '
              'source_ref resolves to the complete URL and scope in source_catalog. '
              'Sharing a URL does not merge claims, candidate IDs, or interpretations.'}
    # Small packets need not pay for the lookup-table explanation.
    size = lambda value: len(_state_json(value))
    return shared if size(shared) < size(compact) else compact


def _nearby_spelling(candidate: Mapping[str, Any]) -> bool:
    distance = candidate.get('edit_distance')
    return isinstance(distance, (int, float)) and distance > 0


def _lexical_metadata_candidate(row: Mapping[str, Any]) -> bool:
    """Reject typed metadata and old Kaikki projections without gating legacy parses.

    Untyped morphology/treebank candidates from the existing lexicon index
    remain eligible. The structural checks cover pre-fix evidence candidates
    that may still arrive from a stale client or direct API caller.
    """
    kind = row.get('candidate_kind')
    if kind is not None and kind not in _PARSE_CANDIDATE_KINDS:
        return True
    if not str(row.get('source_family') or '').startswith('enwiktionary-kaikki-'):
        return False
    if any(str(identifier).endswith(':lemma:entry') for identifier in row.get('claim_ids') or ()):
        return True
    listed = row.get('matched_object_form')
    tags = listed.get('tags') if isinstance(listed, Mapping) else None
    if isinstance(tags, list) and tags and all(
        isinstance(tag, str) and tag.casefold() in _ENTRY_METADATA_TAGS for tag in tags
    ) and not row.get('features') and row.get('relation_raw') != 'form_of':
        return True
    analysis = row.get('analysis')
    if isinstance(analysis, str) and analysis.casefold() in _ENTRY_METADATA_TAGS:
        return True
    if isinstance(analysis, list) and any(
        isinstance(tag, str) and tag.casefold() in _ENTRY_METADATA_TAGS for tag in analysis
    ):
        return True
    return False


def _machine_candidate(row: Any) -> bool:
    return isinstance(row, Mapping) and (
        row.get('candidate_kind') == 'machine_analysis' or
        row.get('basis') == 'machine_analysis' or row.get('candidate_basis') == 'machine')


def _validated_machine_inventory(form, candidates, validation):
    """Reload raw operational evidence; no caller-supplied flag establishes trust."""
    if validation is None and not any(_machine_candidate(row) for row in candidates):
        return None, None
    if not candidates or not all(_machine_candidate(row) for row in candidates):
        return None, 'Machine comparison requires one complete, unmixed receipt inventory.'
    receipt = validation.get('receipt') if isinstance(validation, Mapping) else None
    receipt_id = receipt.get('id') if isinstance(receipt, Mapping) else None
    if not isinstance(receipt_id, str) or not receipt_id:
        return None, 'Machine candidates have no validated raw-analysis receipt.'
    from .machine_morphology import validate_receipt_projection
    try:
        trusted = validate_receipt_projection(receipt_id, list(candidates), form)
    except (ValueError, TypeError, RuntimeError, OSError):
        trusted = None
    if not trusted:
        return None, 'Machine receipt or complete raw candidate projection could not be verified.'
    return trusted, None


def _exact_source_form(value: Any) -> str | None:
    """Canonical Unicode only; never fold accent, quantity, case, or homographs."""
    return unicodedata.normalize('NFC', value) if isinstance(value, str) and value else None


def _source_record_id(claim: Mapping[str, Any]) -> str | None:
    records = {e.get('record_id') for e in claim.get('evidence') or ()
               if isinstance(e, Mapping) and isinstance(e.get('record_id'), str)}
    return next(iter(records)) if len(records) == 1 else None


def _grammatical_tags(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not value or not all(
        isinstance(tag, str) and tag and tag == tag.strip() for tag in value
    ):
        return None
    tags = tuple(sorted(value))
    return tags if len(tags) == len(set(tags)) else None


def _complete_morphology_claim(preview: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Read the accepted full claim only when a compact preview omits forms."""
    obj = preview.get('object')
    if isinstance(obj, Mapping) and isinstance(obj.get('forms'), list):
        return preview
    if not isinstance(obj, Mapping):
        return None
    try:
        from .evidence import EvidenceIndex
        full = EvidenceIndex().get_claim(str(preview['id']))
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error, KeyError):
        return None
    if not _source_claim(full) or not isinstance(full.get('object'), Mapping):
        return None
    forms = full['object'].get('forms')
    compact = {key: value for key, value in full['object'].items() if key != 'forms'}
    if not isinstance(forms, list):
        return None
    compact['listed_form_count'] = len(forms)
    if (compact != obj or any(full.get(key) != preview.get(key) for key in
        ('id', 'subject', 'predicate', 'source_family', 'evidence'))):
        return None
    return full


def _source_bridged_pair(
    form: str, relation: Mapping[str, Any], listed: Mapping[str, Any],
    proofs: Mapping[str, Mapping[str, Any]],
) -> bool:
    """One Kaikki reading only when accepted source rows explicitly join it.

    A diacritic-folded lookup match is never enough. The form-of target must
    exactly match the canonical form in the listed entry, whose exact listed
    row must link to the queried form. The inflected entry supplies matching
    part of speech. All of this is general lexicon scope, not passage proof.
    """
    family = relation.get('source_family')
    if (relation.get('candidate_kind') != 'explicit_form_of' or
        listed.get('candidate_kind') != 'grammatical_analysis' or
        not isinstance(family, str) or not family.startswith('enwiktionary-kaikki-') or
        family != listed.get('source_family') or
        relation.get('relation_raw') != 'form_of' or
        any(_nearby_spelling(row) or row.get('features') or row.get('analysis_text') or
            row.get('dialect') or row.get('gloss') for row in (relation, listed))):
        return False
    relation_ids, listed_ids = relation.get('claim_ids'), listed.get('claim_ids')
    if (not isinstance(relation_ids, list) or len(relation_ids) != 1 or
        relation.get('id') != relation_ids[0] or
        not isinstance(listed_ids, list) or len(listed_ids) != 1):
        return False
    form_of, morphology = proofs.get(relation_ids[0]), proofs.get(listed_ids[0])
    if not form_of or not morphology or any(
        claim.get('source_family') != family or
        not isinstance(claim.get('subject'), Mapping) or
        claim['subject'].get('type') != 'form' or claim['subject'].get('passage_id')
        for claim in (form_of, morphology)
    ):
        return False
    if (_source_record_id(form_of) not in (relation.get('evidence_refs') or ()) or
        _source_record_id(morphology) not in (listed.get('evidence_refs') or ())):
        return False
    relation_object, morphology_object = form_of.get('object'), morphology.get('object')
    if (form_of.get('predicate') != 'lemma' or morphology.get('predicate') != 'morphology' or
        not isinstance(relation_object, Mapping) or not isinstance(morphology_object, Mapping) or
        relation_object.get('relation') != 'form_of' or
        _exact_source_form(form_of['subject'].get('form')) != _exact_source_form(form) or
        _exact_source_form(relation.get('matched_form')) != _exact_source_form(form) or
        _exact_source_form(morphology['subject'].get('form')) !=
            _exact_source_form(listed.get('lemma')) or
        _exact_source_form(morphology_object.get('lemma')) !=
            _exact_source_form(listed.get('lemma')) or
        _exact_source_form(listed.get('entry_headword')) !=
            _exact_source_form(listed.get('lemma'))):
        return False
    targets = relation_object.get('targets')
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], Mapping):
        return False
    if (set(targets[0]) - {'word', 'extra'} or relation_object.get('source_raw_tags') or
        relation.get('source_raw_tags') or listed.get('source_raw_tags')):
        return False
    target = _exact_source_form(targets[0].get('word'))
    if not target or target != _exact_source_form(relation.get('lemma')):
        return False
    if relation.get('lemma_targets') is not None and relation['lemma_targets'] != targets:
        return False
    extra = targets[0].get('extra')
    if extra is not None:
        full_morphology = _complete_morphology_claim(morphology)
        forms_full = (full_morphology or {}).get('object', {}).get('forms')
        if (not isinstance(extra, str) or not extra or not isinstance(forms_full, list) or
            len([row for row in forms_full if isinstance(row, Mapping) and
                 row.get('form') == extra and row.get('tags') == ['romanization']]) != 1):
            return False
        inflected_record = _source_record_id(form_of)
        # The accepted sense must repeat the same source target and explicitly
        # link its printed target to this root entry. The Latin-script label
        # remains a source annotation, not an independently inferred identity.
        if not any(
            proof.get('source_family') == family and
            proof.get('predicate') == 'sense_gloss' and
            _source_record_id(proof) == inflected_record and
            isinstance(proof.get('subject'), Mapping) and
            proof['subject'].get('type') == 'form' and
            not proof['subject'].get('passage_id') and
            _exact_source_form(proof['subject'].get('form')) == _exact_source_form(form) and
            isinstance(proof.get('object'), Mapping) and
            isinstance(proof['object'].get('source_sense'), Mapping) and
            proof['object']['source_sense'].get('form_of') == targets and
            not proof['object']['source_sense'].get('raw_tags') and
            any(isinstance(link, list) and len(link) == 2 and
                _exact_source_form(link[0]) == target and
                _exact_source_form(link[1]) == f"{_exact_source_form(listed.get('lemma'))}#Ancient_Greek"
                for link in proof['object']['source_sense'].get('links') or ()) and
            any(isinstance(gloss, str) and f'({extra})' in gloss
                for gloss in proof['object']['source_sense'].get('glosses') or ())
            for proof in proofs.values()
        ):
            return False
    tags = _grammatical_tags(listed.get('analysis'))
    source_tags = relation_object.get('source_tags')
    if (not tags or tags != _grammatical_tags(relation.get('analysis')) or
        not isinstance(source_tags, list) or source_tags.count('form-of') != 1 or
        tags != _grammatical_tags([tag for tag in source_tags if tag != 'form-of'])):
        return False
    forms = morphology_object.get('forms')
    suffix = str(listed.get('id') or '').removeprefix(f"{listed_ids[0]}#form:")
    if (not str(listed.get('id') or '').startswith(f"{listed_ids[0]}#form:") or
        not suffix.isdecimal()):
        return False
    ordinal = int(suffix)
    if isinstance(forms, list):
        canonical = [row for row in forms if isinstance(row, Mapping) and
                     isinstance(row.get('tags'), list) and 'canonical' in row['tags']]
        if (len(canonical) != 1 or target != _exact_source_form(canonical[0].get('form')) or
            ordinal >= len(forms) or forms[ordinal] != listed.get('matched_object_form')):
            return False
    else:
        # Word previews intentionally compact large form arrays. Their source
        # claim still carries the canonical first-row quotation and template.
        # Require the exact accepted EvidenceIndex form-edge row and ordinal,
        # not merely the candidate's own claimed spelling/link. These are
        # several fields of ONE dictionary source, not independent witnesses.
        count = morphology_object.get('listed_form_count')
        templates = morphology_object.get('inflection_templates')
        projected_rows = morphology.get('matched_object_forms')
        projected_ordinals = morphology.get('matched_object_form_ordinals')
        quoted_canonical = []
        for evidence in morphology.get('evidence') or ():
            if not isinstance(evidence, Mapping) or evidence.get('locator') != '/entry/forms':
                continue
            try:
                quoted = json.loads(evidence.get('quote') or '')
            except (TypeError, ValueError):
                continue
            if isinstance(quoted, Mapping) and 'canonical' in (quoted.get('tags') or ()):
                quoted_canonical.append(quoted.get('form'))
        if (not isinstance(count, int) or isinstance(count, bool) or ordinal >= count or
            not isinstance(projected_rows, list) or not isinstance(projected_ordinals, list) or
            len(projected_rows) != len(projected_ordinals) or
            (ordinal, listed.get('matched_object_form')) not in
                list(zip(projected_ordinals, projected_rows)) or
            len(quoted_canonical) != 1 or target != _exact_source_form(quoted_canonical[0]) or
            not isinstance(templates, list) or not any(
                isinstance(template, Mapping) and isinstance(template.get('args'), Mapping) and
                _exact_source_form(template['args'].get('1')) == target
                for template in templates)):
            return False
    source_row = listed.get('matched_object_form')
    if (not isinstance(source_row, Mapping) or source_row.get('source') != 'declension' or
        source_row.get('raw_tags') or
        _grammatical_tags(source_row.get('tags')) != tags or
        _exact_source_form(source_row.get('form')) != _exact_source_form(listed.get('matched_form'))):
        return False
    links = source_row.get('links')
    if not isinstance(links, list) or not any(
        isinstance(link, list) and len(link) == 2 and
        _exact_source_form(link[0]) == _exact_source_form(source_row.get('form')) and
        _exact_source_form(link[1]) == f'{_exact_source_form(form)}#Ancient_Greek'
        for link in links
    ):
        return False
    # The linked inflected entry explicitly marks itself as a noun form; an
    # identical-looking form with a different POS must remain separate.
    inflected_record = _source_record_id(form_of)
    pos = morphology_object.get('pos')
    return bool(pos and inflected_record and any(
        proof.get('source_family') == family and
        proof.get('predicate') == 'lemma' and
        str(proof.get('id') or '').endswith(':lemma:entry') and
        _source_record_id(proof) == inflected_record and
        isinstance(proof.get('subject'), Mapping) and
        proof['subject'].get('type') == 'form' and
        not proof['subject'].get('passage_id') and
        _exact_source_form(proof['subject'].get('form')) == _exact_source_form(form) and
        isinstance(proof.get('object'), Mapping) and
        proof['object'].get('pos') == pos and
        isinstance(proof['object'].get('head_templates'), list) and
        any(isinstance(template, Mapping) and
            str(template.get('name') or '').startswith('grc-') and
            str(template.get('name') or '').endswith(' form')
            for template in proof['object']['head_templates'])
        for proof in proofs.values()
    ))


def _group_source_bridged_options(
    form: str, options: list[dict[str, Any]], claims: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    proofs = {str(claim['id']): claim for claim in claims}
    # Resolve both directions against the entire input before consuming any
    # option. A second form-of sense for one listed row is ambiguous even if
    # a greedy first match would otherwise hide it.
    relations: dict[int, list[int]] = {}
    listed: dict[int, list[int]] = {}
    for relation_index, relation in enumerate(options):
        if relation.get('candidate_kind') != 'explicit_form_of':
            continue
        for listed_index, candidate in enumerate(options):
            if relation_index == listed_index or not _source_bridged_pair(
                form, relation, candidate, proofs
            ):
                continue
            relations.setdefault(relation_index, []).append(listed_index)
            listed.setdefault(listed_index, []).append(relation_index)
    replacements: dict[int, dict[str, Any]] = {}
    consumed: set[int] = set()
    groups = 0
    for first, matches in relations.items():
        if len(matches) != 1 or len(listed[matches[0]]) != 1:
            continue
        second = matches[0]
        relation, source_listed = options[first], options[second]
        group = dict(source_listed)  # Existing listed-form ID remains the decision ID.
        group['claim_ids'] = list(dict.fromkeys([*relation['claim_ids'], *source_listed['claim_ids']]))
        group['evidence_refs'] = list(dict.fromkeys([
            *(relation.get('evidence_refs') or ()), *(source_listed.get('evidence_refs') or ())]))
        group['source_references'] = [*relation['source_references'], *source_listed['source_references']]
        group['decision_group'] = {
            'basis': 'accepted_exact_form_of_target_canonical_and_listed_form_link',
            'member_candidate_ids': [relation['id'], source_listed['id']],
            'source_lemma_spellings': [relation['lemma'], source_listed['lemma']],
            'source_form_spellings': [relation['matched_form'], source_listed['matched_form']],
            'source_form_of_target': proofs[relation['claim_ids'][0]]['object']['targets'],
            'scope': 'One general dictionary reading; no passage attestation or independent witness.',
        }
        replacements[first] = group
        consumed.update((first, second))
        groups += 1
    return [replacements[index] if index in replacements else option
            for index, option in enumerate(options) if index not in consumed or index in replacements], groups


def build_evidence_packet(
    form: str, passage: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] = (),
    author_profile: Sequence[Mapping[str, Any]] = (),
    dialect_rules: Sequence[Mapping[str, Any]] = (),
    *, machine_validation: Mapping[str, Any] | None = None,
    source_guard_candidates: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a bounded, inspectable decision state from supplied evidence.

    Unaccepted or model-inferred claims are never promoted into the packet.
    Author profile and dialect rules must be source claims too; merely knowing
    an author's name never turns a word into an exclusive dialect form.
    """
    context = passage or {}
    warnings: list[str] = []
    machine, machine_error = _validated_machine_inventory(form, candidates, machine_validation)
    source_guard_packet = None
    if machine is not None:
        if source_guard_candidates is None or any(_machine_candidate(row) for row in source_guard_candidates):
            machine_error = 'Machine comparison requires the original source candidate safety inventory.'
        else:
            source_guard_packet = build_evidence_packet(form, passage, source_guard_candidates,
                claims, author_profile, dialect_rules)
            warnings.extend(source_guard_packet['warnings'])
    if sum(map(len, (claims, author_profile, dialect_rules))) > MAX_CLAIMS:
        warnings.append(f"More than {MAX_CLAIMS} claims; no subset was silently chosen.")
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, rows in (("claims", claims), ("author_profile", author_profile),
                       ("dialect_rules", dialect_rules)):
        groups[name] = [_claim_record(row) for row in rows if _source_claim(row)]
        dropped = len(rows) - len(groups[name])
        if dropped:
            warnings.append(f"{dropped} {name} record(s) excluded: not source-bearing accepted claims.")
    known_claim_ids = {row["id"] for rows in groups.values() for row in rows}
    raw_claims = {str(row['id']): row for row in claims if _source_claim(row)}
    incomplete_senses: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(candidates, 1):
        if not isinstance(row, Mapping):
            warnings.append(f"Candidate {index} is not an object.")
            continue
        cid = str(row.get("id") or f"candidate_{index}")
        if not _machine_candidate(row) and _lexical_metadata_candidate(row):
            warnings.append(f"Candidate {cid} excluded: lexical entry metadata is not a grammatical choice.")
            continue
        if cid == "abstain" or cid in seen:
            warnings.append(f"Duplicate or reserved candidate ID: {cid}.")
            continue
        seen.add(cid)
        if _machine_candidate(row):
            if machine is not None:
                options.append({**row, 'matched_form': form,
                    'claim_ids': [], 'source_references': [], 'evidence_refs': []})
            # An unverified machine row must never fall through to the legacy
            # source-URL path. The inventory error below blocks the full call.
            continue
        source_refs: list[dict[str, str]] = []
        for field in ("source_url", "gloss_source_url"):
            url = row.get(field)
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                source_refs.append({"id": f"{cid}:{field}", "url": url,
                                    "scope": "candidate metadata; verify source scope"})
        for source in row.get("supporting_sources") or ():
            if isinstance(source, Mapping) and isinstance(source.get("source_url"), str):
                url = source["source_url"]
                if url.startswith(("https://", "http://")) and not any(
                        ref["url"] == url for ref in source_refs):
                    source_refs.append({"id": f"{cid}:support:{len(source_refs)}",
                                        "url": url, "scope": "candidate metadata; verify source scope"})
        linked = [str(claim_id) for claim_id in row.get("claim_ids") or ()
                  if str(claim_id) in known_claim_ids]
        sense_ids = row.get('entry_sense_claim_ids') or []
        senses = []
        if sense_ids:
            from .candidate_senses import project_entry_senses
            anchor_ids = row.get('claim_ids') or []
            anchor = raw_claims.get(anchor_ids[0]) if len(anchor_ids) == 1 else None
            supplied = [raw_claims[sid] for sid in sense_ids if sid in raw_claims]
            senses = project_entry_senses(row, anchor, supplied) if anchor else []
            if (len(sense_ids) != len(set(sense_ids)) or
                    set(sense_ids) != {sense['claim_id'] for sense in senses}):
                incomplete_senses.append({'candidate_id': cid, 'entry_sense_claim_ids': sense_ids})
                senses = []
        options.append({"id": cid, "candidate_kind": row.get("candidate_kind"),
                        "entry_headword": row.get("entry_headword"),
                        "lemma": row.get("lemma"),
                        "analysis": row.get("analysis"),
                        "analysis_text": row.get("analysis_text"),
                        "features": row.get("features"),
                        "equivalent_form": row.get("equivalent_form"),
                        "relation_raw": row.get("relation_raw"),
                        "lemma_targets": row.get("lemma_targets"),
                        "source_tags": row.get("source_tags"),
                        "source_raw_tags": row.get("source_raw_tags"),
                        "dialect": row.get("dialect"),
                        "gloss": row.get("gloss"),
                        "matched_form": row.get("matched_form"),
                        "matched_form_variants": row.get("matched_form_variants"),
                        "matched_object_form": row.get("matched_object_form"),
                        "match_kind": row.get("match_kind"),
                        "edit_distance": row.get("edit_distance"),
                        "strength": row.get("strength"),
                        "match_reason": row.get("match_reason"),
                        "source_family": row.get("source_family"),
                        "comparison_scope": row.get("comparison_scope"),
                        "source_passage_id": row.get("source_passage_id"),
                        "comparison_context": row.get("comparison_context"),
                        "source_projection_status": row.get("source_projection_status"),
                        "source_grammar_alternatives": row.get("source_grammar_alternatives"),
                        "source_projection_note": row.get("source_projection_note"),
                        "entry_senses": senses or None,
                        "entry_sense_claim_ids": sense_ids or None,
                        "evidence_refs": row.get("evidence_refs"),
                        "source_references": source_refs, "claim_ids": linked})
    # Preserve inventory-level incompleteness before grouping can consume a
    # member ID. Source alternatives and their quotes remain unchanged.
    incomplete_projections = [{key: option[key] for key in
        ('id', 'claim_ids', 'source_projection_status', 'source_grammar_alternatives', 'source_projection_note')}
        for option in options
        if option.get('source_projection_status') == 'incomplete_explicit_alternatives']
    original_option_count = len(options)
    options, grouped_count = _group_source_bridged_options(
        form, options, [row for row in claims if _source_claim(row)])
    if original_option_count > MAX_CANDIDATES:
        warnings.append(f"More than {MAX_CANDIDATES} candidates; no subset was silently chosen.")
    constraints = [
        "Choose only an existing candidate ID or abstain.",
        "Source claims and lexical candidates have distinct scopes; do not infer attestation from a dictionary listing.",
        "Author context and literary dialect rules are defeasible, not exclusive dialect assignments.",
        "A nearby spelling is a correction suggestion, not a parse of the queried form.",
        "An equivalent form or listed entry is an alternative relation, not an attested parse in this passage.",
        "A computationally matching context in another edition is a comparison only: its source claim belongs to the original source passage, not proof of edition identity or direct target-passage attestation.",
        "The original passage preserves editorial signs and uncertainty. A search-only diacritic fold or explicit line-division join establishes a lookup match, not secure letters, restored text, or an attested editorial reading; respect the supplied quality and edition.",
        "Preserve conflicting interpretations; abstain if evidence does not resolve them.",
    ]
    if grouped_count:
        constraints.append(
            "A source-bridged decision group contains alternative spellings and claim IDs for one grammatical reading from the same dictionary family, not independent witnesses or a passage-specific analysis."
        )
    if machine is not None:
        constraints.extend([
            'Machine-analysis candidates are engine-derived grammatical hypotheses, not accepted source claims, dictionary senses, or attestation in this passage.',
            'Each machine candidate retains separate literal dictionary_fields and inflection fields. Do not promote dictionary-level features into missing inflection features, split literal dialect labels, or complete absent grammar.',
            'All returned machine inflections are supplied, but a returned inventory is not proof that every possible analysis exists. Abstain if context or preserved editorial uncertainty prevents a responsible choice.',
            'The raw receipt identifies a response and parser, not a verified deployed engine or stem-library revision. Linked lexical URLs do not establish an exact accepted sense identity.',
        ])
    packet = {
        "form": form,
        "passage": {k: context.get(k) for k in
                    ("id", "text", "author", "author_id", "work", "citation",
                     "language", "kind", "quality", "edition", "source_url") if context.get(k) is not None},
        "candidates": options,
        **groups,
        "constraints": constraints,
        "warnings": warnings,
    }
    if incomplete_projections:
        packet['incomplete_source_projections'] = incomplete_projections
    if incomplete_senses:
        packet['incomplete_entry_sense_evidence'] = incomplete_senses
    if source_guard_packet is not None:
        for key in ('incomplete_source_projections', 'incomplete_entry_sense_evidence'):
            if source_guard_packet.get(key):
                packet[key] = source_guard_packet[key]
    if machine_error:
        packet['invalid_machine_inventory'] = machine_error
    if machine is not None:
        packet['candidate_basis'] = 'machine'
        packet['machine_packet_schema'] = MACHINE_PACKET_SCHEMA
        packet['machine_receipt'] = {key: machine['receipt'].get(key) for key in (
            'id', 'request_form', 'url', 'http_status', 'received_utc',
            'raw_sha256', 'parser_version', 'engine_revision')}
    return _compact_packet(packet)


class JevProvider:
    """Official TypeSafe Jev System One HTTP adapter (no account creation)."""

    def __init__(self, api_key: str | None = None, *, model: str = "jev-latest",
                 timeout: float = 8.0):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        self.model = model
        self.timeout = timeout

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.api_key:
            raise RuntimeError("TypeSafe Jev API key is not configured")
        # Choice descriptions must distinguish the actual alternatives. Keep
        # concise source-supplied semantics here, with the full evidence in
        # state, rather than identical ID-lookup instructions for every option.
        # These are projections, not newly merged or completed interpretations.
        summary_fields = (
            'candidate_kind', 'entry_headword', 'lemma', 'analysis', 'analysis_text',
            'features', 'equivalent_form',
            'relation_raw', 'lemma_targets', 'source_tags', 'source_raw_tags',
            'dialect', 'gloss', 'matched_form', 'edit_distance', 'strength',
            'source_family', 'comparison_scope', 'source_passage_id',
            'decision_group',
            'entry_senses', 'entry_sense_claim_ids',
        )
        choices = {str(item['id']): {
            'candidate_id': item['id'],
            **{key: item[key] for key in summary_fields if key in item},
            'evidence': 'Use the complete candidate and its linked source claims in state. Missing fields remain unknown.'}
            for item in packet['candidates']}
        for item in packet['candidates']:
            if item.get('basis') == 'machine_analysis':
                choices[str(item['id'])].update({key: item[key] for key in (
                    'basis', 'dictionary_fields', 'inflection', 'entry_pointer',
                    'inflection_pointer', 'receipt_id') if key in item})
                choices[str(item['id'])]['evidence'] = (
                    'Use this engine-derived inflection and the complete raw-receipt-bound '
                    'candidate in state. This is machine analysis, not source-attested parsing.')
        choices["abstain"] = "The supplied context and source evidence do not support a responsible selection."
        body = {"model": self.model, "state": packet,
                "questions": {"contextual_parse": {
                    "type": "choice",
                    "instructions": "Which supplied candidate best fits this exact Greek passage? Choose a provisional contextual grammatical hypothesis, not a certification of source-attested parsing. Lack of an explicit passage annotation alone does not require abstention when the supplied Greek context supports an existing candidate. Select abstain for unresolved ambiguity, conflicts, missing evidence, or inadequate context. Never create a new reading or assume the author's literary dialect makes every form exclusive.",
                    "criteria": choices}}}
        request = Request(JEV_ENDPOINT, data=_state_json(body).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"TypeSafe Jev HTTP {exc.code}") from None
        except URLError as exc:
            raise RuntimeError(f"TypeSafe Jev transport error: {exc.reason}") from None
        answer = payload.get("answers", {}).get("contextual_parse", {})
        if answer.get("type") != "choice" or not isinstance(answer.get("choice"), str):
            raise RuntimeError("TypeSafe Jev returned no valid choice answer")
        return {"choice": answer["choice"], "model": payload.get("model"),
                "model_probabilities": answer.get("probabilities"),
                "model_confidence": answer.get("confidence"),
                "usage": payload.get("usage"),
                "raw_response": {"model": payload.get("model"),
                                 "answers": payload.get("answers"),
                                 "usage": payload.get("usage")}}


def configured_provider() -> DecisionProvider | None:
    """Use Jev if configured; local inference needs validation and opt-in."""
    if os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY"):
        return JevProvider(model=os.environ.get('MELOS_JEV_MODEL', JEV_MODEL))
    try:
        from .local_classifier import LocalModelProvider, local_model_status
        status = local_model_status()
        if (status.get("installed") and status.get("validated")
                and os.environ.get("MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER") == "1"):
            return LocalModelProvider()
    except (ImportError, RuntimeError, OSError):
        pass
    return None


def provider_status() -> dict[str, Any]:
    """Describe capability without exposing credentials or calling a model."""
    if os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY"):
        return {"configured": True, "provider": "TypeSafe Jev",
                "model": os.environ.get('MELOS_JEV_MODEL', JEV_MODEL), "reason": "Jev is configured; each comparison is an evidence-bound model proposal."}
    try:
        from .local_classifier import local_model_status
        status = local_model_status()
        if status.get("installed"):
            enabled = bool(status.get("validated") and
                           os.environ.get("MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER") == "1")
            reason = ("Validated local model is explicitly enabled; no request made."
                      if enabled else
                      "Validated local model requires MELOS_EXPERIMENTAL_LOCAL_CLASSIFIER=1; inference is disabled."
                      if status.get("validated") else
                      "TypeSafe Jev is preferred, but TYPESAFE_API_KEY is not configured. The installed local diagnostic model remains disabled because its contextual accuracy is unverified.")
            return {"configured": enabled, "provider": "local", "model": status.get("model"),
                    "installed": True, "validated": bool(status.get("validated")),
                    "reason": reason}
    except (ImportError, RuntimeError, OSError):
        pass
    return {"configured": False, "provider": None, "model": None,
            "reason": "No TypeSafe Jev key or local classifier is configured."}


def classify_context(
    form: str, passage: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] = (),
    author_profile: Sequence[Mapping[str, Any]] = (),
    dialect_rules: Sequence[Mapping[str, Any]] = (),
    provider: DecisionProvider | None = None,
    *, machine_validation: Mapping[str, Any] | None = None,
    source_guard_candidates: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a model proposal or a reasoned abstention, never a corpus claim."""
    kwargs = {'machine_validation': machine_validation} if machine_validation is not None else {}
    if source_guard_candidates is not None:
        kwargs['source_guard_candidates'] = source_guard_candidates
    packet = build_evidence_packet(form, passage, candidates, claims,
                                   author_profile, dialect_rules, **kwargs)
    result: dict[str, Any] = {"status": "abstained", "decision_stage": "preflight", "candidate_id": None,
                              "reason": "", "model": None, "evidence_ids": [],
                              "packet": packet, "warnings": list(packet["warnings"])}
    if packet.get('candidate_basis') == 'machine':
        result['candidate_basis'] = 'machine'
    if packet.get('invalid_machine_inventory'):
        result['reason'] = packet['invalid_machine_inventory']
        return result
    if packet["warnings"] and any("silently chosen" in w or "candidate ID" in w
                                   for w in packet["warnings"]):
        result["reason"] = "Input exceeds safe bounds or has ambiguous candidate IDs."
        return result
    context = packet["passage"]
    if not context.get("text") or context.get("language", "grc") != "grc" or context.get("kind", "text") != "text":
        result["reason"] = "An original Greek text passage is required."
        return result
    # Normalize only a lookup copy, before tokenizing: combining underdots and
    # other marks must not split a word into spurious tokens. search_text joins
    # explicit Greek line divisions only; brackets, lacunae and digits remain
    # boundaries. The model still receives the unchanged editorial passage.
    context_tokens = tokenize(normalize(search_text(str(context['text']))))
    if normalize(form) not in set(context_tokens):
        result["reason"] = "The queried form does not occur as a token in the supplied Greek passage."
        return result
    if packet.get('incomplete_source_projections'):
        result['reason'] = ('A source explicitly gives grammatical alternatives, but the candidate inventory '
                            'does not preserve all of those alternatives. Comparison was not run; '
                            'the original source claims and quoted alternatives remain available.')
        return result
    if packet.get('incomplete_entry_sense_evidence'):
        result['reason'] = ('Exact dictionary-entry sense evidence is incomplete or inconsistent. '
                            'Comparison was not run; no partial homograph distinction was assumed.')
        return result
    if not packet["candidates"]:
        result["reason"] = "No existing candidate is available."
        return result
    if all(_nearby_spelling(candidate) for candidate in packet['candidates']):
        result['reason'] = ('Only nearby-spelling suggestions are available, not parses of this form. '
                            'No model request was made; source-supported candidates for the exact form are needed.')
        return result
    if packet.get('candidate_basis') != 'machine' and not any(c["source_references"] or c["claim_ids"] for c in packet["candidates"]):
        result["reason"] = "Candidates have no source references or accepted claim links."
        return result
    state_chars = len(_state_json(packet))
    if state_chars > MAX_STATE_CHARS:
        result["reason"] = f"Evidence packet exceeds {MAX_STATE_CHARS} characters."
        return result
    provider = provider or configured_provider()
    if provider is None:
        result["reason"] = provider_status()["reason"]
        return result
    from .jev_gateway import GatewayLimit, GatewayUnavailable
    result['decision_stage'] = 'provider_request'
    try:
        answer = provider.decide(packet)
    except (GatewayLimit, GatewayUnavailable):
        raise
    except (RuntimeError, ValueError, TypeError, TimeoutError) as exc:
        result["reason"] = str(exc)
        return result
    choice = answer.get("choice")
    if 'cache_hit' in answer:
        result['cache_hit'] = bool(answer['cache_hit'])
    result["model"] = answer.get("model")
    if not isinstance(result["model"], str) or not result["model"]:
        result["reason"] = "Provider did not identify the model used."
        return result
    # Preserve the provider's uncertainty even when it chooses abstention.
    # These are raw model signals, not philological calibration.
    if answer.get("model_probabilities") is not None:
        result["model_probabilities_uncalibrated"] = answer["model_probabilities"]
    if answer.get("model_confidence") is not None:
        result["model_confidence_uncalibrated"] = answer["model_confidence"]
    if answer.get("usage") is not None:
        result["usage"] = answer["usage"]
    if choice == "abstain":
        result['decision_stage'] = 'model_abstained'
        result["reason"] = "The model abstained on the supplied evidence."
        return result
    selected = next((c for c in packet["candidates"] if c["id"] == choice), None)
    if selected is None:
        result["reason"] = "Provider returned a choice outside the supplied candidate IDs."
        return result
    if _nearby_spelling(selected):
        result["reason"] = "Selected candidate is a nearby-spelling suggestion, not a parse of this form."
        return result
    if selected.get('basis') == 'machine_analysis':
        result.update(status='machine_proposed', decision_stage='model_proposed',
            candidate_id=choice,
            reason='Model-ranked engine-derived analysis; machine hypothesis only, not a source claim or attested parse.',
            machine_evidence={'receipt': packet['machine_receipt'],
                'entry_pointer': selected['entry_pointer'],
                'inflection_pointer': selected['inflection_pointer']})
        return result
    evidence_ids = list(dict.fromkeys(
        selected["claim_ids"] +
        (selected.get('entry_sense_claim_ids') or []) +
        [str(ref) for ref in selected.get("evidence_refs") or () if ref] +
        [r["id"] for r in selected["source_references"]]))
    if not evidence_ids:
        result["reason"] = "Selected candidate has no linked evidence."
        return result
    result.update(status="proposed", decision_stage="model_proposed", candidate_id=choice,
                  reason="Model-ranked existing candidate; interpretive proposal only.",
                  evidence_ids=evidence_ids)
    return result


__all__ = ["DecisionProvider", "JevProvider", "build_evidence_packet",
           "classify_context", "configured_provider", "provider_status"]
