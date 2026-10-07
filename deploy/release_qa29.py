"""Run on Basecamp: snapshot; canary IMAGE; promote IMAGE; verify IMAGE.

Promotion requires canary-pass.json containing passed:true, image, canary_id.
All evidence is owner-only. No paid inference, image deletion, or route resets.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path('/home/alvin/services/melos')
RELEASE = ROOT / 'releases/qa29'
BASE = 'sha256:75868bbfa330949fca011a093c9b8fd53e52495ad173a06a25196c4e6f4dc758'
HOST = 'basecamp.taila44c41.ts.net:8443'
OLD = 'melos-api-before-qa29'
CANARY = 'melos-api-canary'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def capture(*args):
    # Never echo command arguments or subprocess stderr: environment can be secret.
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    require(proc.returncode == 0, 'Command failed: ' + args[0])
    return proc.stdout


def inspect(name):
    return json.loads(capture('docker', 'inspect', name))[0]


def exists(name):
    return subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def save(name, value):
    path = RELEASE / name
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(value, stream, indent=2)


def load(name):
    path = RELEASE / name
    require(path.stat().st_mode & 0o077 == 0, 'Evidence must be owner-only: ' + name)
    return json.loads(path.read_text())


def routes():
    return json.loads(capture('tailscale', 'serve', 'status', '--json'))


def routed(snapshot, port):
    result = copy.deepcopy(snapshot)
    result['Web'][HOST]['Handlers']['/']['Proxy'] = f'http://127.0.0.1:{port}'
    return result


def route(snapshot, before, after):
    require(routes() == routed(snapshot, before), 'Concurrent route mutation; refuse overwrite')
    capture('tailscale', 'funnel', '--bg', '--https=8443', '--yes', f'http://127.0.0.1:{after}')
    require(routes() == routed(snapshot, after), 'Unexpected route configuration after change')


def mounts(container):
    rows = [(m['Destination'], m['Source'], m['RW'], m['Type']) for m in container['Mounts']]
    require(len({r[0] for r in rows}) == len(rows), 'Duplicate mount destination')
    return sorted(rows)


def environment(container):
    rows = container['Config']['Env']
    require(len({v.split('=', 1)[0] for v in rows}) == len(rows), 'Duplicate environment key')
    return dict(v.split('=', 1) for v in rows)


def gateway(name):
    return capture('docker', 'exec', name, 'python', '-c',
                   "import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/app/backend/jev_gateway.py').read_bytes()).hexdigest())").strip()


def baseline():
    old = load('container-before.private.json')
    require(old['Image'] == BASE, 'Snapshot image mismatch')
    return old, load('routes-before.private.json')


def check_original(old):
    actual = inspect('melos-api')
    require(actual['Id'] == old['Id'] and actual['Image'] == BASE and actual['State']['Running'],
            'Original production identity/state changed')
    require(actual['HostConfig'] == old['HostConfig'] and actual['Config'] == old['Config']
            and mounts(actual) == mounts(old), 'Original container configuration changed')


def snapshot():
    old = inspect('melos-api')
    require(old['Image'] == BASE and old['State']['Running'], 'Expected QA28 production is not running')
    require(old['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8791'}]}, 'Production port mismatch')
    expected = [('/app/data', str(ROOT / 'data'), False, 'bind'),
                ('/app/runtime', str(ROOT / 'runtime'), True, 'bind'),
                ('/models', str(ROOT / 'models'), False, 'bind'),
                ('/run/secrets/jev.env', str(ROOT / 'secrets/jev.env'), False, 'bind'),
                ('/app/data/corpus.sqlite', str(ROOT / 'releases/qa27/candidate-data/corpus.sqlite'), False, 'bind'),
                ('/app/data/embeddings/manifest.json', str(ROOT / 'releases/qa27/candidate-data/manifest.json'), False, 'bind')]
    require(mounts(old) == sorted(expected), 'Baseline six-mount contract differs')
    current = routes()
    require(current == routed(current, 8791), 'Public route is not production')
    require(current['AllowFunnel'] == {HOST: True}, 'Unexpected Funnel exposure')
    for port in (443, 80):
        require(current['Web'][f'basecamp.taila44c41.ts.net:{port}']['Handlers']['/']['Proxy'] == 'http://127.0.0.1:7680', 'Private Basecamp route mismatch')
    require('MELOS_SYNTAX_MODEL_PATH' not in environment(old), 'Baseline already has syntax override')
    digest = gateway('melos-api')
    save('container-before.private.json', old)
    save('routes-before.private.json', current)
    save('snapshot.json', {'release': 'qa29', 'image': BASE, 'container_id': old['Id'],
                           'gateway_sha256': digest, 'created_at': time.time()})


def validate_candidate(container, old, image, port):
    require(container['Image'] == image and container['State']['Running'], 'Candidate image/state mismatch')
    require(container['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}, 'Candidate port mismatch')
    expected = mounts(old) + [('/syntax-model', str(RELEASE / 'model/pipeline'), False, 'bind')]
    require(mounts(container) == sorted(expected), 'Candidate mount contract changed')
    expected_env = environment(old)
    expected_env['MELOS_SYNTAX_MODEL_PATH'] = '/syntax-model'
    require(environment(container) == expected_env, 'Candidate environment contract changed')
    # Port and bind changes are checked above; every other Docker restriction
    # must survive, including fields not explicitly enumerated by this helper.
    for key in set(container['HostConfig']) | set(old['HostConfig']):
        if key in ('Binds', 'PortBindings'):
            continue
        require(container['HostConfig'].get(key) == old['HostConfig'].get(key), 'HostConfig mismatch: ' + key)
    for key in ('User', 'Cmd', 'Entrypoint', 'WorkingDir'):
        require(container['Config'][key] == old['Config'][key], 'Container config mismatch: ' + key)


def start(image, name, port, old):
    require((name, port) in (('melos-api', 8791), (CANARY, 8792)), 'Invalid container target')
    require(not exists(name), 'Container name already exists')
    require((RELEASE / 'model/pipeline/melos-provenance.json').is_file(), 'Model receipt missing')
    require(json.loads(capture('docker', 'image', 'inspect', image))[0]['Id'] == image, 'Immutable image unavailable')
    args = ['docker', 'run', '-d', '--name', name, '--restart', 'unless-stopped',
            '--cpus=2', '--cpu-shares=256', '--memory=8g', '--memory-swap=8g', '--pids-limit=128',
            '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--user=1000:1000', '--log-driver=local',
            '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3', '-p', f'127.0.0.1:{port}:8791']
    # An owner-only env file avoids exposing values in process arguments.
    env_path = RELEASE / f'{name}.env.private'
    values = dict(environment(old), MELOS_SYNTAX_MODEL_PATH='/syntax-model')
    require(all('\n' not in v and '\r' not in v for v in values.values()), 'Multiline environment unsupported')
    with os.fdopen(os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(''.join(f'{k}={v}\n' for k, v in values.items()))
    args += ['--env-file', str(env_path)]
    for destination, source, writable, _ in mounts(old):
        args += ['-v', f'{source}:{destination}:{"rw" if writable else "ro"}']
    args += ['-v', f'{RELEASE}/model/pipeline:/syntax-model:ro', image] + old['Config']['Cmd']
    try:
        capture(*args)
    finally:
        env_path.unlink()
    validate_candidate(inspect(name), old, image, port)


def get(origin, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(origin + path, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def warm(port, syntax=True):
    origin = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + 180
    while True:
        try:
            require(get(origin, '/api/status', timeout=5)['passages'] == 288584, 'Corpus count mismatch')
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    passage = get(origin, '/api/passage?id=dcc-sappho%3Abrothers-poem')
    require(passage['id'] == 'dcc-sappho:brothers-poem', 'Warm passage missing')
    if syntax:
        text = passage['text']
        # Short, unchanged substring ending at a word boundary.
        end = next((i for i in range(min(100, len(text)), min(200, len(text))) if text[i].isspace()), min(100, len(text)))
        result = get(origin, '/api/analyze-passage', {'version': 1, 'passage_id': passage['id'],
                     'start': 0, 'end': end, 'offset_unit': 'codepoint', 'selected_text': text[:end],
                     'rerank': False, 'fetch_machine': False}, timeout=240)
        require(result['syntax']['state'] == 'ready' and result['syntax']['tokens'], 'Syntax warmup failed')
        require(get(origin, '/api/passage-analysis/status')['syntax']['state'] == 'ready', 'Syntax did not remain ready')


def public_read():
    result = get('https://greeklyric.com', '/api/search?q=apeira&mode=forms&author=Ibycus&limit=10')
    require(bool(result['results']), 'Public read failed')


def canary(image):
    old, original_routes = baseline()
    check_original(old)
    require(routes() == original_routes, 'Route snapshot changed')
    require(not exists(OLD), 'Prior QA29 promotion already exists')
    if exists(CANARY):
        previous = inspect(CANARY)
        require(previous['Image'] == BASE and not previous['State']['Running'], 'Existing canary is not stopped QA28')
        require(not exists('qa28-canary-retained'), 'Retained QA28 canary name exists')
        capture('docker', 'rename', CANARY, 'qa28-canary-retained')
    start(image, CANARY, 8792, old)
    require(gateway(CANARY) == load('snapshot.json')['gateway_sha256'], 'Gateway changed with shared runtime')
    warm(8792)
    require(routes() == original_routes, 'Canary operation changed routes')
    save('canary-start.json', {'image': image, 'canary_id': inspect(CANARY)['Id'], 'warm': True})


def promote(image):
    old, original_routes = baseline()
    check_original(old)
    candidate = inspect(CANARY)
    validate_candidate(candidate, old, image, 8792)
    receipt = load('canary-pass.json')
    require(receipt.get('passed') is True and receipt.get('image') == image
            and receipt.get('canary_id') == candidate['Id'], 'Canary pass receipt mismatch')
    require(not exists(OLD) and not exists('melos-api-qa29-failed'), 'Promotion retention names exist')
    require(routes() == original_routes, 'Route snapshot changed')
    require(gateway(CANARY) == gateway('melos-api') == load('snapshot.json')['gateway_sha256'], 'Gateway shared-runtime contract changed')
    warm(8792)
    public_read()
    try:
        route(original_routes, 8791, 8792)
        public_read()
        check_original(old)
        capture('docker', 'stop', '--time', '30', 'melos-api')
        capture('docker', 'rename', 'melos-api', OLD)
        start(image, 'melos-api', 8791, old)
        warm(8791)
        route(original_routes, 8792, 8791)
        public_read()
        require(inspect(CANARY)['Id'] == candidate['Id'], 'Canary identity changed')
        capture('docker', 'stop', '--time', '30', CANARY)
        verify(image)
        save('promotion-receipt.json', {'image': image, 'container_id': inspect('melos-api')['Id'],
                                      'retained_container_id': old['Id'], 'routes_preserved': True,
                                      'completed_at': time.time()})
    except BaseException:
        current = routes()
        require(current in (routed(original_routes, 8791), routed(original_routes, 8792)),
                'Concurrent route mutation: manual recovery required; routes untouched')
        if exists(OLD):
            prior = inspect(OLD)
            require(prior['Id'] == old['Id'] and prior['Image'] == BASE, 'Rollback identity mismatch')
            if current == routed(original_routes, 8791):
                spare = inspect(CANARY)
                require(spare['Id'] == candidate['Id'], 'Rollback canary identity mismatch')
                if not spare['State']['Running']:
                    capture('docker', 'start', CANARY)
                warm(8792)
                route(original_routes, 8791, 8792)
            if exists('melos-api'):
                failed = inspect('melos-api')
                require(failed['Image'] == image, 'Rollback candidate mismatch')
                capture('docker', 'stop', '--time', '30', 'melos-api')
                capture('docker', 'rename', 'melos-api', 'melos-api-qa29-failed')
            capture('docker', 'rename', OLD, 'melos-api')
        else:
            require(inspect('melos-api')['Id'] == old['Id'], 'Rollback original identity mismatch')
        capture('docker', 'start', 'melos-api')
        warm(8791, syntax=False)
        if routes() == routed(original_routes, 8792):
            route(original_routes, 8792, 8791)
        check_original(old)
        require(routes() == original_routes, 'Rollback routes mismatch')
        public_read()
        print('Rollback restored the exact prior container and routes.', flush=True)
        raise


def verify(image):
    old, original_routes = baseline()
    validate_candidate(inspect('melos-api'), old, image, 8791)
    require(routes() == original_routes, 'Production route configuration differs')
    require(inspect(OLD)['Id'] == old['Id'] and not inspect(OLD)['State']['Running'], 'Prior container not retained stopped')
    warm(8791)
    public_read()


def main():
    import fcntl
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'canary', 'promote', 'verify'))
    parser.add_argument('image', nargs='?')
    args = parser.parse_args()
    require(args.command == 'snapshot' or bool(re.fullmatch(r'sha256:[0-9a-f]{64}', args.image or '')), 'Immutable image ID required')
    require(RELEASE.is_dir(), 'Release directory missing')
    with (RELEASE / 'release.lock').open('a') as lock:
        os.chmod(RELEASE / 'release.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'snapshot':
            snapshot()
        else:
            globals()[args.command](args.image)
    print('QA29 ' + args.command + ' passed.', flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    main()
