"""Release C: narrow audited code overlays, unchanged B image/data/config.

Preparation only until an independent receipt and explicit release authorization.
Imports the frozen B guard implementation without altering its historical files.
"""
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location('_lexical_b_for_c', Path(__file__).with_name('lexical_release.py'))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)
BASE = guard.BASE
BASE_CONTAINER = 'ec2cdc5176ed0f747cb03de0037d7bfb1bc00e93644fae7fbf761822e6eb6aa5'
RELEASE = guard.ROOT / 'releases/lexical-20261007c'
CANARY = 'melos-api-lexical-canary-c'
OLD = 'melos-api-before-lexical-20261007c'
MODULES = frozenset(('lexicon_senses.py', 'interlinear.py', 'passage_analysis.py', 'server.py', 'lexical_variants.py'))
NEW_MODULES = frozenset(('lexical_variants.py',))
PRESERVED_MODULES = frozenset(('classifier.py', 'sense_ranker.py'))
BASELINE_MODULES = MODULES | PRESERVED_MODULES | frozenset(('morphology.py', 'lexicon_render.py', 'textutils.py', 'wiktionary.py', 'candidate_senses.py', 'evidence.py'))
B_RELEASE = guard.ROOT / 'releases/lexical-20261007b'
require, capture, inspect, sha, release = guard.require, guard.capture, guard.inspect, guard.sha, guard.release
_b_mounts = guard.base_mounts
_b_validate = guard.validate_candidate


def base_mounts():
    original = [row for row in _b_mounts() if not row[0].startswith('/app/backend/')]
    return sorted(original + [('/app/backend/' + name, str(B_RELEASE / 'candidate-code' / name), False, 'bind')
                              for name in ('classifier.py', 'interlinear.py', 'lexicon_senses.py', 'passage_analysis.py', 'sense_ranker.py')])


def named_hashes(container, names, allow_absent=False):
    result = {}
    for name in sorted(names):
        path = '/app/backend/' + name
        if name in NEW_MODULES and allow_absent:
            result[name] = None if capture('docker', 'exec', container, 'sh', '-c',
                                          'if test -e ' + path + '; then echo present; else echo absent; fi').strip() == 'absent' else 'UNEXPECTED_PRESENT'
        else:
            result[name] = capture('docker', 'exec', container, 'sha256sum', path).split()[0]
    return result


def module_hashes(container):
    return named_hashes(container, MODULES)


def snapshot():
    # B snapshot verifies image, exact mounts, data hashes/stat and private routes.
    previous = guard.module_hashes
    guard.module_hashes = lambda container: named_hashes(container, BASELINE_MODULES, allow_absent=True)
    try:
        guard.snapshot()
    finally:
        guard.module_hashes = previous
    before = release.load('snapshot.json')
    require(all(before['module_sha256'][name] is None for name in NEW_MODULES), 'New module already exists in baseline')


def approved_modules():
    receipt, before = release.load('modules-pass.json'), release.load('snapshot.json')
    require(receipt.get('verdict') == 'PASS' and receipt.get('base_container_id') == BASE_CONTAINER
            and receipt.get('image') == BASE, 'Independent C approval baseline mismatch')
    files = receipt.get('files', {})
    require(set(files) == MODULES, 'Exactly the scoped C modules required')
    for name, row in files.items():
        require(row.get('verdict') == 'PASS' and 'baseline_sha256' in row
                and row['baseline_sha256'] == before['module_sha256'][name], 'Module baseline approval differs: ' + name)
        if name in NEW_MODULES:
            require(row.get('baseline_absent') is True and row['baseline_sha256'] is None, 'New module absence must be audited')
        if name == 'server.py':
            require(row.get('scoped_live_baseline_patch') is True, 'Server must be an audited scoped live-baseline patch')
        require(sha(RELEASE / 'candidate-code' / name) == row.get('sha256'), 'Frozen module changed: ' + name)
    return files


def validate_candidate(container, old, image, port):
    _b_validate(container, old, image, port)
    before = release.load('snapshot.json')['module_sha256']
    preserved = BASELINE_MODULES - MODULES
    require(named_hashes(container['Id'], preserved) == {name: before[name] for name in preserved},
            'Unchanged module dependencies differ')


for _name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'base_mounts', 'module_hashes', 'approved_modules', 'validate_candidate'):
    setattr(guard, _name, globals()[_name])
expected_binds = guard.expected_binds


if __name__ == '__main__':
    guard.signal.signal(guard.signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    # Preserve guard.snapshot separately: main resolves this adapter's snapshot.
    original_snapshot = guard.snapshot
    def _snapshot_adapter():
        guard.snapshot = original_snapshot
        try:
            snapshot()
        finally:
            guard.snapshot = _snapshot_adapter
    guard.snapshot = _snapshot_adapter
    guard.main()
