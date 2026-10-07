"""Prepare a local, non-deployed opt-in release delta against the exact I server.

Source archives are only inventoried and hash-verified; no corpus is rewritten.
The release owner must compare required dependencies with the target container
and package any absent/mismatched artifacts before enabling the feature.
"""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.machine_subentries import MachineSubentryResolver
from backend.lexicon_render import _source_path

BASE = ROOT / 'runtime/lexical-release-i/candidate-code/server.py'
BASE_SHA = '1d12ab817e2a92bd9fb663ecf9b375ce47a5a7de0da2234c1158a8513e9c4f57'
OUTPUT = ROOT / 'runtime/machine-subentry-local-release'
INDEX = 'data/staging/lyric-subentries-20261006-v2/subentries.sqlite'
MANIFEST = 'data/lexica/entries.jsonl'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path), 'bytes': path.stat().st_size}


def prepare():
    helper_audit = json.loads((ROOT / 'docs/audits/machine-subentries-helper.json').read_text(encoding='utf8'))
    for relative, expected in helper_audit['reviewed_files_sha256'].items():
        if sha(ROOT / relative) != expected:
            raise ValueError('Approved helper dependency changed: ' + relative)
    if sha(BASE) != BASE_SHA:
        raise ValueError('Exact I server baseline changed')
    resolver = MachineSubentryResolver(ROOT / INDEX, ROOT / MANIFEST,
        expected_index_sha256=helper_audit['reviewed_files_sha256'][INDEX])
    raw_files = {}
    for record in resolver.records.values():
        raw = _source_path(record['raw_path'])
        expected = record['raw_sha256']
        if raw in raw_files and raw_files[raw] != expected:
            raise ValueError('Conflicting raw-source identity')
        raw_files[raw] = expected
    for raw, expected in raw_files.items():
        if sha(raw) != expected:
            raise ValueError('Archived source SHA mismatch: ' + str(raw))

    # Transplant only the approved wiring hunks, never the full dirty local server.
    local = (ROOT / 'backend/server.py').read_text(encoding='utf8')
    baseline = BASE.read_text(encoding='utf8')
    marker = '# Providers are lazy: importing the API never downloads or loads model weights.\n'
    begin = '@lru_cache(maxsize=1)\ndef _passage_subentry_resolver():\n'
    if local.count(begin) != 1 or baseline.count(marker) != 1 or begin in baseline:
        raise ValueError('Unexpected server wiring anchors')
    block = local[local.index(begin):local.index(marker)]
    extra = "    machine_subentry_lookup=(_passage_machine_subentries\n                            if os.environ.get('MELOS_MACHINE_SUBENTRIES_ENABLED') == '1' else None),\n"
    anchor = '    rerank_allowed=_passage_rerank_allowed,\n'
    if local.count(extra) != 1 or baseline.count(anchor) != 1:
        raise ValueError('Unexpected router wiring anchors')
    candidate = baseline.replace(marker, block + marker).replace(anchor, anchor + extra)
    word_start = "@app.get('/api/word')\ndef word_request("
    word_end = 'class MachineAnalysisRequest(BaseModel):\n'
    source_route = "@app.get('/api/word')\ndef word("
    if local.count(word_start) != 1 or candidate.count(source_route) != 1 or candidate.count(word_end) != 1:
        raise ValueError('Unexpected ordinary word route anchors')
    word_block = local[local.index(word_start):local.index(word_end)]
    candidate = candidate.replace(source_route, 'def word(').replace(word_end, word_block + word_end)
    compile(candidate, 'release/backend/server.py', 'exec')
    overlay = OUTPUT / 'overlay'
    (overlay / 'backend').mkdir(parents=True, exist_ok=True)
    (overlay / 'backend/server.py').write_text(candidate, encoding='utf8', newline='\n')
    modules = ['backend/passage_routes.py', 'backend/interlinear.py', 'backend/passage_analysis.py',
               'backend/machine_subentries.py', 'backend/lexicon_subentries.py', 'js/passage-analysis.js']
    for relative in modules + [INDEX]:
        target = overlay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    expected_paths = set(modules + [INDEX, 'backend/server.py'])
    actual_paths = {path.relative_to(overlay).as_posix() for path in overlay.rglob('*') if path.is_file()}
    if actual_paths != expected_paths:
        raise ValueError('Overlay contains unexpected or missing files; refuse stale package contents')
    (OUTPUT / 'server-on-exact-i.patch').write_text(''.join(difflib.unified_diff(
        baseline.splitlines(keepends=True), candidate.splitlines(keepends=True),
        fromfile='a/backend/server.py', tofile='b/backend/server.py')), encoding='utf8', newline='\n')
    prerequisites = [MANIFEST, 'backend/lexicon_senses.py', 'backend/lexicon_render.py', 'backend/machine_morphology.py']
    metadata = {
        'status': 'LOCAL_CANDIDATE_NOT_DEPLOYMENT_APPROVAL',
        'base_server': artifact(BASE),
        'overlay': [artifact(path) for path in sorted(overlay.rglob('*')) if path.is_file()],
        'required_existing_or_packaged': [artifact(ROOT / p) for p in prerequisites] +
                                       [artifact(p) for p in sorted(raw_files)],
        'source_index_rows': resolver.dependencies['index_rows'],
        'source_parent_count': len(resolver.records), 'raw_archive_count': len(raw_files),
        'environment': {'MELOS_MACHINE_SUBENTRIES_ENABLED': '1',
                        'MELOS_SUBENTRY_INDEX': '/app/' + INDEX,
                        'MELOS_SUBENTRY_MANIFEST': '/app/' + MANIFEST,
                        'MELOS_SUBENTRY_INDEX_SHA256': helper_audit['reviewed_files_sha256'][INDEX]},
        'environment_path_note': 'Paths assume the existing /app container root; owner must confirm mount paths.',
        'preserve': 'I gzip and all unlisted I files; no corpus/morphology-cache replacement.',
        'ranking_status': 'unsupported_source_type; dictionary alternatives only',
        'audits': ['docs/audits/machine-subentries-helper.json',
                   'runtime/alcaeus-morpheus-maintenance/machine-subentry-integration-audit.json'],
    }
    (OUTPUT / 'dependency-manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf8')
    return metadata


if __name__ == '__main__':
    result = prepare()
    print(json.dumps({'output': str(OUTPUT), 'raw_archives': result['raw_archive_count'],
                      'overlay_files': len(result['overlay']), 'status': result['status']}))
