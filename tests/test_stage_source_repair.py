"""Synthetic staging mechanics; fixture Greek/claims are not corpus entries."""
import copy
from contextlib import closing, redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import build_corpus, build_evidence, extract_p2_notes
from scripts.stage_source_repair import stage, sha, records
from scripts import stage_source_repair as repair_tool


class SourceRepairTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for relative in ('data/raw', 'data/processed', 'data/claims', 'data/reports', 'data/staging'):
            (self.root / relative).mkdir(parents=True)
        artifact = self.root / 'data/raw/fixture.html'
        artifact.write_bytes(b'<html>SYNTHETIC TEST FIXTURE, NOT SOURCE DATA</html>')
        common = {'source': 'fixture', 'source_url': 'https://example.test/synthetic',
                  'raw_path': 'data/raw/fixture.html', 'raw_sha256': sha(artifact),
                  'author': 'Synthetic author', 'work': 'Synthetic work', 'edition': 'Fixture',
                  'language': 'grc', 'kind': 'text', 'quality': 'source_text', 'license': 'fixture', 'citation': 'Synthetic 1'}
        self.old = [common | {'id': 'digital-sappho:fixture:1', 'text': 'αβγ λύει'},
                    common | {'id': 'digital-sappho:fixture:note', 'text': 'λύει pres. act. ind.',
                              'kind': 'commentary', 'parent_id': 'digital-sappho:fixture:1',
                              'metadata': {'subtype': 'vocabulary'}},
                    common | {'id': 'digital-sappho:unrelated:2', 'text': 'ζηθ'}]
        self.old_path = self.root / 'data/processed/sappho.jsonl'
        self.write(self.old_path, self.old)
        source_manifest = {'files': {'sappho.jsonl': {'verdict': 'PASS', 'sha256': sha(self.old_path), 'records': len(self.old)}}}
        (self.root / 'data/reports/audit-acceptance.json').write_text(json.dumps(source_manifest), encoding='utf-8')
        with patch.object(build_corpus, 'ROOT', self.root), redirect_stdout(io.StringIO()):
            build_corpus.build(self.root / 'data/corpus.sqlite')
        old_rows, old_lines = records(self.old_path)
        hashes = {key: hashlib.sha256(value.rstrip(b'\r\n')).hexdigest() for key, value in old_lines.items()}
        claims = extract_p2_notes.digital_vocabulary(self.old[1], self.old[0], hashes)
        self.assertEqual(len(claims), 1)
        self.claims_path = self.root / 'data/claims/p2_notes.jsonl'
        self.write(self.claims_path, claims)
        claim_manifest = {'files': {'p2_notes.jsonl': {'verdict': 'PASS', 'sha256': sha(self.claims_path), 'records': len(claims)}}}
        (self.root / 'data/reports/p2-claim-acceptance.json').write_text(json.dumps(claim_manifest), encoding='utf-8')
        build_evidence.build(root=self.root)
        self.new_path = self.root / 'data/staging/parser.jsonl'
        self.output = self.root / 'data/staging/snapshot'

    def write(self, path, values):
        path.write_text(''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in values), encoding='utf-8')

    def test_stages_split_source_and_realigns_claim_without_active_mutation(self):
        revised = copy.deepcopy(self.old)
        revised[0]['text'] = 'λύει'
        revised.insert(1, self.old[0] | {'id': 'digital-sappho:fixture:new-section', 'text': 'αβγ', 'citation': 'Synthetic 1 section'})
        self.write(self.new_path, revised)
        protected = list((self.root / 'data/reports').glob('*')) + [self.old_path, self.claims_path,
                     self.root / 'data/corpus.sqlite', self.root / 'data/evidence.sqlite']
        before = {path: sha(path) for path in protected}
        result = stage(self.new_path, self.output, self.root)
        self.assertEqual(result['status'], 'PENDING_INDEPENDENT_AUDIT')
        self.assertEqual(result['source_diff']['added'], ['digital-sappho:fixture:new-section'])
        self.assertEqual(result['source_diff']['changed'], ['digital-sappho:fixture:1'])
        self.assertEqual({path: sha(path) for path in protected}, before)
        _, old_lines = records(self.old_path)
        _, new_lines = records(self.output / 'sappho.jsonl')
        self.assertEqual(old_lines['digital-sappho:unrelated:2'], new_lines['digital-sappho:unrelated:2'])
        with closing(sqlite3.connect(self.output / 'corpus.sqlite')) as con:
            self.assertEqual(con.execute('SELECT text FROM passages WHERE id=?', ('digital-sappho:fixture:1',)).fetchone()[0], 'λύει')
            self.assertEqual(con.execute('SELECT sequence FROM passages ORDER BY sequence').fetchall(), [(0,), (1,), (2,), (3,)])
            self.assertEqual(con.execute('SELECT sum(count) FROM tokens WHERE normalized=?', ('αβγ',)).fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT count FROM vocabulary WHERE normalized=?', ('αβγ',)).fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT id FROM passage_fts WHERE passage_fts MATCH 'αβγ'").fetchall(), [('digital-sappho:fixture:new-section',)])
        with closing(sqlite3.connect(self.output / 'evidence.sqlite')) as con:
            self.assertEqual(con.execute('SELECT start_offset,end_offset FROM claims').fetchone(), (0, 4))
            digest = con.execute('SELECT sha256 FROM input_files').fetchone()[0]
            self.assertEqual(digest, sha(self.output / 'p2_notes.jsonl'))
        self.assertEqual(result['embeddings']['status'], 'REBUILD_REQUIRED')

    def test_removed_note_removes_only_derived_claim(self):
        revised = [self.old[0], self.old[2]]
        self.write(self.new_path, revised)
        result = stage(self.new_path, self.output, self.root)
        self.assertEqual(len(result['claim_diff']['removed']), 1)
        with closing(sqlite3.connect(self.output / 'evidence.sqlite')) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM claims').fetchone()[0], 0)

    def test_rejects_overwrite_or_nonstaging_output(self):
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        self.output.mkdir()
        with self.assertRaises(ValueError):
            stage(self.new_path, self.output, self.root)
        with self.assertRaises(ValueError):
            stage(self.new_path, self.root / 'data/active', self.root)

    def test_rejects_raw_or_accepted_input_hash_changes(self):
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        (self.root / 'data/raw/fixture.html').write_bytes(b'changed fixture')
        with self.assertRaisesRegex(ValueError, 'Raw artifact hash mismatch'):
            stage(self.new_path, self.output, self.root)
        self.assertFalse(self.output.exists())

    def test_rejects_undeclared_active_source_rows(self):
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        with closing(sqlite3.connect(self.root / 'data/corpus.sqlite')) as con:
            values = list(con.execute('SELECT * FROM passages LIMIT 1').fetchone())
            values[0] = 'digital-sappho:stale-unaccepted'
            con.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
            con.commit()
        with self.assertRaisesRegex(ValueError, 'source membership differs'):
            stage(self.new_path, self.output, self.root)
        self.assertFalse((self.output / 'repair-manifest.json').exists())

    def test_rejects_active_claim_status_drift_instead_of_overwriting_it(self):
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        with closing(sqlite3.connect(self.root / 'data/evidence.sqlite')) as con:
            con.execute("UPDATE claims SET status='needs_review'")
            con.commit()
        with self.assertRaisesRegex(ValueError, 'note claim differs'):
            stage(self.new_path, self.output, self.root)
        self.assertFalse((self.output / 'repair-manifest.json').exists())

    def test_preserves_accepted_uncertain_status_during_realignment(self):
        claims = list(records(self.claims_path)[0].values())
        claims[0]['status'] = 'needs_review'
        self.write(self.claims_path, claims)
        manifest_path = self.root / 'data/reports/p2-claim-acceptance.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files']['p2_notes.jsonl']['sha256'] = sha(self.claims_path)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        build_evidence.build(root=self.root)
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        stage(self.new_path, self.output, self.root)
        with closing(sqlite3.connect(self.output / 'evidence.sqlite')) as con:
            self.assertEqual(con.execute('SELECT status,start_offset FROM claims').fetchone(), ('needs_review', 0))

    def test_rechecks_raw_inputs_after_staging(self):
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, *self.old[1:]])
        original = repair_tool.patch_evidence
        def mutate_after_build(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.root / 'data/raw/fixture.html').write_bytes(b'concurrently changed fixture')
            return result
        with patch.object(repair_tool, 'patch_evidence', mutate_after_build):
            with self.assertRaisesRegex(RuntimeError, 'input changed during staging'):
                stage(self.new_path, self.output, self.root)
        self.assertFalse((self.output / 'repair-manifest.json').exists())

    def test_reorders_other_source_work_even_when_its_record_values_are_unchanged(self):
        self.old[2]['work'] = 'Other synthetic work'
        self.old.append(self.old[2] | {'id': 'digital-sappho:unrelated:3', 'text': 'ικλ'})
        self.write(self.old_path, self.old)
        manifest_path = self.root / 'data/reports/audit-acceptance.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files']['sappho.jsonl'].update(sha256=sha(self.old_path), records=4)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with patch.object(build_corpus, 'ROOT', self.root), redirect_stdout(io.StringIO()):
            build_corpus.build(self.root / 'data/corpus.sqlite')
        self.write(self.new_path, [self.old[0] | {'text': 'λύει'}, self.old[1], self.old[3], self.old[2]])
        result = stage(self.new_path, self.output, self.root)
        with closing(sqlite3.connect(self.output / 'corpus.sqlite')) as con:
            ordered = con.execute("SELECT id FROM passages WHERE work='Other synthetic work' ORDER BY sequence").fetchall()
        self.assertEqual(ordered, [('digital-sappho:unrelated:3',), ('digital-sappho:unrelated:2',)])
        self.assertEqual(result['source_diff']['changed'], ['digital-sappho:fixture:1'])
        pending = json.loads((self.output / 'audit-acceptance.candidate.json').read_text(encoding='utf-8'))
        self.assertEqual(pending['files']['sappho.jsonl']['verdict'], 'PENDING')


if __name__ == '__main__':
    unittest.main()
