"""Stage F by exact-context patching live E bytes, never dirty server copies."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from lexical_release_f import BASE_CONTAINER, MODULES, COMPARISONS_SHA

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.benchmarks/lexical-f-baseline' / BASE_CONTAINER
OUTPUT = ROOT / 'runtime/lexical-release-f/candidate-code'
PATCHES = {
    'f-backend-integration.patch': '31f9773a1ce7dc93b2a1d1c0c879997d327e418e7d02a0fef3a85296f1ae8549',
    'f-linked-dictionary-transport.patch': 'fa6e58543144d7cae0296a11cbc12f5822c8810602344232d2e311158ea07801',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def apply_unique_context(inputs, patch):
    """Allow line-number displacement only: full unchanged/deleted context exact."""
    lines, output, positions = patch.splitlines(keepends=True), dict(inputs), []
    i, name = 0, None
    while i < len(lines):
        row = lines[i]
        if row.startswith(b'diff --git '):
            i += 1
            continue
        if row.startswith(b'--- a/backend/'):
            name = row.strip().removeprefix(b'--- a/backend/').decode('ascii')
            if name not in ('server.py', 'passage_analysis.py') or name not in output:
                raise ValueError('Patch file outside exact F scope')
            i += 1
            if lines[i].strip() != ('+++ b/backend/' + name).encode():
                raise ValueError('Patch destination differs')
            i += 1
            continue
        header = re.fullmatch(rb'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\r\n]*[\r\n]*', row)
        if not header or name is None:
            raise ValueError('Unexpected patch structure')
        i += 1
        body = []
        while i < len(lines) and not lines[i].startswith((b'@@ ', b'--- ', b'diff --git ')):
            if lines[i][:1] not in (b' ', b'-', b'+'):
                raise ValueError('Unsupported patch row')
            body.append(lines[i])
            i += 1
        before = [line[1:].rstrip(b'\r\n') for line in body if line[:1] in (b' ', b'-')]
        after_count = sum(line[:1] in (b' ', b'+') for line in body)
        if not before or len(before) != int(header[2] or b'1') or after_count != int(header[4] or b'1'):
            raise ValueError('Patch hunk counts differ')
        original = output[name].splitlines(keepends=True)
        normalized = [line.rstrip(b'\r\n') for line in original]
        matches = [j for j in range(len(original) - len(before) + 1) if normalized[j:j + len(before)] == before]
        if len(matches) != 1:
            raise ValueError('Patch context must match exactly once')
        start, replacement, cursor = matches[0], [], matches[0]
        for line in body:
            if line[:1] == b' ':
                replacement.append(original[cursor])
            elif line[:1] == b'+':
                replacement.append(line[1:])
            if line[:1] in (b' ', b'-'):
                cursor += 1
        output[name] = b''.join([*original[:start], *replacement, *original[cursor:]])
        positions.append({'file': name, 'declared_old_line': int(header[1]), 'matched_line': start + 1,
                          'old_lines': len(before), 'new_lines': after_count})
    return output, positions


def stage(crossrefs_sha, aliases_sha):
    expected = {
        'translation_comparisons.py': 'efd866b9d2fa28238b0c9b8fcb09853af4d0490dafb86fbad6a803109bcbcc0d',
        'translation_comparisons_data.json': COMPARISONS_SHA,
        'dictionary_crossrefs.py': crossrefs_sha,
        'source_link_aliases.py': aliases_sha,
        'linked_dictionary.py': '8fe4afbf8f34acf96dc07c7566b2ace1d59066614bccfbe3dcfe3a14e56223ee',
        'interlinear.py': '5e093a96302df53fcca2133b1eaee127ee204f78b061f24dcf1973e71804caff',
        'sense_ranker.py': 'f4433c3c21a0fcdb8a0bf85d4750965c87f8ec6f16818d1b27041647f9133c56',
    }
    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in expected.values()):
        raise ValueError('Every artifact requires a frozen SHA256')
    baseline = json.loads((BASELINE / 'baseline.json').read_text(encoding='utf-8'))
    candidates = {name: (BASELINE / name).read_bytes() for name in ('server.py', 'passage_analysis.py')}
    for name, data in candidates.items():
        if sha(data) != baseline['files'][name]['sha256']:
            raise ValueError('Live E baseline bytes changed')
    positions = {}
    for filename, expected_sha in PATCHES.items():
        data = (ROOT / 'runtime/alcaeus-translations' / filename).read_bytes()
        if sha(data) != expected_sha:
            raise ValueError('Frozen narrow patch differs: ' + filename)
        candidates, positions[filename] = apply_unique_context(candidates, data)
    for name, expected_sha in expected.items():
        data = (ROOT / 'backend' / name).read_bytes()
        if sha(data) != expected_sha:
            raise ValueError('Frozen F artifact differs: ' + name)
        candidates[name] = data
    if set(candidates) != MODULES:
        raise ValueError('F candidate scope differs')
    for name, data in candidates.items():
        compile(data, name, 'exec') if name.endswith('.py') else json.loads(data)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, data in sorted(candidates.items()):
        path = OUTPUT / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Never overwrite an F artifact')
        if not path.exists():
            path.write_bytes(data)
        files[name] = {'baseline_sha256': baseline['files'][name]['sha256'], 'candidate_sha256': sha(data)}
    receipt = {'verdict': 'STAGED_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'files': files, 'patch_sha256': PATCHES, 'patch_positions': positions,
               'scope': 'Exact E source with complete-context narrow patches; source labels and sidecar bytes unchanged.'}
    data = json.dumps(receipt, indent=2).encode()
    target = OUTPUT.parent / 'staging.json'
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Never overwrite F staging evidence')
    if not target.exists():
        target.write_bytes(data)
    print(data.decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crossrefs-sha', required=True)
    parser.add_argument('--aliases-sha', required=True)
    args = parser.parse_args()
    stage(args.crossrefs_sha, args.aliases_sha)
