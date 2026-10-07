"""Source-bound, optional aesthetic annotations; never a literary-subject taxonomy.

Annotations are model judgments. Literal validation establishes provenance, not
the correctness of the interpretation. This module never writes to the corpus.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Callable

from .author_aliases import canonical as canonical_author

ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = ROOT / 'data/annotations/visual-themes/validated.json'
THEMES = ('sea_coast', 'garden_grove', 'meadow_pasture',
          'mountain_woodland', 'river_spring')
MODIFIERS = ('moonlight', 'dawn_dusk', 'storm')
POETS = ('Archilochus', 'Alcman', 'Sappho', 'Alcaeus', 'Stesichorus',
         'Ibycus', 'Anacreon', 'Simonides', 'Pindar', 'Bacchylides')


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def source_identity(record: dict) -> dict:
    return {**{key: record.get(key) for key in ('source', 'work_id', 'citation')},
            'author': canonical_author(record.get('author', ''))}


@lru_cache(maxsize=4)
def _load(path: str, stamp: int, size: int):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if document.get('schema_version') != 1:
        raise ValueError('Unsupported visual-theme annotation schema')
    rows = document['records']
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate visual-theme record IDs')
    return {row['id']: row for row in rows}, document['manifest']


def load_annotations(path: Path = ANNOTATIONS):
    """An absent optional sidecar is harmless; malformed sidecars fail visibly."""
    path = Path(path)
    if not path.exists():
        return {}, {'available': False, 'review_complete': False}
    stat = path.stat()
    return _load(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def annotation_for(record: dict, lookup: Callable[[str], dict | None] | None = None,
                   path: Path = ANNOTATIONS) -> dict | None:
    """Return a matching annotation, failing closed on stale source/context.

``lookup`` must obey the caller's corpus visibility policy. It is mandatory
for inherited translations and for evidence in a different Greek record.
No text/author/citation fuzzy matching, mirror inheritance, or guessed parents.
    """
    rows, _ = load_annotations(path)
    saved = rows.get(record.get('id'))
    if not saved or saved['source_text_sha256'] != text_sha256(record.get('text', '')):
        return None
    if source_identity(record) != saved['source_identity']:
        return None
    if record.get('quality') != 'source_text':
        return None
    parent_id = saved.get('parent_id')
    if parent_id:
        if record.get('kind') != 'translation' or record.get('parent_id') != parent_id or lookup is None:
            return None
        parent = lookup(parent_id)
        if not parent or parent.get('kind') != 'text' or parent.get('language') != 'grc':
            return None
        if (parent.get('quality') != 'source_text' or text_sha256(parent.get('text', '')) != saved['parent_text_sha256'] or
                source_identity(parent) != saved['parent_source_identity']):
            return None
    elif record.get('kind') != 'text' or record.get('language') != 'grc':
        return None
    for label in saved.get('labels', []):
        for span in label['evidence']:
            if span['id'] == record['id']:
                source = record
            else:
                source = lookup(span['id']) if lookup else None
            if (not source or source.get('id') != span['id'] or
                    source.get('quality') != 'source_text' or source.get('kind') != 'text' or
                    source.get('language') != 'grc'):
                return None
            text = source.get('text', '')
            if (text_sha256(text) != span['source_text_sha256'] or
                    source_identity(source) != span['source_identity'] or
                    text[span['start']:span['end']] != span['quote']):
                return None
    return {'status': saved['status'], 'themes': [x['theme'] for x in saved.get('labels', [])],
            'labels': saved.get('labels', []), 'reason': saved['reason'],
            'provenance': 'model_annotation_literal_evidence_validated',
            'source_text_sha256': saved['source_text_sha256'],
            **({'inherited_from_parent_id': parent_id} if parent_id else {})}


def attach_visual_themes(record: dict, lookup=None, path: Path = ANNOTATIONS) -> dict:
    """Mutate only the API response object, never corpus records on disk."""
    annotation = annotation_for(record, lookup, path)
    if annotation is not None:
        record['visual_themes'] = annotation
    return record
