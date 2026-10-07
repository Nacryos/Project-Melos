"""J subentry/code overlay over exact I; explicit pinned index and four settings."""
import importlib.util
from copy import deepcopy
from pathlib import Path


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('lexical_release_c.py', '_lexical_c_for_j')
previous = load('lexical_release_i.py', '_lexical_i_base_for_j')
BASE = core.BASE
BASE_CONTAINER = 'f888ab8692593446a2495b3543be2ce7274bfcd672cc0d5f8379083af8f50a19'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007j'
CANARY = 'melos-api-lexical-canary-j'
OLD = 'melos-api-before-lexical-20261007j'
MODULES = frozenset(('server.py', 'passage_routes.py', 'passage_analysis.py', 'interlinear.py',
                     'machine_subentries.py', 'lexicon_subentries.py', 'morphology.py'))
NEW_MODULES = frozenset(('machine_subentries.py', 'lexicon_subentries.py'))
BASELINE_MODULES = previous.BASELINE_MODULES | MODULES


def base_mounts():
    replaced = {'/app/backend/' + name for name in previous.MODULES}
    rows = [row for row in previous.base_mounts() if row[0] not in replaced]
    rows += [('/app/backend/' + name, str(previous.RELEASE / 'candidate-code' / name), False, 'bind')
             for name in sorted(previous.MODULES)]
    return sorted(rows)


for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'NEW_MODULES', 'BASELINE_MODULES'):
    setattr(core, name, globals()[name])
for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'base_mounts'):
    setattr(core.guard, name, globals()[name])
core.base_mounts = base_mounts

# Only this new immutable locator index and these four nonsecret settings may
# differ from the exact I data/environment. Raw dictionary archives stay put.
INDEX_SHA = '33f9a798232948baa3efa13f402ffd8e278414b987a2230f63b5fff89fafcb81'
INDEX_DEST = '/app/subentry-index.sqlite'
CONFIG = {
    'MELOS_MACHINE_SUBENTRIES_ENABLED': '1',
    'MELOS_SUBENTRY_INDEX': INDEX_DEST,
    'MELOS_SUBENTRY_MANIFEST': '/app/data/lexica/entries.jsonl',
    'MELOS_SUBENTRY_INDEX_SHA256': INDEX_SHA,
}
_approved = core.approved_modules
_binds = core.guard.expected_binds
_validate = core.guard.validate_candidate
_start = core.guard.start


def approved_modules():
    files = _approved()
    receipt = core.release.load('modules-pass.json')
    expected = {'candidate-data/subentries.sqlite': {'sha256': INDEX_SHA, 'bytes': 4837376}}
    core.require(receipt.get('data_artifacts') == expected and receipt.get('environment_changes') == CONFIG,
                 'Exact locator index and four configuration changes must be independently approved')
    path = RELEASE / 'candidate-data/subentries.sqlite'
    core.require(core.sha(path) == INDEX_SHA and path.stat().st_size == 4837376, 'Pinned locator index differs')
    dependencies = receipt.get('source_dependencies', {})
    core.require(len(dependencies) == 24 and 'data/lexica/entries.jsonl' in dependencies,
                 'Existing entries and all 23 raw source archive hashes required')
    for name, digest in dependencies.items():
        core.require('..' not in Path(name).parts and name.startswith(('data/raw/lexica/', 'data/lexica/')),
                     'Unexpected source dependency path')
        core.require(core.sha(core.guard.ROOT / name) == digest, 'Existing dictionary source changed: ' + name)
    return files


def configured(old):
    expected = deepcopy(old)
    values = core.release.environment(old)
    values.update(CONFIG)
    expected['Config']['Env'] = [key + '=' + value for key, value in values.items()]
    return expected


def expected_binds(old):
    binds = _binds(old)
    core.require(not any(bind.rsplit(':', 2)[1] == INDEX_DEST for bind in binds), 'Index target already mounted')
    return binds + [str(RELEASE / 'candidate-data/subentries.sqlite') + ':' + INDEX_DEST + ':ro']


def validate_candidate(container, old, image, port):
    # The inherited validator still compares every environment key, resource,
    # bind and dependency. Its sole expected delta is this explicit setting map.
    _validate(container, configured(old), image, port)


def start(image, name, port, old):
    _start(image, name, port, configured(old))


core.guard.approved_modules = approved_modules
core.guard.expected_binds = expected_binds
core.guard.validate_candidate = validate_candidate
core.guard.start = start


if __name__ == '__main__':
    core.guard.signal.signal(core.guard.signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    original_snapshot = core.guard.snapshot
    def snapshot():
        core.guard.snapshot = original_snapshot
        try:
            core.snapshot()
        finally:
            core.guard.snapshot = snapshot
    core.guard.snapshot = snapshot
    core.guard.main()
