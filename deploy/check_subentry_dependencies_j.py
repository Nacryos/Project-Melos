"""Read-only exact live-I prerequisites for the proposed J subentry index."""
import hashlib
import json
from pathlib import Path
import shlex
from discovery_transport import connect, run
from lexical_baseline_j import BASE_CONTAINER

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest_path = ROOT / 'runtime/machine-subentry-local-release/dependency-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {row['path']: row for row in manifest['required_existing_or_packaged']}
    for path in expected:
        if '..' in Path(path).parts or not path.startswith(('data/lexica/', 'data/raw/lexica/', 'backend/')):
            raise ValueError('Dependency path outside source/code scope')
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != BASE_CONTAINER or not info['State']['Running']:
            raise ValueError('Exact live I required')
        code = ('import hashlib,json;from pathlib import Path;names=' + repr(sorted(expected)) + ';'
                'print(json.dumps({name:{"sha256":hashlib.file_digest((Path("/app")/name).open("rb"),"sha256").hexdigest(),'
                '"bytes":(Path("/app")/name).stat().st_size} if (Path("/app")/name).is_file() else None for name in names}))')
        actual = json.loads(run(client, 'docker exec melos-api python -c ' + shlex.quote(code)))
    finally:
        client.close()
    matches = {name: bool(actual.get(name) and actual[name]['sha256'] == row['sha256'] and actual[name]['bytes'] == row['bytes'])
               for name, row in expected.items()}
    receipt = {'status': 'PASS' if all(matches.values()) else 'MISMATCH', 'container_id': BASE_CONTAINER,
               'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
               'actual_files': actual, 'exact_matches': matches, 'writes': 0}
    output = ROOT / 'runtime/lexical-release-j/dependency-preflight.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps({'path': str(output), 'status': receipt['status'], 'count': len(actual),
                      'mismatches': [name for name, match in matches.items() if not match]}))


if __name__ == '__main__':
    main()
