"""Single-use lab orchestrator; remote execution requires audited local launcher."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time

WORK = Path('/home/alvin/services/melos/lab/libmorpheus-offline-eval-20261006')
PREFIX = 'melos-libmorpheus-offline-eval-20261006'
LOG = WORK / 'build.log'
DEADLINE = None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    (WORK / name).write_text(json.dumps(value, indent=2) + '\n')


def command(argv, timeout=30, capture=True):
    if DEADLINE is not None:
        timeout = min(timeout, max(.1, DEADLINE - time.monotonic()))
    with LOG.open('ab') as log:
        log.write((json.dumps(argv) + '\n').encode())
        proc = subprocess.run(argv, stdout=subprocess.PIPE if capture else log,
                              stderr=log, timeout=timeout, check=True)
    return proc.stdout if capture else b''


def inspect(name):
    return json.loads(command(['docker', 'inspect', name]))[0]


def create(name, image, network, args, user='0:0'):
    argv = ['docker', 'create', '--name', name, '--pull', 'never', '--cpus', '1',
            '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '128',
            '--network', network, '--security-opt', 'no-new-privileges:true',
            '--log-driver', 'json-file', '--log-opt', 'max-size=8m', '--log-opt', 'max-file=1',
            '--user', user, '--label', 'project=melos-offline-experiment', image] + args
    command(argv)
    obj = inspect(name)
    host = obj['HostConfig']
    if (obj['Mounts'] or host['PortBindings'] or host['NanoCpus'] != 1000000000 or
            host['Memory'] != 1073741824 or host['MemorySwap'] != 1073741824 or
            host['NetworkMode'] != network or host['Privileged']):
        raise RuntimeError('Unexpected isolated build configuration')
    return obj


def start(name):
    # A timed-out Docker attach does not stop the container, so always kill the
    # exact experiment container on timeout. No other names are accepted.
    if name not in (PREFIX + '-packages', PREFIX + '-compile'):
        raise ValueError('Container outside experiment')
    try:
        command(['docker', 'start', '-a', name], timeout=300, capture=False)
    except BaseException:
        subprocess.run(['docker', 'kill', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=False)
        raise
    obj = inspect(name)
    if obj['State']['ExitCode'] != 0 or obj['State'].get('OOMKilled'):
        raise RuntimeError('Build container failed or exceeded memory budget')
    return obj


def main():
    global DEADLINE
    if Path(__file__).resolve().parent != WORK:
        raise ValueError('Unexpected lab workspace')
    plan = json.loads((WORK / 'build-plan.json').read_text())
    audit = json.loads((WORK / 'audit.json').read_text())
    pin = json.loads((WORK / 'base-pin.json').read_text())
    if digest((WORK / 'input.tar').read_bytes()) != plan['input_sha256']:
        raise ValueError('Transferred build input mismatch')
    if digest(Path(__file__).read_bytes()) != plan['code_sha256']['deploy/libmorpheus-offline/remote_build.py']:
        raise ValueError('Remote helper mismatch')
    if audit.get('verdict') != 'PASS' or audit['bindings']['plan_sha256'] != digest((WORK / 'build-plan.json').read_bytes()):
        raise ValueError('Audit mismatch')
    base = pin['base']
    # Explicit, digest-pinned image acquisition. No legacy code runs here.
    command(['docker', 'pull', '--platform', 'linux/amd64', base], timeout=120, capture=False)
    base_meta = json.loads(command(['docker', 'image', 'inspect', base]))[0]
    if base_meta['Architecture'] != 'amd64' or base_meta['Os'] != 'linux':
        raise ValueError('Unexpected base architecture')
    DEADLINE = time.monotonic() + 300
    started = time.time()
    packages, compiler, runtime = (PREFIX + s for s in ('-packages', '-compile', '-runtime-image'))
    result = {'base_reference': base, 'base_image_id': base_meta['Id'], 'started_at': started,
              'input_sha256': plan['input_sha256'], 'production_touched': False}
    try:
        result['packages_before'] = create(packages, base, 'bridge', ['sh', '-ec',
            'export DEBIAN_FRONTEND=noninteractive; apt-get -o Acquire::Retries=0 update; '
            'apt-get -o Acquire::Retries=0 install --no-install-recommends -y build-essential cmake ninja-build'])
        result['packages_after'] = start(packages)
        toolchain = command(['docker', 'commit', packages, PREFIX + ':toolchain']).decode().strip()
        result['toolchain_image_id'] = toolchain
        result['compile_before'] = create(compiler, toolchain, 'none', ['sh', '-ec',
            'mkdir /lab; tar -xf /input.tar -C /lab; sh /lab/build.sh'])
        # Docker cp extracts only the deterministic, audited safe-member input.
        command(['docker', 'cp', str(WORK / 'input.tar'), compiler + ':/input.tar'])
        result['compile_after'] = start(compiler)
        command(['docker', 'cp', compiler + ':/lab/artifacts', str(WORK / 'artifacts')])
        artifacts = WORK / 'artifacts'
        rows = [{'path': str(p.relative_to(artifacts)).replace('\\', '/'), 'size': p.stat().st_size,
                 'sha256': digest(p.read_bytes())} for p in sorted(artifacts.rglob('*')) if p.is_file()]
        save('artifact-manifest.json', rows)
        with tarfile.open(WORK / 'artifacts.tar', 'w') as tar:
            tar.add(artifacts, arcname='artifacts')
        # New runtime image contains only base + exact CLI/stem/notices/deps. No
        # compiler, source tree, host mounts, application secrets or service ports.
        create(runtime, base, 'none', ['/opt/libmorpheus/bin/analysis_probe'], user='1000:1000')
        command(['docker', 'cp', str(artifacts / 'rootfs') + '/.', runtime + ':/'])
        runtime_id = command(['docker', 'commit', '--change', 'USER 1000:1000',
                              '--change', 'ENV MORPHLIB=/opt/libmorpheus/stemlib', runtime,
                              PREFIX + ':runtime']).decode().strip()
        result.update({'status': 'built_not_executed', 'runtime_image_id': runtime_id,
                       'runtime_image_tag': PREFIX + ':runtime',
                       'artifact_manifest_sha256': digest((WORK / 'artifact-manifest.json').read_bytes()),
                       'artifacts_tar_sha256': digest((WORK / 'artifacts.tar').read_bytes()),
                       'elapsed_build_seconds': time.time()-started})
    except BaseException as exc:
        result.update({'status': 'failed_no_retry', 'error_type': type(exc).__name__,
                       'error': str(exc), 'elapsed_build_seconds': time.time()-started})
        # Tests may fail after writing evidence. Preserve their bytes even though
        # no image is accepted, outside the terminated computation budget.
        try:
            failed = WORK / 'failure-artifacts'
            copied = subprocess.run(['docker', 'cp', compiler + ':/lab/artifacts', str(failed)],
                                    capture_output=True, timeout=30, check=False)
            if copied.returncode == 0:
                rows = [{'path': str(p.relative_to(failed)).replace('\\', '/'),
                         'size': p.stat().st_size, 'sha256': digest(p.read_bytes())}
                        for p in sorted(failed.rglob('*')) if p.is_file()]
                save('artifact-manifest.json', rows)
                with tarfile.open(WORK / 'artifacts.tar', 'w') as tar:
                    tar.add(failed, arcname='failure-artifacts')
                result['failure_artifacts_preserved'] = True
            else:
                result['failure_artifacts_preserved'] = False
        except BaseException as preservation:
            result['preservation_error_type'] = type(preservation).__name__
        save('result.json', result)
        raise
    save('result.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'runtime_image_id', 'elapsed_build_seconds')}))


if __name__ == '__main__':
    main()
