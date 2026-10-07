"""Gzip-only I overlay; reuse frozen guards, retaining exact public H runtime."""
import importlib.util
from pathlib import Path


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('lexical_release_c.py', '_lexical_c_for_i')
previous = load('lexical_release_h.py', '_lexical_h_base_for_i')
BASE = core.BASE
BASE_CONTAINER = 'e37c1e216b508388caa8d9260298390b59edc9b5bf07b3d825fc5d3fb3b68eda'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007i'
CANARY = 'melos-api-lexical-canary-i'
OLD = 'melos-api-before-lexical-20261007i'
MODULES = frozenset(('server.py', 'large_json_gzip.py'))
NEW_MODULES = frozenset(('large_json_gzip.py',))
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
