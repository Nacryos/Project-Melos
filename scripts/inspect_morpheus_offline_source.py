"""Read-only official source fingerprinting; never extracts or executes code.

Downloads the pinned repository archive into bounded memory, reports hashes,
and exits. No morphology service calls or local/cache/corpus writes.
"""
import hashlib
import io
import json
import tarfile
import urllib.request

REVISION = '2f1a30d65ed7ae9c6120dbf64d730b863be412e4'
URL = 'https://codeload.github.com/alpheios-project/morpheus/tar.gz/' + REVISION
MAX_ARCHIVE = 20 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint():
    with urllib.request.urlopen(URL, timeout=30) as response:
        archive = response.read(MAX_ARCHIVE + 1)
    if len(archive) > MAX_ARCHIVE:
        raise ValueError('Source archive exceeded research read limit')
    rows = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        members = tar.getmembers()
        if sum(m.size for m in members) > MAX_EXPANDED:
            raise ValueError('Expanded source exceeded research read limit')
        for member in members:
            if not member.isfile():
                continue
            rows.append({'path': '/'.join(member.name.split('/')[1:]),
                         'size': member.size, 'sha256': sha(tar.extractfile(member).read())})
    def manifest(prefix):
        selected = sorted([r for r in rows if r['path'].startswith(prefix)], key=lambda r: r['path'])
        canonical = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        return {'files': len(selected), 'bytes': sum(r['size'] for r in selected),
                'sha256': sha(canonical)}
    return {'revision': REVISION, 'url': URL, 'archive_bytes': len(archive), 'archive_sha256': sha(archive),
            'manifest_encoding': 'UTF-8 compact sorted-key JSON list of path,size,sha256; sorted by path',
            'source_manifest': manifest('src/'), 'stemlib_manifest': manifest('dist/stemlib/'),
            'license': next(r for r in rows if r['path'] == 'LICENSE'),
            'saved_or_executed': False}


if __name__ == '__main__':
    print(json.dumps(fingerprint(), indent=2))
