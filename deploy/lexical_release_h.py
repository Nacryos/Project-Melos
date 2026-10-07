"""Two-module H overlay; reuse frozen guards, retaining exact public G runtime."""
import importlib.util
from pathlib import Path


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('lexical_release_c.py', '_lexical_c_for_h')
previous = load('lexical_release_g.py', '_lexical_g_base_for_h')
BASE = core.BASE
BASE_CONTAINER = 'b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007h'
CANARY = 'melos-api-lexical-canary-h'
OLD = 'melos-api-before-lexical-20261007h'
MODULES = frozenset(('lexicon_senses.py', 'interlinear.py'))
NEW_MODULES = frozenset()
BASELINE_MODULES = previous.BASELINE_MODULES


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
