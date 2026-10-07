"""Basecamp discovery code-only release layered on the verified QA29 image.

Uses QA29's audited routing/rollback procedure with an exact seven-mount,
environment and security configuration clone. All receipts are owner-only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import time

import release_qa29 as release

BASE = 'sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777'
ROOT = Path('/home/alvin/services/melos')
RELEASE = ROOT / 'releases/discovery-20261006'
CANARY = 'melos-api-discovery-canary'
OLD = 'melos-api-before-discovery'
require = release.require
capture = release.capture
inspect = release.inspect
exists = release.exists
_qa29_warm = release.warm


def warm(port, syntax=True):
    _qa29_warm(port, syntax=syntax)
    if not syntax:
        return  # Restoring the exact QA29 baseline, which has no discovery API.
    origin = f'http://127.0.0.1:{port}'
    semantic = release.get(origin, '/api/search?q=love&mode=themes&limit=3', timeout=240)
    require(bool(semantic.get('results')), 'Semantic warmup failed')
    dictionary = release.get(origin, '/api/lexicon?limit=3', timeout=240)
    require(bool(dictionary.get('results')), 'Dictionary warmup failed')
    result = release.get(origin, '/api/theme-search?q=love%20and%20longing&author=Sappho&unit=line&limit=3', timeout=240)
    require(result['search_contract']['child_semantic_reranking']['available'] is True,
            'Child semantic warmup failed')


def snapshot():
    old = inspect('melos-api')
    require(old['Image'] == BASE and old['State']['Running'], 'QA29 baseline not running')
    require(old['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8791'}]}, 'Production port differs')
    expected = [('/app/data', str(ROOT / 'data'), False, 'bind'),
                ('/app/runtime', str(ROOT / 'runtime'), True, 'bind'),
                ('/models', str(ROOT / 'models'), False, 'bind'),
                ('/run/secrets/jev.env', str(ROOT / 'secrets/jev.env'), False, 'bind'),
                ('/app/data/corpus.sqlite', str(ROOT / 'releases/qa27/candidate-data/corpus.sqlite'), False, 'bind'),
                ('/app/data/embeddings/manifest.json', str(ROOT / 'releases/qa27/candidate-data/manifest.json'), False, 'bind'),
                ('/syntax-model', str(ROOT / 'releases/qa29/model/pipeline'), False, 'bind')]
    require(release.mounts(old) == sorted(expected), 'Baseline seven-mount contract differs')
    routes = release.routes()
    require(routes == release.routed(routes, 8791), 'Public route differs')
    require(routes['AllowFunnel'] == {release.HOST: True}, 'Unexpected public exposure')
    for port in (443, 80):
        require(routes['Web'][f'basecamp.taila44c41.ts.net:{port}']['Handlers']['/']['Proxy'] == 'http://127.0.0.1:7680', 'Private route differs')
    release.save('container-before.private.json', old)
    release.save('routes-before.private.json', routes)
    release.save('snapshot.json', {'release': 'discovery-20261006', 'image': BASE,
                 'container_id': old['Id'], 'gateway_sha256': release.gateway('melos-api'),
                 'created_at': time.time()})


def validate_candidate(container, old, image, port):
    require(container['Image'] == image and container['State']['Running'], 'Candidate image/state differs')
    require(container['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}, 'Candidate port differs')
    require(release.mounts(container) == release.mounts(old), 'Mount contract changed')
    require(sorted(container['HostConfig']['Binds']) == sorted(old['HostConfig']['Binds']), 'Bind contract changed')
    require(release.environment(container) == release.environment(old), 'Environment contract changed')
    for key in set(container['HostConfig']) | set(old['HostConfig']):
        if key in ('PortBindings', 'Binds'):
            continue
        require(container['HostConfig'].get(key) == old['HostConfig'].get(key), 'HostConfig changed: ' + key)
    for key in ('User', 'Cmd', 'Entrypoint', 'WorkingDir'):
        require(container['Config'][key] == old['Config'][key], 'Container configuration changed: ' + key)


def start(image, name, port, old):
    require((name, port) in (('melos-api', 8791), (CANARY, 8792)), 'Invalid container target')
    require(not exists(name), 'Target container exists')
    require(json.loads(capture('docker', 'image', 'inspect', image))[0]['Id'] == image, 'Immutable image missing')
    args = ['docker', 'run', '-d', '--name', name, '--restart', 'unless-stopped',
            '--cpus=2', '--cpu-shares=256', '--memory=8g', '--memory-swap=8g', '--pids-limit=128',
            '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--user=1000:1000', '--log-driver=local',
            '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3', '-p', f'127.0.0.1:{port}:8791']
    env_path = RELEASE / f'{name}.env.private'
    values = release.environment(old)
    require(all('\n' not in value and '\r' not in value for value in values.values()), 'Multiline environment unsupported')
    with os.fdopen(os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    args += ['--env-file', str(env_path)]
    # Preserve original bind order as well as effective mounts.
    for bind in old['HostConfig']['Binds']:
        args += ['-v', bind]
    args += [image] + old['Config']['Cmd']
    try:
        capture(*args)
    finally:
        env_path.unlink()
    validate_candidate(inspect(name), old, image, port)


def canary(image):
    old, routes = release.baseline()
    release.check_original(old)
    require(release.routes() == routes, 'Routes changed since snapshot')
    require(not exists(OLD), 'Promotion retention name exists')
    if exists(CANARY):
        validate_candidate(inspect(CANARY), old, image, 8792)
    else:
        start(image, CANARY, 8792, old)
    require(release.gateway(CANARY) == release.load('snapshot.json')['gateway_sha256'], 'Shared runtime gateway changed')
    release.warm(8792)
    require(release.routes() == routes, 'Canary operation changed routing')
    release.save('canary-start.json', {'image': image, 'canary_id': inspect(CANARY)['Id'], 'warm': True})


def smoke(image):
    old, routes = release.baseline()
    candidate = inspect(CANARY)
    validate_candidate(candidate, old, image, 8792)
    require(release.routes() == routes, 'Canary route changed')
    annotation_result = capture('python3', str(RELEASE / 'validate_discovery_annotations.py'))
    annotations = json.loads(annotation_result)
    if (RELEASE / 'annotation-check.json').exists():
        require(release.load('annotation-check.json') == annotations, 'Annotation receipt differs')
    else:
        release.save('annotation-check.json', annotations)
    for script in ('smoke_backend.py', 'qa_regressions.py', 'qa29_features.py', 'discovery_smoke.py'):
        command = ['python3', str(RELEASE / script), '--origin', 'http://127.0.0.1:8792']
        if script == 'smoke_backend.py':
            command += ['--expected-passages', '288584']
        if script == 'qa_regressions.py':
            command += ['--cgl']
        output = capture(*command)
        with os.fdopen(os.open(RELEASE / (script + '.result.txt'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as stream:
            stream.write(output)
    release.save('canary-pass.json', {'passed': True, 'image': image,
                 'canary_id': candidate['Id'], 'completed_at': time.time()})


def main():
    import fcntl
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'canary', 'smoke', 'promote', 'verify'))
    parser.add_argument('image', nargs='?')
    args = parser.parse_args()
    require(args.command == 'snapshot' or bool(re.fullmatch(r'sha256:[0-9a-f]{64}', args.image or '')), 'Immutable image ID required')
    require(RELEASE.is_dir(), 'Release directory missing')
    for name, value in {'BASE': BASE, 'RELEASE': RELEASE, 'OLD': OLD, 'CANARY': CANARY,
                        'snapshot': snapshot, 'start': start, 'validate_candidate': validate_candidate,
                        'canary': canary, 'warm': warm}.items():
        setattr(release, name, value)
    # Reuse QA29's verified promotion and automatic rollback implementation.
    # Its failed-container retention name is unchanged, and preflight requires
    # that this name is absent before any production changes.
    with (RELEASE / 'release.lock').open('a') as lock:
        os.chmod(RELEASE / 'release.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'snapshot':
            snapshot()
        elif args.command == 'smoke':
            smoke(args.image)
        else:
            getattr(release, args.command)(args.image)
    print('Discovery ' + args.command + ' passed.', flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    main()
