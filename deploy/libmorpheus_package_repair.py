"""One audited packaging-only repair; no compilation or container starts.

Preserves failed result/artifacts. Copies only verified /opt/libmorpheus into a
fresh pinned-base container after byte-matching every required base dependency.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import tarfile
import time

from discovery_transport import connect

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'runtime/libmorpheus-offline-eval'
REMOTE = '/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006'
NAME = 'melos-libmorpheus-offline-eval-20261006-package-repair'
TAG = 'melos-libmorpheus-offline-eval-20261006:runtime-repaired'
OPT_PREFIX = 'rootfs/opt/libmorpheus/'
DEPENDENCIES = ('rootfs/lib/x86_64-linux-gnu/libc.so.6',
                'rootfs/lib64/ld-linux-x86-64.so.2')
DEADLINE = None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bindings():
    paths = {'script_sha256': Path(__file__), 'failed_result_sha256': EVIDENCE / 'result.json',
             'artifact_manifest_sha256': EVIDENCE / 'artifact-manifest.json',
             'artifacts_tar_sha256': EVIDENCE / 'artifacts.tar',
             'base_pin_sha256': EVIDENCE / 'base-pin.json'}
    return {k: sha(p.read_bytes()) for k, p in paths.items()}


def remaining():
    value = DEADLINE - time.monotonic()
    if value <= 0:
        raise TimeoutError('Packaging exceeded the shared 300-second deadline')
    return value


def command(client, args):
    budget = remaining()
    # Bound both server-side commands and client reads. These commands never
    # start a container or rebuild source. A timeout never accepts an image.
    wrapped = ['timeout', '--signal=KILL', f'{budget:.3f}s'] + args
    _, stdout, stderr = client.exec_command(shlex.join(wrapped), timeout=budget)
    try:
        output = stdout.read()
        stdout.channel.settimeout(remaining())
        errors = stderr.read()
        stdout.channel.settimeout(remaining())
        code = stdout.channel.recv_exit_status()
        remaining()
        if code:
            raise RuntimeError(f'Packaging command failed ({code}); stderr suppressed')
        return output
    finally:
        stdout.channel.close()


def literal_tar(raw):
    rows = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar:
            if member.isdir():
                continue
            if not member.isfile() or member.name in rows:
                raise ValueError('Unexpected archive entry during verification')
            content = tar.extractfile(member).read()
            rows[member.name] = {'size': len(content), 'sha256': sha(content)}
    return rows


def main():
    global DEADLINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--go', required=True)
    args = parser.parse_args()
    if args.go != 'PACKAGE_ONLY_VERIFIED_LIBMORPHEUS':
        raise ValueError('Packaging-only GO missing')
    DEADLINE = time.monotonic() + 300
    bound = bindings()
    gate = json.loads(Path(args.audit).read_text())
    if gate.get('verdict') != 'PASS' or gate.get('bindings') != bound:
        raise ValueError('Independent repair code/artifact audit missing')
    target = EVIDENCE / 'runtime-image.json'
    if target.exists():
        raise ValueError('Recovery receipt exists; no implicit retry')
    failed = json.loads((EVIDENCE / 'result.json').read_text())
    if (failed['status'] != 'failed_no_retry' or failed['compile_after']['State']['ExitCode'] != 0
            or failed['compile_after']['State']['OOMKilled']):
        raise ValueError('This is not the audited successful-build packaging failure')
    manifest = json.loads((EVIDENCE / 'artifact-manifest.json').read_text())
    source = {row['path']: {'size': row['size'], 'sha256': row['sha256']} for row in manifest}
    if len(source) != len(manifest) or not all(p in source for p in DEPENDENCIES):
        raise ValueError('Dependency/manifest mismatch')
    pin = json.loads((EVIDENCE / 'base-pin.json').read_text())
    if failed['base_reference'] != pin['base']:
        raise ValueError('Base pin differs from compiled artifact provenance')
    # The local failure archive is an additional byte-for-byte source receipt.
    archived = literal_tar((EVIDENCE / 'artifacts.tar').read_bytes())
    if {p.removeprefix('failure-artifacts/'): r for p, r in archived.items()} != source:
        raise ValueError('Saved artifact archive does not match manifest')
    client = connect()
    remaining()
    receipt = {'status': 'packaging_started', 'bindings': bound, 'production_touched': False,
               'source_rebuilt': False, 'parser_executed': False}
    try:
        # Verify all candidate files on disk before Docker receives the path.
        script = """import hashlib,json,pathlib
