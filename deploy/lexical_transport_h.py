"""H two-file staging/transport, parameterizing the already audited G transport."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from lexical_release_h import BASE, BASE_CONTAINER, MODULES, NEW_MODULES, RELEASE

spec = importlib.util.spec_from_file_location('_lexical_transport_for_h', Path(__file__).with_name('lexical_transport_g.py'))
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
ROOT, REMOTE = transport.ROOT, RELEASE.as_posix()
for name in ('BASE', 'BASE_CONTAINER', 'MODULES', 'NEW_MODULES', 'REMOTE'):
    setattr(transport, name, globals()[name])
    setattr(transport.core, name, globals()[name])
transport.HELPERS = ('lexical_release_h.py', 'lexical_release_g.py', 'lexical_release_f.py',
                     'lexical_release_e.py', 'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py')
original_upload = transport.upload_new


def upload_new(client, source, relative, mode=0o600):
    allowed = set(transport.HELPERS) | {'modules-pass.json', 'canary-pass.json'} | {'candidate-code/' + name for name in MODULES}
    if relative not in allowed:
        raise ValueError('Outside two-module H release scope')
    if relative != 'lexical_release_h.py':
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
            raise RuntimeError('Never replace H helper')
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if stream.read() != data:
                raise RuntimeError('H helper transfer differs')
    return {'path': relative, 'sha256': transport.core.digest(data), 'bytes': len(data)}


transport.upload_new = upload_new


def stage():
    baseline_dir = ROOT / '.benchmarks/lexical-h-baseline' / BASE_CONTAINER
    baseline_path = baseline_dir / 'baseline.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    if baseline['container_id'] != BASE_CONTAINER or baseline['image'] != BASE:
        raise ValueError('Exact G baseline required')
    sources = {
        'lexicon_senses.py': (ROOT / 'backend/lexicon_senses.py', '60b141a7f2dc6b435279c5d1a82cb66ddb74cd3190bde96d86d31f97b9a94a22'),
        'interlinear.py': (ROOT / 'runtime/alcaeus-morpheus-maintenance/interlinear-tense-approved.py', '463667edc5bc24757480ea8a70a2f8149cae59b344634631bc0519e3bb73b598'),
    }
    folder = ROOT / 'runtime/lexical-release-h/candidate-code'
    files, candidates = {}, {}
    for name, (source, expected) in sources.items():
        data = source.read_bytes()
        if transport.core.digest(data) != expected or transport.core.digest((baseline_dir / name).read_bytes()) != baseline['files'][name]['sha256']:
            raise ValueError('Frozen source/baseline changed: ' + name)
        compile(data, name, 'exec')
        if (folder / name).exists() and (folder / name).read_bytes() != data:
            raise ValueError('Never replace H candidate')
        candidates[name] = data
        files[name] = {'baseline_sha256': baseline['files'][name]['sha256'], 'candidate_sha256': expected}
    receipt = {'verdict': 'STAGED_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'baseline_receipt_sha256': transport.core.digest(baseline_path.read_bytes()), 'files': files,
               'scope': 'Two audited tense-restriction modules; exact G source/data/runtime/routes unchanged.'}
    encoded = json.dumps(receipt, indent=2).encode()
    receipt_path = folder.parent / 'staging.json'
    if receipt_path.exists() and receipt_path.read_bytes() != encoded:
        raise ValueError('Never replace H stage receipt')
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
