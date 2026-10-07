"""Execute only the exact reviewed two-packet relevance diagnostic, once.

Requires separate exact manifest AND runner hash approvals. No retry/resume,
new preparation, threshold edits or source writes. A fixed lifetime ledger is
reserved before any provider attempt, including failed/indeterminate attempts.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_commentary_relevance import captured_request, encoded, sha, exact_delta

OUTPUT = ROOT / 'runtime/lexical-relevance-comparison-03'
LEDGER = ROOT / 'runtime/lexical-relevance-comparison-lifetime.sqlite'
MANIFEST_SHA256 = '7049457b7dbc1d638a53fc7a757f9ecf5d80aa3a03dc033fa412aadd4452add0'


def verified_inputs(approved_manifest, approved_runner):
    if approved_manifest != MANIFEST_SHA256:
        raise ValueError('Exact reviewed manifest approval required.')
    if approved_runner != sha(Path(__file__).read_bytes()):
        raise ValueError('Exact reviewed runner approval required.')
    raw = (OUTPUT / 'manifest.json').read_bytes()
    if sha(raw) != MANIFEST_SHA256:
        raise ValueError('Frozen manifest changed.')
    manifest = json.loads(raw)
    if (manifest['approved_output_directory'] != str(OUTPUT.resolve())
            or manifest['model'] != 'jev-1.13.0'
            or manifest['baseline_arm'] != 'commentary_only'
            or manifest['maximum_new_provider_calls'] != 2
            or manifest['maximum_attempts_per_case'] != 1
            or manifest['retries_permitted'] is not False
            or manifest['thresholds_unchanged'] != {'score': .75, 'margin': .20}
            or [r['case'] for r in manifest['cases']] != [0, 2]):
        raise ValueError('Frozen scope/bound changed.')
    for path, digest in manifest['dependencies'].items():
        if sha((ROOT / path).read_bytes()) != digest:
            raise ValueError('Reviewed dependency changed; stop for review.')
    pending = []
    for row in manifest['cases']:
        raw = (OUTPUT / row['packet_file']).read_bytes()
        request = (OUTPUT / row['request_file']).read_bytes()
        original = Path(row['original_packet_file']).read_bytes()
        if (sha(raw) != row['packet_sha256'] or sha(request) != row['request_sha256']
                or sha(original) != row['original_packet_sha256']
                or sha(Path(row['original_answer_file']).read_bytes()) != row['original_answer_sha256']):
            raise ValueError('Frozen comparison artifact changed.')
        packet = json.loads(raw)
        exact_delta(json.loads(original), packet)
        if captured_request(packet, manifest['model']) != request:
            raise ValueError('Provider request differs from the reviewed request bytes.')
        if (OUTPUT / f"{row['case']}-relevance.answer.json").exists():
            raise ValueError('Saved answer already exists; no repeat.')
        pending.append((row['case'], packet))
    return manifest, pending


def secure_api_key():
    value = os.environ.get('TYPESAFE_API_KEY') or os.environ.get('JEV_API_KEY')
    if value:
        return value
    from dotenv import dotenv_values
    for filename in ('.env', '.env.local'):
        path = ROOT / filename
        if path.is_file():
            values = dotenv_values(path)
            value = values.get('TYPESAFE_API_KEY') or values.get('JEV_API_KEY')
            if value:
                return value
    raise ValueError('Configured Jev credential is unavailable; no provider attempt.')


def execute_reserved(provider, pending, *, ledger_path, output, manifest_sha256):
    """Single lifetime batch. Any exception stops, never retries or resumes."""
    if [case for case, _ in pending] != [0, 2]:
        raise ValueError('Expected exactly the two reviewed cases.')
    with sqlite3.connect(ledger_path, isolation_level=None) as ledger:
        ledger.execute('CREATE TABLE IF NOT EXISTS attempts (case_id INTEGER PRIMARY KEY, manifest TEXT, status TEXT)')
        ledger.execute('BEGIN IMMEDIATE')
        if ledger.execute('SELECT count(*) FROM attempts').fetchone()[0]:
            ledger.rollback()
            raise ValueError('Lifetime batch already reserved; no retry, resume or budget reset.')
        ledger.executemany('INSERT INTO attempts VALUES (?,?,?)',
                           [(case, manifest_sha256, 'reserved') for case, _ in pending])
        ledger.commit()
        for case, packet in pending:
            started = time.monotonic()
            try:
                answer = provider.decide(packet)
                with (output / f'{case}-relevance.answer.json').open('xb') as file:
                    file.write(encoded(answer))
            except Exception:
                ledger.execute('UPDATE attempts SET status=? WHERE case_id=?', ('failed_or_indeterminate', case))
                raise RuntimeError('Experiment stopped; attempt remains counted and unused reservations stay blocked. No retry.') from None
            ledger.execute('UPDATE attempts SET status=? WHERE case_id=?', ('completed', case))
            print(json.dumps({'case': case, 'seconds': round(time.monotonic() - started, 2),
                              'cache_hit': bool(answer.get('cache_hit'))}))


def run(approved_manifest, approved_runner):
    manifest, pending = verified_inputs(approved_manifest, approved_runner)
    from backend.classifier import JevProvider
    from backend.jev_gateway import CachedJevProvider
    provider = CachedJevProvider(JevProvider(secure_api_key(), model=manifest['model'], timeout=30),
        sha(b'melos-commentary-relevance-comparison-lifetime'), state_path=OUTPUT / 'gateway.sqlite')
    execute_reserved(provider, pending, ledger_path=LEDGER, output=OUTPUT, manifest_sha256=approved_manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-manifest-sha256', required=True)
    parser.add_argument('--approved-runner-sha256', required=True)
    args = parser.parse_args()
    run(args.approved_manifest_sha256, args.approved_runner_sha256)
