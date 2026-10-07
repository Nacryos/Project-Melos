"""Release D: C's scoped overlays with independently audited source-POS guard.

The live B baseline and all original artifacts stay unchanged. C is retained.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('_lexical_c_for_d', Path(__file__).with_name('lexical_release_c.py'))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
BASE, BASE_CONTAINER, MODULES = core.BASE, core.BASE_CONTAINER, core.MODULES
NEW_MODULES, BASELINE_MODULES = core.NEW_MODULES, core.BASELINE_MODULES
RELEASE = core.guard.ROOT / 'releases/lexical-20261007d'
CANARY = 'melos-api-lexical-canary-d'
OLD = 'melos-api-before-lexical-20261007d'

for name in ('RELEASE', 'CANARY', 'OLD'):
    setattr(core, name, globals()[name])
    setattr(core.guard, name, globals()[name])

approved_modules, expected_binds = core.approved_modules, core.expected_binds


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
