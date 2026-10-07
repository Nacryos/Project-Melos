"""F preparation guard tests; no remote access or source-data mutation."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_f as tool
import lexical_release_e as previous
import lexical_transport_f as transport
import lexical_transport_e as previous_transport
import lexical_baseline_f as baseline
import stage_lexical_f as staging


class ReleaseFTests(unittest.TestCase):
    def test_new_scope_exact(self):
        self.assertEqual(len(tool.MODULES), 9)
        self.assertEqual(tool.NEW_MODULES, baseline.NEW_FILES)
        self.assertEqual(tool.BASELINE_MODULES, baseline.FILES)
        self.assertNotIn('classifier.py', tool.MODULES)
        self.assertNotIn('candidate_senses.py', tool.MODULES)
        self.assertNotIn('morphology.py', tool.MODULES)

    def test_live_e_baseline_and_target(self):
        self.assertEqual(tool.BASE_CONTAINER, baseline.BASE_CONTAINER)
        self.assertEqual(tool.RELEASE.name, 'lexical-20261007f')
        self.assertEqual(tool.CANARY, 'melos-api-lexical-canary-f')
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007f')

    def test_prior_adapters_are_unchanged(self):
        self.assertEqual(previous.RELEASE.name, 'lexical-20261007e')
        self.assertEqual(previous_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007e')
        self.assertNotEqual(previous.BASE_CONTAINER, tool.BASE_CONTAINER)

    def test_baseline_exactly_preserves_e_overlays(self):
        mounts = {row[0]: row for row in tool.base_mounts()}
        self.assertEqual(len(mounts), 18)
        for name in previous.MODULES:
            source = mounts['/app/backend/' + name][1]
            self.assertIn('lexical-20261007e', source)
        self.assertIn('lexical-20261007d', mounts['/app/backend/interlinear.py'][1])
        self.assertIn('lexical-20261007b', mounts['/app/backend/classifier.py'][1])
        self.assertIn('campbell-20261007b', mounts['/app/data/corpus.sqlite'][1])
        self.assertTrue(mounts['/app/runtime'][2])
        self.assertFalse(mounts['/run/secrets/jev.env'][2])

    def test_patch_offset_without_fuzzy_context(self):
        source = {'server.py': b'live prefix\r\nanchor\r\nreturn\r\n'}
        patch = b'diff --git a/backend/server.py b/backend/server.py\n--- a/backend/server.py\n+++ b/backend/server.py\n@@ -999,2 +999,3 @@\n anchor\n+insert\n return\n'
        result, locations = staging.apply_unique_context(source, patch)
        self.assertEqual(result['server.py'], b'live prefix\r\nanchor\r\ninsert\nreturn\r\n')
        self.assertEqual(locations[0]['matched_line'], 2)
        self.assertEqual(locations[0]['declared_old_line'], 999)

    def test_patch_ambiguous_context_fails(self):
        patch = b'--- a/backend/server.py\n+++ b/backend/server.py\n@@ -1 +1,2 @@\n same\n+insert\n'
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            staging.apply_unique_context({'server.py': b'same\nsame\n'}, patch)

    def test_patch_extra_module_fails(self):
        patch = b'--- a/backend/discovery.py\n+++ b/backend/discovery.py\n'
        with self.assertRaisesRegex(ValueError, 'outside exact F scope'):
            staging.apply_unique_context({'discovery.py': b''}, patch)


if __name__ == '__main__':
    unittest.main()
