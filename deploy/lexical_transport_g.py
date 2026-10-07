"""Immutable G-only audited artifacts; no upload authorizes startup/promotion."""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex

from lexical_release_g import BASE, BASE_CONTAINER, MODULES, NEW_MODULES, RELEASE

spec = importlib.util.spec_from_file_location('_lexical_c_transport_for_g', Path(__file__).with_name('lexical_transport_c.py'))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
ROOT, REMOTE = core.ROOT, RELEASE.as_posix()
for name in ('BASE', 'BASE_CONTAINER', 'MODULES', 'NEW_MODULES', 'REMOTE'):
    setattr(core, name, globals()[name])
HELPERS = ('lexical_release_g.py', 'lexical_release_f.py', 'lexical_release_e.py', 'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py', 'prepare_lexical_g_runtime.py')
approval = core.approval


def upload_new(client, source, relative, mode=0o600):
    private_imports = {
        'canary-runtime/sync_morphology_receipts.py': 'cb2cbab4287b15b596fb8abe5b2b75b665b2beced9450d57b8445adb27761eac',
        'canary-runtime/successful-receipts.json': '865d281ed3e8887e8ecfedb3370868ece4f9d02b03abffe22dadc1dc62490dfc',
    }
    if relative not in ('lexical_release_g.py', 'lexical_release_f.py', 'lexical_release_e.py',
                        'prepare_lexical_g_runtime.py', 'private-runtime-pass.json') and relative not in private_imports:
        return core.upload_new(client, source, relative, mode)
    data = Path(source).read_bytes()
    if relative in private_imports and core.digest(data) != private_imports[relative]:
        raise ValueError('Private importer/bundle differs from audited eight-receipt artifacts')
    with client.open_sftp() as sftp:
        target = REMOTE + '/' + relative
        try:
            with sftp.file(target, 'rb') as stream:
                previous = stream.read()
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != data:
            raise RuntimeError('Refusing to overwrite G helper')
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if core.digest(stream.read()) != core.digest(data):
                raise RuntimeError('G helper transfer differs')
    return {'path': relative, 'sha256': core.digest(data), 'bytes': len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare',))
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path, required=True)
    args = parser.parse_args()
    approval(args.approval, args.candidate_dir)
    client = core.connect()
    try:
        core.run(client, 'mkdir -p ' + shlex.quote(REMOTE + '/candidate-code') + ' && chmod 700 ' + shlex.quote(REMOTE) + ' ' + shlex.quote(REMOTE + '/candidate-code'))
        rows = [upload_new(client, args.candidate_dir / name, 'candidate-code/' + name, 0o644) for name in sorted(MODULES)]
        rows += [upload_new(client, ROOT / 'deploy' / name, name) for name in HELPERS]
        rows.append(upload_new(client, args.approval, 'modules-pass.json'))
        print(json.dumps(rows, indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
