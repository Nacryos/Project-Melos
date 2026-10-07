"""Explicit audited offline reference/corpus stages; preserves failures locally."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import stat

from discovery_transport import connect, run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'runtime/perseids-offline-eval'
REMOTE = '/home/alvin/services/melos/lab/perseids-offline-eval-20261006'
CODE = ('deploy/perseids_offline_run.py', 'deploy/perseids-offline/remote_parse.py',
        'scripts/project_perseids_offline_tags.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bindings():
    plan = json.loads((EVIDENCE / 'input-plan.json').read_text(encoding='utf-8'))
    maps = {}
    for name, row in plan['map_provenance'].items():
        path = EVIDENCE / 'adapter-sources' / name
        if sha(path) != row['sha256']:
            raise ValueError('Adapter source changed')
        maps[name] = row['sha256']
    result = json.loads((EVIDENCE / 'result.json').read_text())
    if result['status'] != 'built_not_executed':
        raise ValueError('Build was not successful')
    return {'code_sha256': {p: sha(ROOT / p) for p in CODE},
            'input_plan_sha256': sha(EVIDENCE / 'input-plan.json'),
            'build_result_sha256': sha(EVIDENCE / 'result.json'),
            'maps_sha256': maps, 'image_id': result['runtime_image_id']}


def download_stage(sftp, stage):
    remote = REMOTE + '/runs/' + stage
    local = EVIDENCE / 'runs' / stage
    try:
        entries = sftp.listdir_attr(remote)
    except FileNotFoundError:
        return {'remote_stage_created': False, 'files': []}
    local.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in entries:
        if not stat.S_ISREG(item.st_mode) or '/' in item.filename or '\\' in item.filename or item.filename in ('.', '..'):
            raise ValueError('Unexpected evidence entry')
        target = local / item.filename
        if target.exists():
            raise ValueError('Local evidence exists; will not overwrite')
        sftp.get(remote + '/' + item.filename, str(target))
        rows.append({'path': item.filename, 'size': target.stat().st_size, 'sha256': sha(target)})
    receipt = {'remote_stage_created': True, 'files': rows}
    (local / 'download-manifest.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('reference', 'corpus'), required=True)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--go', required=True)
    args = parser.parse_args()
    if args.go != 'RUN_AUDITED_OFFLINE_INPUTS':
        raise ValueError('Explicit runtime GO required')
    frozen = bindings()
    audit = json.loads(Path(args.audit).read_text(encoding='utf-8'))
    if (audit.get('verdict') != 'PASS' or audit.get('bindings') != frozen
            or not all(audit.get(k) for k in ('acquisition_pass', 'build_pass', 'input_pass'))):
        raise ValueError('Independent runtime audit missing or stale')
    if args.stage == 'corpus':
        parity_path = EVIDENCE / 'audit/reference-output.json'
        parity = json.loads(parity_path.read_text())
        if parity.get('verdict') != 'PASS' or parity.get('input_plan_sha256') != frozen['input_plan_sha256']:
            raise ValueError('Independent reference output audit missing')
    if (EVIDENCE / 'runs' / args.stage).exists():
        raise ValueError('Local run evidence exists; no implicit retry')
    client = connect()
    execution_error = None
    try:
        with client.open_sftp() as sftp:
            for source, target in ((ROOT / CODE[1], 'remote_parse.py'), (EVIDENCE / 'input-plan.json', 'input-plan.json')):
                try:
                    with sftp.open(REMOTE + '/' + target, 'rb') as existing:
                        old = hashlib.sha256(existing.read()).hexdigest()
                    if old != sha(source):
                        raise ValueError('Conflicting remote runtime file')
                except FileNotFoundError:
                    sftp.put(str(source), REMOTE + '/' + target)
                    sftp.chmod(REMOTE + '/' + target, 0o600)
        argv = ['python3', REMOTE + '/remote_parse.py', '--plan-sha256', frozen['input_plan_sha256'],
                '--code-sha256', frozen['code_sha256'][CODE[1]], '--image-id', frozen['image_id'],
                '--stage', args.stage, '--go', args.go]
        _, stdout, stderr = client.exec_command(shlex.join(argv), timeout=1500)
        try:
            out, err = stdout.read(), stderr.read()
            code = stdout.channel.recv_exit_status()
            log = EVIDENCE / ('runtime-' + args.stage)
            log.with_suffix('.stdout').write_bytes(out)
            log.with_suffix('.stderr').write_bytes(err)
            if code:
                execution_error = RuntimeError('Offline parser stage failed; no retry')
        except BaseException as exc:
            execution_error = exc
        finally:
            with client.open_sftp() as sftp:
                receipt = download_stage(sftp, args.stage)
        print(json.dumps({'stage': args.stage, 'downloaded_files': len(receipt['files']),
                          'completed': execution_error is None}))
        if execution_error:
            raise execution_error
    finally:
        client.close()


if __name__ == '__main__':
    main()
