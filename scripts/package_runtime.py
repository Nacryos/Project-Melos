"""Package an existing audited runtime snapshot without changing any source data.

Includes hashes and exact timestamps so moving a frozen embedding index between
Windows and Linux does not silently invalidate its corpus snapshot identity.
No credentials, old vectors, training checkpoints or unrelated raw data enter it.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'data/embeddings/manifest.json').read_text(encoding='utf-8'))
    paths = [ROOT / 'data' / name for name in ('corpus.sqlite', 'evidence.sqlite', 'wiktionary.sqlite')]
    paths += sorted((ROOT / 'data/lexica').glob('*.jsonl'))
    paths += sorted((ROOT / 'data/claims').glob('*.jsonl'))
    paths += [ROOT / 'data/metadata' / name for name in ('chronology.json', 'p2-author-profiles.json')]
    paths += [ROOT / 'data/reports' / name for name in (
        'audit-lexica.json', 'wiktionary-audit.json', 'p2-claim-acceptance.json', 'audit-acceptance.json')]
    paths += sorted((ROOT / 'data/raw/lexica').rglob('*.xml'))
    for name in ('manifest.json', manifest['rows_file'], manifest['vectors_file']):
        target = (ROOT / 'data/embeddings' / name).resolve()
        if target.parent != (ROOT / 'data/embeddings').resolve():
            raise ValueError('Embedding path leaves its directory')
        paths.append(target)
    snapshot = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'x:gz', compresslevel=1, format=tarfile.PAX_FORMAT) as archive:
        for path in paths:
            rel = path.relative_to(ROOT).as_posix()
            before = path.stat()
            sha = digest(path)
            archive.add(path, arcname=rel, recursive=False)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f'Source changed during packaging: {rel}')
            snapshot.append({'path': rel, 'size': before.st_size, 'mtime_ns': before.st_mtime_ns, 'sha256': sha})
        raw = json.dumps({'files': snapshot}, indent=2).encode()
        info = tarfile.TarInfo('runtime-snapshot.json')
        info.size = len(raw)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(raw))
    print(json.dumps({'files': len(snapshot), 'source_bytes': sum(r['size'] for r in snapshot),
                      'archive_bytes': args.output.stat().st_size, 'archive_sha256': digest(args.output)}), flush=True)


if __name__ == '__main__':
    main()
