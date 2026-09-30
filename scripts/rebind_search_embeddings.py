"""Rebind unchanged passage embeddings after a search-only index migration.

Refuses any source-record difference, stale input manifest, or concurrent index
change. This does not regenerate vectors or relax the runtime stale-index gate.
"""
import argparse
import itertools
import json
from pathlib import Path
import sqlite3


def signature(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def rebind(previous, current, manifest, output):
    previous, current, manifest, output = map(lambda p: Path(p).resolve(), (previous, current, manifest, output))
    if output.exists() or previous == current:
        raise ValueError('Require distinct corpus snapshots and a new output manifest')
    before = signature(previous), signature(current), signature(manifest)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if before[0] != (data['corpus_mtime_ns'], data['corpus_size']):
        raise ValueError('Existing embeddings do not identify the previous corpus snapshot')
    fields = 'id,work_id,source,author,work,edition,citation,language,kind,quality,text,data,sequence'
    with sqlite3.connect(f'file:{previous.as_posix()}?mode=ro',uri=True) as old, sqlite3.connect(f'file:{current.as_posix()}?mode=ro',uri=True) as new:
        count = 0
        # Search-only migration preserves row order. Any insertion/deletion,
        # reordering or source-field change fails closed, without a huge sort.
        old_rows = old.execute(f'SELECT {fields} FROM passages ORDER BY rowid')
        new_rows = new.execute(f'SELECT {fields} FROM passages ORDER BY rowid')
        for left, right in itertools.zip_longest(old_rows, new_rows):
            if left != right:
                raise ValueError('Passage inputs differ; rebuild embeddings instead')
            count += 1
    if before != (signature(previous), signature(current), signature(manifest)):
        raise ValueError('Snapshots changed during validation; no manifest written')
    data['corpus_mtime_ns'], data['corpus_size'] = before[1]
    data['search_only_rebind'] = {'verified_unchanged_source_records': count,
                                'previous_corpus_mtime_ns': before[0][0],
                                'previous_corpus_size': before[0][1]}
    with output.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)
    return {'verified_unchanged_source_records': count, 'vectors_unchanged': True}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',required=True)
    parser.add_argument('--current',required=True)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(rebind(args.previous,args.current,args.manifest,args.output)))
