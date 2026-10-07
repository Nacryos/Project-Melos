"""Read-only hash proof for reusing v1 word/dictionary checks on v2."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
from discovery_transport import connect, run

MODULES = ('server.py', 'morphology.py', 'wiktionary.py')


def capture(client, container):
    info = json.loads(run(client, 'docker inspect ' + shlex.quote(container)))[0]
    if not info['HostConfig']['ReadonlyRootfs']:
        raise RuntimeError('Container root is not immutable')
    targets = ['/app/backend/' + module for module in MODULES]
    for mount in info['Mounts']:
        if any(target == mount['Destination'] or target.startswith(mount['Destination'].rstrip('/') + '/')
               for target in targets):
            raise RuntimeError('Lexical source module is overlaid')
    if info['State']['Running']:
        command = ['docker', 'exec', container, 'sha256sum', *targets]
        method = 'running container source bytes'
    else:
        command = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                   '--entrypoint', 'sha256sum', info['Image'], *targets]
        method = 'immutable image bytes; stopped container root is read-only and target modules have no mounts'
    output = run(client, shlex.join(command)).decode()
    hashes = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in output.splitlines())}
    if set(hashes) != set(MODULES):
        raise RuntimeError('Module hash output differs')
    return {'container_id': info['Id'], 'image': info['Image'], 'modules': hashes,
            'hash_method': method,
            'backend_mounts': [{'path': m['Destination'], 'source': m['Source'], 'read_only': not m['RW']}
                               for m in info['Mounts'] if m['Destination'].startswith('/app/backend')]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Proof output already exists; do not overwrite historical evidence')
    client = connect()
    try:
        before = capture(client, 'melos-api-campbell-canary')
        after = capture(client, 'melos-api-campbell-canary-v2')
    finally:
        client.close()
    if before['image'] != after['image'] or before['modules'] != after['modules']:
        raise RuntimeError('Lexical endpoint module/image mismatch')
    allowed = {'/app/backend/passage_analysis.py', '/app/backend/interlinear.py'}
    if any(m['path'] not in allowed or not m['read_only'] for row in (before, after) for m in row['backend_mounts']):
        raise RuntimeError('Unexpected backend overlay')
    result = {'method': 'pinned SSH; docker inspect plus source-byte SHA256 with immutable-image binding for stopped containers',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'equal': True,
              'unchanged_endpoints': ['/api/word', '/api/wiktionary'], 'before': before, 'after': after,
              'limitation': 'Corpus citation metadata changed; caller must separately revalidate exact Greek context hashes. Runtime caches are shared, not asserted immutable.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(args.output), 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(), 'equal': True}))


if __name__ == '__main__':
    main()
