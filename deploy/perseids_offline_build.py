"""Audit-gated, isolated Morpheus experiment. Never touches a live container.

prepare only constructs literal-source input artifacts. resolve-base only reads
registry metadata. execute requires an independent PASS bound to all code/input
hashes, a digest-pinned Ubuntu base, and explicit go token. No morphology calls.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'runtime/perseids-offline-eval'
REMOTE = '/home/alvin/services/melos/lab/perseids-offline-eval-20261006'
REVISION = 'ab6898ffed335fc6169fa02c9940657a9b5a78e0'
ARCHIVE_SHA = '1bbd436396fb1c8a08364698acc0e1ff8c98dec43cbed82a10631531a5aac610'
HELPERS = ('deploy/perseids-offline/build.sh', 'deploy/perseids-offline/remote_build.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def prepare():
    raw = (EVIDENCE / 'raw/morpheus.tar.gz').read_bytes()
    if sha(raw) != ARCHIVE_SHA:
        raise ValueError('Pinned source archive mismatch')
    included, excluded, payload = [], [], {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != 'morpheus-' + REVISION or '..' in parts:
                raise ValueError('Unsafe or unexpected archive path')
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('Non-regular archive member is not allowed')
            relative = '/'.join(parts[1:])
            data = archive.extractfile(member).read()
            name = PurePosixPath(relative)
            notice = relative in ('README.md',) or any(s in name.name.lower() for s in ('license', 'copying', 'copyright', 'notice'))
            source = relative.startswith('src/') and (name.suffix in ('.c', '.h', '.l', '.y') or name.name.lower() == 'makefile')
            stem = relative.startswith('stemlib/')
            row = {'path': relative, 'size': len(data), 'sha256': sha(data)}
            if source:
                # The allowlist also rejects binary magic disguised as source.
                if data.startswith((b'\x7fELF', b'!<arch>', b'MZ')) or b'\x00' in data:
                    raise ValueError('Binary disguised as source: ' + relative)
            if source or stem:
                payload['source/' + relative] = data
                included.append({**row, 'kind': 'source' if source else 'stemlib'})
            if notice:
                payload['notices/' + relative] = data
                included.append({**row, 'kind': 'notice'})
            if not (source or stem or notice):
                excluded.append(row)
    required_notices = {'README.md', 'LICENSE'}
    if not required_notices.issubset({r['path'] for r in included if r['kind'] == 'notice'}):
        raise ValueError('Required embedded license notice missing')
    payload['build.sh'] = (ROOT / HELPERS[0]).read_bytes()
    output = EVIDENCE / 'clean-build-input.tar'
    with tarfile.open(output, mode='w') as tar:
        for name, data in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    value = {'archive_sha256': ARCHIVE_SHA, 'revision': REVISION,
             'input_sha256': sha(output.read_bytes()),
             'included': included, 'excluded': excluded,
             'code_sha256': {p: sha((ROOT / p).read_bytes()) for p in
                             ('deploy/perseids_offline_build.py',) + HELPERS},
             'limits': {'build_cpus': 1, 'build_memory': '1g', 'build_seconds': 300,
                        'runtime_cpus': .5, 'runtime_memory': '256m', 'runtime_pids': 32,
                        'runtime_seconds': 10, 'runtime_output_bytes': 1048576},
             'remote_workspace': REMOTE, 'source_executed': False}
    write_json(EVIDENCE / 'build-plan.json', value)
    print(json.dumps({'input_sha256': value['input_sha256'], 'included': len(included),
                      'excluded': len(excluded), 'source_executed': False}))


def resolve_base():
    # Read-only authenticated Docker Hub metadata; public bearer token is not saved.
    url = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/ubuntu:pull'
    with urllib.request.urlopen(url, timeout=30) as r:
        token = json.load(r)['token']
    req = urllib.request.Request('https://registry-1.docker.io/v2/library/ubuntu/manifests/22.04',
                                headers={'Authorization': 'Bearer ' + token,
                                         'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw, digest = r.read(1048576), r.headers['Docker-Content-Digest']
    if sha(raw) != digest.split(':', 1)[1]:
        raise ValueError('Registry index digest mismatch')
    obj = json.loads(raw)
    candidates = [v for v in obj['manifests'] if v.get('platform', {}).get('os') == 'linux'
                  and v['platform'].get('architecture') == 'amd64']
    if len(candidates) != 1:
        raise ValueError('Expected one linux/amd64 manifest')
    base = 'ubuntu@' + candidates[0]['digest']
    write_json(EVIDENCE / 'base-pin.json', {'base': base, 'index_digest': digest,
                                         'platform_manifest': candidates[0]})
    (EVIDENCE / 'raw/ubuntu-22.04-index.json').write_bytes(raw)
    print(json.dumps({'base': base, 'pulled': False}))


def execute(audit_path, go):
    if go != 'BUILD_ISOLATED_PERSEIDS':
        raise ValueError('Explicit execution token required')
    plan_path = EVIDENCE / 'build-plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    pin_path = EVIDENCE / 'base-pin.json'
    pin = json.loads(pin_path.read_text(encoding='utf-8'))
    audit = json.loads(Path(audit_path).read_text(encoding='utf-8'))
    expected = {p: sha((ROOT / p).read_bytes()) for p in plan['code_sha256']}
    if expected != plan['code_sha256']:
        raise ValueError('Code changed after preparation')
    bindings = {'plan_sha256': sha(plan_path.read_bytes()), 'base_pin_sha256': sha(pin_path.read_bytes()),
                'code_sha256': expected, 'archive_sha256': ARCHIVE_SHA,
                'input_sha256': sha((EVIDENCE / 'clean-build-input.tar').read_bytes())}
    if audit.get('verdict') != 'PASS' or audit.get('bindings') != bindings or not audit.get('acquisition_pass'):
        raise ValueError('Independent acquisition/code audit gate missing or stale')
    if not re.fullmatch(r'ubuntu@sha256:[0-9a-f]{64}', pin['base']):
        raise ValueError('Digest-pinned Ubuntu required')
    from discovery_transport import connect, run
    client = connect()
    try:
        # Existing workspace means a previous attempt: never overwrite or retry it.
        run(client, 'test ! -e ' + shlex.quote(REMOTE) + ' && mkdir -m 700 -p ' + shlex.quote(REMOTE))
        with client.open_sftp() as sftp:
            for local, dest in ((EVIDENCE / 'clean-build-input.tar', 'input.tar'),
                                (ROOT / HELPERS[1], 'remote_build.py'),
                                (plan_path, 'build-plan.json'), (pin_path, 'base-pin.json'),
                                (Path(audit_path), 'audit.json')):
                sftp.put(str(local), REMOTE + '/' + dest)
                sftp.chmod(REMOTE + '/' + dest, 0o600)
        command = 'python3 ' + shlex.quote(REMOTE + '/remote_build.py')
        # Caller runs this in an async exec cell; helper records status locally too.
        _, stdout, stderr = client.exec_command(command, timeout=480)
        result, errors = stdout.read(), stderr.read()
        code = stdout.channel.recv_exit_status()
        (EVIDENCE / 'remote-build.stdout').write_bytes(result)
        (EVIDENCE / 'remote-build.stderr').write_bytes(errors)
        with client.open_sftp() as sftp:
            for name in ('result.json', 'build.log', 'artifact-manifest.json', 'artifacts.tar'):
                try:
                    sftp.get(REMOTE + '/' + name, str(EVIDENCE / name))
                except FileNotFoundError:
                    pass  # A failed build can legitimately have no final artifacts.
        if code:
            raise RuntimeError('Isolated build failed; retained evidence, no retry')
        print(result.decode('utf-8'))
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'resolve-base', 'execute'))
    parser.add_argument('--audit')
    parser.add_argument('--go')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'resolve-base':
        resolve_base()
    else:
        execute(args.audit, args.go)
