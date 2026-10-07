"""Build offline C candidates, preserving live server bytes outside audited block.

No SSH, upload, containers, data edits or routing. Never overwrite a candidate.
The staged hashes still require a separate independent release approval.
"""
import hashlib
import json
from pathlib import Path

from lexical_release_c import BASE_CONTAINER, MODULES

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.benchmarks/lexical-c-baseline' / BASE_CONTAINER
OUTPUT = ROOT / 'runtime/lexical-release-c/candidate-code'
FROZEN = {
    'lexicon_senses.py': '00d2fe4ed17066a1f7ba211b723cc56e074ce43b563c5d6e07c8e9deebd3dde9',
    'interlinear.py': '58e507315621f32afefe43830a4fa02029b5d8216c1d4e90506e5dca81dab722',
    'lexical_variants.py': 'aa7d8ca247019bf1af08100deec3f52ee61e22e49ff5387530781a4f1f24ff4c',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def server_patch(base, local):
    begin = b'    # Lexical variants can supply an entry meaning without supplying a parse.'
    end = b"    result['parallel_contexts'] = []"
    if local.count(begin) != 1 or local.count(end) != 1 or base.count(end) != 1 or begin in base:
        raise ValueError('Server lexical patch anchors differ')
    block = local[local.index(begin):local.index(end)]
    if len(block.splitlines()) != 14:
        raise ValueError('Expected exact bounded lexical block')
    return base.replace(end, block + end, 1)


def passage_patch(base, local):
    substitutions = (
        (b'"lexical_evidence", "quarantined_source_analyses"',
         b'"lexical_evidence", "lexical_variants", "dictionary_crossreferences", "lexical_variant_supporting_claims", "lexical_variant_status", "quarantined_source_analyses"'),
        (b'claims = [*token["structured_evidence"].get("claims", []), *token.get("contextual_supporting_claims", [])]',
         b'claims = [*token["structured_evidence"].get("claims", []), *token.get("contextual_supporting_claims", []), *token.get("lexical_variant_supporting_claims", [])]'),
    )
    result = base
    for before, after in substitutions:
        if result.count(before) != 1:
            raise ValueError('Passage patch anchor differs')
        result = result.replace(before, after, 1)
    # Only newline differences are tolerated from the development checkout.
    if result.replace(b'\r\n', b'\n') != local.replace(b'\r\n', b'\n'):
        raise ValueError('Unexpected passage changes beyond audited passthrough')
    return result


def main():
    baseline = json.loads((BASELINE / 'baseline-expanded.json').read_text(encoding='utf-8'))
    integration = json.loads((ROOT / 'docs/audits/lexical-variants-integration.json').read_text(encoding='utf-8'))
    if integration.get('verdict') != 'PASS':
        raise ValueError('Independent lexical integration audit missing')
    candidates, report = {}, {}
    for name in sorted(MODULES):
        local = (ROOT / 'backend' / name).read_bytes()
        if name in FROZEN:
            if digest(local) != FROZEN[name]:
                raise ValueError('Frozen reviewed module changed: ' + name)
            candidates[name] = local
        else:
            if digest(local) != integration['code_sha256']['backend/' + name]:
                raise ValueError('Audited development patch changed: ' + name)
            base = (BASELINE / name).read_bytes()
            if digest(base) != baseline['files'][name]['sha256']:
                raise ValueError('Live baseline bytes changed: ' + name)
            candidates[name] = server_patch(base, local) if name == 'server.py' else passage_patch(base, local)
        compile(candidates[name], name, 'exec')
        report[name] = {'baseline_sha256': baseline['files'][name]['sha256'],
                        'candidate_sha256': digest(candidates[name]),
                        'development_sha256': digest(local),
                        'candidate_equals_development': candidates[name] == local}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in candidates.items():
        target = OUTPUT / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Refusing to overwrite frozen candidate: ' + name)
        if not target.exists():
            target.write_bytes(data)
    receipt = {'base_container_id': BASE_CONTAINER, 'candidate_dir': str(OUTPUT),
               'verdict': 'STAGED_NOT_APPROVED', 'files': report,
               'server_scope': 'Exact live bytes plus audited lexical block; other development edits excluded.'}
    target = OUTPUT.parent / 'staging.json'
    data = json.dumps(receipt, indent=2).encode()
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Refusing to overwrite staging receipt')
    if not target.exists():
        target.write_bytes(data)
    print(data.decode())


if __name__ == '__main__':
    main()
