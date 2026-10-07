"""Verify bundled positive annotation evidence against the live read-only corpus."""
import subprocess

CODE = '''
import json
from backend import discovery, server
from backend.visual_themes import load_annotations, annotation_for
path = discovery._annotation_path()
rows, manifest = load_annotations(path)
assert rows, 'Annotation sidecar missing'
positive = [row for row in rows.values() if row.get('labels')]
assert len(positive) == 247, 'Unexpected positive annotation count'
with server.connect() as con:
    cache = {}
    def lookup(identifier):
        if identifier not in cache:
            row = con.execute('SELECT data FROM passages WHERE id=?', (identifier,)).fetchone()
            cache[identifier] = json.loads(row['data']) if row else None
        return cache[identifier]
    for saved in positive:
        record = lookup(saved['id'])
        assert record, 'Annotated record missing'
        actual = annotation_for(record, lookup, path)
        assert actual and actual['themes'], 'Annotation did not match source identity/hash/evidence'
print(json.dumps({'passed': True, 'positive_annotations_verified': len(positive),
                  'total_sidecar_records': len(rows), 'source_records_unchanged': True}))
'''

if __name__ == '__main__':
    subprocess.run(['docker', 'exec', '-i', 'melos-api-discovery-canary', 'python', '-'],
                   input=CODE, text=True, check=True)
