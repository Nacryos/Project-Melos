"""Verify and build the exact frozen discovery context on Basecamp, offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path('/home/alvin/services/melos/releases/discovery-20261006')
FILES = {'Dockerfile', 'backend/server.py', 'backend/discovery.py',
         'backend/discovery_units.py', 'backend/visual_themes.py',
         'discovery-data/validated.json', 'manifest.json'}
BASE = 'sha256:2f60b62520d88098663fa79e2cb76cdeae8b7540e24752d586df042fc09d1777'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sha256')
    parser.add_argument('--revision', choices=('v1', 'v2', 'v3'), default='v1')
    args = parser.parse_args()
    os.umask(0o077)
    suffix = '' if args.revision == 'v1' else '-' + args.revision
    archive = ROOT / ('package' + suffix + '.tar.gz')
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == args.sha256, 'Archive hash differs'
    stage = ROOT / ('context' + suffix)
    stage.mkdir(exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        assert len(members) == len(FILES) and {m.name for m in members} == FILES
        for member in members:
            assert member.isfile() and member.size < 10_000_000
            target = stage / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member).read()
            if target.exists():
                assert target.read_bytes() == data, 'Existing stage differs'
            else:
                target.write_bytes(data)
    manifest = json.loads((stage / 'manifest.json').read_text())
    assert set(manifest) == FILES - {'manifest.json'}
    for name, digest in manifest.items():
        assert hashlib.sha256((stage / name).read_bytes()).hexdigest() == digest, name
    baseline = json.loads(subprocess.check_output(['docker', 'inspect', 'melos-api']))[0]
    assert baseline['Image'] == BASE and baseline['State']['Running']
    base_tag = 'melos-api:discovery-base-qa29'
    subprocess.run(['docker', 'tag', BASE, base_tag], check=True)
    assert json.loads(subprocess.check_output(['docker', 'image', 'inspect', base_tag]))[0]['Id'] == BASE
    with (ROOT / ('build' + suffix + '.log')).open('a') as log:
        subprocess.run(['docker', 'build', '--network=none', '--pull=false',
                        '--build-arg', 'BASE_IMAGE=' + base_tag, '--iidfile',
                        str(ROOT / ('image-id' + suffix)), '-t', 'melos-api:20261006-discovery' + suffix, str(stage)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print(json.dumps({'image': (ROOT / ('image-id' + suffix)).read_text().strip(),
                      'archive_sha256': args.sha256, 'files_verified': len(manifest)}))


if __name__ == '__main__':
    main()
