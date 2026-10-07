"""Offline D stage: replace exactly two C artifacts; retain others byte-for-byte."""
import argparse
import hashlib
import json
from pathlib import Path

from lexical_release_d import BASE_CONTAINER, MODULES

ROOT = Path(__file__).resolve().parents[1]
C_CODE = ROOT / 'runtime/lexical-release-c/candidate-code'
OUTPUT = ROOT / 'runtime/lexical-release-d/candidate-code'
HELPER_SHA = 'e6271e256b982e94d955078910339fcfebf67f91952ce53f3ceb6d038918a53f'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stage(interlinear_sha):
    if len(interlinear_sha) != 64 or any(char not in '0123456789abcdef' for char in interlinear_sha):
        raise ValueError('Frozen interlinear SHA256 required')
    approval = json.loads((ROOT / 'docs/audits/lexical-context-backend-c.json').read_text(encoding='utf-8'))
    if approval.get('verdict') != 'PASS' or approval.get('base_container_id') != BASE_CONTAINER:
        raise ValueError('Exact C approval missing')
    expected = {'interlinear.py': interlinear_sha, 'lexical_variants.py': HELPER_SHA}
    candidates, files = {}, {}
    for name in sorted(MODULES):
        previous = (C_CODE / name).read_bytes()
        if digest(previous) != approval['files'][name]['sha256']:
            raise ValueError('Immutable C artifact differs: ' + name)
        data = (ROOT / 'backend' / name).read_bytes() if name in expected else previous
        if name in expected and digest(data) != expected[name]:
            raise ValueError('Frozen D module differs: ' + name)
        compile(data, name, 'exec')
        candidates[name] = data
        files[name] = {'baseline_sha256': approval['files'][name]['baseline_sha256'],
                       'c_sha256': digest(previous), 'candidate_sha256': digest(data),
                       'unchanged_from_c': data == previous}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in candidates.items():
        path = OUTPUT / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Refusing to overwrite frozen D candidate: ' + name)
        if not path.exists():
            path.write_bytes(data)
    receipt = {'base_container_id': BASE_CONTAINER, 'candidate_dir': str(OUTPUT),
               'verdict': 'STAGED_NOT_APPROVED', 'files': files,
               'scope': 'Only interlinear and lexical_variants supersede C; independent D review required.'}
    data = json.dumps(receipt, indent=2).encode()
    target = OUTPUT.parent / 'staging.json'
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Refusing to overwrite D staging receipt')
    if not target.exists():
        target.write_bytes(data)
    print(data.decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interlinear-sha', required=True)
    stage(parser.parse_args().interlinear_sha)
