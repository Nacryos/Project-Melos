"""Stage the five independently audited Campbell Alcaeus texts, never live data.

This narrowly wraps the established schema-2 append/preservation checker. Existing
editions stay untouched. An optional semantic manifest may retain old vectors after
the exhaustive preservation check; the five new IDs are explicitly marked pending
embedding, rather than silently disabling all existing semantic retrieval.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import stage_corpus_addition as append

FRAGMENTS = frozenset(('34a', '129', '130b', '326', '350'))


def assignment_rows(records, acceptance, root, source):
    rows, approval, raw_hashes = append.accepted_rows(
        Path(records), Path(acceptance), Path(root).resolve(), source)
    labels = []
    for row in rows.values():
        if (row['author'], row['language'], row['kind']) != ('Alcaeus', 'grc', 'text'):
            raise ValueError('Assignment scope is Alcaeus Greek source text only')
        if row['quality'] not in ('source_text', 'machine_corrected_ocr'):
            raise ValueError('Assignment text must have an audited searchable quality')
        label = (row.get('metadata') or {}).get('assignment_fragment')
        if not isinstance(label, str):
            raise ValueError('metadata.assignment_fragment must identify the assigned fragment')
        labels.append(label)
    if len(labels) != 5 or set(labels) != FRAGMENTS:
        raise ValueError('Require exactly one audited text for each assigned fragment')
    return rows


def retained_semantic_manifest(manifest_path, corpus, candidate, added_ids):
    """Rebind only unchanged existing vector coverage; no embeddings are invented.

    Call only after append.verify_preserved succeeded. File references remain
    unchanged, so the deployment must preserve their current read-only mounts.
    """
    manifest = append.read_json(manifest_path)
    stat = Path(corpus).stat()
    if (manifest.get('corpus_mtime_ns'), manifest.get('corpus_size')) != (stat.st_mtime_ns, stat.st_size):
        raise ValueError('Existing semantic manifest does not bind the base corpus')
    for key in ('rows_file', 'vectors_file'):
        value = manifest.get(key)
        if not isinstance(value, str) or Path(value).name != value or '\\' in value:
            raise ValueError('Unsafe or missing semantic artifact reference')
    if not isinstance(manifest.get('count'), int) or manifest['count'] <= 0:
        raise ValueError('Existing semantic coverage is missing')
    revised = copy.deepcopy(manifest)
    target = Path(candidate).stat()
    revised.update(corpus_mtime_ns=target.st_mtime_ns, corpus_size=target.st_size)
    revised['eligible_count'] = manifest.get('eligible_count', manifest['count']) + len(added_ids)
    pending = set(manifest.get('pending_embedding_ids', [])) | set(added_ids)
    revised['pending_embedding_ids'] = sorted(pending)
    revised['corpus_rebinding'] = {
        'method': 'append-only corpus; exhaustive preservation check of all pre-existing rows',
        'base_manifest_sha256': append.sha(Path(manifest_path)),
        'new_ids': sorted(added_ids),
        'new_ids_embedded': False,
    }
    return revised


def stage(records, acceptance, output, *, corpus, evidence, base_audit,
          runtime_acceptance, source, root=ROOT, semantic_manifest=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    rows = assignment_rows(records, acceptance, root, source)
    original_semantic_hash = append.sha(Path(semantic_manifest)) if semantic_manifest else None
    if semantic_manifest:
        # Preflight the old manifest before a potentially large SQLite clone.
        retained_semantic_manifest(semantic_manifest, corpus, corpus, rows)
    report = append.stage_addition(records, acceptance, output, corpus=corpus,
        evidence=evidence, base_audit=base_audit, runtime_acceptance=runtime_acceptance,
        source=source, root=root)
    if semantic_manifest:
        if append.sha(Path(semantic_manifest)) != original_semantic_hash:
            raise RuntimeError('Semantic input changed during staging')
        manifest = retained_semantic_manifest(semantic_manifest, corpus,
                                              output / 'corpus.sqlite', rows)
        append.write_json(output / 'manifest.json', manifest)
    receipt = {
        'status': 'PENDING_INDEPENDENT_INTEGRATION_AUDIT',
        'fragments': sorted(FRAGMENTS), 'added_ids': sorted(rows),
        'source_sha256': report['source_sha256'],
        'base_corpus_sha256': append.sha(Path(corpus)),
        'candidate_corpus_sha256': append.sha(output / 'corpus.sqlite'),
        'preservation_report': 'addition-manifest.json',
        'semantic': {'old_coverage_retained': bool(semantic_manifest),
                     'new_ids_embedded': False,
                     'manifest_sha256': append.sha(output / 'manifest.json') if semantic_manifest else None},
        'publication': 'Staging only. Requires independent integration PASS before deployment.',
    }
    append.write_json(output / 'campbell-assignment-integration.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('records', 'acceptance', 'output', 'corpus', 'evidence', 'base-audit', 'runtime-acceptance'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--source', required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--semantic-manifest', type=Path)
    args = vars(parser.parse_args())
    print(json.dumps(stage(**args), indent=2))
