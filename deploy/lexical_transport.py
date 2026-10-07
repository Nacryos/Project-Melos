"""Pinned-host lexical release transport; baseline is read-only on the host.

prepare/upload require an exact independent modules-pass.json. No live files are
overwritten, no container is started, and no route is changed by this transport.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex

from discovery_transport import connect, run
from lexical_release import BASE, BASE_CONTAINER, MODULES

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/alvin/services/melos/releases/lexical-20261007b'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def baseline(client):
    info = json.loads(run(client, 'docker inspect melos-api'))[0]
    if info['Id'] != BASE_CONTAINER or info['Image'] != BASE or not info['State']['Running']:
        raise RuntimeError('Expected live Campbell baseline changed')
    folder = ROOT / '.benchmarks/lexical-baseline' / BASE_CONTAINER
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in sorted(MODULES):
        data = run(client, 'docker exec melos-api cat ' + shlex.quote('/app/backend/' + name))
        path = folder / name
        if path.exists() and path.read_bytes() != data:
            raise RuntimeError('Previously recorded baseline bytes differ')
        if not path.exists():
            path.write_bytes(data)
        files[name] = {'sha256': digest(data), 'bytes': len(data), 'local_path': str(path)}
    receipt = {'container_id': info['Id'], 'image': info['Image'],
        'read_at': datetime.now(timezone.utc).isoformat(), 'files': files,
        'mounts': info['Mounts'], 'read_only_root': info['HostConfig']['ReadonlyRootfs'],
        'method': 'Pinned SSH; docker inspect plus exact running-container source bytes. No environment values or secrets retrieved.'}
    receipt_path = folder / 'baseline.json'
    if not receipt_path.exists():
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'receipt': str(receipt_path), 'files': files}, indent=2))


def approval(path):
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    if result.get('verdict') != 'PASS' or result.get('image') != BASE or result.get('base_container_id') != BASE_CONTAINER:
        raise ValueError('Independent approval for exact baseline required')
    if set(result.get('files', {})) != MODULES:
        raise ValueError('Approval must bind exactly the five allowed backend modules')
    for name, row in result['files'].items():
        if row.get('verdict') != 'PASS' or digest((ROOT / 'backend' / name).read_bytes()) != row.get('sha256'):
            raise ValueError('Approved module differs: ' + name)
    return result


def upload_new(client, source, relative, mode=0o600):
    if relative not in {'modules-pass.json', 'canary-pass.json', 'lexical_release.py', 'release_qa29.py'} | {
            'candidate-code/' + name for name in MODULES}:
        raise ValueError('Upload outside exact release allowlist')
    destination = REMOTE + '/' + relative
    data = Path(source).read_bytes()
    with client.open_sftp() as sftp:
        try:
            with sftp.file(destination, 'rb') as stream:
                existing = stream.read()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing != data:
                raise RuntimeError('Refusing to overwrite a staged release artifact: ' + relative)
        else:
            with sftp.file(destination, 'wx') as stream:
                stream.write(data)
            sftp.chmod(destination, mode)
        with sftp.file(destination, 'rb') as stream:
            if digest(stream.read()) != digest(data):
                raise RuntimeError('Transfer verification failed')
    return {'path': relative, 'sha256': digest(data), 'bytes': len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('baseline', 'prepare'))
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        if not args.approval:
            raise ValueError('Frozen independent approval path required')
        approval(args.approval)
    client = connect()
    try:
        if args.command == 'baseline':
            baseline(client)
        else:
            # Creating only this new, scoped release is authorized by prepare.
            run(client, 'mkdir -p ' + shlex.quote(REMOTE + '/candidate-code') + ' && chmod 700 ' +
                shlex.quote(REMOTE) + ' ' + shlex.quote(REMOTE + '/candidate-code'))
            results = [upload_new(client, ROOT / 'backend' / name, 'candidate-code/' + name, 0o644)
                       for name in sorted(MODULES)]
            results += [upload_new(client, ROOT / 'deploy' / name, name)
                        for name in ('lexical_release.py', 'release_qa29.py')]
            results.append(upload_new(client, args.approval, 'modules-pass.json'))
            print(json.dumps(results, indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
