"""QA19 exact-entry sense pilot: offline by default; at most six Jev attempts.

The input packets and reviewer rubric are separate, frozen staging artifacts.
This runner never constructs Greek, changes production evidence, uses the local
gateway cache, or retries a reserved/failed/interrupted arm. The QA16 receipt
code is reused as a tested transport/atomic-I/O primitive, not its artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_classifier_prompt_eval as receipt_io

MAX_ATTEMPTS = 6
RECEIPT_NAME = 'qa19_evaluation_receipt.json'
ARTIFACT_TYPE = 'qa19_exact_entry_sense_packets'
REVIEW_TYPE = 'qa19_exact_entry_sense_review'
REQUIRED_INPUTS = frozenset({
    'data/corpus.sqlite', 'data/evidence.sqlite',
    'data/reports/audit-acceptance.json',
    'data/lexica/entries.jsonl', 'data/lexica/forms.jsonl',
})
SENSE_FIELDS = frozenset({'entry_senses', 'entry_sense_claim_ids'})
SOURCE_REFERENCE_FORMAT = (
    'Each candidate source_references item preserves its evidence id; '
    'source_ref resolves to the complete URL and scope in source_catalog. '
    'Sharing a URL does not merge claims, candidate IDs, or interpretations.'
)
SENSE_REFERENCE_FORMAT = (
    'Each candidate entry_sense_claim_ids resolves to literal general dictionary-entry '
    'senses in entry_sense_catalog. Sharing a sense claim does not merge candidate IDs, '
    'homographs, grammatical alternatives, or establish a contextual sense.'
)


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    return value


def _ids(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f'{label} must be nonempty string IDs')
    if len(set(value)) != len(value):
        raise ValueError(f'{label} contains duplicate IDs')
    return value


def _file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_inputs(bundle, root):
    files = _object(bundle.get('input_files'), 'input_files')
    fixture = bundle.get('source_fixture')
    if not isinstance(fixture, str) or fixture not in files or not REQUIRED_INPUTS.issubset(files):
        raise ValueError('Required corpus/evidence/lexica and source fixture hashes are missing')
    base = root.resolve()
    for relative, expected in files.items():
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError('Input path must be workspace-relative')
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise ValueError('Input path escapes or is missing from the workspace')
        expected = _object(expected, 'input hash')
        if (type(expected.get('bytes')) is not int or expected['bytes'] < 0
                or target.stat().st_size != expected['bytes']
                or _file_hash(target) != expected.get('sha256')):
            raise ValueError(f'Frozen input size/hash changed: {relative}')
    return receipt_io.sha(receipt_io.encode(files, canonical=True))


def _expand_source_catalog(state):
    """Compare semantic packet content even when URL factoring switches on."""
    normalized = json.loads(receipt_io.encode(state))
    catalog = normalized.pop('source_catalog', {})
    format_text = normalized.pop('source_reference_format', None)
    if (not isinstance(catalog, dict) or
            (format_text != SOURCE_REFERENCE_FORMAT if catalog else format_text is not None)):
        raise ValueError('Source catalog or production reference format is invalid')
    used = set()
    for candidate in normalized.get('candidates', []):
        expanded = []
        for ref in candidate.get('source_references', []):
            if 'source_ref' in ref:
                if set(ref) != {'id', 'source_ref'}:
                    raise ValueError('Compact source reference contains extra model-visible fields')
                payload = catalog.get(ref['source_ref'])
                if not isinstance(payload, dict) or set(payload) != {'url', 'scope'}:
                    raise ValueError('Unresolved compact source reference')
                used.add(ref['source_ref'])
                expanded.append({'id': ref['id'], **payload})
            else:
                expanded.append(ref)
        candidate['source_references'] = expanded
    if set(catalog) != used:
        raise ValueError('Unused source catalog payload is model-visible')
    normalized.pop('entry_sense_catalog', None)
    normalized.pop('entry_sense_reference_format', None)
    return normalized


def _validate_sense_payload(state, reviewed_ids, *, old=False):
    catalog = state.get('entry_sense_catalog', {})
    format_text = state.get('entry_sense_reference_format')
    if (not isinstance(catalog, dict) or
            (format_text != SENSE_REFERENCE_FORMAT if catalog else format_text is not None)):
        raise ValueError('Entry-sense catalog or production reference format is invalid')
    if catalog and set(catalog) != reviewed_ids:
        raise ValueError('Entry-sense catalog contains missing or undeclared IDs')
    for identifier, sense in catalog.items():
        if not isinstance(sense, dict) or sense.get('claim_id') != identifier:
            raise ValueError('Entry-sense catalog claim identity is inconsistent')
    seen_inline = set()
    for candidate in state.get('candidates', []):
        candidate_ids = set(candidate.get('entry_sense_claim_ids') or [])
        for sense in candidate.get('entry_senses') or []:
            if (not isinstance(sense, dict) or sense.get('claim_id') not in candidate_ids
                    or catalog):
                raise ValueError('Inline entry sense lacks exact candidate claim proof')
            seen_inline.add(sense['claim_id'])
    if old:
        if reviewed_ids and (catalog or seen_inline or _sense_ids(state)):
            raise ValueError('Baseline contains unexpected entry-sense enrichment')
    elif ((set(_sense_ids(state)) != reviewed_ids)
          or (not catalog and seen_inline != reviewed_ids)
          or not reviewed_ids.issubset(set(_claim_ids(state)))):
        raise ValueError('Entry-sense proof IDs are not complete in packet claims')


def _request_envelope(body):
    envelope = json.loads(receipt_io.encode(body))
    envelope.pop('state', None)
    envelope['questions']['contextual_parse'].pop('criteria', None)
    return envelope


def _claim_ids(state):
    return sorted({row['id'] for group in ('claims', 'author_profile', 'dialect_rules')
                   for row in state.get(group, []) if isinstance(row, dict) and isinstance(row.get('id'), str)})


def _sense_ids(state):
    return sorted({identifier for candidate in state.get('candidates', [])
                   for identifier in candidate.get('entry_sense_claim_ids', [])})


def _without_sense_enrichment(state, reviewed_ids):
    clean = _expand_source_catalog(state)
    for candidate in clean.get('candidates', []):
        for field in SENSE_FIELDS:
            candidate.pop(field, None)
    for group in ('claims', 'author_profile', 'dialect_rules'):
        clean[group] = [row for row in clean.get(group, []) if row.get('id') not in reviewed_ids]
        clean[group].sort(key=lambda row: row['id'])
    return clean


def _without_sense_descriptions(criteria):
    value = json.loads(receipt_io.encode(criteria))
    for description in value.values():
        if isinstance(description, dict):
            for field in SENSE_FIELDS:
                description.pop(field, None)
    return value


def load_plan(packet_path, rubric_path, *, root=ROOT):
    packet_raw, rubric_raw = packet_path.read_bytes(), rubric_path.read_bytes()
    bundle, rubric = json.loads(packet_raw), json.loads(rubric_raw)
    if (bundle.get('schema_version') != 1 or bundle.get('artifact_type') != ARTIFACT_TYPE
            or rubric.get('schema_version') != 1 or rubric.get('artifact_type') != REVIEW_TYPE
            or rubric.get('review_status') != 'approved'
            or rubric.get('packet_sha256') != receipt_io.sha(packet_raw)):
        raise ValueError('Independent QA19 packet/rubric approval binding is missing')
    manifest_hash = verify_inputs(bundle, root)
    source_fixture = json.loads((root / bundle['source_fixture']).read_bytes())
    if (source_fixture.get('schema_version') != 1
            or source_fixture.get('artifact_type') != 'qa19_homograph_source_evidence'
            or source_fixture.get('paid_calls') != 0):
        raise ValueError('Bound source-only QA19 fixture is invalid')
    source_cases = {case.get('id'): case for case in source_fixture.get('cases', [])
                    if isinstance(case, dict)}
    accepted_sense_ids = {claim.get('id') for claim in source_fixture.get('accepted_sense_claims', [])
                          if isinstance(claim, dict) and claim.get('status') == 'source_claim'
                          and claim.get('assertion_type') != 'model_inference'}
    cases, reviews = bundle.get('cases'), rubric.get('cases')
    if not isinstance(cases, list) or not 2 <= len(cases) <= 3 or not isinstance(reviews, list):
        raise ValueError('Pilot requires two homograph contexts and at most one control')
    roles = [case.get('role') for case in cases]
    if roles.count('homograph_context') != 2 or roles.count('control') != len(cases) - 2:
        raise ValueError('Pilot case roles are not the reviewed two-context design')
    by_id = {row.get('id'): row for row in reviews if isinstance(row, dict)}
    case_ids = [case.get('id') for case in cases]
    if (any(not isinstance(identifier, str) or not identifier for identifier in case_ids)
            or len(set(case_ids)) != len(cases) or len(by_id) != len(reviews)
            or set(by_id) != set(case_ids)):
        raise ValueError('Duplicate or unmatched reviewed case identity')
    model = bundle.get('model')
    baseline = bundle.get('baseline_revision')
    code_hashes = bundle.get('classifier_sha256')
    if (not isinstance(model, str) or not model or not isinstance(baseline, str)
            or not baseline or not isinstance(code_hashes, dict)
            or any(not isinstance(code_hashes.get(arm), str)
                   or len(code_hashes[arm]) != 64 for arm in ('old', 'new'))):
        raise ValueError('Pinned model or classifier source hashes are missing')
    plan = []
    for case in cases:
        review = by_id[case['id']]
        reviewed_ids = set(_ids(case.get('entry_sense_claim_ids'), 'entry_sense_claim_ids'))
        source_case = source_cases.get(case['id'])
        if (not source_case or case.get('form') != source_case.get('form')
                or case.get('passage_id') != source_case.get('passage_id')
                or not reviewed_ids.issubset(accepted_sense_ids)):
            raise ValueError('Case form, passage, or sense claims lack bound accepted source proof')
        if sorted(review.get('entry_sense_claim_ids', [])) != sorted(reviewed_ids):
            raise ValueError('Reviewer did not bind exact entry-sense claim IDs')
        old, new = (_object(case.get(f'{arm}_request'), f'{arm}_request') for arm in ('old', 'new'))
        questions = []
        for arm, body in (('old', old), ('new', new)):
            question = _object(_object(body.get('questions'), 'questions').get('contextual_parse'), 'question')
            choices = _object(question.get('criteria'), 'criteria')
            if (body.get('model') != model or question.get('type') != 'choice'
                    or 'abstain' not in choices or not isinstance(body.get('state'), dict)
                    or review.get('requests', {}).get(arm) != receipt_io.sha(receipt_io.encode(body, canonical=True))):
                raise ValueError('Frozen request or reviewer hash differs')
            questions.append(question)
        if (_request_envelope(old) != _request_envelope(new)
                or set(questions[0]['criteria']) != set(questions[1]['criteria'])
                or _without_sense_descriptions(questions[0]['criteria']) !=
                   _without_sense_descriptions(questions[1]['criteria'])):
            raise ValueError('Model prompt, choice IDs, or grammatical descriptions changed')
        old_state, new_state = old['state'], new['state']
        _validate_sense_payload(old_state, reviewed_ids, old=True)
        _validate_sense_payload(new_state, reviewed_ids)
        if (case.get('form') != old_state.get('form') or
                case.get('passage_id') != (old_state.get('passage') or {}).get('id') or
                old_state.get('form') != new_state.get('form') or
                old_state.get('passage') != new_state.get('passage') or
                sorted(_sense_ids(new_state)) != sorted(reviewed_ids) or
                _sense_ids(old_state) or
                _without_sense_enrichment(old_state, reviewed_ids) !=
                   _without_sense_enrichment(new_state, reviewed_ids)):
            raise ValueError('Packet differs outside independently reviewed exact-entry sense evidence')
        outcomes = review.get('outcomes')
        if (not isinstance(outcomes, dict) or not set(outcomes).issubset(questions[0]['criteria'])
                or review.get('default_outcome') not in receipt_io.OUTCOMES
                or any(label not in receipt_io.OUTCOMES for label in outcomes.values())):
            raise ValueError('Candidate-specific reviewer outcome labels are invalid')
        for arm, body in (('old', old), ('new', new)):
            wire = receipt_io.encode(body)
            plan.append({'case_id': case['id'], 'role': case['role'], 'arm': arm,
                         'model': model, 'wire': wire, 'request_sha256': receipt_io.sha(wire),
                         'canonical_request_sha256': receipt_io.sha(receipt_io.encode(body, canonical=True)),
                         'choices': set(questions[0]['criteria']), 'review': review,
                         'state': body['state'], 'request_bytes': len(wire),
                         'state_chars': len(receipt_io.encode(body['state']).decode('utf-8')),
                         'packet_claim_ids': _claim_ids(body['state']),
                         'entry_sense_claim_ids': _sense_ids(body['state'])})
    return {'packet_sha256': receipt_io.sha(packet_raw),
            'rubric_sha256': receipt_io.sha(rubric_raw),
            'input_manifest_sha256': manifest_hash, 'classifier_sha256': code_hashes,
            'baseline_revision': baseline, 'model': model, 'plan': plan}


def load_modules(frozen, *, root=ROOT):
    from backend import classifier
    source = subprocess.check_output(['git', 'show',
        f"{frozen['baseline_revision']}:backend/classifier.py"], cwd=root)
    if (receipt_io.sha(source) != frozen['classifier_sha256']['old']
            or _file_hash(root / 'backend/classifier.py') != frozen['classifier_sha256']['new']):
        raise ValueError('Pinned baseline or current classifier source hash changed')
    import types
    old = types.ModuleType('backend._qa19_baseline_classifier')
    old.__package__ = 'backend'
    exec(compile(source, f"{frozen['baseline_revision']}:backend/classifier.py", 'exec'), old.__dict__)
    return {'old': old, 'new': classifier}


def production_validation(module, item, choice):
    """Replay the real classifier postflight against the exact frozen state."""
    packet = item['state']

    class FrozenChoice:
        called = False

        def decide(self, supplied):
            self.called = True
            if supplied is not packet:
                raise ValueError('Production validator did not receive the frozen packet')
            return {'choice': choice, 'model': item['model']}

    provider = FrozenChoice()
    with patch.object(module, 'build_evidence_packet', return_value=packet):
        result = module.classify_context(packet['form'], packet['passage'], [], provider=provider)
    selected = next((row for row in packet.get('candidates', []) if row.get('id') == choice), None)
    return {'provider_reached': provider.called, 'status': result['status'],
            'decision_stage': result['decision_stage'], 'candidate_id': result['candidate_id'],
            'reason': result['reason'], 'evidence_ids': result['evidence_ids'],
            'selected_grammar_claim_ids': list(selected.get('claim_ids') or []) if selected else [],
            'selected_entry_sense_claim_ids': list(selected.get('entry_sense_claim_ids') or []) if selected else [],
            'all_packet_claim_ids': item['packet_claim_ids']}


def load_receipt(path, frozen):
    binding = {key: frozen[key] for key in ('packet_sha256', 'rubric_sha256',
        'input_manifest_sha256', 'classifier_sha256', 'baseline_revision', 'model')}
    if not path.exists():
        return {'schema_version': 1, 'artifact_type': REVIEW_TYPE, **binding,
                'max_attempts': MAX_ATTEMPTS, 'attempts': []}
    receipt = json.loads(path.read_bytes())
    if (receipt.get('schema_version') != 1 or receipt.get('artifact_type') != REVIEW_TYPE
            or receipt.get('max_attempts') != MAX_ATTEMPTS
            or any(receipt.get(key) != value for key, value in binding.items())):
        raise ValueError('QA19 receipt belongs to a different reviewed experiment')
    expected = {(item['case_id'], item['arm']): item for item in frozen['plan']}
    attempts, seen = receipt.get('attempts'), set()
    if not isinstance(attempts, list) or len(attempts) > MAX_ATTEMPTS:
        raise ValueError('QA19 attempt budget is invalid')
    for attempt in attempts:
        key = (attempt.get('case_id'), attempt.get('arm'))
        item = expected.get(key)
        if (key in seen or not item or attempt.get('status') not in ('reserved','completed','failed')
                or any(attempt.get(field) != item[field] for field in
                       ('model','request_sha256','canonical_request_sha256','request_bytes'))):
            raise ValueError('QA19 receipt attempt identity is invalid')
        seen.add(key)
    return receipt


def run(packet_path, rubric_path, *, allow_paid=False, root=ROOT,
        transport=receipt_io.send_frozen, modules=None):
    frozen = load_plan(packet_path, rubric_path, root=root)
    resolved_modules = modules or load_modules(frozen, root=root)
    for item in frozen['plan']:
        preflight = production_validation(resolved_modules[item['arm']], item, 'abstain')
        if not preflight['provider_reached'] or preflight['decision_stage'] != 'model_abstained':
            raise ValueError(f"Frozen {item['case_id']}/{item['arm']} is not provider-eligible")
    receipt_path = packet_path.parent / RECEIPT_NAME
    with receipt_io.receipt_lock(receipt_path.with_suffix('.lock')):
        receipt = load_receipt(receipt_path, frozen)
        used = {(attempt['case_id'], attempt['arm']) for attempt in receipt['attempts']}
        pending = [item for item in frozen['plan'] if (item['case_id'], item['arm']) not in used]
        if not allow_paid:
            return {'mode': 'dry_run', 'attempted': len(used), 'pending': len(pending),
                    'max_attempts': MAX_ATTEMPTS, 'model': frozen['model'],
                    'request_bytes': {item['case_id']+'/'+item['arm']: item['request_bytes']
                                      for item in pending},
                    'state_chars': {item['case_id']+'/'+item['arm']: item['state_chars']
                                    for item in pending}}
        key = os.environ.get('TYPESAFE_API_KEY') or os.environ.get('JEV_API_KEY')
        if not key:
            raise RuntimeError('Existing Jev environment key is not configured')
        import time
        for item in pending:
            if len(receipt['attempts']) >= MAX_ATTEMPTS:
                raise RuntimeError('QA19 attempt budget exhausted')
            attempt = {field: item[field] for field in
                       ('case_id','arm','model','request_sha256','canonical_request_sha256','request_bytes')}
            attempt.update(status='reserved', reserved_at=receipt_io.timestamp(),
                           packet_claim_ids=item['packet_claim_ids'],
                           entry_sense_claim_ids=item['entry_sense_claim_ids'],
                           state_chars=item['state_chars'],
                           local_gateway_cache_bypassed=True)
            receipt['attempts'].append(attempt)
            receipt_io.atomic_receipt(receipt_path, receipt)  # Durable before HTTP.
            started = time.monotonic()
            try:
                answer = receipt_io.safe_answer(transport(item, key), item)
                validation = production_validation(resolved_modules[item['arm']], item, answer['choice'])
            except Exception as exc:
                from urllib.error import HTTPError
                attempt.update(status='failed', completed_at=receipt_io.timestamp(),
                    elapsed_ms=round((time.monotonic()-started)*1000,3),
                    error_kind='http_error' if isinstance(exc, HTTPError) else 'provider_or_validation_error')
                if isinstance(exc, HTTPError):
                    attempt['http_status'] = exc.code
                receipt_io.atomic_receipt(receipt_path, receipt)
                return {'mode':'stopped_on_failure','attempted':len(receipt['attempts']),
                        'pending':len(frozen['plan'])-len(receipt['attempts'])}
            attempt.update(status='completed', completed_at=receipt_io.timestamp(),
                           elapsed_ms=round((time.monotonic()-started)*1000,3),
                           result=answer, production_validation=validation)
            receipt_io.atomic_receipt(receipt_path, receipt)
        return {'mode':'complete','attempted':len(receipt['attempts']),
                'completed':sum(row['status']=='completed' for row in receipt['attempts']),
                'failed_or_indeterminate':sum(row['status']!='completed' for row in receipt['attempts'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packets', type=Path, required=True)
    parser.add_argument('--rubric', type=Path, required=True)
    parser.add_argument('--allow-paid', action='store_true')
    args = parser.parse_args()
    try:
        summary = run(args.packets, args.rubric, allow_paid=args.allow_paid)
    except Exception:
        print('QA19 evaluation stopped: frozen validation or I/O failure; no automatic retry.')
        raise SystemExit(2) from None
    print(json.dumps(summary))
    if summary['mode']=='stopped_on_failure':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
