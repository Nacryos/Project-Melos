"""Read-only exact live F code/data identity before G candidate construction."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex

from discovery_transport import connect, run
from lexical_baseline_f import FILES as F_FILES, BASE_IMAGE

ROOT = Path(__file__).resolve().parents[1]
BASE_CONTAINER = 'e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52'
NEW_FILES = frozenset(('noun_entry_features.py', 'editorial_readings.py', 'editorial_analysis.py'))
FILES = F_FILES | NEW_FILES | frozenset(('machine_morphology.py', 'classifier.py'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != BASE_CONTAINER or info['Image'] != BASE_IMAGE or not info['State']['Running']:
            raise RuntimeError('Exact live F baseline required')
        code = ('import base64,json;from pathlib import Path;names=' + repr(sorted(FILES)) + ';'
                'print(json.dumps({name:base64.b64encode((Path("/app/backend")/name).read_bytes()).decode() '
                'if (Path("/app/backend")/name).is_file() else None for name in names}))')
        payload = json.loads(run(client, 'docker exec melos-api python -c ' + shlex.quote(code)))
        code = ('import hashlib,json;from pathlib import Path;names=["evidence.sqlite","wiktionary.sqlite","corpus.sqlite","embeddings/manifest.json"];'
                'print(json.dumps({name:{"sha256":hashlib.file_digest((Path("/app/data")/name).open("rb"),"sha256").hexdigest(),'
                '"bytes":(Path("/app/data")/name).stat().st_size} for name in names}))')
        source_indexes = json.loads(run(client, 'docker exec melos-api python -c ' + shlex.quote(code)))
        current = json.loads(run(client, 'docker inspect melos-api'))[0]
        if current['Id'] != info['Id'] or current['Mounts'] != info['Mounts']:
            raise RuntimeError('Live container changed during read')
    finally:
        client.close()
    folder = ROOT / '.benchmarks/lexical-g-baseline' / BASE_CONTAINER
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    if set(payload) != FILES:
        raise RuntimeError('Baseline inventory differs')
    for name in sorted(FILES):
        content = payload[name]
        if name in NEW_FILES:
            if content is not None:
                raise RuntimeError('Prospective new file already exists: ' + name)
            files[name] = {'sha256': None, 'baseline_absent': True}
            continue
        if content is None:
            raise RuntimeError('Required baseline module missing: ' + name)
        data = base64.b64decode(content, validate=True)
        target = folder / name
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError('Frozen baseline differs: ' + name)
        if not target.exists():
            target.write_bytes(data)
        files[name] = {'sha256': sha(data), 'bytes': len(data), 'local_path': str(target)}
    receipt = {'container_id': info['Id'], 'image': info['Image'], 'files': files,
               'source_indexes': source_indexes, 'mounts': info['Mounts'],
               'read_only_root': info['HostConfig']['ReadonlyRootfs'],
               'read_at': datetime.now(timezone.utc).isoformat(),
               'method': 'Pinned SSH exact running F bytes and source/corpus hashes; no secrets or remote changes.'}
    target = folder / 'baseline.json'
    if target.exists():
        old = json.loads(target.read_text(encoding='utf-8'))
        if old['files'] != files or old['source_indexes'] != source_indexes:
            raise RuntimeError('Prior baseline evidence differs')
    else:
        target.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), 'sha256': sha(target.read_bytes()), 'file_count': len(files),
                      'source_indexes': source_indexes}, indent=2))


if __name__ == '__main__':
    main()
