"""Read existing production receipts verbatim, without parser/cache mutation."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
from discovery_transport import connect, run

ROOT = Path(__file__).resolve().parents[1]
LIVE = 'f888ab8692593446a2495b3543be2ce7274bfcd672cc0d5f8379083af8f50a19'


def main():
    output = ROOT / 'runtime/alcaeus-morpheus-maintenance/production-all-receipts-i.json'
    if output.exists():
        raise RuntimeError('Never overwrite source inventory')
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != LIVE or not info['State']['Running']:
            raise RuntimeError('Exact running I required')
        runtime = next(m for m in info['Mounts'] if m['Destination'] == '/app/runtime')
        if runtime['Source'] != '/home/alvin/services/melos/runtime':
            raise RuntimeError('Unexpected shared runtime path')
        code = '''import sqlite3,json,base64
from pathlib import Path
p=Path('/home/alvin/services/melos/runtime/machine_morphology.sqlite')
c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
c.execute('PRAGMA query_only=ON')
c.execute('BEGIN')
rows=c.execute('SELECT id,metadata,raw FROM receipts ORDER BY id').fetchall()
assert len(rows)<=128
assert sum(len(r[2]) for r in rows)<=64*1024*1024
cache=c.execute('SELECT key,receipt_id,expires FROM cache ORDER BY key').fetchall()
print(json.dumps({'receipts':[{'receipt_id':i,'metadata':m,'raw_base64':base64.b64encode(r).decode()} for i,m,r in rows],
                  'cache':[{'key':k,'receipt_id':i,'expires':e} for k,i,e in cache]}))
c.close()
'''
        encoded = base64.b64encode(code.encode()).decode()
        raw = run(client, 'python3 -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(encoded) + '))'))
        inventory = json.loads(raw)
        for row in inventory['receipts']:
            metadata = json.loads(row['metadata'])
            body = base64.b64decode(row['raw_base64'], validate=True)
            if hashlib.sha256(row['metadata'].encode()).hexdigest() != row['receipt_id']:
                raise RuntimeError('Receipt metadata binding differs')
            if hashlib.sha256(body).hexdigest() != metadata['raw_sha256']:
                raise RuntimeError('Raw source body binding differs')
        inventory.update({'source_container_id': LIVE, 'method': 'Host SQLite read-only URI and query_only held transaction; no service initializer.',
                          'paid_calls': 0, 'parser_fetches': 0, 'cache_writes': 0,
                          'scope': 'All existing receipts, including empty analyses; no morphological normalization/filtering.'})
        with output.open('x', encoding='utf-8') as stream:
            json.dump(inventory, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'path': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                          'receipts': len(inventory['receipts']), 'cache_rows': len(inventory['cache'])}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
