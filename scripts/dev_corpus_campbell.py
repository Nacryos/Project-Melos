"""Build a small local development corpus holding only the Campbell assignment.

The production corpus on Basecamp already carries these five rows; the laptop
copy of data/corpus.sqlite does not. This writes a separate SQLite file with the
same schema, so the backend can be started against it with tools/serve_dev.py.
Never a deployment artifact.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.author_aliases import canonical as canonical_author, component_keys  # noqa: E402
from backend.textutils import normalize, search_text, text_key, tokenize  # noqa: E402


def build(records: Path, output: Path, template: Path) -> dict:
    rows = [json.loads(line) for line in records.read_text(encoding='utf-8').splitlines() if line.strip()]
    if output.exists():
        output.unlink()
    with sqlite3.connect(f'file:{template}?mode=ro', uri=True) as src:
        schema = [sql for (sql,) in src.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'passage_fts_%'")]
    con = sqlite3.connect(output)
    for sql in schema:
        con.execute(sql)
    works, vocabulary = {}, collections.Counter()
    for row in rows:
        identity = [row.get(k) for k in ('source', 'author', 'work', 'edition', 'language')]
        work_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        row['work_id'] = work_id
        indexed = search_text(row['text']) if row['language'] == 'grc' else row['text']
        folded = normalize(indexed)
        sequence = works.get(work_id, {}).get('count', 0)
        display = canonical_author(row['author'])
        con.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (row['id'], work_id, row['source'], row['author'], row['work'], row['edition'], row['citation'],
                     row['language'], row['kind'], row['quality'], row['text'], folded,
                     json.dumps(row, ensure_ascii=False), sequence, display,
                     text_key(row['language'], row['kind'], row['text'])))
        con.executemany('INSERT INTO passage_authors VALUES (?,?)', [(row['id'], k) for k in component_keys(row['author'])])
        con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)',
                    (row['id'], folded, normalize(row['citation']), normalize(row['author']), normalize(row['work'])))
        counts = collections.Counter(tokenize(indexed))
        con.executemany('INSERT INTO tokens VALUES (?,?,?,?)', [(row['id'], w, normalize(w), n) for w, n in counts.items()])
        for w, n in counts.items():
            vocabulary[(normalize(w), w)] += n
        works.setdefault(work_id, dict(zip(('source', 'author', 'work', 'edition', 'language'), identity)) | {'count': 0, 'author_canonical': display})['count'] += 1
    for (norm, form), n in vocabulary.items():
        con.execute('INSERT OR REPLACE INTO vocabulary VALUES (?,?,?)', (norm, form, n))
    for work_id, work in works.items():
        con.execute('INSERT INTO works VALUES (?,?,?,?,?,?,?,?)',
                    (work_id, work['author'], work['work'], work['edition'], work['source'], work['language'], work['count'], work['author_canonical']))
    con.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(
        {'passages': len(rows), 'works': len(works), 'sources': {'campbell_assignment': len(rows)},
         'vocabulary': len(vocabulary), 'files': [], 'dev': True})))
    con.commit()
    con.close()
    return {'output': str(output), 'passages': len(rows), 'ids': [r['id'] for r in rows]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, default=ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl')
    parser.add_argument('--template', type=Path, default=ROOT / 'data/corpus.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/dev/corpus.sqlite')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build(args.records, args.output, args.template), ensure_ascii=False, indent=1))