p=pathlib.Path('/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006/artifacts')
rows={}
for f in sorted(p.rglob('*')):
 if f.is_symlink(): raise ValueError('Unexpected artifact symlink')
 if f.is_file():
  b=f.read_bytes(); rows[str(f.relative_to(p))]={'size':len(b),'sha256':hashlib.sha256(b).hexdigest()}
print(json.dumps(rows))
"""
        remote_rows = json.loads(command(client, ['python3', '-c', script]))
        if remote_rows != source:
            raise ValueError('Remote compiled artifact tree differs')
        command(client, ['docker', 'create', '--name', NAME, '--pull', 'never',
                         '--network', 'none', '--user', '1000:1000', '--cap-drop', 'ALL',
                         '--security-opt', 'no-new-privileges:true', '--cpus', '1',
                         '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '128',
                         '--label', 'project=melos-offline-experiment', pin['base'],
                         '/opt/libmorpheus/bin/analysis_probe'])
        before = json.loads(command(client, ['docker', 'inspect', NAME]))[0]
        host = before['HostConfig']
        if (before['Image'] != failed['base_image_id'] or before['State']['Running']
                or before['Mounts'] or host['PortBindings'] or host['NetworkMode'] != 'none'
                or host['NanoCpus'] != 1000000000 or host['Memory'] != 1073741824
                or host['MemorySwap'] != 1073741824 or host['Privileged']):
            raise ValueError('Unexpected repair container configuration')
        deps = {}
        for path in DEPENDENCIES:
            actual = literal_tar(command(client, ['docker', 'cp', '-L', NAME + ':/' + path[len('rootfs/'):], '-']))
            if len(actual) != 1 or next(iter(actual.values())) != source[path]:
                raise ValueError('Pinned base dependency does not match compiled artifact: ' + path)
            deps[path] = source[path]
        # Confirm the dependency inventory contains no omitted third dependency.
        dependency_list = command(client, ['cat', REMOTE + '/artifacts/dependencies.txt']).decode().splitlines()
        if sorted(dependency_list) != sorted('/' + p[len('rootfs/'):] for p in DEPENDENCIES):
            raise ValueError('Unexpected runtime dependency closure')
        command(client, ['docker', 'cp', REMOTE + '/artifacts/rootfs/opt/libmorpheus', NAME + ':/opt/'])
        copied = literal_tar(command(client, ['docker', 'cp', NAME + ':/opt/libmorpheus', '-']))
        expected = {'libmorpheus/' + p[len(OPT_PREFIX):]: row for p, row in source.items() if p.startswith(OPT_PREFIX)}
        if copied != expected:
            raise ValueError('Packaged payload differs from built artifacts')
        image_id = command(client, ['docker', 'commit', '--change', 'USER 1000:1000',
                                    '--change', 'ENV MORPHLIB=/opt/libmorpheus/stemlib', NAME, TAG]).decode().strip()
        receipt.update({'status': 'built_not_executed', 'runtime_image_id': image_id,
                        'runtime_image_tag': TAG, 'base_reference': pin['base'],
                        'dependencies_verified': deps, 'opt_files_verified': len(copied),
                        'repair_container_id': before['Id'], 'host_config': host})
        payload = (json.dumps(receipt, indent=2)+'\n').encode()
        remaining()
        save_script = ("import pathlib,sys; "
                       "p=pathlib.Path('/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006/runtime-image.json'); "
                       "f=p.open('xb'); f.write(bytes.fromhex(sys.argv[1])); f.close()")
        command(client, ['python3', '-c', save_script, payload.hex()])
        # The local receipt is the runtime audit's acceptance input. Publish it
        # only once every remote operation completed within the shared deadline.
        with target.open('xb') as f:
            f.write(payload)
        print(json.dumps({'status': receipt['status'], 'runtime_image_id': image_id,
                          'opt_files_verified': len(copied)}))
    except BaseException as exc:
        receipt.update({'status': 'packaging_failed_no_retry', 'error_type': type(exc).__name__, 'error': str(exc)})
        with (EVIDENCE / 'packaging-repair-failure.json').open('x') as f:
            f.write(json.dumps(receipt, indent=2)+'\n')
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
