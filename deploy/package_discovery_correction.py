"""Freeze only discovery.py for the editorial-only candidate correction."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    stage = ROOT / '.benchmarks/discovery-correction-package'
    stage.mkdir()
    (stage / 'backend').mkdir()
    source = ROOT / 'backend/discovery.py'
    ast.parse(source.read_text(encoding='utf-8'))
    shutil.copyfile(source, stage / 'backend/discovery.py')
    (stage / 'Dockerfile').write_text(
        'ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nCOPY --chown=1000:1000 backend/discovery.py /app/backend/discovery.py\n')
    manifest = {str(path.relative_to(stage)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(stage.rglob('*')) if path.is_file()}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = ROOT / '.benchmarks/discovery-correction-package.tar.gz'
    with tarfile.open(archive, 'x:gz') as tar:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(stage)).replace('\\', '/'))
    print(json.dumps({'files': manifest, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))
