"""Prepare source-derived, offline old/new prompt packets; never call Jev.

Case selectors and proposed review judgments are experiment configuration,
not corpus claims. All Greek, analyses and quotations come from local indexes.
The resulting staged artifact requires independent case/gold review before use.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import classifier, server


# IDs only select existing sources; no source text is authored here.
CASES = (
    ('dictionary_context', 'wiktionary:kaikki:line:67966:form_of:0',
     'p2_ibycus:edmonds-1924:p86:fr2:l2', 'propose',
     'A general source-backed dative-plural reading can be a contextual proposal without a direct passage annotation.'),
    ('explicit_infinitive', 'p2-notes:9307e7197a7b136f5fda49f3', None, 'propose',
     'The source explicitly labels a present active infinitive; retain unspecified lemma/features as unknown.'),
    ('context_disambiguation', 'p2-notes:c6188fbd168b08d58fc95285', None, 'propose',
     'The passage note specifies accusative plural neuter; general nominative/other-lemma possibilities do not erase its scoped evidence.'),
    ('partial_analysis', 'p2-notes:d56a2eb040b1ca8090cc1bcb', None, 'partial_or_abstain',
     'The shared present-active-participle analysis may be proposed, but the source explicitly leaves accusative singular versus genitive plural unresolved.'),
    ('explicit_mood_alternatives', 'p2-notes:876033cb60412eca832a1d85', None, 'abstain',
     'The source gives infinitive OR middle imperative in damaged context; the extracted single infinitive candidate omits that alternative.'),
    ('daggered_reading', 'p2-notes:c685814e0bbac2bbec069c2c', None, 'abstain',
     'The source says its adjective interpretation makes little sense and discusses another reading; do not certify the flattened sole parse.'),
    ('unresolved_word_division', 'p2-notes:0f79052ad468d189f28a67c4', None, 'abstain',
     'The source explicitly says word breaks are unclear and offers competing parses of a possible subword; the whole damaged token lacks a resolved parse.'),
)

# QA21 selectors refer only to independently admitted, existing source rows.
# No Greek, parse, or source quotation is authored by this configuration.
SCOPE_CONTROLS = (
    ('isolated-adjective-control', 'digital-sappho:fr169-192:8', '175'),
    ('isolated-noun-control', 'digital-sappho:fr169-192:18', '189'),
)
SCOPE_ADDITION = (
    'Choose a provisional contextual grammatical hypothesis, not a certification of source-attested parsing. '
    'Lack of an explicit passage annotation alone does not require abstention when the supplied Greek context '
    'supports an existing candidate.'
)
SCOPE_CONTROL_RAW = 'data/raw/sappho/digitalsappho.org__fragments__fr169-192.html'
SCOPE_CONTROL_RAW_SHA = '3cd31dec5798c3418e42648f7649ca68e723fa59645cc37f7c72a23c63f6d80b'


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def source_state(packet):
    """Only task instructions may differ; all other model inputs must match."""
    return {key: value for key, value in packet.items() if key != 'constraints'}


def old_module(revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:backend/classifier.py'], cwd=ROOT).decode('utf-8')
    module = types.ModuleType('backend._offline_old_classifier')
    module.__package__ = 'backend'
    exec(compile(source, f'{revision}:backend/classifier.py', 'exec'), module.__dict__)
    return module, hashlib.sha256(source.encode('utf-8')).hexdigest()


def request_body(module, packet, model):
    captured = []

    def capture(request, timeout):
        captured.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'model': model, 'answers': {
            'contextual_parse': {'type': 'choice', 'choice': 'abstain'}}}).encode())

    with patch.object(module, 'urlopen', capture):
        module.JevProvider(api_key='offline-fixture-not-a-key', model=model).decide(packet)
    if len(captured) != 1:
        raise RuntimeError('Offline request capture failed')
    return captured[0]


def scope_instruction_pair(body):
    """Change one instruction field only; source state and choices are identical."""
    before = deepcopy(body)
    after = deepcopy(body)
    question = after['questions']['contextual_parse']
    prefix = 'Which supplied candidate best fits this exact Greek passage?'
    original = question.get('instructions')
    if not isinstance(original, str) or not original.startswith(prefix + ' ') or SCOPE_ADDITION in original:
        raise ValueError('Unexpected or already-modified question instructions')
    question['instructions'] = prefix + ' ' + SCOPE_ADDITION + original[len(prefix):]
    check = deepcopy(after)
    check['questions']['contextual_parse']['instructions'] = original
    if check != before:
        raise ValueError('Non-instruction difference in scope ablation')
    return before, after


def prepare_scope_ablation(qa19_path, expected_sha):
    """Reuse three frozen QA19 requests and capture two source-admitted controls.

    The existing QA16 runner can execute this exact five-case plan after a
    separate reviewed rubric and paid authorization. This function is offline.
    """
    raw = qa19_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('QA19 packet hash differs from the admitted source')
    previous = json.loads(raw)
    if (previous.get('model') != classifier.JEV_MODEL or len(previous.get('cases', [])) != 3
            or {row['id'] for row in previous['cases']} != {
                'ibycus-287-adjective', 'ibycus-287-eye-control', 'medea-672-adjective'}):
        raise ValueError('Unexpected frozen positive case set or model')
    if hashlib.sha256((ROOT / SCOPE_CONTROL_RAW).read_bytes()).hexdigest() != SCOPE_CONTROL_RAW_SHA:
        raise ValueError('Audited control source snapshot changed')
    output = []
    for case in previous['cases']:
        before, after = scope_instruction_pair(case['new_request'])
        output.append({'id': case['id'], 'role': 'qa19_frozen_positive',
            'form': case['form'], 'passage_id': case['passage_id'],
            'source_request_sha256': digest(case['new_request']),
            'old_request': before, 'new_request': after})

    class OfflineProvider:
        calls = 0

        def decide(self, packet):
            self.calls += 1
            return {'choice': 'abstain', 'model': 'offline-eligibility-only'}

    def forbidden(*args, **kwargs):
        raise RuntimeError('Network is forbidden during QA21 preparation')

    with patch('backend.jev_gateway.public_enabled', return_value=False), \
            patch.object(classifier, 'urlopen', forbidden):
        for case_id, passage_id, citation in SCOPE_CONTROLS:
            with server.connect() as con:
                row = con.execute('SELECT * FROM passages WHERE id=?', (passage_id,)).fetchone()
                record = server.unpack(row) if row else None
            if (not record or record.get('citation') != citation
                    or record.get('kind') != 'text' or record.get('language') != 'grc'):
                raise ValueError('Admitted control source identity changed')
            form = record['text'].split()[0]
            provider = OfflineProvider()
            with patch.object(classifier, 'configured_provider', return_value=provider):
                result = server.classify_context_request(
                    server.ContextRequest(form=form, passage_id=passage_id), None)
            if provider.calls != 1 or result.get('decision_stage') != 'model_abstained':
                raise ValueError(f'Control is not currently provider-eligible: {case_id}')
            body = request_body(classifier, result['packet'], previous['model'])
            before, after = scope_instruction_pair(body)
            proofs = [server.evidence_service().get_claim(claim['id'])
                      for claim in body['state']['claims']]
            if any(not proof or proof.get('status') != 'source_claim' for proof in proofs):
                raise ValueError('Control contains an unaccepted source claim')
            output.append({'id': case_id, 'role': 'source_admitted_ambiguity_control',
                'form': form, 'passage_id': passage_id, 'admission_source_record': record,
                'admission_source_claims': proofs, 'current_preflight_offline_calls': provider.calls,
                'old_request': before, 'new_request': after})
    if len(output) != 5:
        raise ValueError('QA21 must have exactly five fixed cases and ten arms')
    return {'schema_version': 1, 'artifact_type': 'qa21_instruction_scope_ablation',
        'purpose': 'Offline instruction-only diagnostic; no new corpus facts or model predictions',
        'model': previous['model'], 'paid_calls': 0, 'planned_attempt_limit': 10,
        'review_status': 'pending_independent_packet_and_rubric',
        'source_qa19_packet_sha256': expected_sha,
        'baseline_scope': 'Each old arm is current wording; the three positives reuse QA19 NEW requests exactly.',
        'control_source_raw': SCOPE_CONTROL_RAW, 'control_source_raw_sha256': SCOPE_CONTROL_RAW_SHA,
        'classifier_sha256': hashlib.sha256(Path(classifier.__file__).read_bytes()).hexdigest(),
        'instruction_addition': SCOPE_ADDITION, 'cases': output}


def prepare(revision):
    old, source_sha = old_module(revision)
    model = classifier.JEV_MODEL
    output = []
    original_builder = classifier.build_evidence_packet

    class OfflineProvider:
        called = False

        def decide(self, packet):
            self.called = True
            return {'choice': 'abstain', 'model': 'offline-fixture-no-prediction'}

    def forbidden(*args, **kwargs):
        raise RuntimeError('Network is forbidden while preparing source packets')

    # These captures never reach configured credentials, gateway state or HTTP.
    with patch('backend.jev_gateway.public_enabled', return_value=False), \
            patch.object(classifier, 'urlopen', forbidden):
        for name, claim_id, explicit_passage, expected, rationale in CASES:
            source_claim = server.evidence_service().get_claim(claim_id)
            if not source_claim or source_claim.get('status') != 'source_claim':
                raise RuntimeError(f'Missing accepted source claim: {claim_id}')
            subject = source_claim['subject']
            form = subject['form']
            passage_id = explicit_passage or subject['passage_id']
            captured_inputs = []

            def capture_builder(*args, **kwargs):
                captured_inputs.append((deepcopy(args), deepcopy(kwargs)))
                return original_builder(*args, **kwargs)

            provider = OfflineProvider()
            with patch.object(classifier, 'build_evidence_packet', capture_builder), \
                    patch.object(classifier, 'configured_provider', return_value=provider):
                result = server.classify_context_request(server.ContextRequest(form=form, passage_id=passage_id), None)
            if len(captured_inputs) != 1 or not provider.called:
                raise RuntimeError(f'Case is not model-eligible: {name}: {result.get("reason")}')
            args, kwargs = captured_inputs[0]
            before = old.build_evidence_packet(*args, **kwargs)
            after = result['packet']
            if source_state(before) != source_state(after):
                raise RuntimeError(f'Non-prompt packet difference: {name}')
            old_body, new_body = request_body(old, before, model), request_body(classifier, after, model)
            if old_body['questions']['contextual_parse']['criteria'] != new_body['questions']['contextual_parse']['criteria']:
                raise RuntimeError(f'Choice definitions changed: {name}')
            output.append({'id': name, 'form': form, 'passage_id': passage_id,
                'admission_source_claim': source_claim,
                'source_state_sha256': digest(source_state(after)),
                'old_request': old_body, 'new_request': new_body,
                'expected_review_judgment': {'status': 'proposed_pending_independent_review',
                    'action': expected, 'rationale': rationale,
                    'not_a_corpus_fact': True},
                'predictions': None})
    return {'schema_version': 1, 'purpose': 'Offline fixed prompt-only comparison; not a corpus dataset',
        'source_revision': revision, 'old_classifier_sha256': source_sha,
        'new_classifier_sha256': hashlib.sha256(Path(classifier.__file__).read_bytes()).hexdigest(),
        'model': model, 'paid_calls': 0, 'gold_status': 'pending_independent_review', 'cases': output}


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--baseline', help='Pinned old classifier Git revision')
    mode.add_argument('--scope-ablation-from', type=Path, help='Reuse frozen QA19 NEW requests for QA21')
    parser.add_argument('--source-packets-sha256', help='Independently admitted QA19 artifact SHA256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    artifact = (prepare_scope_ablation(args.scope_ablation_from, args.source_packets_sha256)
                if args.scope_ablation_from else prepare(args.baseline))
    if args.output.exists():
        raise SystemExit('Output already exists; choose a new staged artifact path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cases': len(artifact['cases']), 'paid_calls': 0,
        'path': str(args.output), 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
