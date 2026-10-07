"""Save pinned upstream Perseids archive after independent source-discovery PASS.

No archive extraction, execution, parser requests or production connections.
"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runtime/perseids-offline-eval'
REVISION = 'ab6898ffed335fc6169fa02c9940657a9b5a78e0'
URL = 'https://codeload.github.com/perseids-tools/morpheus/tar.gz/' + REVISION
EXPECTED = '1bbd436396fb1c8a08364698acc0e1ff8c98dec43cbed82a10631531a5aac610'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    gate = json.loads((OUT / 'audit/source-discovery.json').read_text())
    if gate.get('verdict') != 'PASS' or gate.get('url') != URL or gate.get('revision') != REVISION:
        raise ValueError('Independent source discovery PASS missing')
    if gate.get('acquisition_script_sha256') != sha(Path(__file__).read_bytes()):
        raise ValueError('Acquisition code changed after audit')
    raw_path = OUT / 'raw/morpheus.tar.gz'
    if raw_path.exists():
        raise ValueError('Raw archive already exists; no implicit redownload')
    with urllib.request.urlopen(URL, timeout=30) as response:
        if response.status != 200:
            raise ValueError('Non-200 source response')
        raw = response.read(30*1024*1024+1)
    if len(raw) > 30*1024*1024 or sha(raw) != EXPECTED:
        raise ValueError('Source size/hash mismatch')
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open('xb') as target:
        target.write(raw)
    rows, seen = [], set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        members = tar.getmembers()
        if sum(m.size for m in members) > 80*1024*1024:
            raise ValueError('Expanded archive exceeded bound')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != 'morpheus-' + REVISION or '..' in parts
                    or member.name.startswith('/') or '\\' in member.name or ':' in member.name):
                raise ValueError('Unsafe archive path')
            if member.isdir():
                continue
            if not member.isfile() or member.name in seen:
                raise ValueError('Non-regular or duplicate archive member')
            seen.add(member.name)
            relative = '/'.join(parts[1:])
            data = tar.extractfile(member).read()
            rows.append({'path': relative, 'size': len(data), 'sha256': sha(data)})
            if relative in ('LICENSE', 'README.md') or any(x in PurePosixPath(relative).name.lower() for x in ('license','copying','copyright','notice')):
                dest = OUT / 'notices' / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as target:
                    target.write(data)
    rows.sort(key=lambda row: row['path'])
    result = {'revision': REVISION, 'url': URL, 'archive_sha256': EXPECTED,
              'archive_bytes': len(raw), 'acquisition_script_sha256': sha(Path(__file__).read_bytes()),
              'files': rows, 'source_executed': False}
    with (OUT / 'archive-manifest.json').open('x', encoding='utf-8') as target:
        target.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'files':len(rows), 'archive_sha256':EXPECTED, 'source_executed':False}))


if __name__ == '__main__':
    main()
