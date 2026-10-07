"""Synthetic mechanics only: no invented text is admitted to a scholarly corpus."""
import json
import hashlib
from pathlib import Path
import sys
import unittest
import numpy as np

from scripts import integrate_campbell_assignment as tool
from scripts import embed_campbell_assignment as embeddings
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stage_corpus_addition as fixtures


class CampbellAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CorpusAdditionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for name in ('common', 'root', 'records', 'acceptance', 'output', 'corpus', 'evidence', 'audit', 'runtime'):
            setattr(self, name, getattr(self.fixture, name))
        self.new = [self.common | {'id': 'synthetic-campbell:' + label,
            'author': 'Alcaeus', 'text': 'SYNTHETIC TEST ONLY ' + label,
            'metadata': {'assignment_fragment': label}}
            for label in sorted(tool.FRAGMENTS)]
        self.accept_new()
        self.semantic = self.root / 'manifest.json'
        stat = self.corpus.stat()
        self.semantic.write_text(json.dumps({'count': 3, 'eligible_count': 3,
            'corpus_mtime_ns': stat.st_mtime_ns, 'corpus_size': stat.st_size,
            'rows_file': 'rows-base.json', 'vectors_file': 'vectors-base.npy'}))

    def accept_new(self):
        self.fixture.new = self.new
        self.fixture.accept_new()

    def test_assignment_stages_five_and_preserves_semantic_coverage_honestly(self):
        report = tool.stage(self.records, self.acceptance, self.output,
            corpus=self.corpus, evidence=self.evidence, base_audit=self.audit,
            runtime_acceptance=self.runtime, source='fixture', root=self.root,
            semantic_manifest=self.semantic)
        self.assertEqual(len(report['added_ids']), 5)
        self.assertFalse(report['semantic']['new_ids_embedded'])
        manifest = tool.append.read_json(self.output / 'manifest.json')
        self.assertEqual(manifest['count'], 3)
        self.assertEqual(manifest['eligible_count'], 8)
        self.assertEqual(len(manifest['pending_embedding_ids']), 5)
        self.assertEqual(manifest['corpus_mtime_ns'], (self.output / 'corpus.sqlite').stat().st_mtime_ns)

    def test_duplicate_or_missing_fragment_is_rejected(self):
        self.new[-1]['metadata']['assignment_fragment'] = '129'
        self.accept_new()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            tool.assignment_rows(self.records, self.acceptance, self.root, 'fixture')

    def test_stale_semantic_manifest_rejected(self):
        manifest = tool.append.read_json(self.semantic)
        manifest['corpus_size'] += 1
        self.semantic.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            tool.retained_semantic_manifest(self.semantic, self.corpus, self.corpus, ['fixture'])

    def test_bounded_embedding_append_keeps_old_vectors_exact(self):
        manifest = tool.append.read_json(self.semantic)
        manifest.update(model=embeddings.MODEL_NAME, model_revision=embeddings.MODEL_REVISION,
            precision='float16', max_seq_length=512, pooling_method=embeddings.POOLING_METHOD,
            dimensions=1024, total_windows=3, counts_by_source={'fixture': 3},
            counts_by_language_kind={'grc:text': 3})
        self.semantic.write_text(json.dumps(manifest))
        old_rows = [{'id': 'old:' + str(i), 'source': 'fixture'} for i in range(3)]
        (self.root / manifest['rows_file']).write_text(json.dumps(old_rows))
        old_vectors = np.eye(3, 1024, dtype=np.float32)
        np.save(self.root / manifest['vectors_file'], old_vectors)
        tool.stage(self.records, self.acceptance, self.output,
            corpus=self.corpus, evidence=self.evidence, base_audit=self.audit,
            runtime_acceptance=self.runtime, source='fixture', root=self.root,
            semantic_manifest=self.semantic)
        addition = self.root / 'five-vectors'
        addition.mkdir()
        np.save(addition / 'addition.npy', np.eye(5, 1024, dtype=np.float32))
        receipt = {'contract': embeddings.contract(manifest),
            'records_sha256': tool.append.sha(self.records),
            'vectors_sha256': tool.append.sha(addition / 'addition.npy'),
            'rows': [{'id': row['id'], 'text_sha256': hashlib.sha256(row['text'].encode()).hexdigest(),
                      'source': 'fixture', 'language': 'grc', 'kind': 'text', 'author': 'Alcaeus',
                      'parent_id': None, 'context_authors': [], 'windows': 1} for row in self.new]}
        (addition / 'addition.json').write_text(json.dumps(receipt))
        result = embeddings.append_vectors(self.records, self.acceptance, self.semantic,
            self.root, addition, self.output, self.corpus, root=self.root, source='fixture')
        self.assertEqual(result['count'], 8)
        revised = tool.append.read_json(self.output / result['manifest'])
        matrix = np.load(self.output / revised['vectors_file'])
        self.assertTrue(np.array_equal(matrix[:3], old_vectors))
        self.assertEqual(revised['pending_embedding_ids'], [])
        self.assertTrue(revised['corpus_rebinding']['new_ids_embedded'])


if __name__ == '__main__':
    unittest.main()
