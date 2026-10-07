"""Offline preparation of two frozen commentary-relevance comparison packets.

This script has no live provider execution mode. The mocked provider captures
request serialization only. Existing results are diagnostic baselines, not
held-out gold labels; two new requests require separate approval/execution.
"""
import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'runtime/lexical-release-g/commentary-ablation-02'
RECORDS = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
BASE_MANIFEST_SHA256 = '10c0118500840e9234ae5aa029e2e02ddee23765811d9297d26e0d84961dc718'
CASES = (0, 2)
BASELINE_ARM = 'commentary_only'
PREVIEW_FIELDS = ('presentation_role', 'selection_is_source_adjudication', 'constrains_sense_candidates')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def exact_delta(original, revised):
    """Reject any incidental inventory, prompt or source change."""
    restored = deepcopy(revised)
    cues = restored.pop('commentary_retrieval_cues')
    if cues.get('status') != 'available':
        raise ValueError('Unavailable source cues cannot enter the comparison.')
    if restored['constraints'][:-2] != original['constraints']:
        raise ValueError('Existing constraints changed.')
    added_constraints = restored['constraints'][-2:]
    restored['constraints'] = restored['constraints'][:-2]
    preview = restored.get('selected_morphology')
    if preview is not None:
        for key in PREVIEW_FIELDS:
            del preview[key]
    if encoded(restored) != encoded(original):
        raise ValueError('Comparison differs beyond the bounded relevance intervention.')
    if encoded(original['candidates']) != encoded(revised['candidates']):
        raise ValueError('Source choices changed.')
    return {'only_added_fields': ['commentary_retrieval_cues'] +
            (['selected_morphology.' + key for key in PREVIEW_FIELDS] if preview is not None else []),
            'only_appended_constraints': added_constraints,
            'reversible_exact_packet_equality': True,
            'source_candidates_byte_equal': True,
            'candidate_inventory_sha256': sha(encoded(original['candidates']))}


def captured_request(packet, model):
    """No network: intercept the fully serialized provider request body."""
    from backend.classifier import JevProvider
    captured = []

    def intercept(request, **kwargs):
        captured.append(request.data)
        return io.StringIO(json.dumps({'answers': {'contextual_parse': {
            'type': 'choice', 'choice': 'abstain', 'probabilities': {}}}}))

    with patch('backend.classifier.urlopen', side_effect=intercept):
        JevProvider(api_key='offline-serialization-only', model=model).decide(packet)
    if len(captured) != 1:
        raise ValueError('Expected exactly one offline request serialization.')
    return captured[0]


