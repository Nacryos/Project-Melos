"""Freeze a two-arm commentary-instruction ablation; preparation is offline.

No corpus writes or generated definitions. The only difference between arms
is one constraint string. Execution requires the exact approved manifest hash,
has an atomic lifetime maximum of twelve provider attempts, and never retries.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ORIGINAL = ('Campbell notes interpret the whole poem, not this word/line or a translation, parse, or dictionary sense. '
            'Printed lemma and carried line groups do not prove occurrence alignment; preserve alternatives and abstain.')
REVISED = ('Use these notes as fallible whole-poem context. Do not assert exact occurrence alignment from their placement. '
           'Choose a supplied sense when the combined evidence supports it; otherwise abstain.')


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def ablated(packet):
    changed = deepcopy(packet)
    if changed['constraints'].count(ORIGINAL) != 1:
        raise ValueError('Expected exactly one frozen commentary instruction.')
    changed['constraints'][changed['constraints'].index(ORIGINAL)] = REVISED
    return changed


def prepare(args):
    from backend.interlinear import interlinear_reading
    from backend.linked_dictionary import lookup_linked_dictionary
    from backend.sense_ranker import sense_packet
    if not 1 <= len(args.responses) <= 6 or len(set(args.responses)) != len(args.responses):
        raise ValueError('Provide one to six distinct source responses.')
    passages = {r['id']: r for r in (json.loads(line) for line in args.records.read_text(encoding='utf-8').splitlines() if line.strip())}
    cases, packets, occurrences = [], [], set()
    for number, path in enumerate(args.responses):
        raw = path.read_bytes()
        result = json.loads(raw)
        words = [t for t in result['tokens'] if t.get('kind') == 'word']
        if len(words) != 1:
            raise ValueError('Use saved single-word occurrence responses.')
        word = words[0]
        occurrence = (result['passage']['id'], word['start'], word['end'])
        if occurrence in occurrences:
            raise ValueError('Duplicate occurrence.')
        occurrences.add(occurrence)
        # Rebuild source-only dictionaries, but never inspect previous sense
        # model results to choose cases or assign an expected winning sense.
        word['linked_dictionary'] = lookup_linked_dictionary(word['text'])
        result['sense_ranking'] = {'status': 'not_requested'}
        result['interlinear'] = interlinear_reading(result)
        projected = next(t for t in result['interlinear']['readings'][0]['tokens'] if t.get('kind') == 'word')
        try:
            packet = sense_packet(passages[occurrence[0]], result, projected)
        except ValueError as exc:
            raise ValueError(f'Case {number} {word["text"]}: {exc}') from None
        if len(packet['candidates']) < 2:
            raise ValueError('Ablation requires at least two source sense choices.')
        alternative = ablated(packet)
        files = []
        for arm, value in [('baseline', packet), ('commentary_only', alternative)]:
            payload = encoded(value)
            name = f'{number}-{arm}.packet.json'
            packets.append((name, payload))
            files.append({'arm': arm, 'file': name, 'sha256': digest_bytes(payload), 'characters': len(payload.decode('utf-8'))})
        cases.append({'case': number, 'passage_id': occurrence[0], 'start': occurrence[1], 'end': occurrence[2],
                      'form': word['text'], 'source_response': str(path.resolve()), 'source_response_sha256': digest_bytes(raw),
                      'choices': len(packet['candidates']), 'inventory_sha256': packet['inventory_sha256'], 'arms': files})
    manifest = {'version': 'commentary-constraint-ablation-v1', 'cases': cases, 'maximum_provider_calls': len(cases) * 2,
                'lifetime_hard_cap': 12, 'selection_policy': 'Explicit source occurrence list frozen before new experiment results; not a blind or random sample.',
                'known_index_case': 'Previously observed Alcaeus 350 παχέων is a diagnostic regression, not a held-out accuracy case.',
                'sole_change': {'from': ORIGINAL, 'to': REVISED}, 'thresholds_unchanged': {'score': .75, 'margin': .20},
                'records_sha256': digest_bytes(args.records.read_bytes()),
                'provider_code_sha256': digest_bytes((ROOT / 'backend/classifier.py').read_bytes()),
                'gateway_code_sha256': digest_bytes((ROOT / 'backend/jev_gateway.py').read_bytes()),
                'approved_output_directory': str(args.output.resolve()),
                'model': args.model,
                'script_sha256': digest_bytes(Path(__file__).read_bytes()), 'gold_labels': None,
                'promotion_rule': 'No automatic promotion; independently assess wrong decisive choices and justified abstentions, not score increases.'}
    args.output.mkdir(parents=True, exist_ok=False)
    for name, payload in packets:
        (args.output / name).write_bytes(payload)
    payload = encoded(manifest)
    (args.output / 'manifest.json').write_bytes(payload)
    print(json.dumps({'manifest_sha256': digest_bytes(payload), 'maximum_provider_calls': len(cases) * 2,
                      'cases': [{k: r[k] for k in ('case', 'form', 'passage_id', 'choices')} for r in cases]}, ensure_ascii=False))


def run(args):
    from backend.classifier import JevProvider
    from backend.jev_gateway import CachedJevProvider
    manifest_path = args.output / 'manifest.json'
    raw = manifest_path.read_bytes()
    if not args.approved_manifest_sha256 or digest_bytes(raw) != args.approved_manifest_sha256:
        raise ValueError('Exact reviewed manifest SHA256 required before any provider call.')
    manifest = json.loads(raw)
    if manifest.get('approved_output_directory') != str(args.output.resolve()):
        raise ValueError('Experiment directory differs from reviewed manifest; copied manifests cannot reset budgets.')
    if (manifest['provider_code_sha256'] != digest_bytes((ROOT / 'backend/classifier.py').read_bytes())
            or manifest['gateway_code_sha256'] != digest_bytes((ROOT / 'backend/jev_gateway.py').read_bytes())
            or manifest['script_sha256'] != digest_bytes(Path(__file__).read_bytes())):
        raise ValueError('Frozen provider or experiment code changed; stop for review.')
    cases = manifest['cases']
    if not 1 <= len(cases) <= 6 or manifest['maximum_provider_calls'] != 2 * len(cases):
        raise ValueError('Invalid experiment bound.')
    pending = []
    for case in cases:
        arms = {}
        for row in case['arms']:
            payload = (args.output / row['file']).read_bytes()
            if digest_bytes(payload) != row['sha256']:
                raise ValueError('Frozen packet changed.')
            arms[row['arm']] = json.loads(payload)
        if set(arms) != {'baseline', 'commentary_only'} or arms['commentary_only'] != ablated(arms['baseline']):
            raise ValueError('Arms differ beyond the approved commentary instruction.')
        for arm in ('baseline', 'commentary_only') if case['case'] % 2 == 0 else ('commentary_only', 'baseline'):
            pending.append((case['case'], arm, arms[arm]))
    if args.model != manifest['model']:
        raise ValueError('Model differs from reviewed manifest.')
    provider = CachedJevProvider(JevProvider(model=manifest['model'], timeout=30),
        digest_bytes(b'melos-commentary-prompt-ablation'), state_path=args.output / 'gateway.sqlite')
    with sqlite3.connect(args.output / 'attempts.sqlite', isolation_level=None) as ledger:
        ledger.execute('CREATE TABLE IF NOT EXISTS attempts (case_id INTEGER, arm TEXT, manifest TEXT, status TEXT, PRIMARY KEY(case_id,arm))')
        if ledger.execute('SELECT count(*) FROM attempts').fetchone()[0]:
            raise ValueError('Experiment already attempted; no implicit retry or resume.')
        for case, arm, packet in pending:
            ledger.execute('BEGIN IMMEDIATE')
            if ledger.execute('SELECT count(*) FROM attempts').fetchone()[0] >= min(12, manifest['maximum_provider_calls']):
                ledger.rollback()
                raise ValueError('Lifetime experiment call cap reached.')
            ledger.execute('INSERT INTO attempts VALUES (?,?,?,?)', (case, arm, args.approved_manifest_sha256, 'reserved'))
            ledger.commit()
            started = time.monotonic()
            try:
                answer = provider.decide(packet)
            except Exception as exc:
                ledger.execute('UPDATE attempts SET status=? WHERE case_id=? AND arm=?', ('failed_or_indeterminate', case, arm))
                raise SystemExit(f'Experiment stopped after {type(exc).__name__}; reserved attempt remains counted. No retry.') from None
            (args.output / f'{case}-{arm}.answer.json').write_bytes(encoded(answer))
            ledger.execute('UPDATE attempts SET status=? WHERE case_id=? AND arm=?', ('completed', case, arm))
            print(json.dumps({'case': case, 'arm': arm, 'seconds': round(time.monotonic() - started, 2), 'cache_hit': bool(answer.get('cache_hit'))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--records', type=Path, default=ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl')
    parser.add_argument('--responses', type=Path, nargs='*')
    parser.add_argument('--approved-manifest-sha256')
    parser.add_argument('--model', default='jev-1.13.0')
    args = parser.parse_args()
    if args.mode == 'prepare':
        if not args.responses:
            parser.error('Preparation requires saved source responses.')
        prepare(args)
    else:
        run(args)


if __name__ == '__main__':
    main()
