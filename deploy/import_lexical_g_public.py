"""Authorized eight-receipt G import using audited validator, with preimage."""
import argparse
import base64
import json
from pathlib import Path
import shlex

from discovery_transport import connect, run
from lexical_release_g import BASE, RELEASE

ROOT = Path(__file__).resolve().parents[1]
LIVE = 'b7b0d8996609a41f3ca8b740f4ccf19979462845c89445e571c1972398eb75bb'
REMOTE = RELEASE.as_posix()
IMPORTER_SHA = 'cb2cbab4287b15b596fb8abe5b2b75b665b2beced9450d57b8445adb27761eac'
BUNDLE_SHA = '865d281ed3e8887e8ecfedb3370868ece4f9d02b03abffe22dadc1dc62490dfc'


def main(phase):
    output = ROOT / 'runtime/lexical-release-g' / ('public-import-' + phase + '.json')
    if output.exists():
        raise RuntimeError('Never replace public import evidence')
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != LIVE or info['Image'] != BASE or not info['State']['Running']:
            raise RuntimeError('Exact promoted G required')
        mounts = [m['Source'] for m in info['Mounts'] if m['Destination'] == '/app/runtime']
        if mounts != ['/home/alvin/services/melos/runtime']:
            raise RuntimeError('Expected original production runtime')
        if phase == 'before':
            code = '''from pathlib import Path
from contextlib import closing
import sqlite3,sys,json,hashlib,os
sys.path.insert(0,RELEASE)
from prepare_lexical_g_runtime import table_proofs
source=Path('/home/alvin/services/melos/runtime/machine_morphology.sqlite')
target=Path(RELEASE)/'public-machine-before.sqlite'
if target.exists(): raise RuntimeError('Existing snapshot')
os.umask(0o077)
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as reader:
 reader.execute('BEGIN')
 proof=table_proofs(reader)
 with closing(sqlite3.connect(target)) as writer:
  reader.backup(writer)
  assert writer.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
  assert table_proofs(writer)==proof
  writer.commit()
  assert writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
 reader.rollback()
assert not any(Path(str(target)+s).exists() for s in ('-wal','-shm','-journal'))
print(json.dumps({'path':str(target),'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest(),'proof':proof,'source_read_only':True}))
'''
            data = run(client, 'python3 -c ' + shlex.quote('RELEASE=' + repr(REMOTE) + '\n' + code))
        else:
            if not (output.parent / 'public-import-before.json').exists():
                raise RuntimeError('Pre-import snapshot required')
            if phase == 'applied':
                preview = json.loads((output.parent / 'public-import-preview.json').read_text())
                if preview['eligible'] != 8 or preview['mode'] != 'preview':
                    raise RuntimeError('Verified eight-receipt preview required')
            for name, digest in (('sync_morphology_receipts.py', IMPORTER_SHA), ('successful-receipts.json', BUNDLE_SHA)):
                source = REMOTE + '/canary-runtime/' + name
                if run(client, 'sha256sum ' + source).decode().split()[0] != digest:
                    raise RuntimeError('Audited transfer artifact changed')
                content = run(client, 'cat ' + source)
                code = ('from pathlib import Path;import base64;'
                        'p=Path(' + repr('/tmp/melos-g-' + name) + ');'
                        'data=base64.b64decode(' + repr(base64.b64encode(content).decode()) + ');'
                        'assert not p.exists() or p.read_bytes()==data;'
                        'p.open("xb").write(data) if not p.exists() else None')
                run(client, 'docker exec melos-api python -c ' + shlex.quote(code))
            command = ('docker exec -e PYTHONPATH=/app melos-api python /tmp/melos-g-sync_morphology_receipts.py '
                       'import /app/runtime/machine_morphology.sqlite /tmp/melos-g-successful-receipts.json')
            data = run(client, command + (' --apply' if phase == 'applied' else ''))
        result = json.loads(data)
        with output.open('xb') as stream:
            stream.write(data)
        print(json.dumps({'path': str(output), 'result': result}, ensure_ascii=True))
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'preview', 'applied'))
    main(parser.parse_args().phase)
