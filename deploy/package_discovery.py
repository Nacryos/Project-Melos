"""Freeze the allowlisted discovery patch against retrieved QA29 source."""
import ast
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BASE_SERVER = '16ffa671afc26a25480000648811118b2d1daf7d851179ea09b25968d9776c7e'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', choices=('v1', 'v2', 'v3'), default='v1')
    args = parser.parse_args()
    suffix = '' if args.revision == 'v1' else '-' + args.revision
    stage = ROOT / ('.benchmarks/discovery-package' + suffix)
    if stage.exists():
        raise RuntimeError('Frozen stage already exists; choose a fresh reviewed release')
    source = (ROOT / '.benchmarks/discovery-baseline/backend/server.py').read_bytes()
    assert hashlib.sha256(source).hexdigest() == BASE_SERVER
    server = source.decode().replace('\r\n', '\n')
    before = "    for item in merged.values():\n        item['merged']=len(item['labels'])>1\n"
    after = before + "        item['author_chronology']=author_chronology(item['author'])\n"
    assert server.count(before) == 1
    server = server.replace(before, after)
    anchor = "for directory in ('js','css'):"
    assert server.count(anchor) == 1
    server = server.replace(anchor, "from .discovery import router as discovery_router\napp.include_router(discovery_router)\n\n" + anchor)
    ast.parse(server)
    (stage / 'backend').mkdir(parents=True)
    (stage / 'discovery-data').mkdir()
    (stage / 'backend/server.py').write_text(server, encoding='utf-8', newline='\n')
    for name in ('discovery.py', 'discovery_units.py', 'visual_themes.py'):
        ast.parse((ROOT / 'backend' / name).read_text(encoding='utf-8'))
        shutil.copyfile(ROOT / 'backend' / name, stage / 'backend' / name)
    shutil.copyfile(ROOT / 'data/annotations/visual-themes/validated.json', stage / 'discovery-data/validated.json')
    shutil.copyfile(ROOT / 'deploy/Dockerfile.discovery', stage / 'Dockerfile')
    manifest = {str(path.relative_to(stage)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(stage.rglob('*')) if path.is_file()}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = ROOT / ('.benchmarks/discovery-package' + suffix + '.tar.gz')
    with tarfile.open(archive, 'x:gz') as tar:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(stage)).replace('\\', '/'))
    print(json.dumps({'files': manifest, 'archive': str(archive),
                      'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
