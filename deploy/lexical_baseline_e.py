"""Read-only pinned-host baseline for the prospective E code/commentary overlay."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex

from discovery_transport import connect, run

ROOT = Path(__file__).resolve().parents[1]
BASE_CONTAINER = '71c6555a265f83a01f781e3673a815a073c2ed9bc7f8153d36297b8f6797b0c0'
BASE_IMAGE = 'sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777'
NEW_FILES = frozenset(('syntax_context.py', 'edition_commentary.py', 'edition_commentary_data.json'))
FILES = NEW_FILES | frozenset(('server.py', 'passage_analysis.py', 'passage_ranker.py',
    'sense_ranker.py', 'syntax_provider.py', 'classifier.py', 'interlinear.py',
    'lexicon_senses.py', 'lexical_variants.py', 'candidate_senses.py', 'evidence.py',
    'textutils.py', 'phrase_meaning.py', 'translation_languages.py', 'normalization_contract.py',
    'source_grammar.py', 'publication.py', 'lexicon_render.py', 'morphology.py', 'wiktionary.py'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != BASE_CONTAINER or info['Image'] != BASE_IMAGE or not info['State']['Running']:
            raise RuntimeError('Exact live D baseline required')
        remote_code = ('import base64,json;from pathlib import Path;names=' + repr(sorted(FILES)) + ';'
            'print(json.dumps({name:base64.b64encode((Path("/app/backend")/name).read_bytes()).decode() '
            'if (Path("/app/backend")/name).is_file() else None for name in names}))')
        payload = json.loads(run(client, 'docker exec melos-api python -c ' + shlex.quote(remote_code)))
        if set(payload) != FILES:
            raise RuntimeError('Baseline file inventory differs')
        current = json.loads(run(client, 'docker inspect melos-api'))[0]
        if current['Id'] != info['Id'] or current['Mounts'] != info['Mounts']:
            raise RuntimeError('Live container changed during read')
    finally:
        client.close()
    folder = ROOT / '.benchmarks/lexical-e-baseline' / BASE_CONTAINER
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
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
        'mounts': info['Mounts'], 'read_only_root': info['HostConfig']['ReadonlyRootfs'],
        'read_at': datetime.now(timezone.utc).isoformat(),
        'method': 'Pinned SSH; exact running D source bytes only. No environment values saved. No remote changes.'}
    target = folder / 'baseline.json'
    if not target.exists():
        target.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), 'sha256': sha(target.read_bytes()), 'files': files}, indent=2))


if __name__ == '__main__':
    main()
