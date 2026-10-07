"""Same-image QA29 corpus and narrowly audited tokenizer canary/promotion.

Run on Basecamp from releases/campbell-20261007b. No secrets are changed. The only
permitted code overlays are independently approved passage_analysis.py and
interlinear.py, for token handling and source-bound dictionary joins.
A tested old-container rollback and route guard come from release_qa29.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import release_qa29 as release

BASE = 'sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777'
ROOT = Path('/home/alvin/services/melos')
RELEASE = ROOT / 'releases/campbell-20261007b'
CANARY = 'melos-api-campbell-canary-v2'
OLD = 'melos-api-before-campbell'
require, capture, inspect, exists = release.require, release.capture, release.inspect, release.exists


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replacements():
    """Auditor defines exactly the release artifacts, never arbitrary bind mounts."""
    receipt = release.load('integration-pass.json')
    require(receipt.get('verdict') == 'PASS', 'Independent integration PASS required')
    require(len(receipt.get('added_ids', [])) == 5, 'Five assignment IDs required')
    artifacts = receipt['artifacts']
    require('corpus.sqlite' in artifacts and 'manifest.json' in artifacts, 'Core candidate artifacts missing')
    result = {}
    for name, digest in artifacts.items():
        require(Path(name).name == name and '\\' not in name, 'Artifact path is unsafe')
        require(name in ('corpus.sqlite', 'manifest.json', 'passage_analysis.py', 'interlinear.py') or name.startswith(('rows-campbell-', 'vectors-campbell-')),
                'Artifact exceeds corpus/embedding scope')
        path = RELEASE / 'candidate-data' / name
        require(path.is_file() and sha(path) == digest, 'Audited candidate hash mismatch: ' + name)
        target = ('/app/backend/' + name if name in ('passage_analysis.py', 'interlinear.py')
                  else '/app/data/corpus.sqlite' if name == 'corpus.sqlite'
                  else '/app/data/embeddings/' + name)
        result[target] = str(path)
    manifest = json.loads((RELEASE / 'candidate-data/manifest.json').read_text())
    stat = (RELEASE / 'candidate-data/corpus.sqlite').stat()
    require((manifest.get('corpus_mtime_ns'), manifest.get('corpus_size')) == (stat.st_mtime_ns, stat.st_size),
            'Candidate semantic manifest stat binding differs')
    embedded = manifest.get('corpus_rebinding', {}).get('new_ids_embedded') is True
    expected = {'corpus.sqlite', 'manifest.json'}
    patches = receipt.get('backend_patches', [])
    require(len(patches) == 2 and {p.get('path') for p in patches} ==
            {'backend/passage_analysis.py', 'backend/interlinear.py'}, 'Two exact backend patch approvals required')
    for patch in patches:
        name = Path(patch['path']).name
        require(patch.get('verdict') == 'PASS' and patch.get('sha256') == artifacts.get(name),
                'Narrow backend patch approval differs')
        expected.add(name)
    if embedded:
        expected.update((manifest['rows_file'], manifest['vectors_file']))
    require(set(artifacts) == expected, 'Audited artifact set does not match exact semantic manifest references')
    require(receipt.get('semantic_count') == manifest.get('count'), 'Audited semantic count differs')
    require(set(receipt.get('text_sha256', {})) == set(receipt['added_ids']), 'Full text hashes missing from receipt')
    return result


def expected_binds(old):
    edits = replacements()
    binds = []
    for bind in old['HostConfig']['Binds']:
        source, destination, mode = bind.rsplit(':', 2)
        binds.append(f'{edits.pop(destination, source)}:{destination}:{mode}')
    binds.extend(f'{source}:{target}:ro' for target, source in sorted(edits.items()))
    return binds


def snapshot():
    old = inspect('melos-api')
    require(old['Image'] == BASE and old['State']['Running'], 'Exact QA29 baseline required')
    require(old['Id'].startswith('cc62bec35b7b'), 'Unexpected current container identity')
    current = release.routes()
    require(current == release.routed(current, 8791), 'Current public route mismatch')
    require(current['AllowFunnel'] == {release.HOST: True}, 'Unexpected Funnel exposure')
    for port in (443, 80):
        require(current['Web'][f'basecamp.taila44c41.ts.net:{port}']['Handlers']['/']['Proxy'] == 'http://127.0.0.1:7680',
                'Private Basecamp route differs')
    release.save('container-before.private.json', old)
    release.save('routes-before.private.json', current)
    release.save('snapshot.json', {'image': BASE, 'container_id': old['Id'],
        'gateway_sha256': release.gateway('melos-api'), 'created_at': time.time()})


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
        require(container['Config'][key] == old['Config'][key], 'Runtime configuration differs')


def start(image, name, port, old):
    require((name, port) in ((CANARY, 8792), ('melos-api', 8791)), 'Invalid container target')
    require(image == BASE and not exists(name), 'Container target/image invalid')
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
    origin = f'http://127.0.0.1:{port}'
    count = 288589 if syntax else 288584  # rollback retains the unmodified old corpus
    deadline = time.monotonic() + 180
    while True:
        try:
            status = release.get(origin, '/api/status', timeout=5)
            require(status['passages'] == count, 'Corpus count mismatch')
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    embeddings = status.get('embeddings', {})
    expected_count = release.load('integration-pass.json')['semantic_count'] if syntax else 116191
    require(embeddings.get('ready') is True and embeddings.get('count') == expected_count,
            'Semantic readiness/coverage differs')
    if syntax:
        manifest = json.loads((RELEASE / 'candidate-data/manifest.json').read_text())
        require(embeddings.get('counts_by_source') == manifest.get('counts_by_source'), 'Semantic source coverage differs')
    result = release.get(origin, '/api/search?q=love&mode=themes&limit=3', timeout=240)
    require(bool(result.get('results')), 'Existing semantic coverage unavailable')
    if syntax:
        from urllib.parse import quote
        for identifier in release.load('integration-pass.json')['added_ids']:
            passage = release.get(origin, '/api/passage?id=' + quote(identifier, safe=''))
            require(passage['id'] == identifier and passage.get('text'), 'Assignment text missing')
            require(hashlib.sha256(passage['text'].encode()).hexdigest() ==
                    release.load('integration-pass.json')['text_sha256'][identifier], 'Full assignment text differs')
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
    release.save('canary-start.json', {'image': image, 'canary_id': inspect(CANARY)['Id'], 'warm': True})


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
    print('Campbell ' + args.command + ' passed.')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Terminated')))
    main()
