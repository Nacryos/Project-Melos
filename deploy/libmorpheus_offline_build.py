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
EVIDENCE = ROOT / 'runtime/libmorpheus-offline-eval'
REMOTE = '/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006'
REVISION = '9005feb4dcd85c7898899ee3abc2782519f8f050'
ARCHIVE_SHA = '06ba749e0a4cb0e90bd0842492af1ee5fde52cd4d62927fec345d1b5784e101b'
DATA_REVISION = '4632415fe93c85e9fdca47a0c5a13f31385f0023'
DATA_SHA = 'ae25bb469c419291463fd1441e3beac011c56df68092020a633c977d1c13bcd0'
HELPERS = ('deploy/libmorpheus-offline/build.sh', 'deploy/libmorpheus-offline/remote_build.py',
           'deploy/libmorpheus-offline/analysis_probe.c')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def prepare():
    raw = (EVIDENCE / 'raw/code.tar.gz').read_bytes()
    data_raw = (EVIDENCE / 'raw/data.tar.gz').read_bytes()
    if sha(raw) != ARCHIVE_SHA or sha(data_raw) != DATA_SHA:
        raise ValueError('Pinned source/data archive mismatch')
    included, excluded, payload = [], [], {}
    for kind, archive_raw, archive_root in (
            ('code', raw, 'libmorpheus-' + REVISION),
            ('data', data_raw, 'morpheus-' + DATA_REVISION)):
        with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as archive:
            seen = set()
            for member in archive:
                parts = PurePosixPath(member.name).parts
                if (not parts or parts[0] != archive_root or '..' in parts
                        or member.name.startswith('/') or '\\' in member.name or ':' in member.name):
                    raise ValueError('Unsafe archive path')
                if member.isdir():
                    continue
                if not member.isfile() or member.name in seen:
                    raise ValueError('Non-regular or duplicate archive member')
                seen.add(member.name)
                relative = '/'.join(parts[1:])
                content = archive.extractfile(member).read()
                name = PurePosixPath(relative)
                notice = (relative == 'README.md' or relative.startswith('LICENSES/')
                          or relative == 'dist/bin/platform/MPL-1.1.txt'
                          or any(x in name.name.lower() for x in ('license', 'copying', 'copyright', 'notice')))
                source = (kind == 'code' and not relative.startswith(
                    ('stemlib/', 'vendor/', '.github/', 'bench/', 'bindings/')))
                stem = kind == 'data' and relative.startswith('dist/stemlib/')
                row = {'archive': kind, 'path': relative, 'size': len(content), 'sha256': sha(content)}
                if source:
                    if (name.suffix.lower() in ('.o', '.a', '.so', '.dll', '.exe', '.gz', '.zip')
                            or content.startswith((b'\x7fELF', b'!<arch>', b'MZ')) or b'\x00' in content):
                        excluded.append(row)
                        continue
                    payload['source/' + relative] = content
                    included.append({**row, 'kind': 'source'})
                if stem:
                    payload['data/' + relative[len('dist/'):]] = content
                    included.append({**row, 'kind': 'stemlib'})
                if notice:
                    payload['notices/' + kind + '/' + relative] = content
                    included.append({**row, 'kind': 'notice'})
                if not (source or stem or notice):
                    excluded.append(row)
    required = {'notices/code/LICENSE', 'notices/code/LICENSE-AGPL-3.0-or-later',
                'notices/data/LICENSE', 'notices/data/dist/bin/platform/license.txt',
                'notices/data/dist/bin/platform/MPL-1.1.txt'}
    if not required.issubset(payload):
        raise ValueError('Required code/data notice missing')
    payload['build.sh'] = (ROOT / HELPERS[0]).read_bytes()
    payload['analysis_probe.c'] = (ROOT / HELPERS[2]).read_bytes()
    output = EVIDENCE / 'clean-build-input.tar'
    with tarfile.open(output, mode='w') as tar:
        for name, content in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), 0o644, 0
            tar.addfile(info, io.BytesIO(content))
    value = {'archive_sha256': ARCHIVE_SHA, 'revision': REVISION,
             'data_archive_sha256': DATA_SHA, 'data_revision': DATA_REVISION,
             'input_sha256': sha(output.read_bytes()), 'included': included, 'excluded': excluded,
             'code_sha256': {p: sha((ROOT / p).read_bytes()) for p in
                             ('deploy/libmorpheus_offline_build.py',) + HELPERS},
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
    req = urllib.request.Request('https://registry-1.docker.io/v2/library/ubuntu/manifests/24.04',
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
    (EVIDENCE / 'raw').mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'raw/ubuntu-24.04-index.json').write_bytes(raw)
    print(json.dumps({'base': base, 'pulled': False}))


def execute(audit_path, go):
    if go != 'BUILD_ISOLATED_LIBMORPHEUS':
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
