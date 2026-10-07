"""Encode only the audited assignment on CUDA; append without changing old vectors.

The encoder contract must equal the currently published float16 BGE-M3 contract.
Output is a small transferable addition, not a rebuilt corpus or model index.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts import integrate_campbell_assignment as integration
from scripts.build_embeddings import encode_passage_batch, MODEL_NAME, MODEL_REVISION, POOLING_METHOD


def contract(manifest):
    expected = {'model': MODEL_NAME, 'model_revision': MODEL_REVISION,
                'precision': 'float16', 'max_seq_length': 512,
                'pooling_method': POOLING_METHOD, 'dimensions': 1024}
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError('Base embedding contract differs from the pinned assignment encoder')
    return expected


def encode(records, acceptance, manifest, output, root=ROOT, source='campbell_assignment'):
    rows = integration.assignment_rows(records, acceptance, root, source)
    base = integration.append.read_json(manifest)
    settings = contract(base)
    output = Path(output)
    if output.exists():
        raise ValueError('Encoding output must be a fresh directory')
    os.environ.setdefault('USE_TF', '0')
    os.environ.setdefault('USE_FLAX', '0')
    import torch
    from sentence_transformers import SentenceTransformer
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable: do not silently change the float16 contract')
    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device='cuda', local_files_only=True)
    model.half()
    model.max_seq_length = settings['max_seq_length']
    ordered = [rows[key] for key in sorted(rows)]
    matrix, windows = encode_passage_batch(model, [r['text'] for r in ordered], 5, 512)
    if matrix.shape != (5, 1024) or not np.isfinite(matrix).all():
        raise ValueError('Five bounded assignment vectors expected')
    output.mkdir(parents=True, exist_ok=False)
    np.save(output / 'addition.npy', matrix)
    receipt = {'contract': settings, 'records_sha256': integration.append.sha(Path(records)),
        'vectors_sha256': integration.append.sha(output / 'addition.npy'),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'rows': [{'id': r['id'], 'text_sha256': hashlib.sha256(r['text'].encode()).hexdigest(),
                  'source': r['source'], 'language': r['language'], 'kind': r['kind'],
                  'author': r['author'], 'parent_id': r.get('parent_id'),
                  'context_authors': [], 'windows': n} for r, n in zip(ordered, windows)]}
    integration.append.write_json(output / 'addition.json', receipt)
    return {'count': 5, 'vectors_sha256': receipt['vectors_sha256']}


def append_vectors(records, acceptance, base_manifest, base_index, additions, staged, corpus, root=ROOT,
                   source='campbell_assignment'):
    rows = integration.assignment_rows(records, acceptance, root, source)
    staged, base_index, additions = map(Path, (staged, base_index, additions))
    base = integration.append.read_json(base_manifest)
    settings = contract(base)
    receipt = integration.append.read_json(additions / 'addition.json')
    if receipt['contract'] != settings or receipt['records_sha256'] != integration.append.sha(Path(records)):
        raise ValueError('Addition contract/source hash mismatch')
    if receipt['vectors_sha256'] != integration.append.sha(additions / 'addition.npy'):
        raise ValueError('Addition vector hash mismatch')
    new = receipt['rows']
    if len(new) != 5 or {r['id'] for r in new} != set(rows):
        raise ValueError('Addition IDs do not match assignment')
    for row in new:
        source_row = rows[row['id']]
        if row['text_sha256'] != hashlib.sha256(source_row['text'].encode()).hexdigest():
            raise ValueError('Embedding text hash mismatch')
        if any(row[k] != source_row[k] for k in ('source', 'language', 'kind', 'author')):
            raise ValueError('Embedding row attribution mismatch')
    preservation = integration.append.read_json(staged / 'addition-manifest.json')
    if preservation['source_sha256'] != receipt['records_sha256'] or preservation['added_ids'] != list(rows):
        raise ValueError('Staged corpus addition differs')
    if preservation['input_hashes'].get(str(Path(corpus).resolve())) != integration.append.sha(Path(corpus)):
        raise ValueError('Base corpus no longer matches preservation report')
    old_rows = integration.append.read_json(base_index / base['rows_file'])
    old_vectors = np.load(base_index / base['vectors_file'], mmap_mode='r')
    new_vectors = np.load(additions / 'addition.npy', allow_pickle=False)
    if len(old_rows) != base['count'] or old_vectors.shape != (len(old_rows), 1024):
        raise ValueError('Base vector count/shape mismatch')
    if {r['id'] for r in old_rows} & set(rows):
        raise ValueError('Addition collides with existing embedding')
    if new_vectors.shape != (5, 1024) or not np.isfinite(new_vectors).all():
        raise ValueError('Addition matrix invalid')
    if not np.allclose(np.linalg.norm(new_vectors, axis=1), 1, atol=.01):
        raise ValueError('Addition vectors are not normalized')
    suffix = receipt['vectors_sha256'][:20]
    rows_file, vectors_file = f'rows-campbell-{suffix}.json', f'vectors-campbell-{suffix}.npy'
    if (staged / rows_file).exists() or (staged / vectors_file).exists():
        raise ValueError('Never overwrite a previous embedding append')
    merged = np.lib.format.open_memmap(staged / vectors_file, mode='w+', dtype=old_vectors.dtype,
                                     shape=(len(old_rows) + 5, 1024))
    merged[:len(old_rows)] = old_vectors
    merged[len(old_rows):] = new_vectors
    merged.flush()
    if not np.array_equal(merged[:len(old_rows)], old_vectors):
        raise RuntimeError('Existing vectors changed')
    del merged
    published_new = [{k: v for k, v in row.items() if k != 'text_sha256'} for row in new]
    integration.append.write_json(staged / rows_file, old_rows + published_new)
    manifest = integration.retained_semantic_manifest(base_manifest, corpus, staged / 'corpus.sqlite', rows)
    manifest.update(count=len(old_rows) + 5, rows_file=rows_file, vectors_file=vectors_file,
                    total_windows=base['total_windows'] + sum(r['windows'] for r in new),
                    built_at=datetime.now(timezone.utc).isoformat())
    for field, keys in (('counts_by_source', [r['source'] for r in new]),
                        ('counts_by_language_kind', [r['language'] + ':' + r['kind'] for r in new])):
        manifest[field] = dict(Counter(base[field]) + Counter(keys))
    manifest['pending_embedding_ids'] = [x for x in manifest['pending_embedding_ids'] if x not in rows]
    manifest['corpus_rebinding']['new_ids_embedded'] = True
    # Separate final filename: pending manifest remains as a receipt, not overwritten.
    integration.append.write_json(staged / 'manifest-embedded.json', manifest)
    result = {'count': len(old_rows) + 5, 'preserved_vectors': len(old_rows),
              'manifest': 'manifest-embedded.json',
              'artifacts': {name: integration.append.sha(staged / name)
                            for name in (rows_file, vectors_file, 'manifest-embedded.json')}}
    integration.append.write_json(staged / 'embedding-append-receipt.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for mode in ('encode', 'append'):
        cmd = sub.add_parser(mode)
        for name in ('records', 'acceptance'):
            cmd.add_argument('--' + name, required=True, type=Path)
        cmd.add_argument('--root', type=Path, default=ROOT)
        cmd.add_argument('--source', default='campbell_assignment')
        names = ('manifest', 'output') if mode == 'encode' else ('base-manifest', 'base-index', 'additions', 'staged', 'corpus')
        for name in names:
            cmd.add_argument('--' + name, required=True, type=Path)
    args = vars(parser.parse_args())
    function = encode if args.pop('command') == 'encode' else append_vectors
    print(json.dumps(function(**args), indent=2))
