"""Independent read-only output schema, provenance and containment checks."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
output = root/'assets/authors/catalog.json'
catalog = read(output)
assert catalog == read(root/'data/author-profiles/staged.json')
assert catalog['schema_version'] == 1
assert set(catalog) == {'schema_version','authors'}
authors = catalog['authors']
assert len(authors) == len({p['author'] for p in authors}) == len({p['slug'] for p in authors}) == 13
bio_keys = {'text','source_url','source_title','revision_url','license','license_url','attribution','extraction','url','fetched_at','status','sha256','raw_file'}
destinations = set()
for p in authors:
    assert set(p) == {'author','slug','greek','biography','portrait','reading'}
    assert p['author'] and p['slug'] and isinstance(p['greek'],str)
    assert isinstance(p['reading'],list)
    assert set(p['biography']) == bio_keys
    assert all(p['biography'][k] for k in bio_keys)
    portrait = p['portrait']
    if not portrait:
        assert p['author'] in {'Homer','Hesiod','Theocritus'}
        continue
    assert portrait['image'].startswith('/assets/authors/')
    path = (root/portrait['image'].lstrip('/')).resolve()
    assert path.is_relative_to((root/'assets/authors').resolve())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == portrait['sha256']
    destinations.add(path)
    if p['author'] == 'Archilochus':
        assert '?' in portrait['description']
        assert portrait['caption'] == 'Attributed portrait · identity uncertain'
    elif p['author'] == 'Bacchylides':
        assert 'Dithyrambs' in portrait['title'] and 'Papyrus' in portrait['title']
        assert portrait['caption'] == 'Dithyrambs manuscript · not a portrait'
    elif p['author'] in {'Sappho','Alcaeus'}:
        assert 'Alma-Tadema' in portrait['artist'] and '1870' in portrait['description']
        assert portrait['caption'] == 'Sappho and Alcaeus · later artistic depiction'
    print('PASS output',p['author'],path.name,portrait.get('caption',''))
assert len(destinations) == 9
assert set((root/'assets/authors').iterdir()) == destinations | {output}
print('PASS: 13 unique records, 0 missing required biography fields, 10 image references, 9 byte-exact image files, 3 intentional null images, root-relative destinations contained')
