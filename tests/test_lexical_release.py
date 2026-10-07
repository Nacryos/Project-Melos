"""Synthetic deployment guard tests; never contacts Docker, SSH or production."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release as tool


class LexicalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / 'candidate-code').mkdir()
        self.approval = {'verdict': 'PASS', 'base_container_id': tool.BASE_CONTAINER,
                         'image': tool.BASE, 'files': {}}
        self.snapshot = {'module_sha256': {}}
        for name in tool.MODULES:
            content = ('# Synthetic deployment fixture: ' + name).encode()
            (self.folder / 'candidate-code' / name).write_bytes(content)
            self.snapshot['module_sha256'][name] = 'before-' + name
            self.approval['files'][name] = {'verdict': 'PASS',
                'baseline_sha256': 'before-' + name, 'sha256': hashlib.sha256(content).hexdigest()}
        self.addCleanup(patch.stopall)
        patch.object(tool, 'RELEASE', self.folder).start()
        patch.object(tool.release, 'load', side_effect=lambda name:
                     self.approval if name == 'modules-pass.json' else self.snapshot).start()

    def test_exact_five_modules_are_hash_bound(self):
        self.assertEqual(set(tool.approved_modules()), tool.MODULES)

    def test_corpus_or_unapproved_module_cannot_enter_receipt(self):
        self.approval['files']['corpus.sqlite'] = {'verdict': 'PASS'}
        with self.assertRaisesRegex(RuntimeError, 'five explicitly'):
            tool.approved_modules()

    def test_local_changes_after_approval_fail_closed(self):
        (self.folder / 'candidate-code/classifier.py').write_text('# changed')
        with self.assertRaisesRegex(RuntimeError, 'Frozen module changed'):
            tool.approved_modules()

    def test_wrong_live_baseline_rejected(self):
        self.approval['files']['interlinear.py']['baseline_sha256'] = 'another release'
        with self.assertRaisesRegex(RuntimeError, 'baseline approval'):
            tool.approved_modules()

    def test_existing_data_and_secret_binds_survive_exactly(self):
        old = {'HostConfig': {'Binds': [
            '/fixed/corpus.sqlite:/app/data/corpus.sqlite:ro',
            '/fixed/manifest.json:/app/data/embeddings/manifest.json:ro',
            '/fixed/secret.env:/run/secrets/jev.env:ro',
            '/fixed/runtime:/app/runtime:rw',
            '/old/interlinear.py:/app/backend/interlinear.py:ro',
            '/old/passage_analysis.py:/app/backend/passage_analysis.py:ro']}}
        before = copy.deepcopy(old)
        result = tool.expected_binds(old)
        self.assertEqual(result[:4], old['HostConfig']['Binds'][:4])
        self.assertEqual(old, before)
        self.assertEqual(len(result), 9)
        self.assertEqual(len([bind for bind in result if ':/app/backend/' in bind]), 5)


if __name__ == '__main__':
    unittest.main()
