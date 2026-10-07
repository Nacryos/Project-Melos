"""Freeze ten G overlays from exact F and reviewed, bounded changes only."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from lexical_release_g import BASE_CONTAINER, MODULES
from stage_lexical_f import apply_unique_context

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.benchmarks/lexical-g-baseline' / BASE_CONTAINER
OUTPUT = ROOT / 'runtime/lexical-release-g/candidate-code'
PATCH = ROOT / 'runtime/alcaeus-assignment-qa/g-editorial-backend.patch'
PATCH_SHA = 'bd1f655463e4833c21063e256ea8a0298fe0c4a60ae2deae91e4c3c8d59ecf8a'
FROZEN = {
    'noun_entry_features.py': 'f76b06f93709dd7024cbaa370d5bf9082c049b6eb7eff0ac0e7bfb56b5d98dfd',
    'linked_dictionary.py': '8bc98545f4ec4efd8da0ce9b0beaa33e7da199092241802265af8e495ec604c6',
    'editorial_readings.py': '5d6a77348213b919d784e8110c898d322ab62e1ea5bac3c09ea9c034da99abb7',
    'editorial_analysis.py': 'f58dbbe476816d21b123f2db099f86d90b2ffbdd31c527e1a9e0a1fac241536d',
    'machine_morphology.py': '6918e20b3cf0a279542d6c0d34f50fcf6059d899c04cee4670d6b3bc06865b97',
    'classifier.py': '0ff045b04e7b30948a7d178b995fcd29e2770ad081892ed63d153d496d0a48b5',
    'interlinear.py': 'c8ca0b41d8ece747875766525c68567541e0814fc08544144adc9096cb5c57cc',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stage(sense_ranker_sha):
    if not re.fullmatch(r'[0-9a-f]{64}', sense_ranker_sha):
        raise ValueError('Final frozen sense-ranker SHA256 required')
    baseline = json.loads((BASELINE / 'baseline.json').read_text(encoding='utf-8'))
    if baseline['container_id'] != BASE_CONTAINER:
        raise ValueError('Not exact F baseline')
    candidates = {name: (BASELINE / name).read_bytes() for name in ('server.py', 'passage_analysis.py')}
    for name, data in candidates.items():
        if sha(data) != baseline['files'][name]['sha256']:
            raise ValueError('Frozen baseline changed: ' + name)
    patch = PATCH.read_bytes()
    if sha(patch) != PATCH_SHA:
        raise ValueError('Reviewed editorial patch changed')
    candidates, positions = apply_unique_context(candidates, patch)
    for name, expected in {**FROZEN, 'sense_ranker.py': sense_ranker_sha}.items():
        source = (ROOT / 'runtime/alcaeus-morpheus-maintenance/interlinear-homograph-approved-g.py'
                  if name == 'interlinear.py' else ROOT / 'backend' / name)
        data = source.read_bytes()
        if sha(data) != expected:
            raise ValueError('Frozen G artifact changed: ' + name)
        candidates[name] = data
    if set(candidates) != MODULES:
        raise ValueError('Exact G inventory required')
    for name, data in candidates.items():
        compile(data, name, 'exec')
    files = {name: {'baseline_sha256': baseline['files'][name]['sha256'], 'candidate_sha256': sha(data)}
             for name, data in sorted(candidates.items())}
    receipt = {'verdict': 'STAGED_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'baseline_receipt_sha256': sha((BASELINE / 'baseline.json').read_bytes()),
               'files': files, 'patch_sha256': PATCH_SHA, 'patch_positions': positions,
               'scope': 'Exact F plus reviewed G code only; no source/corpus/cache import, paid requests or publication.'}
    serialized = json.dumps(receipt, indent=2).encode()
    target = OUTPUT.parent / 'staging.json'
    # Check all outputs before any writes: a changed candidate needs a new release.
    for name, data in candidates.items():
        if (OUTPUT / name).exists() and (OUTPUT / name).read_bytes() != data:
            raise ValueError('Never overwrite G candidate: ' + name)
    if target.exists() and target.read_bytes() != serialized:
        raise ValueError('Never overwrite G staging evidence')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in candidates.items():
        if not (OUTPUT / name).exists():
            (OUTPUT / name).write_bytes(data)
    if not target.exists():
        target.write_bytes(serialized)
    print(serialized.decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sense-ranker-sha', required=True)
    stage(parser.parse_args().sense_ranker_sha)
