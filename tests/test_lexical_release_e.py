"""Synthetic E target, artifact-scope and old-release isolation guards."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_e as tool
import lexical_release_d as prior
import lexical_transport_e as transport
import lexical_transport_d as prior_transport
import lexical_baseline_e as baseline
import stage_lexical_e as staging


class ReleaseETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder / 'candidate-code').mkdir()
        self.receipt = {'verdict': 'PASS', 'base_container_id': tool.BASE_CONTAINER, 'image': tool.BASE, 'files': {}}
        self.snapshot = {'module_sha256': {}}
        for name in tool.MODULES:
            raw = ('# synthetic ' + name).encode()
            (self.folder / 'candidate-code' / name).write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            before = None if name in tool.NEW_MODULES else hashlib.sha256(('old ' + name).encode()).hexdigest()
            self.snapshot['module_sha256'][name] = before
            self.receipt['files'][name] = {'verdict': 'PASS', 'sha256': digest, 'baseline_sha256': before}
            if name in tool.NEW_MODULES:
                self.receipt['files'][name]['baseline_absent'] = True
        self.receipt['files']['server.py']['scoped_live_baseline_patch'] = True
        self.receipt['files']['edition_commentary_data.json']['source_projection_audit'] = 'PASS'
        self.addCleanup(patch.stopall)
        patch.object(tool.core, 'RELEASE', self.folder).start()
        patch.object(tool.core.guard, 'RELEASE', self.folder).start()
        patch.object(tool, 'COMMENTARY_SHA', self.receipt['files']['edition_commentary_data.json']['sha256']).start()
        patch.object(tool.core.release, 'load', side_effect=lambda name: self.receipt if name == 'modules-pass.json' else self.snapshot).start()

    def test_exact_scoped_artifacts(self):
        self.assertEqual(set(tool.approved_modules()), tool.MODULES)
        self.assertEqual(tool.MODULES, baseline.FILES & tool.MODULES)

    def test_commentary_source_audit_required(self):
        del self.receipt['files']['edition_commentary_data.json']['source_projection_audit']
        with self.assertRaisesRegex(RuntimeError, 'approved commentary'):
            tool.approved_modules()

    def test_translation_comparison_out_of_scope(self):
        self.receipt['files']['translation_comparisons.py'] = {'verdict': 'PASS'}
        with self.assertRaisesRegex(RuntimeError, 'scoped C modules'):
            tool.approved_modules()

    def test_exact_d_baseline_and_new_target(self):
        self.assertEqual(tool.BASE_CONTAINER, baseline.BASE_CONTAINER)
        self.assertEqual(tool.RELEASE.name, 'lexical-20261007e')
        self.assertEqual(prior.RELEASE.name, 'lexical-20261007d')
        self.assertEqual(prior.BASE_CONTAINER, 'ec2cdc5176ed0f747cb03de0037d7bfb1bc00e93644fae7fbf761822e6eb6aa5')
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007e')
        self.assertEqual(prior_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007d')

    def test_preserved_d_source_conflict_overlays(self):
        mounts = {row[0]: row[1] for row in tool.base_mounts()}
        for name in ('interlinear.py', 'lexicon_senses.py', 'lexical_variants.py'):
            self.assertIn('lexical-20261007d', mounts['/app/backend/' + name])
            self.assertNotIn(name, tool.MODULES)
        self.assertIn('lexical-20261007b', mounts['/app/backend/classifier.py'])

    def test_scoped_unified_patch_preserves_unedited_bytes(self):
        source = {'passage_analysis.py': b'one\r\ntwo\r\nthree\r\n'}
        change = b'--- a/backend/passage_analysis.py\n+++ b/backend/passage_analysis.py\n@@ -1,3 +1,3 @@\n one\n-two\n+new\n three\n'
        output = staging.apply_patch_bytes(source, change)
        self.assertEqual(output['passage_analysis.py'], b'one\r\nnew\nthree\r\n')
        self.assertEqual(source['passage_analysis.py'], b'one\r\ntwo\r\nthree\r\n')

    def test_patch_source_change_fails_closed(self):
        change = b'--- a/backend/passage_ranker.py\n+++ b/backend/passage_ranker.py\n@@ -1 +1 @@\n-wrong\n+new\n'
        with self.assertRaisesRegex(ValueError, 'source bytes differ'):
            staging.apply_patch_bytes({'passage_ranker.py': b'old\n'}, change)

    def test_server_three_line_insertion_preserves_live_bytes(self):
        base = b"# live\r\n    result.update(translation_previews(result,result.get('related',[]),full_text=True))\r\n    return result\r\n# live tail\r\n"
        result = staging.server_patch(base)
        self.assertTrue(result.startswith(base.split(b'    return result')[0]))
        self.assertTrue(result.endswith(b'    return result\r\n# live tail\r\n'))
        self.assertEqual(len(result.splitlines()) - len(base.splitlines()), 3)


if __name__ == '__main__':
    unittest.main()
