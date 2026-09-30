"""Synthetic staging mechanics only; these strings are not corpus entries."""
from contextlib import closing, redirect_stdout
import copy
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import build_corpus
from scripts import stage_corpus_addition as tool


class CorpusAdditionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('raw', 'processed', 'reports', 'staging'):
            (self.root / 'data' / name).mkdir(parents=True)
        self.raw = self.root / 'data/raw/synthetic.html'
        self.raw.write_bytes(b'SYNTHETIC TEST FIXTURE; NOT SCHOLARLY SOURCE DATA')
        self.common = {'source': 'fixture', 'source_url': 'https://example.test/synthetic',
            'raw_path': 'data/raw/synthetic.html', 'raw_sha256': tool.sha(self.raw),
            'author': 'Homer', 'work': 'Synthetic work', 'edition': 'Synthetic edition',
            'citation': 'Fixture 1', 'language': 'grc', 'kind': 'text',
            'quality': 'source_text', 'license': 'synthetic fixture'}
        self.initial = [self.common | {'id': 'old:1', 'text': 'αβ αβ'},
                        self.common | {'id': 'old:2', 'text': 'γδ', 'quality': 'machine_corrected_ocr'},
                        self.common | {'id': 'old:3', 'text': 'Unresolved fixture', 'kind': 'reference', 'quality': 'needs_review'}]
        old_path = self.root / 'data/processed/original.jsonl'
        self.write_rows(old_path, self.initial)
        self.runtime = self.root / 'data/reports/audit-acceptance.json'
        self.runtime.write_text(json.dumps({'files': {'original.jsonl': {
            'verdict': 'PASS', 'sha256': tool.sha(old_path), 'records': len(self.initial)}}}), encoding='utf-8')
        self.corpus = self.root / 'data/corpus.sqlite'
        with patch.object(build_corpus, 'ROOT', self.root), redirect_stdout(io.StringIO()):
            build_corpus.build(self.corpus)
        self.evidence = self.root / 'data/evidence.sqlite'
        with closing(sqlite3.connect(self.evidence)) as con:
            con.execute('CREATE TABLE fixture (id TEXT, status TEXT)')
            con.execute("INSERT INTO fixture VALUES ('unchanged', 'needs_review')")
            con.commit()
        self.audit = self.root / 'data/staging/base-audit.json'
        self.bind_base()
        self.records = self.root / 'data/staging/addition.jsonl'
        self.acceptance = self.root / 'data/staging/source-acceptance.json'
        self.new = [self.common | {'id': 'new:1', 'text': 'αβ εζ'},
                    self.common | {'id': 'new:translation', 'author': 'Synthetic translator',
                        'language': 'ell', 'kind': 'translation', 'text': 'Συνθετικό κείμενο', 'parent_id': 'new:1'},
                    self.common | {'id': 'new:review', 'text': 'Uncertain test', 'quality': 'needs_review'}]
        self.accept_new()
        self.output = self.root / 'data/staging/candidate'

    def write_rows(self, path, rows):
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')

    def bind_base(self):
        self.audit.write_text(json.dumps({'verdict': 'PASS', 'corpus_sha256': tool.sha(self.corpus),
            'evidence_sha256': tool.sha(self.evidence)}), encoding='utf-8')

    def accept_new(self):
        self.write_rows(self.records, self.new)
        self.acceptance.write_text(json.dumps({'files': {self.records.name: {'verdict': 'PASS',
            'sha256': tool.sha(self.records), 'records': len(self.new)}}}), encoding='utf-8')

    def run_stage(self, **overrides):
        args = dict(corpus=self.corpus, evidence=self.evidence, base_audit=self.audit,
                    runtime_acceptance=self.runtime, source='fixture', root=self.root)
        args.update(overrides)
        return tool.stage_addition(self.records, self.acceptance, self.output, **args)

    def test_append_preserves_base_policy_evidence_and_all_existing_rows(self):
        protected = [self.corpus, self.evidence, self.runtime, self.audit, self.records, self.acceptance]
        before = {p: tool.sha(p) for p in protected}
        with closing(sqlite3.connect(self.corpus)) as con:
            original = con.execute('SELECT * FROM passages ORDER BY id').fetchall()
        result = self.run_stage()
        self.assertEqual({p: tool.sha(p) for p in protected}, before)
        self.assertEqual(tool.sha(self.output / 'evidence.sqlite'), before[self.evidence])
        self.assertEqual((self.output / self.records.name).read_bytes(), self.records.read_bytes())
        self.assertEqual(result['status'], 'PENDING_INDEPENDENT_AUDIT')
        self.assertEqual(result['evidence']['new_structured_claims'], 0)
        self.assertEqual(result['embeddings']['status'], 'REBUILD_REQUIRED')
        with closing(sqlite3.connect(self.output / 'corpus.sqlite')) as con:
            self.assertEqual(con.execute("SELECT * FROM passages WHERE id LIKE 'old:%' ORDER BY id").fetchall(), original)
            self.assertEqual(con.execute("SELECT sequence FROM passages WHERE id='new:1'").fetchone()[0], 3)
            self.assertEqual(con.execute('SELECT count FROM works WHERE id=?', (tool.work_identity(self.common),)).fetchone()[0], 5)
            self.assertEqual(con.execute("SELECT count FROM vocabulary WHERE normalized='αβ'").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT id FROM passage_fts WHERE passage_fts MATCH 'εζ'").fetchall(), [('new:1',)])
            self.assertEqual(con.execute("SELECT count(*) FROM tokens WHERE passage_id='new:review'").fetchone()[0], 0)
            self.assertEqual(json.loads(con.execute("SELECT data FROM passages WHERE id='new:translation'").fetchone()[0])['parent_id'], 'new:1')
            manifest = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
            self.assertEqual(manifest['passages'], 6)
            self.assertEqual(manifest['schema'], 2)
            self.assertIn('machine_corrected_ocr', manifest['searchable_qualities'])
        candidate = json.loads((self.output / 'audit-acceptance.candidate.json').read_text())
        self.assertIn('original.jsonl', candidate['files'])
        self.assertEqual(candidate['files'][self.records.name]['sha256'], before[self.records])

    def test_future_columns_and_unrelated_metadata_survive(self):
        with closing(sqlite3.connect(self.corpus)) as con:
            con.execute("ALTER TABLE passages ADD COLUMN future TEXT DEFAULT 'keep' ")
            con.execute("ALTER TABLE works ADD COLUMN future TEXT DEFAULT 'keep-work'")
            con.execute("INSERT INTO metadata VALUES ('unrelated', 'preserve')")
            con.commit()
        self.bind_base()
        self.run_stage()
        with closing(sqlite3.connect(self.output / 'corpus.sqlite')) as con:
            self.assertEqual(con.execute('SELECT DISTINCT future FROM passages').fetchall(), [('keep',)])
            self.assertEqual(con.execute('SELECT DISTINCT future FROM works').fetchall(), [('keep-work',)])
            self.assertEqual(con.execute("SELECT value FROM metadata WHERE key='unrelated'").fetchone()[0], 'preserve')

    def test_source_audit_must_match_verdict_hash_and_count(self):
        for field, value in [('verdict', 'PENDING'), ('sha256', '0' * 64), ('records', 100)]:
            with self.subTest(field=field):
                self.accept_new()
                report = json.loads(self.acceptance.read_text())
                report['files'][self.records.name][field] = value
                self.acceptance.write_text(json.dumps(report), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.run_stage()
                self.assertFalse(self.output.exists())

    def test_base_binding_and_raw_hash_mismatch_are_rejected(self):
        self.audit.write_text(json.dumps({'verdict': 'PASS', 'corpus_sha256': 'bad', 'evidence_sha256': tool.sha(self.evidence)}))
        with self.assertRaisesRegex(ValueError, 'Base artifact'):
            self.run_stage()
        self.bind_base()
        self.raw.write_bytes(b'changed raw source fixture')
        with self.assertRaisesRegex(ValueError, 'Raw artifact hash mismatch'):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_duplicate_collision_scope_and_parent_guards(self):
        cases = [lambda rows: rows.append(copy.deepcopy(rows[0])),
                 lambda rows: rows[0].update(id='old:1'),
                 lambda rows: rows[0].update(source='outside'),
                 lambda rows: rows[0].update(parent_id='not-found'),
                 lambda rows: rows[0].update(parent_id='new:translation')]
        baseline = copy.deepcopy(self.new)
        for mutate in cases:
            self.new = copy.deepcopy(baseline)
            mutate(self.new)
            self.accept_new()
            with self.assertRaises(ValueError):
                self.run_stage()
            self.assertFalse(self.output.exists())

    def test_active_journal_and_nonstaging_or_existing_output_are_rejected(self):
        journal = Path(str(self.corpus) + '-wal')
        journal.write_bytes(b'SYNTHETIC ACTIVE JOURNAL')
        with self.assertRaisesRegex(ValueError, 'journal'):
            self.run_stage()
        journal.unlink()
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh directory'):
            self.run_stage()
        self.output = self.root / 'data/active'
        with self.assertRaisesRegex(ValueError, 'fresh directory'):
            self.run_stage()

    def test_existing_acceptance_entry_cannot_be_replaced(self):
        approval = json.loads(self.runtime.read_text())
        approval['files'][self.records.name] = {'verdict': 'PASS', 'sha256': 'other'}
        self.runtime.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, 'replace an existing'):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_concurrent_input_change_leaves_no_final_manifest(self):
        original = tool.append_rows
        def mutate(*args):
            result = original(*args)
            self.raw.write_bytes(b'concurrent raw mutation')
            return result
        with patch.object(tool, 'append_rows', mutate):
            with self.assertRaisesRegex(RuntimeError, 'Input changed'):
                self.run_stage()
        self.assertFalse((self.output / 'addition-manifest.json').exists())

    def test_unrelated_row_mutation_fails_preservation_gate(self):
        original = tool.append_rows
        def mutate(con, *args):
            result = original(con, *args)
            con.execute("UPDATE passages SET quality='source_text' WHERE id='old:2'")
            return result
        with patch.object(tool, 'append_rows', mutate):
            with self.assertRaisesRegex(RuntimeError, 'Existing rows changed'):
                self.run_stage()
        self.assertFalse((self.output / 'addition-manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
