"""Compile only a diagnostic consumer; reuse exact audited engine/data layers.

prepare is local and inert. execute requires an independent hash-bound PASS and
explicit GO after the strict corpus run has finished. No engine rebuild or apt.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import tarfile
import time

import libmorpheus_package_repair as bounded
from discovery_transport import connect

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / 'runtime/libmorpheus-offline-eval'
EVIDENCE = ROOT / 'runtime/libmorpheus-offline-diagnostic-eval'
REMOTE = '/home/alvin/services/melos/lab/libmorpheus-offline-diagnostic-eval-20261006'
ORIGINAL_REMOTE = '/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006'
PREFIX = 'melos-libmorpheus-offline-diagnostic-eval-20261006'
PROBE = ROOT / 'deploy/libmorpheus-offline/diagnostic_probe.c'
HEADER_MEMBER = 'libmorpheus-9005feb4dcd85c7898899ee3abc2782519f8f050/include/morpheus/morpheus.h'
LIBRARY_PATH = 'rootfs/opt/libmorpheus/lib/libmorpheus.so.1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare():
    original_plan = json.loads((ORIGINAL / 'build-plan.json').read_text())
    raw = (ORIGINAL / 'raw/code.tar.gz').read_bytes()
    if sha(raw) != original_plan['archive_sha256']:
        raise ValueError('Original code archive differs')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        header = archive.extractfile(HEADER_MEMBER).read()
    source = PROBE.read_bytes()
    if len(header) > 50000 or len(source) > 50000:
        raise ValueError('Consumer/header exceeds bounded artifact size')
    inputs = EVIDENCE / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    for name, data in (('morpheus.h', header), ('diagnostic_probe.c', source)):
        path = inputs / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Prepared diagnostic input conflicts')
        if not path.exists():
            path.write_bytes(data)
    value = bindings()
    (EVIDENCE / 'build-plan.json').write_text(json.dumps(value, indent=2)+'\n')
    print(json.dumps(value, indent=2))


def bindings():
    manifest = json.loads((ORIGINAL / 'artifact-manifest.json').read_text())
    library = next(row for row in manifest if row['path'] == LIBRARY_PATH)
    original = json.loads((ORIGINAL / 'runtime-image.json').read_text())
    build = json.loads((ORIGINAL / 'result.json').read_text())
    return {'script_sha256': sha(Path(__file__).read_bytes()),
            'transport_sha256': sha(Path(bounded.__file__).read_bytes()),
            'probe_sha256': sha(PROBE.read_bytes()),
            'prepared_probe_sha256': sha((EVIDENCE / 'inputs/diagnostic_probe.c').read_bytes()),
            'header_sha256': sha((EVIDENCE / 'inputs/morpheus.h').read_bytes()),
            'original_build_plan_sha256': sha((ORIGINAL / 'build-plan.json').read_bytes()),
            'original_runtime_receipt_sha256': sha((ORIGINAL / 'runtime-image.json').read_bytes()),
            'original_artifact_manifest_sha256': sha((ORIGINAL / 'artifact-manifest.json').read_bytes()),
            'strict_image_id': original['runtime_image_id'],
            'toolchain_image_id': build['toolchain_image_id'], 'library': library,
            'approved_options': [32, 2]}


def cmd(client, args):
    return bounded.command(client, args)


def write_remote(client, relative, data):
    if len(data) > 50000 or relative not in ('inputs/diagnostic_probe.c', 'inputs/include/morpheus/morpheus.h', 'runtime-image.json'):
        raise ValueError('Unexpected diagnostic write')
    script = "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);f=p.open('xb');f.write(bytes.fromhex(sys.argv[2]));f.close()"
    cmd(client, ['python3', '-c', script, REMOTE + '/' + relative, data.hex()])


def create(client, name, image, args, user):
    cmd(client, ['docker', 'create', '--name', name, '--pull', 'never', '--network', 'none',
                 '--cpus', '1', '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '128',
                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                 '--user', user, '--label', 'project=melos-offline-diagnostics', image] + args)
    obj = json.loads(cmd(client, ['docker', 'inspect', name]))[0]
    h = obj['HostConfig']
    if (obj['Image'] != image or obj['Mounts'] or h['PortBindings'] or h['NetworkMode'] != 'none'
            or h['NanoCpus'] != 1000000000 or h['Memory'] != 1073741824
            or h['MemorySwap'] != 1073741824 or h['Privileged']):
        raise ValueError('Unexpected diagnostic build containment')
    return obj


def execute(audit, go):
    if go != 'BUILD_DIAGNOSTIC_CONSUMER_ONLY':
        raise ValueError('Diagnostic consumer GO missing')
    frozen = bindings()
    gate = json.loads(Path(audit).read_text())
    if (gate.get('verdict') != 'PASS' or gate.get('bindings') != frozen
            or gate.get('strict_corpus_run_completed') is not True):
        raise ValueError('Diagnostic consumer audit missing/stale or strict corpus still running')
    if frozen['probe_sha256'] != frozen['prepared_probe_sha256']:
        raise ValueError('Prepared diagnostic source differs')
    bounded.DEADLINE = time.monotonic() + 300
    client = connect()
    receipt = {'status': 'preparing', 'bindings': frozen, 'engine_rebuilt': False,
               'new_stem_data': False, 'parser_executed': False, 'production_touched': False}
    compiler = PREFIX + '-compile'
    runtime = PREFIX + '-runtime'
    try:
        cmd(client, ['mkdir', '-m', '700', REMOTE])
        write_remote(client, 'inputs/diagnostic_probe.c', (EVIDENCE / 'inputs/diagnostic_probe.c').read_bytes())
        write_remote(client, 'inputs/include/morpheus/morpheus.h', (EVIDENCE / 'inputs/morpheus.h').read_bytes())
        # Exact existing engine bytes are copied, never relinked or recompiled.
        copy_library = """import hashlib,pathlib,sys
