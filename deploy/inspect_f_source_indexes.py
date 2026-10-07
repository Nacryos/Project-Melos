"""Read-only compare the source records actually required by F adapters."""
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.evidence import EvidenceIndex
from backend.dictionary_crossrefs import lookup_crossreference_meanings
from backend.source_link_aliases import lookup_form_link_aliases
from discovery_transport import connect, run


def main():
    evidence = EvidenceIndex()
    identifiers = set()
    for form in ('παχέων', 'δᾶμον'):
        for lookup in (lookup_form_link_aliases, lookup_crossreference_meanings):
            result = lookup(form, evidence)
            identifiers.update(record['id'] for record in result['supporting_source_records'])
    if not identifiers:
        raise RuntimeError('No source proof records discovered')
    code = '''import hashlib,json,sqlite3
con=sqlite3.connect('file:/app/data/wiktionary.sqlite?mode=ro',uri=True)
ids=IDS
rows={}
for identifier in sorted(ids):
    found=con.execute('SELECT record_json FROM entries WHERE id=?',(identifier,)).fetchone()
    rows[identifier]=None if found is None else hashlib.sha256(json.dumps(json.loads(found[0]),ensure_ascii=False).encode()).hexdigest()
print(json.dumps({'records':rows,'count':con.execute('SELECT count(*) FROM entries').fetchone()[0],'schema':con.execute('PRAGMA table_info(entries)').fetchall()}))
'''.replace('ids=IDS', 'ids=' + repr(sorted(identifiers)))
    client = connect()
    try:
        info = json.loads(run(client, 'docker inspect melos-api'))[0]
        if info['Id'] != '0acc39cfe31fb883bedf3cbf4818f05a5f46c400a58e111f494315301e3116f5':
            raise RuntimeError('Live E changed')
        remote = json.loads(run(client, 'docker exec melos-api python -c ' + shlex.quote(code)))
    finally:
        client.close()
    local = {}
    with sqlite3.connect(f'file:{(ROOT / "data/wiktionary.sqlite").as_posix()}?mode=ro', uri=True) as connection:
        for identifier in sorted(identifiers):
            found = connection.execute('SELECT record_json FROM entries WHERE id=?', (identifier,)).fetchone()
            local[identifier] = None if found is None else hashlib.sha256(json.dumps(json.loads(found[0]), ensure_ascii=False).encode()).hexdigest()
        count = connection.execute('SELECT count(*) FROM entries').fetchone()[0]
        schema = [list(row) for row in connection.execute('PRAGMA table_info(entries)').fetchall()]
    result = {'live_container_id': info['Id'], 'record_count_checked': len(identifiers),
              'all_required_record_bytes_equivalent': local == remote['records'],
              'local_record_sha256': local, 'live_record_sha256': remote['records'],
              'local_entries': count, 'live_entries': remote['count'],
              'schema_equal': schema == remote['schema'], 'local_schema': schema, 'live_schema': remote['schema'],
              'hash_method': 'Exact runtime _entry_proof serialization: json.dumps(record, ensure_ascii=False), including source key order.',
              'scope': 'Only closure records for two requested probe forms; not a full database equality proof.'}
    target = ROOT / 'runtime/lexical-release-f/source-index-probe-runtime-binding.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({'path': str(target), 'record_count_checked': len(identifiers),
                      'records_equal': result['all_required_record_bytes_equivalent'], 'schema_equal': result['schema_equal'],
                      'local_entries': count, 'live_entries': remote['count']}))


if __name__ == '__main__':
    main()
