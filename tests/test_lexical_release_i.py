"""Gzip-only I scope preserves exact public H and its shared runtime."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_i as tool
import lexical_release_h as previous
import lexical_transport_i as transport
import lexical_transport_h as previous_transport
import lexical_baseline_i as baseline


class ReleaseITests(unittest.TestCase):
    def test_two_modules_only(self):
        self.assertEqual(tool.MODULES, {'server.py', 'large_json_gzip.py'})
        self.assertEqual(tool.NEW_MODULES, {'large_json_gzip.py'})
        self.assertEqual(tool.BASELINE_MODULES, baseline.FILES)
        self.assertEqual(tool.BASE_CONTAINER, baseline.BASE_CONTAINER)

    def test_isolated_configuration(self):
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007i')
        self.assertEqual(previous.RELEASE.name, 'lexical-20261007h')
        self.assertEqual(previous_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007h')

    def test_original_h_mounts(self):
        mounts = {row[0]: row for row in tool.base_mounts()}
        self.assertEqual(len(mounts), 27)
        for name in previous.MODULES:
            self.assertIn('lexical-20261007h', mounts['/app/backend/' + name][1])
        self.assertEqual(mounts['/app/runtime'][1], str(tool.core.guard.ROOT / 'runtime'))
        self.assertTrue(mounts['/app/runtime'][2])
        self.assertNotIn('/app/backend/large_json_gzip.py', mounts)


if __name__ == '__main__':
    unittest.main()
