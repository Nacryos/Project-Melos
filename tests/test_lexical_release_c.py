"""Release C guard tests: synthetic bytes only, no SSH or Docker."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_c as tool
import lexical_transport_c as transport
import stage_lexical_c as staging


class ReleaseCTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.code = self.folder / 'candidate-code'
        self.code.mkdir()
        self.approval = {'verdict': 'PASS', 'base_container_id': tool.BASE_CONTAINER,
                         'image': tool.BASE, 'files': {}}
        self.snapshot = {'module_sha256': {}}
        for name in tool.MODULES:
            data = ('# synthetic guard fixture ' + name).encode()
            (self.code / name).write_bytes(data)
            baseline = None if name in tool.NEW_MODULES else hashlib.sha256(('old ' + name).encode()).hexdigest()
            self.snapshot['module_sha256'][name] = baseline
            self.approval['files'][name] = {'verdict': 'PASS', 'baseline_sha256': baseline,
                                          'sha256': hashlib.sha256(data).hexdigest()}
            if name in tool.NEW_MODULES:
                self.approval['files'][name]['baseline_absent'] = True
        self.approval['files']['server.py']['scoped_live_baseline_patch'] = True
        self.addCleanup(patch.stopall)
        patch.object(tool, 'RELEASE', self.folder).start()
        patch.object(tool.guard, 'RELEASE', self.folder).start()
        patch.object(tool.release, 'load', side_effect=lambda name: self.approval if name == 'modules-pass.json' else self.snapshot).start()

    def test_exact_modules_and_new_absence(self):
        self.assertEqual(set(tool.approved_modules()), tool.MODULES)

    def test_missing_explicit_new_absence_rejected(self):
        del self.approval['files']['lexical_variants.py']['baseline_absent']
        with self.assertRaisesRegex(RuntimeError, 'absence must be audited'):
            tool.approved_modules()

    def test_new_module_existing_baseline_rejected(self):
        self.snapshot['module_sha256']['lexical_variants.py'] = 'preexisting'
        with self.assertRaisesRegex(RuntimeError, 'baseline approval differs'):
            tool.approved_modules()

    def test_unscoped_server_rejected(self):
        del self.approval['files']['server.py']['scoped_live_baseline_patch']
        with self.assertRaisesRegex(RuntimeError, 'scoped live-baseline patch'):
            tool.approved_modules()

    def test_frozen_hash_rejected_on_mutation(self):
        (self.code / 'server.py').write_text('# unrelated dirty edits')
        with self.assertRaisesRegex(RuntimeError, 'Frozen module changed'):
            tool.approved_modules()

    def test_extra_index_is_out_of_scope(self):
        self.approval['files']['lexicon_subentries.py'] = {'verdict': 'PASS'}
        with self.assertRaisesRegex(RuntimeError, 'scoped C modules'):
            tool.approved_modules()

    def test_b_classifier_sense_ranker_and_data_preserved(self):
        old = {'HostConfig': {'Binds': [
            '/b/classifier.py:/app/backend/classifier.py:ro',
            '/b/sense_ranker.py:/app/backend/sense_ranker.py:ro',
            '/fixed/corpus.sqlite:/app/data/corpus.sqlite:ro',
            '/fixed/runtime:/app/runtime:rw',
            '/fixed/secret:/run/secrets/jev.env:ro',
            '/b/interlinear.py:/app/backend/interlinear.py:ro']}}
        before = copy.deepcopy(old)
        binds = tool.expected_binds(old)
        self.assertEqual(binds[:5], old['HostConfig']['Binds'][:5])
        self.assertEqual(old, before)
        self.assertEqual(len(binds), 10)

    def test_explicit_candidate_transport_hashes(self):
        receipt = self.folder / 'approval.json'
        receipt.write_text(json.dumps(self.approval))
        self.assertEqual(transport.approval(receipt, self.code), self.approval)

    def test_transport_rejects_dirty_backend(self):
        with self.assertRaisesRegex(ValueError, 'Dirty backend'):
            transport.approval('does-not-matter.json', transport.ROOT / 'backend')

    def test_remote_destination_is_posix(self):
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007c')

    def test_server_patch_preserves_unrelated_baseline_bytes(self):
        marker = b"    result['parallel_contexts'] = []"
        base = b'# exact live prefix\r\n' + marker + b'\r\n# exact live suffix\r\n'
        block = b'    # Lexical variants can supply an entry meaning without supplying a parse.\n' + b'    # synthetic extra line\n' * 13
        local = b'# rejected dirty prefix\n' + block + marker + b'\n# rejected dirty suffix\n'
        self.assertEqual(staging.server_patch(base, local), base.replace(marker, block + marker))

    def test_server_duplicate_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError, 'anchors differ'):
            staging.server_patch(b'', b'')


if __name__ == '__main__':
    unittest.main()
