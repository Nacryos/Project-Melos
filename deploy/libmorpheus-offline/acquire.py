"""Audit-bound inert acquisition of exactly pinned engine and declared data."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runtime/libmorpheus-offline-eval'
SPECS = {
    'code': ('https://codeload.github.com/defense-humanites/libmorpheus/tar.gz/9005feb4dcd85c7898899ee3abc2782519f8f050',
             'libmorpheus-9005feb4dcd85c7898899ee3abc2782519f8f050',
             '06ba749e0a4cb0e90bd0842492af1ee5fde52cd4d62927fec345d1b5784e101b'),
    'data': ('https://codeload.github.com/alpheios-project/morpheus/tar.gz/4632415fe93c85e9fdca47a0c5a13f31385f0023',
             'morpheus-4632415fe93c85e9fdca47a0c5a13f31385f0023',
             'ae25bb469c419291463fd1441e3beac011c56df68092020a633c977d1c13bcd0'),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    gate = json.loads((OUT / 'audit/source-discovery.json').read_text())
    if gate.get('verdict') != 'PASS' or gate.get('acquisition_script_sha256') != sha(Path(__file__).read_bytes()):
        raise ValueError('Independent acquisition gate missing or stale')
    for name, (url, archive_root, expected) in SPECS.items():
        if gate[name]['url'] != url or gate[name]['sha256'] != expected:
            raise ValueError('Source discovery pin differs')
        path = OUT / 'raw' / (name + '.tar.gz')
        if path.exists():
            raise ValueError('Raw artifact exists; no implicit retry')
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise ValueError('Non-200 acquisition response')
            raw = response.read(30*1024*1024+1)
        if len(raw) > 30*1024*1024 or sha(raw) != expected:
            raise ValueError('Archive size/hash mismatch')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as target:
            target.write(raw)
        rows, seen = [], set()
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            members = archive.getmembers()
            if sum(m.size for m in members) > 100*1024*1024:
                raise ValueError('Expanded archive exceeded bound')
            for member in members:
                parts = PurePosixPath(member.name).parts
                if (not parts or parts[0] != archive_root or '..' in parts
                        or member.name.startswith('/') or '\\' in member.name or ':' in member.name):
                    raise ValueError('Unsafe archive path')
                if member.isdir():
                    continue
                if not member.isfile() or member.name in seen:
                    raise ValueError('Non-regular or duplicate archive member')
                seen.add(member.name)
                relative = '/'.join(parts[1:])
                content = archive.extractfile(member).read()
                rows.append({'path': relative, 'size': len(content), 'sha256': sha(content)})
                notice = (relative == 'README.md' or relative.startswith('LICENSES/')
                          or relative == 'dist/bin/platform/MPL-1.1.txt'
                          or any(x in PurePosixPath(relative).name.lower() for x in ('license', 'copying', 'copyright', 'notice')))
                if notice:
                    dest = OUT / 'notices' / name / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open('xb') as target:
                        target.write(content)
        result = {'url': url, 'archive_sha256': expected, 'archive_bytes': len(raw),
                  'script_sha256': sha(Path(__file__).read_bytes()),
                  'files': sorted(rows, key=lambda row: row['path']), 'source_executed': False}
        with (OUT / (name+'-manifest.json')).open('x', encoding='utf-8') as target:
            target.write(json.dumps(result, indent=2)+'\n')
        print(json.dumps({'archive': name, 'files': len(rows), 'sha256': expected}))


if __name__ == '__main__':
    main()
