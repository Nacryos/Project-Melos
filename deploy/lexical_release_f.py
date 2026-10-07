"""Prospective F: scoped source-linked candidates and translation comparisons.

Prepared tooling only. Exact independent frozen-artifact approval is required;
private validation and public promotion remain separate operator decisions.
"""
import importlib.util
from pathlib import Path


def _load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load('lexical_release_c.py', '_lexical_c_for_f')
previous = _load('lexical_release_e.py', '_lexical_e_base_for_f')
BASE = core.BASE
BASE_CONTAINER = '0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007f'
CANARY = 'melos-api-lexical-canary-f'
OLD = 'melos-api-before-lexical-20261007f'
NEW_MODULES = frozenset(('translation_comparisons.py', 'translation_comparisons_data.json',
                         'dictionary_crossrefs.py', 'source_link_aliases.py', 'linked_dictionary.py'))
MODULES = NEW_MODULES | frozenset(('server.py', 'passage_analysis.py', 'interlinear.py', 'sense_ranker.py'))
BASELINE_MODULES = previous.BASELINE_MODULES | MODULES
COMPARISONS_SHA = '416e44b50208d1d68688b846770d9d928f8f19299226dd3c4cd88c333c00a16e'
_old_approval = core.approved_modules


def base_mounts():
    replaced = {'/app/backend/' + name for name in previous.MODULES}
    rows = [row for row in previous.base_mounts() if row[0] not in replaced]
    rows += [('/app/backend/' + name, str(previous.RELEASE / 'candidate-code' / name), False, 'bind')
             for name in sorted(previous.MODULES)]
    return sorted(rows)


def approved_modules():
    rows = _old_approval()
    row = rows['translation_comparisons_data.json']
    core.require(row.get('sha256') == COMPARISONS_SHA and row.get('source_projection_audit') == 'PASS',
                 'Exact independently approved comparison projection required')
    return rows


for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'NEW_MODULES', 'BASELINE_MODULES'):
    setattr(core, name, globals()[name])
for name in ('BASE_CONTAINER', 'RELEASE', 'CANARY', 'OLD', 'MODULES', 'base_mounts', 'approved_modules'):
    setattr(core.guard, name, globals()[name])
core.base_mounts = base_mounts
core.approved_modules = approved_modules
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
