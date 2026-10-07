"""Prepared, not deployed: audited five-module release over live Campbell data.

No corpus/index changes are supported. A new subentry index needs a separate
explicit artifact/loader contract; this helper rejects it rather than guessing.
Uses the established guarded route switch and exact-container rollback helper.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from urllib.parse import quote

import release_qa29 as release

BASE = 'sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777'
BASE_CONTAINER = '99ac41bf357439a2e07bb69cde3f279b6bf8ae8b89690c8cc7d9ee28be517460'
ROOT = Path('/home/alvin/services/melos')
RELEASE = ROOT / 'releases/lexical-20261007b'
CANARY = 'melos-api-lexical-canary-b'
OLD = 'melos-api-before-lexical-20261007b'
MODULES = frozenset(('lexicon_senses.py', 'interlinear.py', 'sense_ranker.py', 'passage_analysis.py', 'classifier.py'))
CAMPBELL = ROOT / 'releases/campbell-20261007b'
DATA_HASHES = {
    'corpus.sqlite': 'f57e0bdd5c27d9e6364319f0bb5789ee62aa5289abc249437e43380116ea0fc9',
    'manifest.json': '11739ed23b4d5ca6dc1bcf8be137b0edea4639a437776960d58645f709e69cca',
}
require, capture, inspect, exists = release.require, release.capture, release.inspect, release.exists


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def base_mounts():
    return sorted([
        ('/app/data', str(ROOT / 'data'), False, 'bind'),
        ('/app/runtime', str(ROOT / 'runtime'), True, 'bind'),
        ('/models', str(ROOT / 'models'), False, 'bind'),
        ('/syntax-model', str(ROOT / 'releases/qa29/model/pipeline'), False, 'bind'),
        ('/run/secrets/jev.env', str(ROOT / 'secrets/jev.env'), False, 'bind'),
        ('/app/data/corpus.sqlite', str(CAMPBELL / 'candidate-data/corpus.sqlite'), False, 'bind'),
        ('/app/data/embeddings/manifest.json', str(CAMPBELL / 'candidate-data/manifest.json'), False, 'bind'),
        ('/app/backend/interlinear.py', str(CAMPBELL / 'candidate-data/interlinear.py'), False, 'bind'),
        ('/app/backend/passage_analysis.py', str(CAMPBELL / 'candidate-data/passage_analysis.py'), False, 'bind'),
    ])


def module_hashes(container):
    output = capture('docker', 'exec', container, 'sha256sum',
                     *('/app/backend/' + name for name in sorted(MODULES)))
    result = {Path(path).name: digest for digest, path in
              (line.split(None, 1) for line in output.splitlines())}
    require(set(result) == MODULES, 'Module hash output differs')
    return result


def verify_data():
    for name, digest in DATA_HASHES.items():
        require(sha(CAMPBELL / 'candidate-data' / name) == digest, 'Live Campbell data changed: ' + name)
    manifest = json.loads((CAMPBELL / 'candidate-data/manifest.json').read_text())
    stat = (CAMPBELL / 'candidate-data/corpus.sqlite').stat()
    require((manifest['corpus_mtime_ns'], manifest['corpus_size']) == (stat.st_mtime_ns, stat.st_size),
            'Existing semantic corpus binding changed')
    return manifest


def snapshot():
    old = inspect('melos-api')
    require(old['Id'] == BASE_CONTAINER and old['Image'] == BASE and old['State']['Running'],
            'Exact live Campbell baseline required')
    require(release.mounts(old) == base_mounts(), 'Baseline mount contract changed')
    require(old['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8791'}]},
            'Baseline port differs')
    current = release.routes()
    require(current == release.routed(current, 8791), 'Current public route differs')
    require(current['AllowFunnel'] == {release.HOST: True}, 'Unexpected Funnel exposure')
    for port in (443, 80):
        require(current['Web'][f'basecamp.taila44c41.ts.net:{port}']['Handlers']['/']['Proxy'] == 'http://127.0.0.1:7680',
                'Private Basecamp route differs')
    verify_data()
    release.save('container-before.private.json', old)
    release.save('routes-before.private.json', current)
    release.save('snapshot.json', {'image': BASE, 'container_id': old['Id'],
        'gateway_sha256': release.gateway('melos-api'), 'module_sha256': module_hashes('melos-api'),
        'corpus_artifacts': DATA_HASHES, 'created_at': time.time()})


def approved_modules():
    receipt = release.load('modules-pass.json')
    before = release.load('snapshot.json')
    require(receipt.get('verdict') == 'PASS' and receipt.get('base_container_id') == BASE_CONTAINER
            and receipt.get('image') == BASE, 'Independent module approval baseline mismatch')
    files = receipt.get('files', {})
    require(set(files) == MODULES, 'Only the five explicitly scoped modules may ship')
    for name, row in files.items():
        require(row.get('verdict') == 'PASS' and row.get('baseline_sha256') == before['module_sha256'][name],
                'Module baseline approval differs: ' + name)
        require(sha(RELEASE / 'candidate-code' / name) == row.get('sha256'), 'Frozen module changed: ' + name)
    return files


def expected_binds(old):
    files = approved_modules()
    edits = {'/app/backend/' + name: str(RELEASE / 'candidate-code' / name) for name in files}
    binds = []
    for bind in old['HostConfig']['Binds']:
        source, destination, mode = bind.rsplit(':', 2)
        binds.append(f'{edits.pop(destination, source)}:{destination}:{mode}')
    binds.extend(f'{source}:{target}:ro' for target, source in sorted(edits.items()))
    return binds


def validate_candidate(container, old, image, port):
    require(image == BASE and container['Image'] == BASE and container['State']['Running'], 'Same image required')
    require(container['HostConfig']['PortBindings'] == {'8791/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]},
            'Candidate port differs')
    binds = expected_binds(old)
    require(sorted(container['HostConfig']['Binds']) == sorted(binds), 'Candidate binds differ')
    expected = sorted((b.rsplit(':', 2)[1], b.rsplit(':', 2)[0], b.rsplit(':', 2)[2] == 'rw', 'bind') for b in binds)
    require(release.mounts(container) == expected, 'Effective mounts differ')
    require(release.environment(container) == release.environment(old), 'Environment differs')
    for key in set(container['HostConfig']) | set(old['HostConfig']):
        if key not in ('PortBindings', 'Binds'):
            require(container['HostConfig'].get(key) == old['HostConfig'].get(key), 'HostConfig differs: ' + key)
    for key in ('User', 'Cmd', 'Entrypoint', 'WorkingDir'):
        require(container['Config'][key] == old['Config'][key], 'Runtime configuration differs: ' + key)
    require(module_hashes(container['Id']) == {name: row['sha256'] for name, row in approved_modules().items()},
            'Effective module bytes differ')
    started = RELEASE / 'canary-start.json'
    if started.exists():
        require(release.load('canary-start.json')['modules_pass_sha256'] == sha(RELEASE / 'modules-pass.json'),
                'Module approval changed since canary start')


def start(image, name, port, old):
    require((name, port) in ((CANARY, 8792), ('melos-api', 8791)), 'Invalid container target')
    require(image == BASE and not exists(name), 'Container target/image invalid')
    approved_modules()
    verify_data()
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
    for bind in expected_binds(old):
        args += ['-v', bind]
    args += [image] + old['Config']['Cmd']
    try:
        capture(*args)
    finally:
        env_path.unlink()
    validate_candidate(inspect(name), old, image, port)


def warm(port, syntax=True):
    # Candidate and rollback share the exact same corpus and vector artifacts.
    origin = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + 180
    while True:
        try:
            status = release.get(origin, '/api/status', timeout=5)
            require(status['passages'] == 288589, 'Corpus count differs')
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    manifest = verify_data()
    embeddings = status.get('embeddings', {})
    require(embeddings.get('ready') is True and embeddings.get('count') == 116191
            and embeddings.get('counts_by_source') == manifest['counts_by_source'], 'Semantic coverage differs')
    source = json.loads((CAMPBELL / 'integration-pass.json').read_text())
    for identifier, digest in source['text_sha256'].items():
        passage = release.get(origin, '/api/passage?id=' + quote(identifier, safe=''))
        require(hashlib.sha256(passage['text'].encode()).hexdigest() == digest, 'Campbell source text differs')
    result = release.get(origin, '/api/search?q=love&mode=themes&limit=3', timeout=240)
    require(bool(result.get('results')), 'Existing semantic search failed')
    if syntax:
        passage = release.get(origin, '/api/passage?id=dcc-sappho%3Abrothers-poem')
        text = passage['text']
        end = next((i for i in range(min(100, len(text)), min(200, len(text))) if text[i].isspace()), min(100, len(text)))
        analysis = release.get(origin, '/api/analyze-passage', {'version': 1,
            'passage_id': passage['id'], 'start': 0, 'end': end, 'offset_unit': 'codepoint',
            'selected_text': text[:end], 'rerank': False, 'fetch_machine': False}, timeout=240)
        require(analysis['syntax']['state'] == 'ready' and analysis['syntax']['tokens'], 'Syntax warmup failed')


def canary(image):
    old, routes = release.baseline()
    release.check_original(old)
    require(release.routes() == routes, 'Routes changed since snapshot')
    require(not exists(OLD), 'Retained promotion name exists')
    if exists(CANARY):
        validate_candidate(inspect(CANARY), old, image, 8792)
    else:
        start(image, CANARY, 8792, old)
    warm(8792)
    require(release.gateway(CANARY) == release.load('snapshot.json')['gateway_sha256'], 'Shared gateway changed')
    require(release.routes() == routes, 'Canary modified routes')
    release.save('canary-start.json', {'image': image, 'canary_id': inspect(CANARY)['Id'], 'warm': True,
        'modules_pass_sha256': sha(RELEASE / 'modules-pass.json')})


def main():
    import fcntl
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'canary', 'promote', 'verify'))
    args = parser.parse_args()
    require(RELEASE.is_dir(), 'Release directory missing')
    for name in ('BASE', 'RELEASE', 'OLD', 'CANARY', 'start', 'validate_candidate', 'warm', 'canary'):
        setattr(release, name, globals()[name])
    with (RELEASE / 'release.lock').open('a') as lock:
        os.chmod(RELEASE / 'release.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'snapshot':
            snapshot()
        else:
            getattr(release, args.command)(BASE)
    print('Lexical ' + args.command + ' passed.')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    main()