def prepare(output):
    from backend.edition_commentary import for_passage, DATA_PATH, DATA_SHA256
    from backend.sense_ranker import add_context_relevance, _request_size_proxy
    baseline_bytes = (BASE / 'manifest.json').read_bytes()
    if sha(baseline_bytes) != BASE_MANIFEST_SHA256:
        raise ValueError('Original experiment manifest changed.')
    baseline = json.loads(baseline_bytes)
    if sha(RECORDS.read_bytes()) != baseline['records_sha256']:
        raise ValueError('Original passage records changed.')
    if sha(DATA_PATH.read_bytes()) != DATA_SHA256:
        raise ValueError('Approved commentary changed.')
    passages = {r['id']: r for r in map(json.loads, RECORDS.read_text(encoding='utf-8').splitlines())}
    rows, files = [], []
    for number in CASES:
        source_case = next(r for r in baseline['cases'] if r['case'] == number)
        source_arm = next(r for r in source_case['arms'] if r['arm'] == BASELINE_ARM)
        original_bytes = (BASE / source_arm['file']).read_bytes()
        if sha(original_bytes) != source_arm['sha256']:
            raise ValueError('Frozen baseline packet changed.')
        original = json.loads(original_bytes)
        revised = deepcopy(original)
        passage = passages[source_case['passage_id']]
        target = {key: source_case[key] for key in ('start', 'end')}
        target['text'] = source_case['form']
        add_context_relevance(revised, passage, target, commentary=for_passage(passage, for_model=True))
        delta = exact_delta(original, revised)
        # Capture the same dictionary ordering a later exact-file execution
        # will reload, so even serialized request bytes are reproducible.
        revised = json.loads(encoded(revised))
        original_request = captured_request(original, baseline['model'])
        revised_request = captured_request(revised, baseline['model'])
        old_body, new_body = json.loads(original_request), json.loads(revised_request)
        old_body.pop('state')
        new_body.pop('state')
        if old_body != new_body:
            raise ValueError('Provider question/model changed between packets.')
        payload = encoded(revised)
        filename = f'{number}-relevance.packet.json'
        request_filename = f'{number}-relevance.request.json'
        files.extend([(filename, payload), (request_filename, revised_request)])
        answer_path = BASE / f'{number}-{BASELINE_ARM}.answer.json'
        if not answer_path.is_file():
            raise ValueError('Original completed baseline result missing.')
        state_chars, request_proxy, total_proxy = _request_size_proxy(revised)
        # This offline comparator is NOT Jev's tokenizer or billing estimate.
        import tiktoken
        proxy_tokens = len(tiktoken.get_encoding('cl100k_base').encode(revised_request.decode('utf-8')))
        rows.append({'case': number, 'form': source_case['form'], 'passage_id': passage['id'],
                     'start': target['start'], 'end': target['end'],
                     'packet_file': filename, 'packet_sha256': sha(payload),
                     'request_file': request_filename, 'request_sha256': sha(revised_request),
                     'original_packet_file': str((BASE / source_arm['file']).resolve()),
                     'original_packet_sha256': sha(original_bytes),
                     'original_answer_file': str(answer_path.resolve()),
                     'original_answer_sha256': sha(answer_path.read_bytes()),
                     'source_inventory_sha256': original['inventory_sha256'],
                     'candidate_ids': [r['id'] for r in original['candidates']],
                     'choices': len(original['candidates']),
                     'state_characters': state_chars,
                     'request_characters': len(revised_request.decode('utf-8')),
                     'request_utf8_bytes': len(revised_request),
                     'request_character_upper_proxy': request_proxy,
                     'request_total_character_upper_proxy': total_proxy,
                     'token_usage': None, 'cl100k_base_token_proxy': proxy_tokens,
                     'token_proxy_scope': 'Offline comparator only; not Jev tokenizer, usage or billing estimate.',
                     'diff': delta})
    dependencies = ['backend/commentary_retrieval.py', 'backend/edition_commentary.py',
                    'backend/sense_ranker.py', 'backend/classifier.py', 'backend/jev_gateway.py',
                    'scripts/prepare_commentary_relevance.py']
    manifest = {'version': 'frozen-commentary-relevance-comparison-v1',
                'approved_output_directory': str(output.resolve()), 'cases': rows,
                'baseline_manifest_sha256': BASE_MANIFEST_SHA256, 'model': baseline['model'],
                'baseline_arm': BASELINE_ARM,
                'maximum_new_provider_calls': 2, 'maximum_attempts_per_case': 1,
                'retries_permitted': False, 'execution_authorized': False,
                'thresholds_unchanged': baseline['thresholds_unchanged'],
                'source_records_sha256': sha(RECORDS.read_bytes()), 'commentary_sha256': DATA_SHA256,
                'dependencies': {path: sha((ROOT / path).read_bytes()) for path in dependencies},
                'selection_policy': 'Two previously observed diagnostic failures, not random or held-out; source inventories frozen before this comparison.',
                'intervention': 'Combined literal commentary retrieval cues and explicit heuristic-preview demotion only; effects cannot be attributed separately.',
                'baseline_instruction_retained': True,
                'evaluation': 'Assess source-supported reading, wrong decisive choices, alternatives and abstention; score increase alone is not accuracy.',
                'no_new_gold_labels': True}
    output.mkdir(parents=True, exist_ok=False)
    for filename, payload in files:
        (output / filename).write_bytes(payload)
    manifest_bytes = encoded(manifest)
    (output / 'manifest.json').write_bytes(manifest_bytes)
    print(json.dumps({'manifest_sha256': sha(manifest_bytes), 'maximum_new_provider_calls': 2,
                      'prepared_only': True, 'cases': [{k: r[k] for k in (
                          'case', 'form', 'choices', 'packet_sha256', 'state_characters', 'request_characters',
                          'request_utf8_bytes', 'request_character_upper_proxy')} for r in rows]}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
