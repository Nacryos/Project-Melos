"""Scoped G code overlays on exact F, with separate audit/canary/promotion gates."""
import importlib.util
from copy import deepcopy
import json
from pathlib import Path


def _load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load('lexical_release_c.py', '_lexical_c_for_g')
previous = _load('lexical_release_f.py', '_lexical_f_base_for_g')
BASE = core.BASE
BASE_CONTAINER = 'e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007g'
CANARY = 'melos-api-lexical-canary-g'
OLD = 'melos-api-before-lexical-20261007g'
NEW_MODULES = frozenset(('noun_entry_features.py', 'editorial_readings.py', 'editorial_analysis.py'))
MODULES = NEW_MODULES | frozenset(('linked_dictionary.py', 'sense_ranker.py', 'machine_morphology.py',
                                  'classifier.py', 'server.py', 'passage_analysis.py', 'interlinear.py'))
BASELINE_MODULES = previous.BASELINE_MODULES | MODULES
PRIVATE_RUNTIME = RELEASE / 'canary-runtime'
_original_start = core.guard.start


def private_baseline(old):
    """Only a canary creation/validation view, never a mutated saved baseline."""
    receipt = json.loads((RELEASE / 'private-runtime-pass.json').read_text())
    core.require(receipt.get('verdict') == 'PASS' and receipt.get('base_container_id') == BASE_CONTAINER
                 and receipt.get('path') == str(PRIVATE_RUNTIME)
                 and receipt.get('backup_method') == 'sqlite_backup_api'
                 and set(receipt.get('databases', {})) == {'classifier.sqlite', 'machine_morphology.sqlite'},
                 'Audited private runtime snapshot required')
    clone = deepcopy(old)
    rows = clone['HostConfig']['Binds']
    matches = [i for i, row in enumerate(rows) if row.rsplit(':', 2)[1] == '/app/runtime']
    core.require(len(matches) == 1, 'One runtime bind required')
    index = matches[0]
    source, destination, mode = rows[index].rsplit(':', 2)
    core.require(source in (str(core.guard.ROOT / 'runtime'), str(PRIVATE_RUNTIME)) and mode == 'rw',
                 'Unexpected runtime bind')
    rows[index] = f'{PRIVATE_RUNTIME}:{destination}:rw'
    return clone


def start(image, name, port, old):
    core.require((name, port) in ((CANARY, 8792), ('melos-api', 8791)), 'Invalid G target')
    if port == 8792:
        # Only at first creation: subsequent controlled private imports and
        # request caches legitimately change these SQLite files.
        receipt = json.loads((RELEASE / 'private-runtime-pass.json').read_text())
        for filename in ('classifier.sqlite', 'machine_morphology.sqlite'):
            path = PRIVATE_RUNTIME / filename
            core.require(core.sha(path) == receipt['databases'][filename]['backup_sha256'],
                         'Approved initial private DB bytes changed')
            core.require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
                         'Unexpected pre-start private DB sidecar')
    return _original_start(image, name, port, private_baseline(old) if port == 8792 else old)


def validate_candidate(container, old, image, port):
    core.require(port in (8791, 8792), 'Invalid G port')
    core.validate_candidate(container, private_baseline(old) if port == 8792 else old, image, port)


def base_mounts():
    replaced = {'/app/backend/' + name for name in previous.MODULES}
    rows = [row for row in previous.base_mounts() if row[0] not in replaced]
    rows += [('/app/backend/' + name, str(previous.RELEASE / 'candidate-code' / name), False, 'bind')
             for name in sorted(previous.MODULES)]
    return sorted(rows)


for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'NEW_MODULES', 'BASELINE_MODULES'):
    setattr(core, name, globals()[name])
for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'base_mounts', 'start', 'validate_candidate'):
    setattr(core.guard, name, globals()[name])
core.base_mounts = base_mounts
expected_binds = core.expected_binds


if __name__ == '__main__':
    core.guard.signal.signal(core.guard.signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    original_snapshot = core.guard.snapshot
    def _snapshot_adapter():
        core.guard.snapshot = original_snapshot
        try:
            core.snapshot()
        finally:
            core.guard.snapshot = _snapshot_adapter
    core.guard.snapshot = _snapshot_adapter
    core.guard.main()
