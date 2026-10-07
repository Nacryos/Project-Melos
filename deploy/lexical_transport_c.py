"""Pinned read-only C baseline retrieval; explicit reviewed candidate directory.

No automatic deployment: prepare requires fresh exact independent module approval.
Never reads candidate modules from the dirty backend working directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex

from discovery_transport import connect, run
from lexical_release_c import BASE, BASE_CONTAINER, MODULES, NEW_MODULES, BASELINE_MODULES, RELEASE

ROOT = Path(__file__).resolve().parents[1]
REMOTE = RELEASE.as_posix()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def baseline(client):
    info = json.loads(run(client, 'docker inspect melos-api'))[0]
    if info['Id'] != BASE_CONTAINER or info['Image'] != BASE or not info['State']['Running']:
        raise RuntimeError('Exact live B baseline changed')
    folder = ROOT / '.benchmarks/lexical-c-baseline' / BASE_CONTAINER
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in sorted(BASELINE_MODULES):
        remote = '/app/backend/' + name
        if name in NEW_MODULES:
            exists = run(client, 'docker exec melos-api sh -c ' + shlex.quote('if test -e ' + remote + '; then echo present; else echo absent; fi')).strip()
            if exists != b'absent':
                raise RuntimeError('Expected new module already exists: ' + name)
            files[name] = {'sha256': None, 'baseline_absent': True}
            continue
        data = run(client, 'docker exec melos-api cat ' + shlex.quote(remote))
        path = folder / name
        if path.exists() and path.read_bytes() != data:
            raise RuntimeError('Previously recorded baseline differs: ' + name)
        if not path.exists():
            path.write_bytes(data)
        files[name] = {'sha256': digest(data), 'bytes': len(data), 'local_path': str(path)}
    current = json.loads(run(client, 'docker inspect melos-api'))[0]
    if current['Id'] != info['Id'] or current['Mounts'] != info['Mounts']:
        raise RuntimeError('Live container changed during snapshot')
    receipt = {'container_id': info['Id'], 'image': info['Image'], 'files': files,
               'mounts': info['Mounts'], 'read_only_root': info['HostConfig']['ReadonlyRootfs'],
               'read_at': datetime.now(timezone.utc).isoformat(),
               'method': 'Pinned SSH exact running-container source retrieval; no secret values saved.'}
    target = folder / 'baseline-expanded.json'
    if not target.exists():
        target.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'receipt': str(target), 'files': files}, indent=2))


def approval(path, candidate_dir):
    folder = Path(candidate_dir).resolve(strict=True)
    if folder == (ROOT / 'backend').resolve():
        raise ValueError('Dirty backend directory cannot be a release candidate')
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    if result.get('verdict') != 'PASS' or result.get('image') != BASE or result.get('base_container_id') != BASE_CONTAINER:
        raise ValueError('Independent approval for exact B baseline required')
    if set(result.get('files', {})) != MODULES:
        raise ValueError('Exactly the scoped C modules required')
    for name, row in result['files'].items():
        target = folder / name
        if target.resolve().parent != folder:
            raise ValueError('Candidate symlink escapes staged directory')
        if row.get('verdict') != 'PASS' or digest(target.read_bytes()) != row.get('sha256'):
            raise ValueError('Approved candidate differs: ' + name)
        if name == 'server.py' and row.get('scoped_live_baseline_patch') is not True:
            raise ValueError('Server live-baseline scoped patch approval required')
        if name in NEW_MODULES and (row.get('baseline_absent') is not True or row.get('baseline_sha256', 'missing') is not None):
            raise ValueError('New module absence must be audited')
    return result


def upload_new(client, source, relative, mode=0o600):
    allowed = {'modules-pass.json', 'canary-pass.json', 'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py'} | {'candidate-code/' + name for name in MODULES}
    if relative not in allowed:
        raise ValueError('Outside C artifact allowlist')
    data = Path(source).read_bytes()
    with client.open_sftp() as sftp:
        target = REMOTE + '/' + relative
        try:
            with sftp.file(target, 'rb') as stream:
                previous = stream.read()
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != data:
            raise RuntimeError('Refusing to overwrite C artifact: ' + relative)
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if digest(stream.read()) != digest(data):
                raise RuntimeError('Transferred artifact differs')
    return {'path': relative, 'sha256': digest(data), 'bytes': len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('baseline', 'prepare'))
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--candidate-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        if not args.approval or not args.candidate_dir:
            raise ValueError('Explicit frozen approval and staged candidate directory required')
        approval(args.approval, args.candidate_dir)
    client = connect()
    try:
        if args.command == 'baseline':
            baseline(client)
        else:
            run(client, 'mkdir -p ' + shlex.quote(REMOTE + '/candidate-code') + ' && chmod 700 ' + shlex.quote(REMOTE) + ' ' + shlex.quote(REMOTE + '/candidate-code'))
            rows = [upload_new(client, args.candidate_dir / name, 'candidate-code/' + name, 0o644) for name in sorted(MODULES)]
            rows += [upload_new(client, ROOT / 'deploy' / name, name) for name in ('lexical_release_c.py', 'lexical_release.py', 'release_qa29.py')]
            rows.append(upload_new(client, args.approval, 'modules-pass.json'))
            print(json.dumps(rows, indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
