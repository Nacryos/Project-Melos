"""Exclusive D artifact transport; no source C artifact is overwritten."""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex

from lexical_release_d import MODULES, RELEASE

_spec = importlib.util.spec_from_file_location('_lexical_c_transport_for_d', Path(__file__).with_name('lexical_transport_c.py'))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

ROOT, REMOTE = core.ROOT, RELEASE.as_posix()
core.REMOTE = REMOTE


def upload_new(client, source, relative, mode=0o600):
    if relative != 'lexical_release_d.py':
        return core.upload_new(client, source, relative, mode)
    data = Path(source).read_bytes()
    with client.open_sftp() as sftp:
        target = REMOTE + '/' + relative
        try:
            with sftp.file(target, 'rb') as stream:
                previous = stream.read()
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != data:
            raise RuntimeError('Refusing to overwrite D helper')
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if core.digest(stream.read()) != core.digest(data):
                raise RuntimeError('D helper transfer differs')
    return {'path': relative, 'sha256': core.digest(data), 'bytes': len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('baseline', 'prepare'))
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--candidate-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        if not args.approval or not args.candidate_dir:
            raise ValueError('Explicit frozen approval and staged candidate directory required')
        core.approval(args.approval, args.candidate_dir)
    client = core.connect()
    try:
        if args.command == 'baseline':
            core.baseline(client)
        else:
            core.run(client, 'mkdir -p ' + shlex.quote(REMOTE + '/candidate-code') + ' && chmod 700 ' + shlex.quote(REMOTE) + ' ' + shlex.quote(REMOTE + '/candidate-code'))
            rows = [upload_new(client, args.candidate_dir / name, 'candidate-code/' + name, 0o644) for name in sorted(MODULES)]
            rows += [upload_new(client, ROOT / 'deploy' / name, name) for name in ('lexical_release_d.py', 'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py')]
            rows.append(upload_new(client, args.approval, 'modules-pass.json'))
            print(json.dumps(rows, indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
