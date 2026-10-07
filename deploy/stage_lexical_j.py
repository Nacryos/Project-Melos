"""Freeze reviewed J snapshots, proving server/routes against exact live I."""
import argparse
import hashlib
import json
from pathlib import Path
from lexical_release_j import BASE_CONTAINER, MODULES, INDEX_SHA
from stage_lexical_f import apply_unique_context

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.benchmarks/lexical-j-baseline' / BASE_CONTAINER
OWNER = ROOT / 'runtime/machine-subentry-local-release'
OUTPUT = ROOT / 'runtime/lexical-release-j'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-audit', type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.owner_audit.read_text(encoding='utf-8'))
    if audit.get('verdict') != 'PASS':
        raise ValueError('Final independent owner audit required')
    baseline = json.loads((BASELINE / 'baseline.json').read_text(encoding='utf-8'))
    manifest = json.loads((OWNER / 'dependency-manifest.json').read_text(encoding='utf-8'))
    if baseline['container_id'] != BASE_CONTAINER:
        raise ValueError('Exact I baseline required')
    candidates = {}
    for row in manifest['overlay']:
        path = ROOT / row['path']
        if path.parent.name != 'backend':
            continue
        data = path.read_bytes()
        if sha(data) != row['sha256'] or len(data) != row['bytes']:
            raise ValueError('Frozen owner module changed: ' + path.name)
        candidates[path.name] = data
    memo_audit_path = ROOT / 'docs/audits/morphology-render-memo-review.json'
    memo_audit = json.loads(memo_audit_path.read_text(encoding='utf-8'))
    candidates['morphology.py'] = (ROOT / 'backend/morphology.py').read_bytes()
    if (sha(candidates['morphology.py']) != memo_audit['current_morphology_sha256'] or
            baseline['files']['morphology.py']['sha256'] != memo_audit['pre_memo_i_baseline_morphology_sha256']):
        raise ValueError('Exact audited memo baseline/candidate required')
    if set(candidates) != MODULES:
        raise ValueError('Only seven frozen backend modules allowed')
    patch_evidence = {}
    for module, filename in [('server.py', 'server-on-exact-i.patch'), ('passage_routes.py', 'passage-routes.patch')]:
        original = (BASELINE / module).read_bytes()
        if sha(original) != baseline['files'][module]['sha256']:
            raise ValueError('Frozen live baseline changed')
        raw = (OWNER / filename).read_bytes()
        # Existing strict patch engine permits server.py. Map only path headers
        # for route code and omit its two explanatory comment lines; all hunk
        # context is still required to match exactly once, without fuzzy edits.
        adapted = b''.join(line for line in raw.splitlines(keepends=True) if not line.startswith(b'#'))
        adapted = adapted.replace(b'a/backend/passage_routes.py', b'a/backend/server.py').replace(
            b'b/backend/passage_routes.py', b'b/backend/server.py')
        result, positions = apply_unique_context({'server.py': original}, adapted)
        # Owner snapshots use LF consistently; the historical server has mixed
        # CRLF/LF. Permit only this explicitly recorded newline normalization,
        # never whitespace/content changes outside the exact scoped hunks.
        normalized = result['server.py'].replace(b'\r\n', b'\n')
        if normalized != candidates[module]:
            raise ValueError('Owner snapshot is not exact scoped I patch: ' + module)
        patch_evidence[module] = {'source_patch_sha256': sha(raw), 'adapted_patch_sha256': sha(adapted),
                                  'positions': positions, 'line_endings': 'CRLF to LF only',
                                  'pre_normalization_sha256': sha(result['server.py']),
                                  'normalized_sha256': sha(normalized)}
    index_row = next(row for row in manifest['overlay'] if row['path'].endswith('/subentries.sqlite'))
    index = (ROOT / index_row['path']).read_bytes()
    if sha(index) != INDEX_SHA or len(index) != 4837376:
        raise ValueError('Pinned index changed')
    receipt = {'verdict': 'STAGED_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'baseline_sha256': sha((BASELINE / 'baseline.json').read_bytes()),
               'owner_audit': str(args.owner_audit), 'owner_audit_sha256': sha(args.owner_audit.read_bytes()),
               'owner_manifest_sha256': sha((OWNER / 'dependency-manifest.json').read_bytes()),
               'memo_audit_sha256': sha(memo_audit_path.read_bytes()), 'patches': patch_evidence,
               'files': {name: {'sha256': sha(data), 'baseline_sha256': baseline['files'][name]['sha256']}
                         for name, data in sorted(candidates.items())},
               'index_sha256': INDEX_SHA, 'commentary_changes_included': False}
    artifacts = {OUTPUT / 'candidate-code' / name: data for name, data in candidates.items()}
    artifacts[OUTPUT / 'candidate-data/subentries.sqlite'] = index
    artifacts[OUTPUT / 'staging.json'] = json.dumps(receipt, indent=2).encode()
    for name, data in candidates.items():
        compile(data, name, 'exec')
    for path, data in artifacts.items():
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Never replace J artifact: ' + str(path))
    for path, data in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
