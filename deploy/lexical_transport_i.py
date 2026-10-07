"""I gzip-only staging/transport, parameterizing the already audited G transport."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from lexical_release_i import BASE, BASE_CONTAINER, MODULES, NEW_MODULES, RELEASE

spec = importlib.util.spec_from_file_location('_lexical_transport_for_i', Path(__file__).with_name('lexical_transport_g.py'))
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
ROOT, REMOTE = transport.ROOT, RELEASE.as_posix()
for name in ('BASE', 'BASE_CONTAINER', 'MODULES', 'NEW_MODULES', 'REMOTE'):
    setattr(transport, name, globals()[name])
    setattr(transport.core, name, globals()[name])
transport.HELPERS = ('lexical_release_i.py', 'lexical_release_h.py', 'lexical_release_g.py', 'lexical_release_f.py',
                     'lexical_release_e.py', 'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py')
original_upload = transport.upload_new


def upload_new(client, source, relative, mode=0o600):
    allowed = set(transport.HELPERS) | {'modules-pass.json', 'canary-pass.json'} | {'candidate-code/' + name for name in MODULES}
    if relative not in allowed:
        raise ValueError('Outside gzip-only I release scope')
    if relative not in ('lexical_release_i.py', 'lexical_release_h.py'):
        return original_upload(client, source, relative, mode)
    data = Path(source).read_bytes()
    with client.open_sftp() as sftp:
        target = REMOTE + '/' + relative
        try:
            with sftp.file(target, 'rb') as stream:
                previous = stream.read()
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != data:
            raise RuntimeError('Never replace I helper')
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if stream.read() != data:
                raise RuntimeError('I helper transfer differs')
    return {'path': relative, 'sha256': transport.core.digest(data), 'bytes': len(data)}


transport.upload_new = upload_new


def stage():
    from stage_lexical_f import apply_unique_context
    baseline_dir = ROOT / '.benchmarks/lexical-i-baseline' / BASE_CONTAINER
    baseline_path = baseline_dir / 'baseline.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    if baseline['container_id'] != BASE_CONTAINER or baseline['image'] != BASE:
        raise ValueError('Exact H baseline required')
    server = (baseline_dir / 'server.py').read_bytes()
    if transport.core.digest(server) != baseline['files']['server.py']['sha256']:
        raise ValueError('Frozen server baseline changed')
    patch = (ROOT / 'runtime/lexical-release-g/large-json-gzip-insertion.patch').read_bytes()
    patch_sha = 'a5b1728b0b072b9d0791a83d69a99c78a08edd36d8d5889229e7ca607fb6f346'
    if transport.core.digest(patch) != patch_sha:
        raise ValueError('Audited gzip patch changed')
    # Adapt only the two known path headers for the existing strict patcher.
    adapted = patch.replace(b'a/server.py', b'a/backend/server.py').replace(b'b/server.py', b'b/backend/server.py')
    candidates, positions = apply_unique_context({'server.py': server}, adapted)
    gzip_module = (ROOT / 'backend/large_json_gzip.py').read_bytes()
    if transport.core.digest(gzip_module) != '95b5804db12e0eee91844e313c0c6edc06a7c55e8e429a8d7f38da7aa180e5eb':
        raise ValueError('Frozen gzip module changed')
    candidates['large_json_gzip.py'] = gzip_module
    if set(candidates) != MODULES:
        raise ValueError('Only gzip module and exact server patch allowed')
    folder = ROOT / 'runtime/lexical-release-i/candidate-code'
    files = {}
    for name, data in candidates.items():
        compile(data, name, 'exec')
        if (folder / name).exists() and (folder / name).read_bytes() != data:
            raise ValueError('Never replace I candidate')
        files[name] = {'baseline_sha256': baseline['files'][name]['sha256'],
                       'candidate_sha256': transport.core.digest(data)}
    receipt = {'verdict': 'STAGED_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'baseline_receipt_sha256': transport.core.digest(baseline_path.read_bytes()),
               'files': files, 'source_patch_sha256': patch_sha, 'patch_positions': positions,
               'adapted_patch_sha256': transport.core.digest(adapted),
               'scope': 'Negotiated large JSON transport only; H source/data/runtime and application payloads unchanged.'}
    encoded = json.dumps(receipt, indent=2).encode()
    receipt_path = folder.parent / 'staging.json'
    if receipt_path.exists() and receipt_path.read_bytes() != encoded:
        raise ValueError('Never replace I stage receipt')
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in candidates.items():
        if not (folder / name).exists():
            (folder / name).write_bytes(data)
    if not receipt_path.exists():
        receipt_path.write_bytes(encoded)
    print(encoded.decode())


if __name__ == '__main__':
    if sys.argv[1:] == ['stage']:
        stage()
    else:
        transport.main()
