"""Offline E stage: apply audited narrow patches to exact live D source bytes.

Existing server/passages are never copied wholesale from the dirty checkout.
Output remains unapproved until a separate independent exact-artifact review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from lexical_release_e import BASE_CONTAINER, MODULES, COMMENTARY_SHA

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.benchmarks/lexical-e-baseline' / BASE_CONTAINER
OUTPUT = ROOT / 'runtime/lexical-release-e/candidate-code'
SYNTAX_SHA = 'a4322f31ab10e6f4d49de0863c083893647212a16120fc5339feb2684c1c7834'
PATCHES = {
    'syntax-integration.patch': '2563a6c7ee8bd6f0923291dcb03fc7f240b53c2eade2e491333d748a29d94f10',
    'commentary-context.patch': '88ec4b97a40a9da48060b6c82b7661c467a2673b53898d8f00096484af3396d6',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_patch_bytes(inputs, patch):
    """Strict unified patch application, preserving every untouched byte/line."""
    lines = patch.splitlines(keepends=True)
    i, outputs = 0, dict(inputs)
    while i < len(lines):
        if not lines[i].startswith(b'--- a/backend/'):
            raise ValueError('Unexpected patch file header')
        name = lines[i].strip().removeprefix(b'--- a/backend/').decode('ascii')
        if name not in ('passage_analysis.py', 'passage_ranker.py') or name not in inputs:
            raise ValueError('Patch target outside exact scope')
        i += 1
        if lines[i].strip() != ('+++ b/backend/' + name).encode():
            raise ValueError('Patch destination differs')
        i += 1
        original = outputs[name].splitlines(keepends=True)
        cursor, updated = 0, []
        while i < len(lines) and not lines[i].startswith(b'--- '):
            header = re.fullmatch(rb'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\r\n]*[\r\n]*', lines[i])
            if not header:
                raise ValueError('Invalid patch hunk')
            start = int(header[1]) - 1
            if start < cursor or start > len(original):
                raise ValueError('Patch hunk offset differs')
            updated.extend(original[cursor:start])
            cursor, old_count, new_count = start, 0, 0
            i += 1
            while i < len(lines) and not lines[i].startswith((b'@@ ', b'--- ')):
                row = lines[i]
                if row[:1] not in (b' ', b'-', b'+'):
                    raise ValueError('Unsupported patch row')
                if row[:1] in (b' ', b'-'):
                    if cursor >= len(original) or original[cursor].rstrip(b'\r\n') != row[1:].rstrip(b'\r\n'):
                        raise ValueError('Patch source bytes differ')
                    if row[:1] == b' ':
                        updated.append(original[cursor])
                    cursor += 1
                    old_count += 1
                if row[:1] == b'+':
                    updated.append(row[1:])
                if row[:1] in (b' ', b'+'):
                    new_count += 1
                i += 1
            if old_count != int(header[2] or b'1') or new_count != int(header[4] or b'1'):
                raise ValueError('Patch hunk counts differ')
        updated.extend(original[cursor:])
        outputs[name] = b''.join(updated)
    return outputs


def server_patch(base):
    needle = b"    result.update(translation_previews(result,result.get('related',[]),full_text=True))"
    block = (b'    from .edition_commentary import for_passage as edition_commentary_for_passage\n'
             b'    if (published_commentary := edition_commentary_for_passage(result)) is not None:\n'
             b"        result['published_commentary'] = published_commentary\n")
    lines = base.splitlines(keepends=True)
    matches = [i for i, row in enumerate(lines) if row.rstrip(b'\r\n') == needle]
    if len(matches) != 1 or b'edition_commentary_for_passage' in base:
        raise ValueError('Live server commentary anchor differs')
    index = matches[0]
    if lines[index + 1].rstrip(b'\r\n') != b'    return result':
        raise ValueError('Live server return anchor differs')
    return b''.join([*lines[:index + 1], block, *lines[index + 1:]])


def stage(commentary_helper_sha, sense_ranker_sha):
    expected = {'syntax_context.py': SYNTAX_SHA, 'edition_commentary_data.json': COMMENTARY_SHA,
                'edition_commentary.py': commentary_helper_sha, 'sense_ranker.py': sense_ranker_sha}
    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in expected.values()):
        raise ValueError('Every new module requires a frozen SHA256')
    baseline = json.loads((BASELINE / 'baseline.json').read_text(encoding='utf-8'))
    originals = {}
    for name in ('passage_analysis.py', 'passage_ranker.py', 'server.py'):
        originals[name] = (BASELINE / name).read_bytes()
        if digest(originals[name]) != baseline['files'][name]['sha256']:
            raise ValueError('Live D source snapshot differs: ' + name)
    candidates = dict(originals)
    for filename, sha in PATCHES.items():
        patch = (ROOT / 'runtime/syntax-context-integration' / filename).read_bytes()
        if digest(patch) != sha:
            raise ValueError('Audited patch differs: ' + filename)
        candidates = apply_patch_bytes(candidates, patch)
    candidates['server.py'] = server_patch(originals['server.py'])
    for name, sha in expected.items():
        data = (ROOT / 'backend' / name).read_bytes()
        if digest(data) != sha:
            raise ValueError('Frozen E artifact differs: ' + name)
        candidates[name] = data
    if set(candidates) != MODULES:
        raise ValueError('Candidate artifact scope differs')
    for name, data in candidates.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
        else:
            json.loads(data)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, data in sorted(candidates.items()):
        target = OUTPUT / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Refusing to overwrite E artifact: ' + name)
        if not target.exists():
            target.write_bytes(data)
        files[name] = {'baseline_sha256': baseline['files'][name]['sha256'], 'candidate_sha256': digest(data)}
    receipt = {'base_container_id': BASE_CONTAINER, 'verdict': 'STAGED_NOT_APPROVED',
               'candidate_dir': str(OUTPUT), 'files': files, 'patch_sha256': PATCHES,
               'scope': 'Exact D source plus syntax/context patches and3line server insertion; independently approved commentary sidecar only.'}
    data = json.dumps(receipt, indent=2).encode()
    target = OUTPUT.parent / 'staging.json'
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Refusing to overwrite E staging receipt')
    if not target.exists():
        target.write_bytes(data)
    print(data.decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commentary-helper-sha', required=True)
    parser.add_argument('--sense-ranker-sha', required=True)
    args = parser.parse_args()
    stage(args.commentary_helper_sha, args.sense_ranker_sha)
