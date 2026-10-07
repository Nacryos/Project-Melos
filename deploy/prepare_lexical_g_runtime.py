"""Host-only SQLite API snapshot for private G; never modifies live databases."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path('/home/alvin/services/melos')
RELEASE = ROOT / 'releases/lexical-20261007g'
DESTINATION = RELEASE / 'canary-runtime'
BASE_CONTAINER = 'e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52'
DATABASES = ('classifier.sqlite', 'machine_morphology.sqlite')


def table_proofs(connection):
    schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        identifier = '"' + name.replace('"', '""') + '"'
        column_count = len(connection.execute('SELECT * FROM ' + identifier + ' LIMIT 0').description)
        cursor = connection.execute('SELECT * FROM ' + identifier + ' ORDER BY ' + ','.join(str(i + 1) for i in range(column_count)))
        digest, count = hashlib.sha256(), 0
        for row in cursor:
            values = [({'base64': base64.b64encode(value).decode()} if isinstance(value, bytes) else value) for value in row]
            raw = json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(raw)
            count += 1
        tables[name] = {'rows': count, 'sha256': digest.hexdigest()}
    return {'schema_sha256': hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest(), 'tables': tables}


def main():
    old = json.loads(subprocess.check_output(['docker', 'inspect', 'melos-api']))[0]
    if old['Id'] != BASE_CONTAINER or not old['State']['Running']:
        raise RuntimeError('Exact running F required')
    runtime = [m for m in old['Mounts'] if m['Destination'] == '/app/runtime']
    if len(runtime) != 1 or runtime[0]['Source'] != str(ROOT / 'runtime'):
        raise RuntimeError('Unexpected source runtime mount')
    if DESTINATION.exists() or (RELEASE / 'private-runtime-snapshot.json').exists():
        raise RuntimeError('Never replace an existing private snapshot')
    os.umask(0o077)
    DESTINATION.mkdir(mode=0o700)
    proofs = {}
    for name in DATABASES:
        source = ROOT / 'runtime' / name
        target = DESTINATION / name
        # A held read transaction binds table proofs and backup to one snapshot,
        # even when the production DB uses WAL or receives concurrent requests.
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader:
            reader.execute('BEGIN')
            before = table_proofs(reader)
            with closing(sqlite3.connect(target)) as writer:
                reader.backup(writer)
                if writer.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Private SQLite integrity failed')
                after = table_proofs(writer)
                if before != after:
                    raise RuntimeError('Private backup does not match held source snapshot')
                writer.commit()
                if writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                    raise RuntimeError('Private backup checkpoint was blocked')
            reader.rollback()
        if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise RuntimeError('Private backup left unexpected journal sidecars')
        os.chmod(target, 0o600)
        os.chown(target, 1000, 1000)
        proofs[name] = {**after, 'backup_sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()}
    current = json.loads(subprocess.check_output(['docker', 'inspect', 'melos-api']))[0]
    if current['Id'] != BASE_CONTAINER or current['Mounts'] != old['Mounts']:
        raise RuntimeError('Production identity changed during read')
    os.chown(DESTINATION, 1000, 1000)
    receipt = {'verdict': 'SNAPSHOT_NOT_APPROVED', 'base_container_id': BASE_CONTAINER,
               'path': str(DESTINATION), 'backup_method': 'sqlite_backup_api', 'databases': proofs,
               'created_at': datetime.now(timezone.utc).isoformat(), 'live_databases_opened_read_only': True}
    path = RELEASE / 'private-runtime-snapshot.json'
    with path.open('x') as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps({'path': str(path), 'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
                      'verdict': receipt['verdict']}))


if __name__ == '__main__':
    main()
