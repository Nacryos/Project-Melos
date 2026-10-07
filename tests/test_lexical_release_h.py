"""Exact two-module H scope, preserving G including its original runtime."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_h as tool
import lexical_release_g as previous
import lexical_transport_h as transport
import lexical_transport_g as previous_transport
import lexical_baseline_h as baseline


class ReleaseHTests(unittest.TestCase):
    def test_two_modules_only(self):
        self.assertEqual(tool.MODULES, {'lexicon_senses.py', 'interlinear.py'})
        self.assertEqual(tool.NEW_MODULES, set())
        self.assertEqual(tool.BASELINE_MODULES, baseline.FILES)
        self.assertEqual(tool.BASE_CONTAINER, baseline.BASE_CONTAINER)

    def test_isolated_configuration(self):
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007h')
        self.assertEqual(previous.RELEASE.name, 'lexical-20261007g')
        self.assertEqual(previous_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007g')

    def test_original_g_mounts(self):
        mounts = {row[0]: row for row in tool.base_mounts()}
        self.assertEqual(len(mounts), 27)
        for name in previous.MODULES:
            self.assertIn('lexical-20261007g', mounts['/app/backend/' + name][1])
        self.assertEqual(mounts['/app/runtime'][1], str(tool.core.guard.ROOT / 'runtime'))
        self.assertTrue(mounts['/app/runtime'][2])
        self.assertNotEqual(tool.core.guard.start, previous.start)


if __name__ == '__main__':
    unittest.main()
