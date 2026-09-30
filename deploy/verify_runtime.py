"""Verify transferred files before restoring exact timestamp snapshot identities."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3

root = Path(__file__).resolve().parents[1]
snapshot = json.loads((root / 'runtime-snapshot.json').read_text())
for row in snapshot['files']:
    path = (root / row['path']).resolve()
    if not path.is_relative_to(root / 'data'):
        raise RuntimeError('Snapshot path leaves data directory')
    if path.stat().st_size != row['size']:
        raise RuntimeError(f"Size mismatch: {row['path']}")
    with path.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != row['sha256']:
        raise RuntimeError(f"Hash mismatch: {row['path']}")
    os.utime(path, ns=(row['mtime_ns'], row['mtime_ns']))
for name in ('corpus.sqlite', 'evidence.sqlite', 'wiktionary.sqlite'):
    with sqlite3.connect(f'file:{root / "data" / name}?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError(f'Database integrity failure: {name}')
print(f"Verified {len(snapshot['files'])} transferred runtime files and three SQLite databases.")
