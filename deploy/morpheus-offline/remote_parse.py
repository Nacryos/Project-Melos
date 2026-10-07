"""Separately audited, offline per-form runtime; no production mounts or writes.

Main uploads this and the exact input-plan.json after independent adapter audit.
Each experiment container is retained stopped for inspection; no retry/deletion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

WORK = Path('/home/alvin/services/melos/lab/morpheus-offline-eval-20261006')
PREFIX = 'melos-morpheus-offline-eval-20261006-parse-'
CAP = 1048576


def sha(data):
    return hashlib.sha256(data).hexdigest()


def docker(args):
    return subprocess.run(['docker'] + args, capture_output=True, timeout=15, check=True).stdout


def one(row, image, stage):
    ident = int(row['id'])
    name = PREFIX + f'{ident:04d}'
    beta = row['beta']
    if not isinstance(beta, str) or not re.fullmatch(r"[A-Za-z*()/\\=+|_'^0-9-]{1,128}", beta):
        raise ValueError('Unsafe or unsupported Beta Code input')
    data = (beta + '\n').encode('ascii')
    docker(['create', '-i', '--name', name, '--pull', 'never', '--network', 'none',
            '--user', '1000:1000', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--cpus', '0.5',
            '--memory', '256m', '--memory-swap', '256m', '--pids-limit', '32',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=8m', '--log-driver', 'none',
            '--label', 'project=melos-offline-experiment', image,
            '/opt/morpheus/bin/morpheus', '-m/opt/morpheus/stemlib', '-S'])
    obj = json.loads(docker(['inspect', name]))[0]
    host = obj['HostConfig']
    if (obj['Config']['User'] != '1000:1000' or host['NetworkMode'] != 'none'
            or not host['ReadonlyRootfs'] or host['CapDrop'] != ['ALL']
            or host['NanoCpus'] != 500000000 or host['Memory'] != 268435456
            or host['MemorySwap'] != 268435456 or host['PidsLimit'] != 32
            or obj['Mounts'] or host['PortBindings'] or host['Privileged']
            or 'no-new-privileges:true' not in host['SecurityOpt']):
        raise RuntimeError('Runtime isolation configuration mismatch')
    start = time.monotonic()
    output, error = bytearray(), bytearray()
    status = 'completed'
    proc, selector, caught = None, None, None
    cleanup_errors = []
    try:
        proc = subprocess.Popen(['docker', 'start', '-ai', name], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdin.write(data)
        proc.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, output)
        selector.register(proc.stderr, selectors.EVENT_READ, error)
        while selector.get_map():
            if time.monotonic()-start >= 10:
                status = 'timeout'
                break
            for key, _ in selector.select(timeout=.05):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining = CAP-len(output)-len(error)
                key.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    status = 'output_limit'
                    break
            if status != 'completed':
                break
        if status != 'completed':
            docker(['kill', name])
            proc.kill()
        proc.wait(timeout=2)
    except BaseException as exc:
        caught = exc
        if status == 'completed':
            status = 'error'
        try:
            subprocess.run(['docker', 'kill', name], capture_output=True, timeout=10, check=False)
        except BaseException as cleanup:
            cleanup_errors.append({'operation': 'container_kill', 'type': type(cleanup).__name__, 'message': str(cleanup)})
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except BaseException as cleanup:
                cleanup_errors.append({'operation': 'attach_kill', 'type': type(cleanup).__name__, 'message': str(cleanup)})
    finally:
        duration = time.monotonic()-start
        # Save collected bytes before any further Docker call can itself fail.
        target = WORK / 'runs' / stage
        target.mkdir(parents=True, exist_ok=True)
        (target / f'{ident:04d}.xml').write_bytes(output)
        (target / f'{ident:04d}.stderr').write_bytes(error)
        if selector is not None:
            try:
                selector.close()
            except BaseException as cleanup:
                cleanup_errors.append({'operation': 'selector_close', 'type': type(cleanup).__name__, 'message': str(cleanup)})
        if proc is not None:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    stream.close()
                except BaseException as cleanup:
                    cleanup_errors.append({'operation': 'stream_close', 'type': type(cleanup).__name__, 'message': str(cleanup)})
        final = None
        try:
            final = json.loads(docker(['inspect', name]))[0]
        except BaseException as exc:
            if caught is None:
                caught = exc
            if status == 'completed':
                status = 'error'
            cleanup_errors.append({'operation': 'final_inspect', 'type': type(exc).__name__, 'message': str(exc)})
        result = {'id': ident, 'form': row['form'], 'beta': beta, 'status': status,
                  'image_id': image, 'container_id': obj['Id'], 'stdin_sha256': sha(data),
                  'stdout_sha256': sha(output), 'stderr_sha256': sha(error), 'output_bytes': len(output)+len(error),
                  'wall_seconds': duration, 'attach_return_code': proc.returncode if proc is not None else None,
                  'exit_code': final['State']['ExitCode'] if final else None,
                  'oom_killed': final['State']['OOMKilled'] if final else None, 'peak_rss_bytes': None,
                  'peak_rss_note': 'Not measured; Docker limits are not peak usage.',
                  'error': {'type': type(caught).__name__, 'message': str(caught)} if caught else None,
                  'cleanup_errors': cleanup_errors, 'host_config': host}
        (target / f'{ident:04d}.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    if caught is not None:
        raise caught
    if status != 'completed' or result['attach_return_code'] != 0 or result['exit_code'] != 0 or result['oom_killed']:
        raise RuntimeError('Parser execution failed; evidence saved, no retry')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--code-sha256', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--stage', choices=('reference', 'corpus'), required=True)
    parser.add_argument('--go', required=True)
    args = parser.parse_args()
    if Path(__file__).resolve().parent != WORK or args.go != 'RUN_AUDITED_OFFLINE_INPUTS':
        raise ValueError('Runtime execution gate missing')
    raw = (WORK / 'input-plan.json').read_bytes()
    if sha(raw) != args.plan_sha256 or sha(Path(__file__).read_bytes()) != args.code_sha256:
        raise ValueError('Runtime input/code changed after approval')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image_id):
        raise ValueError('Exact built image ID required')
    built = json.loads((WORK / 'result.json').read_text())
    if built['status'] != 'built_not_executed' or built['runtime_image_id'] != args.image_id:
        raise ValueError('Runtime image does not match isolated build')
    rows = json.loads(raw)['inputs']
    if not 1 <= len(rows) <= 115 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Unexpected input count or duplicate IDs')
    rows = [r for r in rows if (int(r['id']) < 20) == (args.stage == 'reference')]
    if (WORK / 'runs' / args.stage).exists():
        raise ValueError('Previous execution evidence exists; no implicit retry')
    results = []
    for row in rows:
        results.append(one(row, args.image_id, args.stage))
        print(json.dumps({'id': row['id'], 'status': results[-1]['status']}), flush=True)
    (WORK / 'runs' / args.stage / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
