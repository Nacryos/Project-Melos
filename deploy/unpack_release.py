"""Verify and unpack one frozen QA29 artifact without overwriting a release."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=('code', 'model'))
    args = parser.parse_args()
    root = Path('/home/alvin/services/melos/releases/qa29')
    manifest = json.loads((root / 'package.json').read_text())[args.component]
    archive = root / manifest['archive']
    assert archive.stat().st_size == manifest['bytes']
    assert sha(archive) == manifest['sha256'], 'Archive hash mismatch'
    destination = root / args.component
    expected = {item['path']: item for item in manifest['files']}
    assert len(expected) == len(manifest['files'])
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        assert len(members) == len(expected)
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert member.name in expected and member.size == expected[member.name]['size']
        destination.mkdir(mode=0o755, exist_ok=False)
        bundle.extractall(destination, members=members, filter='data')
    for item in expected.values():
        path = destination / item['path']
        assert sha(path) == item['sha256'], 'Extracted hash mismatch: ' + item['path']
        path.chmod(0o644)
    for path in destination.rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
    print(f'{args.component}: {len(expected)} files verified and extracted.', flush=True)

if __name__ == '__main__':
    main()