src=pathlib.Path('/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006/artifacts/rootfs/opt/libmorpheus/lib/libmorpheus.so.1')
b=src.read_bytes()
assert hashlib.sha256(b).hexdigest()==sys.argv[1]
dst=pathlib.Path('/home/alvin/services/melos/lab/libmorpheus-offline-diagnostic-eval-20261006/inputs/lib/libmorpheus.so.1')
dst.parent.mkdir(parents=True,exist_ok=True)
with dst.open('xb') as f: f.write(b)
"""
        cmd(client, ['python3', '-c', copy_library, frozen['library']['sha256']])
        compile_line = ('gcc -std=c17 -Wall -Wextra -Werror -I/diag/include /diag/diagnostic_probe.c '
                        "-L/diag/lib -l:libmorpheus.so.1 -Wl,-rpath,'$ORIGIN/../lib' -o /diag/diagnostic_probe")
        receipt['compile_before'] = create(client, compiler, frozen['toolchain_image_id'],
                                           ['sh', '-ec', compile_line], '0:0')
        cmd(client, ['docker', 'cp', REMOTE + '/inputs', compiler + ':/diag'])
        try:
            output = cmd(client, ['docker', 'start', '-a', compiler])
            (EVIDENCE / 'compile.stdout').write_bytes(output)
        except BaseException:
            # Bound timeout abort must stop the one diagnostic compiler too.
            _, out, _ = client.exec_command(shlex.join(['docker', 'kill', compiler]), timeout=10)
            out.channel.close()
            raise
        state = json.loads(cmd(client, ['docker', 'inspect', compiler]))[0]
        receipt['compile_after'] = state
        if state['State']['ExitCode'] or state['State']['OOMKilled']:
            raise ValueError('Diagnostic consumer compilation failed')
        cmd(client, ['docker', 'cp', compiler + ':/diag/diagnostic_probe', REMOTE + '/diagnostic_probe'])
        binary = cmd(client, ['cat', REMOTE + '/diagnostic_probe'])
        (EVIDENCE / 'diagnostic_probe').write_bytes(binary)
        receipt['consumer_sha256'] = sha(binary)
        receipt['runtime_before'] = create(client, runtime, frozen['strict_image_id'],
                                           ['/opt/libmorpheus/bin/diagnostic_probe'], '1000:1000')
        cmd(client, ['docker', 'cp', REMOTE + '/diagnostic_probe', runtime + ':/opt/libmorpheus/bin/diagnostic_probe'])
        copied = bounded.literal_tar(cmd(client, ['docker', 'cp', runtime + ':/opt/libmorpheus/bin/diagnostic_probe', '-']))
        if list(copied.values()) != [{'size': len(binary), 'sha256': sha(binary)}]:
            raise ValueError('Packaged diagnostic binary differs')
        diff = cmd(client, ['docker', 'diff', runtime]).decode().splitlines()
        allowed = {'C /opt', 'C /opt/libmorpheus', 'C /opt/libmorpheus/bin',
                   'A /opt/libmorpheus/bin/diagnostic_probe'}
        if not set(diff).issubset(allowed) or 'A /opt/libmorpheus/bin/diagnostic_probe' not in diff:
            raise ValueError('Unexpected changes to strict runtime image')
        receipt['runtime_diff'] = diff
        image = cmd(client, ['docker', 'commit', runtime, PREFIX + ':runtime']).decode().strip()
        receipt.update({'status': 'built_not_executed', 'runtime_image_id': image,
                        'strict_parent_image_id': frozen['strict_image_id']})
        payload = (json.dumps(receipt, indent=2)+'\n').encode()
        write_remote(client, 'runtime-image.json', payload)
        bounded.remaining()
        with (EVIDENCE / 'runtime-image.json').open('xb') as f:
            f.write(payload)
        print(json.dumps({'status': receipt['status'], 'runtime_image_id': image,
                          'consumer_sha256': receipt['consumer_sha256']}))
    except BaseException as exc:
        receipt.update({'status': 'failed_no_retry', 'error_type': type(exc).__name__, 'error': str(exc)})
        with (EVIDENCE / 'build-failure.json').open('x') as f:
            f.write(json.dumps(receipt, indent=2)+'\n')
        raise
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'execute'))
    parser.add_argument('--audit')
    parser.add_argument('--go')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    else:
        execute(args.audit, args.go)
