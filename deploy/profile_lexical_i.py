"""Root-authorized isolated five-form lookup diagnostic; never the API worker."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
from discovery_transport import connect, run
from lexical_release_i import BASE

ROOT = Path(__file__).resolve().parents[1]
LIVE = 'f888ab8692593446a2495b3543be2ce7274bfcd672cc0d5f8379083af8f50a19'
NAME = 'melos-word-profile-i-20261007-r3'
REMOTE = '/home/alvin/services/melos/lab/word-profile-i-20261007-r3'


def main():
    output = ROOT / 'runtime/lexical-release-i/isolated-word-profile-r3.json'
    if output.exists():
        raise RuntimeError('Never repeat or overwrite isolated diagnostic')
    records = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    source = next(json.loads(line) for line in records.read_text(encoding='utf-8').splitlines()
                  if json.loads(line)['id'] == 'campbell-glp:alcaeus:130b')
    text_sha = hashlib.sha256(source['text'].encode()).hexdigest()
    profiler = (ROOT / 'scripts/profile_word_lookup.py').read_bytes()
    profiler_sha = hashlib.sha256(profiler).hexdigest()
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != LIVE or info['Image'] != BASE or not info['State']['Running']:
            raise RuntimeError('Exact live I baseline required')
        serving_environment = dict(item.split('=', 1) for item in info['Config']['Env'])
        # Image defaults enable the public filter, whereas the current serving
        # policy exposes these exact owner-supplied Campbell source records.
        policy = serving_environment.get('MELOS_PUBLICATION_POLICY')
        if policy != 'source-labels':
            raise RuntimeError('Expected serving source-visibility policy differs')
        available = int(run(client, "awk '/MemAvailable:/{print $2}' /proc/meminfo"))
        if available < 8 * 1024 * 1024:
            raise RuntimeError('Insufficient available memory for optional profile')
        running = run(client, 'docker ps --format {{.Names}}').decode().splitlines()
        if any('canary' in name or 'offline-eval' in name or 'word-profile' in name for name in running):
            raise RuntimeError('Avoid competing bounded diagnostic/canary work')
        run(client, 'mkdir ' + shlex.quote(REMOTE) + ' && chmod 755 ' + shlex.quote(REMOTE))
        with client.open_sftp() as sftp:
            target = REMOTE + '/profile_word_lookup.py'
            with sftp.file(target, 'wx') as stream:
                stream.write(profiler)
            sftp.chmod(target, 0o444)
        args = ['docker', 'run', '-d', '--name', NAME, '--network', 'none', '--read-only',
                '--cpus=1', '--memory=4g', '--memory-swap=4g', '--pids-limit=128',
                '--user=1000:1000', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m', '--log-driver=local',
                '--log-opt', 'max-size=1m', '--log-opt', 'max-file=2',
                '--env', 'PYTHONDONTWRITEBYTECODE=1',
                '--env', 'MELOS_PUBLICATION_POLICY=' + policy]
        mounted = []
        for mount in sorted(info['Mounts'], key=lambda row: row['Destination']):
            dest = mount['Destination']
            if dest == '/run/secrets/jev.env':
                continue
            if not (dest in ('/app/data', '/app/runtime', '/models', '/syntax-model') or
                    dest.startswith('/app/backend/') or dest.startswith('/app/data/')):
                raise RuntimeError('Unexpected mount, refusing diagnostic')
            args += ['-v', mount['Source'] + ':' + dest + ':ro']
            mounted.append(dest)
        args += ['-v', REMOTE + '/profile_word_lookup.py:/app/scripts/profile_word_lookup.py:ro',
                 BASE, 'python', '/app/scripts/profile_word_lookup.py', '--passage-id', source['id'],
                 '--text-sha256', text_sha, '--count', '5']
        # The detached container has its own process, no ports, no secret mount,
        # no production environment, and hard wall-clock termination.
        code = '''import json,subprocess,time
args=ARGS
start=time.monotonic()
identifier=subprocess.check_output(args,text=True).strip()
timed_out=False
try:
    subprocess.run(['docker','wait',NAME],timeout=120,check=True,stdout=subprocess.PIPE)
except subprocess.TimeoutExpired:
    timed_out=True
    subprocess.run(['docker','kill',NAME],check=True,stdout=subprocess.PIPE)
info=json.loads(subprocess.check_output(['docker','inspect',NAME]))[0]
logs=subprocess.run(['docker','logs',NAME],capture_output=True)
result={'container_id':identifier,'timed_out':timed_out,'elapsed_seconds':time.monotonic()-start,
        'exit_code':info['State']['ExitCode'],'oom_killed':info['State']['OOMKilled'],
        'network_mode':info['HostConfig']['NetworkMode'],'read_only':info['HostConfig']['ReadonlyRootfs'],
        'mounts_readonly':all(not m['RW'] for m in info['Mounts']),
        'nano_cpus':info['HostConfig']['NanoCpus'],'memory':info['HostConfig']['Memory'],
        'published_ports':info['HostConfig']['PortBindings'],'stdout':logs.stdout.decode(),
        'stderr':logs.stderr.decode()}
print(json.dumps(result))
'''.replace('ARGS', repr(args)).replace('NAME', repr(NAME))
        encoded = base64.b64encode(code.encode()).decode()
        result = json.loads(run(client, 'python3 -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(encoded) + '))')))
        current = json.loads(run(client, 'docker inspect melos-api'))[0]
        if current['Id'] != LIVE or not current['State']['Running']:
            raise RuntimeError('Public identity changed during diagnostic')
        result.update({'profile_script_sha256': profiler_sha, 'source_text_sha256': text_sha,
                       'baseline_id': LIVE, 'image': BASE, 'readonly_destinations': mounted,
                       'production_environment_copied': False, 'secret_mounts': False,
                       'allowlisted_serving_setting': {'MELOS_PUBLICATION_POLICY': policy}})
        with output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
        print(json.dumps({'path': str(output), 'exit_code': result['exit_code'],
                          'timed_out': result['timed_out'], 'seconds': result['elapsed_seconds']}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
