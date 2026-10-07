"""Prospective E: exact D baseline, bounded syntax and approved commentary sidecar.

No corpus/vector replacement, paid inference, or automatic public promotion.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('_lexical_c_for_e', Path(__file__).with_name('lexical_release_c.py'))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
BASE = core.BASE
BASE_CONTAINER = '71c6555a265f83a01f781e3673a815a073c2ed9bc7f8153d36297b8f6797b0c0'
RELEASE = core.guard.ROOT / 'releases/lexical-20261007e'
CANARY = 'melos-api-lexical-canary-e'
OLD = 'melos-api-before-lexical-20261007e'
MODULES = frozenset(('syntax_context.py', 'edition_commentary.py', 'edition_commentary_data.json',
                     'passage_analysis.py', 'passage_ranker.py', 'sense_ranker.py', 'server.py'))
NEW_MODULES = frozenset(('syntax_context.py', 'edition_commentary.py', 'edition_commentary_data.json'))
BASELINE_MODULES = MODULES | frozenset(('syntax_provider.py', 'classifier.py', 'interlinear.py',
    'lexicon_senses.py', 'lexical_variants.py', 'candidate_senses.py', 'evidence.py',
    'textutils.py', 'phrase_meaning.py', 'translation_languages.py', 'normalization_contract.py',
    'source_grammar.py', 'publication.py', 'lexicon_render.py', 'morphology.py', 'wiktionary.py'))
COMMENTARY_SHA = '9b551021b8dfceb0fcd9efc28e7aac66783dfef65cd495ae43f22cf5678db099'
_old_mounts = core.base_mounts
_old_approval = core.approved_modules


def base_mounts():
    rows = [row for row in _old_mounts() if not row[0].startswith('/app/backend/')]
    for name in ('classifier.py', 'sense_ranker.py', 'lexicon_senses.py', 'interlinear.py',
                 'passage_analysis.py', 'server.py', 'lexical_variants.py'):
        release = 'lexical-20261007b' if name in ('classifier.py', 'sense_ranker.py') else 'lexical-20261007d'
        rows.append(('/app/backend/' + name, str(core.guard.ROOT / 'releases' / release / 'candidate-code' / name), False, 'bind'))
    return sorted(rows)


def approved_modules():
    rows = _old_approval()
    row = rows['edition_commentary_data.json']
    core.require(row.get('sha256') == COMMENTARY_SHA and row.get('source_projection_audit') == 'PASS',
                 'Exact independently approved commentary projection required')
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
